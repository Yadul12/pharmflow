"""
PHARMFLOW — Automated Excel (openpyxl) & CSV Reporting Service
==============================================================
Generates multi-worksheet formatted Excel workbooks across all 8 required tabs:
  1. Executive Summary
  2. Customer Funnel
  3. Customer Retention
  4. Cohort Analysis
  5. Product Category Performance
  6. Subscription Analytics
  7. Customer Segments
  8. Cancellation Analysis

Also generates filtered Customer-level and Order-level CSV exports and logs
every run in PostgreSQL `report_runs` so analysts can review & re-download history.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.config import REPORTS_DIR
from app.database import _apply_schema, fetch_all, fetch_one, get_conn
from app.queries.cancellations import get_cancellation_analytics
from app.queries.categories import get_category_analytics
from app.queries.cohorts import get_cohort_analytics
from app.queries.executive import get_executive_overview
from app.queries.filters import AnalyticsFilter, build_customer_where, build_order_where
from app.queries.funnel import get_funnel_analytics
from app.queries.retention import get_retention_analytics
from app.queries.segmentation import get_segmentation_analytics
from app.queries.subscriptions import get_subscription_analytics
from app.services.insight_engine import generate_business_insights

# Clean Enterprise Styling Palette (Navy & Neutral Slate)
NAVY_FILL = PatternFill(start_color="0F243D", end_color="0F243D", fill_type="solid")
SUBHEADER_FILL = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
BAND_FILL = PatternFill(start_color="E8EEF5", end_color="E8EEF5", fill_type="solid")
ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
COHORT_HIGH = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
COHORT_MED = PatternFill(start_color="EBF2F8", end_color="EBF2F8", fill_type="solid")
COHORT_LOW = PatternFill(start_color="F7F9FB", end_color="F7F9FB", fill_type="solid")

TITLE_FONT = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
SUBTITLE_FONT = Font(name="Calibri", size=10, italic=True, color="D1DCE8")
SECTION_FONT = Font(name="Calibri", size=11, bold=True, color="0F243D")
TH_FONT = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Calibri", size=10, color="111827")
BOLD_FONT = Font(name="Calibri", size=10, bold=True, color="111827")
MUTED_FONT = Font(name="Calibri", size=9, italic=True, color="4B5563")

THIN_BORDER = Border(
    left=Side(style="thin", color="D1D9E2"),
    right=Side(style="thin", color="D1D9E2"),
    top=Side(style="thin", color="D1D9E2"),
    bottom=Side(style="thin", color="D1D9E2"),
)


def _style_banner(ws, title: str, subtitle: str, max_col: int = 10) -> int:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max_col)
    c1 = ws.cell(row=1, column=1, value=title)
    c2 = ws.cell(row=2, column=1, value=subtitle)
    c1.font = TITLE_FONT
    c2.font = SUBTITLE_FONT
    c1.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    c2.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    for r in (1, 2):
        for c in range(1, max_col + 1):
            ws.cell(row=r, column=c).fill = NAVY_FILL
    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 19
    ws.views.sheetView[0].showGridLines = True
    return 4


def _write_section_header(ws, row: int, title: str, max_col: int = 8) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max_col)
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = SECTION_FONT
    cell.alignment = Alignment(vertical="center", horizontal="left")
    for c in range(1, max_col + 1):
        ws.cell(row=row, column=c).fill = BAND_FILL
        ws.cell(row=row, column=c).border = THIN_BORDER
    ws.row_dimensions[row].height = 22
    return row + 1


def _write_table(
    ws,
    start_row: int,
    headers: list[str],
    rows: list[list[Any]],
    num_formats: dict[int, str] | None = None,
) -> int:
    num_formats = num_formats or {}
    for idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=idx, value=h)
        cell.font = TH_FONT
        cell.fill = SUBHEADER_FILL
        cell.alignment = Alignment(horizontal="center" if idx > 1 else "left", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    ws.row_dimensions[start_row].height = 24

    r_ptr = start_row + 1
    for r_i, row_vals in enumerate(rows):
        for c_i, val in enumerate(row_vals, start=1):
            cell = ws.cell(row=r_ptr, column=c_i, value=val)
            cell.font = BODY_FONT
            cell.border = THIN_BORDER
            if r_i % 2 == 1:
                cell.fill = ZEBRA_FILL
            if c_i in num_formats and val is not None:
                cell.number_format = num_formats[c_i]
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif isinstance(val, (int, float)):
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.row_dimensions[r_ptr].height = 20
        r_ptr += 1
    return r_ptr + 1


def _autofit_columns(ws, min_width: int = 12, max_width: int = 44) -> None:
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = min_width
        for cell in col:
            if cell.row in (1, 2):
                continue
            val = cell.value
            if val is not None:
                s = str(val)
                longest_line = max((len(line) for line in s.split("\n")), default=0)
                if longest_line + 3 > max_len:
                    max_len = min(longest_line + 3, max_width)
        ws.column_dimensions[col_letter].width = max_len


def _record_report_run(
    report_type: str,
    filename: str,
    file_path: Path,
    f: AnalyticsFilter,
    row_count: int,
) -> dict[str, Any]:
    size_bytes = file_path.stat().st_size if file_path.exists() else 0
    raw_bytes = file_path.read_bytes() if file_path.exists() else None
    with get_conn() as conn:
        with conn.cursor() as cur:
            _apply_schema(cur)
            cur.execute(
                """
                INSERT INTO report_runs (
                    report_type, filename, file_path, start_date, end_date,
                    filters_json, row_count, file_size_bytes, file_bytes, status
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, 'completed')
                RETURNING run_id, report_type, filename, start_date, end_date,
                          filters_json, row_count, file_size_bytes, status, generated_at;
                """,
                (
                    report_type,
                    filename,
                    str(file_path),
                    f.start_date,
                    f.end_date,
                    json.dumps(f.to_dict()),
                    row_count,
                    size_bytes,
                    raw_bytes,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return {
        "run_id": int(row["run_id"]),
        "report_type": row["report_type"],
        "filename": row["filename"],
        "start_date": row["start_date"].isoformat() if row["start_date"] else None,
        "end_date": row["end_date"].isoformat() if row["end_date"] else None,
        "filters": row["filters_json"],
        "row_count": int(row["row_count"]),
        "file_size_bytes": int(row["file_size_bytes"]),
        "status": row["status"],
        "generated_at": row["generated_at"].isoformat(),
    }


def list_report_runs(limit: int = 30) -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT run_id, report_type, filename, start_date, end_date,
               filters_json AS filters, row_count, file_size_bytes, status, generated_at
        FROM report_runs
        ORDER BY generated_at DESC
        LIMIT %s;
        """,
        (max(1, min(limit, 100)),),
    )
    return rows


