from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.config import ANALYTICS_OUTPUT_DIR, DATASET_END, DATASET_START
from app.database import execute_readonly_sql, fetch_all, fetch_one
from app.queries.cancellations import get_cancellation_analytics
from app.queries.categories import get_category_analytics
from app.queries.cohorts import get_cohort_analytics
from app.queries.executive import get_executive_overview
from app.queries.filters import AnalyticsFilter
from app.queries.funnel import get_funnel_analytics
from app.queries.retention import get_retention_analytics
from app.queries.segmentation import get_segmentation_analytics
from app.queries.sql_lab_catalog import SQL_LAB_CATALOG
from app.queries.subscriptions import get_subscription_analytics
from app.services.insight_engine import generate_business_insights
from app.services.report_service import (
    export_filtered_csv,
    generate_excel_workbook,
    get_report_file,
    list_report_runs,
)

router = APIRouter(prefix="/api", tags=["pharmflow"])


def parse_filters(
    start_date: date = Query(default=DATASET_START),
    end_date: date = Query(default=DATASET_END),
    city: str | None = Query(default=None),
    city_tier: str | None = Query(default=None),
    channel: str | None = Query(default=None),
    device: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    customer_type: str | None = Query(default=None),
    segment: str | None = Query(default=None),
) -> AnalyticsFilter:
    return AnalyticsFilter(
        start_date=start_date,
        end_date=end_date,
        city=city,
        city_tier=city_tier,
        channel=channel,
        device=device,
        category_id=category_id,
        customer_type=customer_type,
        segment=segment,
    ).normalized()


def _read_artifact_json(name: str) -> dict[str, Any] | None:
    p = ANALYTICS_OUTPUT_DIR / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


METRIC_DEFINITIONS = [
    {
        "metric": "Visitor-to-Customer Conversion Rate",
        "formula": "Distinct Customers with >=1 Delivered Order / Distinct Active Session Visitors",
        "scope": "Filtered period & dimensions",
        "notes": "Measures how effectively registered browsing visitors convert into completed buyers.",
    },
    {
        "metric": "Product Search / View / Add-to-Cart / Checkout Rates",
        "formula": "Sequential stage sessions / Prior stage sessions (Step Conversion) & Stage sessions / Total Sessions (Cumulative Rate)",
        "scope": "Interactive browsing sessions (`mv_session_funnel` reconciled 1:1 with raw `user_events`)",
        "notes": "Strictly monotonic 7-step funnel: App Visit → Search → View → Cart → Checkout → Placed → Delivered.",
    },
    {
        "metric": "Completed Order Rate (Funnel End-to-End)",
        "formula": "Session-Initiated Delivered Orders / Total Interactive Sessions",
        "scope": "Excludes cancelled, returned, and duplicate attempts; subscription auto-refills are reconciled separately.",
        "notes": "Guarantees transparent 1:1 reconciliation between interactive session events and orders.",
    },
    {
        "metric": "Monthly Cohort Retention (M0..M12)",
        "formula": "Distinct Cohort Buyers with >=1 Delivered Order in Cohort Month + N / Cohort Size",
        "scope": "Cohort defined by calendar month of first delivered order. Unmatured cells are NULL (never zero-padded).",
        "notes": "Prevents right-censoring bias when comparing early and recent cohorts.",
    },
    {
        "metric": "D1 / D7 Session Retention & D30 / D60 / D90 Repeat Purchase",
        "formula": "Returning Users within window / Eligible Users whose start date is >= window days prior to period end",
        "scope": "Matured eligible denominators enforced explicitly.",
        "notes": "D30/D60/D90 repeat purchase rates align with 30–60 day healthcare replenishment cadences.",
    },
    {
        "metric": "Customer Reactivation Rate",
        "formula": "Buyers returning after >=90 days of order inactivity in Month M / Eligible Inactive Buyer Pool entering Month M",
        "scope": "Delivered orders with LAG(order_date) >= 90 days.",
        "notes": "Tracks win-back efficacy separately from continuously active repeaters.",
    },
    {
        "metric": "Order Cancellation Rate",
        "formula": "Non-Duplicate Cancelled Orders / Non-Duplicate Placed Orders",
        "scope": "Accidental customer double-submit attempts (`is_duplicate_attempt = TRUE`) are tracked separately to prevent inflating operational cancellation rates.",
        "notes": "Duplicate order attempts are still audited in Cancellation Analysis and EDA profiling.",
    },
    {
        "metric": "Subscription Renewal Rate",
        "formula": "Renewed Subscription Cycles / (Renewed Cycles + Cancelled Cycles) in period",
        "scope": "Computed from `subscription_events`.",
        "notes": "Subscriber vs Non-Subscriber retention comparisons note selection bias (observational correlation, not causal lift).",
    },
]