def get_report_file(run_id: int) -> dict[str, Any] | None:
    row = fetch_one(
        "SELECT run_id, filename, file_path, report_type, file_bytes FROM report_runs WHERE run_id = %s;",
        (run_id,),
    )
    if not row:
        return None
    p = Path(row["file_path"])
    file_bytes = row.get("file_bytes")
    if not p.exists() and not file_bytes:
        return None
    return {
        "filename": row["filename"],
        "path": p,
        "report_type": row["report_type"],
        "file_bytes": bytes(file_bytes) if file_bytes is not None else None,
    }


def generate_excel_workbook(f: AnalyticsFilter) -> dict[str, Any]:
    f = f.normalized()
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stamp_display = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    filter_desc = (
        f"Period: {f.start_date.isoformat()} to {f.end_date.isoformat()} | "
        f"City: {f.city or 'All'} | Channel: {f.channel or 'All'} | "
        f"Device: {f.device or 'All'} | Generated: {stamp_display} | 100% Synthetic Data"
    )

    exec_data = get_executive_overview(f)
    insights = generate_business_insights(f)
    funnel_data = get_funnel_analytics(f, breakdown_by="device_type")
    funnel_chan = get_funnel_analytics(f, breakdown_by="acquisition_channel")
    ret_data = get_retention_analytics(f)
    coh_data = get_cohort_analytics(f)
    cat_data = get_category_analytics(f)
    sub_data = get_subscription_analytics(f)
    seg_data = get_segmentation_analytics(f, limit=25)
    can_data = get_cancellation_analytics(f)

    wb = Workbook()

    # ------------------------------------------------------------------
    # Sheet 1: Executive Summary
    # ------------------------------------------------------------------
    ws1 = wb.active
    ws1.title = "Executive Summary"
    r = _style_banner(ws1, "PHARMFLOW — Executive Commercial Analytics Summary", filter_desc, max_col=8)
    k = exec_data["kpis"]
    r = _write_section_header(ws1, r, "1. Headline Commercial KPIs & Exact Definitions", max_col=8)
    kpi_rows = [
        ["Total Interactive Sessions", k["total_sessions"], "Count of filtered sessions in sessions / mv_session_funnel"],
        ["Active Visitors (Unique Accounts)", k["active_visitors"], "Distinct customers with >=1 session in period"],
        ["Ordering Customers (Delivered)", k["ordering_customers"], "Distinct customers with >=1 delivered order in period"],
        ["Visitor-to-Customer Conversion (%)", k["visitor_to_customer_pct"] / 100.0, "Ordering Customers / Active Visitors"],
        ["Completed Session Order Rate (%)", k["session_completed_order_pct"] / 100.0, "Session-Initiated Delivered Orders / Total Sessions"],
        ["Total Delivered Orders", k["delivered_orders"], f"Interactive ({k['interactive_delivered_orders']:,}) + Subscription Auto-Refill ({k['sub_refill_delivered_orders']:,})"],
        ["Delivered Net Revenue (INR)", k["net_revenue"], "SUM(net_amount) where order_status = 'delivered'"],
        ["Average Order Value (INR)", k["avg_order_value"], "Delivered Net Revenue / Total Delivered Orders"],
        ["Repeat Purchase Rate (%)", k["repeat_purchase_rate_pct"] / 100.0, "Customers with >=2 Delivered Orders / Ordering Customers in period"],
        ["Order Cancellation Rate (%)", k["cancellation_rate_pct"] / 100.0, "Non-Duplicate Cancelled Orders / Non-Duplicate Placed Orders"],
        ["Active Subscriptions", k["active_subscriptions"], "Subscriptions with status = 'active' as of period end"],
        ["Active Subscription MRR (INR)", k["active_mrr"], "SUM(monthly_plan_value) for active subscriptions"],
    ]
    r = _write_table(ws1, r, ["Metric", "Value", "Exact Denominator / Definition"], kpi_rows, num_formats={2: "#,##0.00"})
    # Refine specific row formats
    for offset, fmt in [(0, "#,##0"), (1, "#,##0"), (2, "#,##0"), (3, "0.00%"), (4, "0.00%"), (5, "#,##0"), (6, "₹#,##0.00"), (7, "₹#,##0.00"), (8, "0.00%"), (9, "0.00%"), (10, "#,##0"), (11, "₹#,##0.00")]:
        ws1.cell(row=6 + offset, column=2).number_format = fmt

    r = _write_section_header(ws1, r, "2. Data-Driven Business Insights (Correlation vs Causation Tagged)", max_col=8)
    ins_rows = [
        [
            ins["domain"],
            ins["title"],
            ins["what_happened"],
            ins["magnitude"],
            ins["comparison_baseline"],
            ins["evidence_type"],
            ins["recommended_action"],
        ]
        for ins in insights
    ]
    r = _write_table(
        ws1,
        r,
        ["Domain", "Insight", "What Happened", "Magnitude", "Baseline Comparison", "Evidence Type", "Recommended Action"],
        ins_rows,
    )
    ws1.freeze_panes = "A5"
    _autofit_columns(ws1)

    # ------------------------------------------------------------------
    # Sheet 2: Customer Funnel
    # ------------------------------------------------------------------
    ws2 = wb.create_sheet("Customer Funnel")
    r = _style_banner(ws2, "PHARMFLOW — 7-Stage Customer & Order Funnel", filter_desc, max_col=9)
    r = _write_section_header(ws2, r, "1. End-to-End Interactive Session Funnel", max_col=9)
    f_rows = [
        [
            s["step_order"],
            s["stage_name"],
            s["sessions"],
            s["unique_customers"],
            s["cumulative_rate_pct"] / 100.0,
            s["step_conversion_pct"] / 100.0,
            s["step_dropoff_pct"] / 100.0,
            s["sessions_lost"],
            s["denominator_formula"],
        ]
        for s in funnel_data["stages"]
    ]
    r = _write_table(
        ws2,
        r,
        ["Step", "Stage", "Sessions", "Unique Customers", "Cumulative %", "Step Conv %", "Step Drop-Off %", "Sessions Lost", "Denominator Formula"],
        f_rows,
        num_formats={3: "#,##0", 4: "#,##0", 5: "0.00%", 6: "0.00%", 7: "0.00%", 8: "#,##0"},
    )

    r = _write_section_header(ws2, r, "2. Funnel Performance by Device Type", max_col=9)
    d_rows = [
        [
            b["segment_value"],
            b["sessions"],
            b["search_rate_pct"] / 100.0,
            b["view_to_cart_pct"] / 100.0,
            b["cart_to_checkout_pct"] / 100.0,
            b["checkout_to_order_pct"] / 100.0,
            b["session_to_order_pct"] / 100.0,
            b["completed_order_rate_pct"] / 100.0,
        ]
        for b in funnel_data["breakdown"]
    ]
    r = _write_table(
        ws2,
        r,
        ["Device Type", "Sessions", "Search %", "View→Cart %", "Cart→Checkout %", "Checkout→Order %", "Order Conv %", "Completed %"],
        d_rows,
        num_formats={2: "#,##0", 3: "0.00%", 4: "0.00%", 5: "0.00%", 6: "0.00%", 7: "0.00%", 8: "0.00%"},
    )

    r = _write_section_header(ws2, r, "3. Funnel Performance by Acquisition Channel", max_col=9)
    ch_rows = [
        [
            b["segment_value"],
            b["sessions"],
            b["search_rate_pct"] / 100.0,
            b["cart_to_checkout_pct"] / 100.0,
            b["session_to_order_pct"] / 100.0,
            b["completed_order_rate_pct"] / 100.0,
        ]
        for b in funnel_chan["breakdown"]
    ]
    _write_table(
        ws2,
        r,
        ["Acquisition Channel", "Sessions", "Search %", "Cart→Checkout %", "Order Conv %", "Completed %"],
        ch_rows,
        num_formats={2: "#,##0", 3: "0.00%", 4: "0.00%", 5: "0.00%", 6: "0.00%"},
    )
    ws2.freeze_panes = "A5"
    _autofit_columns(ws2)

    # ------------------------------------------------------------------
    # Sheet 3: Customer Retention
    # ------------------------------------------------------------------
    ws3 = wb.create_sheet("Customer Retention")
    r = _style_banner(ws3, "PHARMFLOW — Customer Retention, Repeat Purchase & Reactivation", filter_desc, max_col=9)
    rk = ret_data["kpis"]
    r = _write_section_header(ws3, r, "1. Retention & Lifecycle KPIs (Matured Eligible Denominators)", max_col=9)
    rk_rows = [
        ["D1 Session Return Rate (%)", rk["d1_session_retention_pct"] / 100.0, rk["d1_eligible_customers"], "Returned on signup_date + 1 / Eligible signups"],
        ["D7 Session Return Rate (%)", rk["d7_session_retention_pct"] / 100.0, rk["d7_eligible_customers"], "Returned in days 1–7 post-signup / Eligible signups"],
        ["D30 First-Order Repeat Rate (%)", rk["d30_order_repeat_pct"] / 100.0, rk["d30_eligible_buyers"], "2nd delivered order <=30d / Eligible first buyers"],
        ["D60 First-Order Repeat Rate (%)", rk["d60_order_repeat_pct"] / 100.0, rk["d30_eligible_buyers"], "2nd delivered order <=60d / Eligible first buyers"],
        ["D90 First-Order Repeat Rate (%)", rk["d90_order_repeat_pct"] / 100.0, rk["d90_eligible_buyers"], "2nd delivered order <=90d / Eligible first buyers"],
        ["Overall Repeat Purchase Rate (%)", rk["overall_repeat_purchase_rate_pct"] / 100.0, rk["total_buyers"], "Buyers with >=2 delivered orders / Total buyers"],
        ["90-Day Buyer Inactivity Rate (%)", rk["inactivity_90d_pct"] / 100.0, rk["d90_eligible_buyers"], "Mature buyers with 0 orders in final 90d / Eligible buyers"],
        ["Avg Monthly Reactivation Rate (%)", rk["avg_monthly_reactivation_rate_pct"] / 100.0, rk["inactive_90d_buyers"], "Reactivated >=90d lapsed buyers / Prior-month inactive pool"],
        ["Average Orders per Buyer", rk["avg_orders_per_customer"], rk["total_buyers"], "Total Delivered Orders / Distinct Buyers"],
        ["Average Days Between Orders", rk["avg_days_between_orders"], rk["repeat_buyers"], "Mean inter-order interval across consecutive delivered orders"],
    ]
    r = _write_table(ws3, r, ["Metric", "Value", "Eligible Denominator (N)", "Formula"], rk_rows, num_formats={2: "0.00%", 3: "#,##0"})
    ws3.cell(row=14, column=2).number_format = "0.00"
    ws3.cell(row=15, column=2).number_format = "0.0"

    r = _write_section_header(ws3, r, "2. Monthly New vs Returning Buyers & Reactivation", max_col=9)
    nr_rows = [
        [
            m["year_month"],
            m["new_customers"],
            m["returning_customers"],
            (m["returning_share_pct"] or 0) / 100.0,
            m["new_customer_revenue"],
            m["returning_customer_revenue"],
            m["reactivated_customers"],
            m["eligible_inactive_pool"],
            (m["reactivation_rate_pct"] or 0) / 100.0,
        ]
        for m in ret_data["monthly_new_returning"]
    ]
    _write_table(
        ws3,
        r,
        ["Month", "New Buyers", "Returning Buyers", "Returning Share %", "New Rev (INR)", "Returning Rev (INR)", "Reactivated Buyers", "Inactive Pool", "Reactivation %"],
        nr_rows,
        num_formats={2: "#,##0", 3: "#,##0", 4: "0.00%", 5: "₹#,##0", 6: "₹#,##0", 7: "#,##0", 8: "#,##0", 9: "0.00%"},
    )
    ws3.freeze_panes = "A5"
    _autofit_columns(ws3)

    # ------------------------------------------------------------------
    # Sheet 4: Cohort Analysis
    # ------------------------------------------------------------------
    ws4 = wb.create_sheet("Cohort Analysis")
    r = _style_banner(ws4, "PHARMFLOW — Monthly Customer Retention Cohort Matrix (M0–M12)", filter_desc, max_col=15)
    r = _write_section_header(ws4, r, "1. Monthly Cohort Retention (% of Cohort Placing >=1 Delivered Order)", max_col=15)
    coh_headers = ["Cohort Month", "Cohort Size"] + [f"M{i}" for i in range(13)]
    coh_rows = []
    for c in coh_data["matrix"]:
        row_v: list[Any] = [c["cohort_month"], c["cohort_size"]]
        for i in range(13):
            v = c["retention"].get(f"M{i}")
            row_v.append(None if v is None else v / 100.0)
        coh_rows.append(row_v)
    coh_start = r + 1
    r = _write_table(
        ws4,
        r,
        coh_headers,
        coh_rows,
        num_formats={2: "#,##0", **{i + 3: "0.0%" for i in range(13)}},
    )
    # Apply subtle heatmap fills to M1..M12 cells
    for row_idx in range(coh_start, coh_start + len(coh_rows)):
        for col_idx in range(4, 16):
            cell = ws4.cell(row=row_idx, column=col_idx)
            if isinstance(cell.value, (int, float)):
                if cell.value >= 0.35:
                    cell.fill = COHORT_HIGH
                elif cell.value >= 0.22:
                    cell.fill = COHORT_MED
                else:
                    cell.fill = COHORT_LOW
    ws4.freeze_panes = "C6"
    _autofit_columns(ws4, min_width=10)

    # ------------------------------------------------------------------
    # Sheet 5: Product Category Performance
    # ------------------------------------------------------------------
    ws5 = wb.create_sheet("Product Category Performance")
    r = _style_banner(ws5, "PHARMFLOW — Medicine & Healthcare Category Commercial Performance", filter_desc, max_col=12)
    r = _write_section_header(ws5, r, "1. Category Revenue, Repeat Purchasing, Subscriptions & Cancellations", max_col=12)
    cat_rows = [
        [
            c["category_name"],
            c["category_group"],
            c["delivered_orders"],
            c["net_revenue"],
            c["revenue_share_pct"] / 100.0,
            c["aov"],
            c["distinct_buyers"],
            c["repeat_rate_pct"] / 100.0,
            c["avg_reorder_days"],
            c["sub_attach_rate_pct"] / 100.0,
            c["cancellation_rate_pct"] / 100.0,
            c["return_rate_pct"] / 100.0,
        ]
        for c in cat_data["categories"]
    ]
    r = _write_table(
        ws5,
        r,
        ["Category", "Group", "Delivered Orders", "Net Revenue (INR)", "Rev Share %", "AOV (INR)", "Buyers", "Repeat Rate %", "Avg Reorder Days", "Sub Attach %", "Cancel %", "Return %"],
        cat_rows,
        num_formats={3: "#,##0", 4: "₹#,##0.00", 5: "0.00%", 6: "₹#,##0.00", 7: "#,##0", 8: "0.00%", 9: "0.0", 10: "0.00%", 11: "0.00%", 12: "0.00%"},
    )
    ws5.freeze_panes = "A5"
    _autofit_columns(ws5)

    # ------------------------------------------------------------------
    # Sheet 6: Subscription Analytics
    # ------------------------------------------------------------------
    ws6 = wb.create_sheet("Subscription Analytics")
    r = _style_banner(ws6, "PHARMFLOW — Subscription Lifecycle, Renewal Timing & Retention Comparison", filter_desc, max_col=8)
    sk = sub_data["kpis"]
    r = _write_section_header(ws6, r, "1. Subscription Headline Metrics", max_col=8)
    sk_rows = [
        ["Total Subscriptions Started", sk["total_subscriptions"]],
        ["Active Subscriptions", sk["active_subscriptions"]],
        ["Paused Subscriptions", sk["paused_subscriptions"]],
        ["Cancelled Subscriptions", sk["cancelled_subscriptions"]],
        ["Cycle Renewal Rate (%)", sk["cycle_renewal_rate_pct"] / 100.0],
        ["Cumulative Cancellation Rate (%)", sk["cumulative_cancellation_rate_pct"] / 100.0],
        ["Avg Renewal Interval (Days)", sk["avg_renewal_interval_days"]],
        ["Subscription Auto-Refill Orders", sk["sub_refill_orders"]],
        ["Subscription Revenue Share (%)", sk["sub_revenue_share_pct"] / 100.0],
        ["Active Monthly Recurring Revenue (INR)", sk["active_mrr"]],
    ]
    r = _write_table(ws6, r, ["Metric", "Value"], sk_rows, num_formats={2: "#,##0"})
    for off, fmt in [(4, "0.00%"), (5, "0.00%"), (6, "0.0"), (8, "0.00%"), (9, "₹#,##0.00")]:
        ws6.cell(row=6 + off, column=2).number_format = fmt

    r = _write_section_header(ws6, r, "2. Subscribers vs Non-Subscribers (Observational Association — Selection Bias Applies)", max_col=8)
    sv_rows = [
        [
            x["cohort_group"],
            x["buyers"],
            x["repeat_purchase_rate_pct"] / 100.0,
            x["avg_orders_per_customer"],
            x["avg_order_value"],
            x["avg_ltv"],
            x["avg_days_between_orders"],
        ]
        for x in sub_data["subscriber_vs_non_subscriber"]
    ]
    r = _write_table(
        ws6,
        r,
        ["Group", "Buyers", "Repeat Rate %", "Avg Orders", "Avg AOV (INR)", "Avg LTV (INR)", "Avg Days Between Orders"],
        sv_rows,
        num_formats={2: "#,##0", 3: "0.00%", 4: "0.00", 5: "₹#,##0.00", 6: "₹#,##0.00", 7: "0.0"},
    )

    r = _write_section_header(ws6, r, "3. Subscription Performance by Category", max_col=8)
    sc_rows = [
        [c["category_name"], c["total_subscriptions"], c["active_subscriptions"], c["cancelled_subscriptions"], c["cancel_rate_pct"] / 100.0, c["avg_cadence_days"], c["active_mrr"]]
        for c in sub_data["by_category"]
    ]
    _write_table(
        ws6,
        r,
        ["Category", "Total Subs", "Active", "Cancelled", "Cancel Rate %", "Avg Cadence (d)", "Active MRR (INR)"],
        sc_rows,
        num_formats={2: "#,##0", 3: "#,##0", 4: "#,##0", 5: "0.00%", 6: "0.0", 7: "₹#,##0.00"},
    )
    ws6.freeze_panes = "A5"
    _autofit_columns(ws6)

    # ------------------------------------------------------------------
    # Sheet 7: Customer Segments
    # ------------------------------------------------------------------
    ws7 = wb.create_sheet("Customer Segments")
    r = _style_banner(ws7, "PHARMFLOW — RFM Business Segments & K-Means Behavioral Clusters", filter_desc, max_col=11)
    r = _write_section_header(ws7, r, "1. RFM Business Segments", max_col=11)
    seg_rows = [
        [
            s["business_segment"],
            s["customer_count"],
            s["customer_share_pct"] / 100.0,
            s["total_revenue"],
            s["revenue_share_pct"] / 100.0,
            s["avg_ltv"],
            s["avg_aov"],
            s["avg_frequency"],
            s["avg_recency_days"],
            s["subscriber_share_pct"] / 100.0,
            (s["high_churn_risk_pct"] or 0) / 100.0,
        ]
        for s in seg_data["business_segments"]
    ]
    r = _write_table(
        ws7,
        r,
        ["Segment", "Customers", "Cust Share %", "Total Revenue (INR)", "Rev Share %", "Avg LTV", "Avg AOV", "Avg Orders", "Avg Recency (d)", "Subscriber %", "High Churn Risk %"],
        seg_rows,
        num_formats={2: "#,##0", 3: "0.00%", 4: "₹#,##0.00", 5: "0.00%", 6: "₹#,##0.00", 7: "₹#,##0.00", 8: "0.00", 9: "0.0", 10: "0.00%", 11: "0.00%"},
    )

    r = _write_section_header(ws7, r, "2. K-Means Behavioral Clusters (Ordering Customers)", max_col=11)
    km_rows = [
        [
            c["cluster_label"],
            c["customer_count"],
            c["share_of_buyers_pct"] / 100.0,
            c["avg_recency_days"],
            c["avg_frequency"],
            c["avg_monetary"],
            c["avg_aov"],
            c["subscriber_share_pct"] / 100.0,
            c["high_churn_risk_pct"] / 100.0,
        ]
        for c in seg_data["kmeans_live_profiles"]
    ]
    _write_table(
        ws7,
        r,
        ["K-Means Cluster", "Buyers", "Buyer Share %", "Avg Recency (d)", "Avg Orders", "Avg LTV (INR)", "Avg AOV (INR)", "Subscriber %", "High Churn Risk %"],
        km_rows,
        num_formats={2: "#,##0", 3: "0.00%", 4: "0.0", 5: "0.00", 6: "₹#,##0.00", 7: "₹#,##0.00", 8: "0.00%", 9: "0.00%"},
    )
    ws7.freeze_panes = "A5"
    _autofit_columns(ws7)

    # ------------------------------------------------------------------
    # Sheet 8: Cancellation Analysis
    # ------------------------------------------------------------------
    ws8 = wb.create_sheet("Cancellation Analysis")
    r = _style_banner(ws8, "PHARMFLOW — Order Cancellations, Refund Drivers & Regional SLA Performance", filter_desc, max_col=9)
    r = _write_section_header(ws8, r, "1. Cancellation Drivers Pareto", max_col=9)
    cr_rows = [
        [
            x["cancellation_reason"],
            x["cancellation_stage"],
            x["initiated_by"],
            x["cancellations"],
            x["share_pct"] / 100.0,
            x["lost_order_value"],
            x["avg_hours_after_order"],
        ]
        for x in can_data["cancel_reasons"]
    ]
    r = _write_table(
        ws8,
        r,
        ["Cancellation Reason", "Stage", "Initiated By", "Orders", "Share %", "Lost Value (INR)", "Avg Hours to Cancel"],
        cr_rows,
        num_formats={4: "#,##0", 5: "0.00%", 6: "₹#,##0.00", 7: "0.0"},
    )

    r = _write_section_header(ws8, r, "2. Refund Breakdown by Reason & Type", max_col=9)
    rr_rows = [
        [
            x["refund_reason"],
            x["refund_type"],
            x["refund_count"],
            x["share_pct"] / 100.0,
            x["total_refund_amount"],
            x["avg_refund_amount"],
            x["avg_processing_hours"],
        ]
        for x in can_data["refund_reasons"]
    ]
    r = _write_table(
        ws8,
        r,
        ["Refund Reason", "Type", "Refunds", "Share %", "Total Refunded (INR)", "Avg Refund (INR)", "Avg Processing (Hrs)"],
        rr_rows,
        num_formats={3: "#,##0", 4: "0.00%", 5: "₹#,##0.00", 6: "₹#,##0.00", 7: "0.0"},
    )

    r = _write_section_header(ws8, r, "3. Geographic Cancellation Rate & Delivery SLA Adherence", max_col=9)
    geo_rows = [
        [
            x["city"],
            x["city_tier"],
            x["placed_orders"],
            x["cancelled_orders"],
            x["cancellation_rate_pct"] / 100.0,
            x["avg_promised_days"],
            x["avg_actual_days"],
            (x["sla_breach_pct"] or 0) / 100.0,
            x["cancelled_value"],
        ]
        for x in can_data["by_city"]
    ]
    _write_table(
        ws8,
        r,
        ["City", "Tier", "Placed Orders", "Cancelled", "Cancel Rate %", "Promised Days", "Actual Days", "SLA Breach %", "Cancelled Value (INR)"],
        geo_rows,
        num_formats={3: "#,##0", 4: "#,##0", 5: "0.00%", 6: "0.0", 7: "0.00", 8: "0.00%", 9: "₹#,##0.00"},
    )
    ws8.freeze_panes = "A5"
    _autofit_columns(ws8)

    filename = f"pharmflow_analytics_{f.start_date.strftime('%Y%m%d')}_{f.end_date.strftime('%Y%m%d')}_{ts_str}.xlsx"
    out_path = REPORTS_DIR / filename
    wb.save(out_path)

    total_rows = (
        len(kpi_rows) + len(ins_rows) + len(f_rows) + len(d_rows) + len(nr_rows)
        + len(coh_rows) + len(cat_rows) + len(sv_rows) + len(seg_rows) + len(cr_rows) + len(geo_rows)
    )
    return _record_report_run("excel_workbook", filename, out_path, f, total_rows)