@router.get("/health")
def health_check() -> dict[str, Any]:
    counts = fetch_one(
        """
        SELECT
            (SELECT COUNT(*) FROM customers) AS customers,
            (SELECT COUNT(*) FROM sessions) AS sessions,
            (SELECT COUNT(*) FROM user_events) AS user_events,
            (SELECT COUNT(*) FROM orders) AS orders,
            (SELECT COUNT(*) FROM subscriptions) AS subscriptions;
        """
    )
    return {"status": "ok", "service": "pharmflow-api", "counts": counts}


@router.get("/meta/filters")
def get_meta_filters() -> dict[str, Any]:
    cities = fetch_all("SELECT DISTINCT primary_city AS value, city_tier AS tier FROM customers ORDER BY primary_city;")
    channels = [r["acquisition_channel"] for r in fetch_all("SELECT DISTINCT acquisition_channel FROM customers ORDER BY 1;")]
    devices = [r["primary_device"] for r in fetch_all("SELECT DISTINCT primary_device FROM customers ORDER BY 1;")]
    categories = fetch_all("SELECT category_id, category_name, category_group FROM medicine_categories ORDER BY category_name;")
    segments = [r["business_segment"] for r in fetch_all("SELECT DISTINCT business_segment FROM customer_segments ORDER BY 1;")]
    return {
        "dataset_start": DATASET_START.isoformat(),
        "dataset_end": DATASET_END.isoformat(),
        "cities": cities,
        "city_tiers": ["Tier 1", "Tier 2", "Tier 3"],
        "channels": channels,
        "devices": devices,
        "categories": categories,
        "segments": segments,
        "metric_definitions": METRIC_DEFINITIONS,
        "synthetic_disclaimer": "All PharmFlow customer, session, order, and subscription records are 100% synthetic (seed=42) with non-identifying codes and zero personal health records or diagnoses.",
    }


@router.get("/executive")
def executive_endpoint(f: AnalyticsFilter = Depends(parse_filters)) -> dict[str, Any]:
    data = get_executive_overview(f)
    data["insights"] = generate_business_insights(f)
    data["validation_status"] = {
        "eda": _read_artifact_json("eda_profile.json"),
        "reconciliation": _read_artifact_json("reconciliation_report.json"),
        "statistical_tests": _read_artifact_json("statistical_tests.json"),
    }
    return data


@router.get("/funnel")
def funnel_endpoint(
    f: AnalyticsFilter = Depends(parse_filters),
    breakdown_by: str = Query(default="device_type"),
) -> dict[str, Any]:
    data = get_funnel_analytics(f, breakdown_by=breakdown_by)
    stats_art = _read_artifact_json("statistical_tests.json")
    if stats_art:
        data["statistical_tests"] = [
            t for t in stats_art.get("proportion_tests", [])
            if t["test_id"] in ("mobile_web_vs_app_checkout",)
        ]
    else:
        data["statistical_tests"] = []
    return data


@router.get("/retention")
def retention_endpoint(f: AnalyticsFilter = Depends(parse_filters)) -> dict[str, Any]:
    return get_retention_analytics(f)


@router.get("/cohorts")
def cohorts_endpoint(f: AnalyticsFilter = Depends(parse_filters)) -> dict[str, Any]:
    data = get_cohort_analytics(f)
    stats_art = _read_artifact_json("statistical_tests.json")
    if stats_art:
        data["statistical_tests"] = [
            t for t in stats_art.get("proportion_tests", [])
            if t["test_id"] in ("q2_2026_vs_baseline_m1",)
        ]
    else:
        data["statistical_tests"] = []
    return data


@router.get("/segmentation")
def segmentation_endpoint(
    f: AnalyticsFilter = Depends(parse_filters),
    selected_segment: str | None = Query(default=None),
    churn_band: str | None = Query(default=None),
    limit: int = Query(default=50, ge=10, le=200),
) -> dict[str, Any]:
    return get_segmentation_analytics(f, selected_segment=selected_segment, churn_band=churn_band, limit=limit)


@router.get("/subscriptions")
def subscriptions_endpoint(f: AnalyticsFilter = Depends(parse_filters)) -> dict[str, Any]:
    return get_subscription_analytics(f)


@router.get("/categories")
def categories_endpoint(f: AnalyticsFilter = Depends(parse_filters)) -> dict[str, Any]:
    data = get_category_analytics(f)
    stats_art = _read_artifact_json("statistical_tests.json")
    if stats_art:
        data["statistical_tests"] = [
            t for t in stats_art.get("proportion_tests", [])
            if t["test_id"] in ("chronic_vs_nonchronic_repeat",)
        ]
    else:
        data["statistical_tests"] = []
    return data


@router.get("/cancellations")
def cancellations_endpoint(f: AnalyticsFilter = Depends(parse_filters)) -> dict[str, Any]:
    data = get_cancellation_analytics(f)
    stats_art = _read_artifact_json("statistical_tests.json")
    if stats_art:
        data["statistical_tests"] = [
            t for t in stats_art.get("proportion_tests", [])
            if t["test_id"] in ("tier3_vs_tier1_cancellations",)
        ]
    else:
        data["statistical_tests"] = []
    return data


# ---------------------------------------------------------------------------
# SQL Lab Endpoints
# ---------------------------------------------------------------------------
class SqlExecuteRequest(BaseModel):
    sql: str = Field(..., min_length=5, max_length=15000)
    limit: int = Field(default=200, ge=1, le=500)
    include_explain: bool = Field(default=False)


@router.get("/sql-lab/catalog")
def sql_lab_catalog() -> dict[str, Any]:
    return {"queries": SQL_LAB_CATALOG}


@router.post("/sql-lab/execute")
def sql_lab_execute(payload: SqlExecuteRequest) -> dict[str, Any]:
    try:
        return execute_readonly_sql(
            sql=payload.sql,
            limit=payload.limit,
            include_explain=payload.include_explain,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PostgreSQL query error: {exc}") from exc


# ---------------------------------------------------------------------------
# Reports & Export Endpoints
# ---------------------------------------------------------------------------
class ReportGenerateRequest(BaseModel):
    start_date: date = DATASET_START
    end_date: date = DATASET_END
    city: str | None = None
    city_tier: str | None = None
    channel: str | None = None
    device: str | None = None
    category_id: int | None = None
    customer_type: str | None = None
    segment: str | None = None
    entity: str = "orders"  # 'orders' or 'customers' for CSV exports


def _req_to_filter(req: ReportGenerateRequest) -> AnalyticsFilter:
    return AnalyticsFilter(
        start_date=req.start_date,
        end_date=req.end_date,
        city=req.city,
        city_tier=req.city_tier,
        channel=req.channel,
        device=req.device,
        category_id=req.category_id,
        customer_type=req.customer_type,
        segment=req.segment,
    ).normalized()


@router.get("/reports/runs")
def reports_runs(limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
    return {"runs": list_report_runs(limit=limit)}


@router.post("/reports/excel")
def reports_generate_excel(req: ReportGenerateRequest) -> dict[str, Any]:
    run = generate_excel_workbook(_req_to_filter(req))
    return {"run": run, "download_url": f"/api/reports/download/{run['run_id']}"}


@router.post("/reports/csv")
def reports_export_csv(req: ReportGenerateRequest) -> dict[str, Any]:
    entity = "customers" if req.entity == "customers" else "orders"
    run = export_filtered_csv(_req_to_filter(req), entity=entity)
    return {"run": run, "download_url": f"/api/reports/download/{run['run_id']}"}


@router.get("/reports/download/{run_id}")
def reports_download(run_id: int):
    info = get_report_file(run_id)
    if not info:
        raise HTTPException(status_code=404, detail="Report file not found.")
    media_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if info["report_type"] == "excel_workbook"
        else "text/csv"
    )
    if info["path"].exists():
        return FileResponse(path=info["path"], filename=info["filename"], media_type=media_type)
    if info.get("file_bytes"):
        return Response(
            content=info["file_bytes"],
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{info["filename"]}"'},
        )
    raise HTTPException(status_code=404, detail="Report file not found.")