def export_filtered_csv(f: AnalyticsFilter, entity: str = "orders", max_rows: int = 15000) -> dict[str, Any]:
    f = f.normalized()
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    cap = max(100, min(max_rows, 50000))

    if entity == "customers":
        cw, cp = build_customer_where(f, alias="cl")
        clauses = [cw]
        params = list(cp)
        if f.segment:
            clauses.append("cs.business_segment = %s")
            params.append(f.segment)
        clauses.append("cl.signup_date BETWEEN %s AND %s")
        params.extend([f.start_date, f.end_date])
        rows = fetch_all(
            f"""
            SELECT
                cl.customer_code,
                cl.signup_date,
                cl.cohort_month,
                cl.primary_city,
                cl.city_tier,
                cl.acquisition_channel,
                cl.primary_device,
                cl.age_band,
                cl.delivered_orders,
                cl.lifetime_net_revenue,
                cl.avg_order_value,
                cl.avg_days_between_orders,
                cl.is_subscriber,
                cs.business_segment,
                cs.rfm_code,
                cs.recency_days,
                cs.kmeans_label,
                cs.churn_risk_score,
                cs.churn_risk_band
            FROM mv_customer_lifecycle cl
            LEFT JOIN customer_segments cs ON cs.customer_id = cl.customer_id
            WHERE {' AND '.join(clauses)}
            ORDER BY cl.lifetime_net_revenue DESC
            LIMIT %s;
            """,
            tuple(params + [cap]),
        )
        report_type = "customers_csv"
        filename = f"pharmflow_customers_{f.start_date.strftime('%Y%m%d')}_{f.end_date.strftime('%Y%m%d')}_{ts_str}.csv"
    else:
        ow, op = build_order_where(f, alias="o")
        rows = fetch_all(
            f"""
            SELECT
                o.order_code,
                c.customer_code,
                o.order_date,
                o.order_source,
                o.order_status,
                o.is_first_order,
                o.is_duplicate_attempt,
                o.city,
                o.city_tier,
                o.acquisition_channel,
                o.device_type,
                mc.category_name AS primary_category,
                o.gross_amount,
                o.discount_amount,
                o.delivery_fee,
                o.net_amount,
                p.payment_method,
                p.payment_status,
                o.promised_delivery_days,
                o.actual_delivery_days,
                can.cancellation_reason
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            JOIN medicine_categories mc ON mc.category_id = o.primary_category_id
            LEFT JOIN payments p ON p.order_id = o.order_id
            LEFT JOIN cancellations can ON can.order_id = o.order_id
            WHERE {ow}
            ORDER BY o.order_date DESC, o.order_id DESC
            LIMIT %s;
            """,
            tuple(op + [cap]),
        )
        report_type = "orders_csv"
        filename = f"pharmflow_orders_{f.start_date.strftime('%Y%m%d')}_{f.end_date.strftime('%Y%m%d')}_{ts_str}.csv"

    out_path = REPORTS_DIR / filename
    if rows:
        fieldnames = list(rows[0].keys())
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        out_path.write_text("no_matching_records\n", encoding="utf-8")

    return _record_report_run(report_type, filename, out_path, f, len(rows))
