"""
PHARMFLOW — Automated Analytical, API, SQL Lab & Reporting Validation Suite
===========================================================================
Covers every validation requirement:
  1. Customer & buyer population integrity
  2. Session & 7-stage funnel reconciliation (raw user_events vs mv_session_funnel vs orders)
  3. Duplicate order handling & financial math checks
  4. Cohort matrix maturation & denominator checks
  5. Retention denominator & repeat purchase validation
  6. Subscription lifecycle & renewal rate validation
  7. SQL vs Pandas parity assertion
  8. Filter responsiveness across all endpoints
  9. SQL Lab read-only guard & curated query execution
 10. 8-sheet Excel workbook generation & Customer/Order CSV export validation
"""

from __future__ import annotations

import csv
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from analytics.reconciliation import run_reconciliation
from app.database import fetch_one
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_and_dataset_scale(client: TestClient):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    counts = body["counts"]
    assert counts["customers"] == 30_000
    assert counts["sessions"] >= 100_000
    assert counts["user_events"] >= 300_000
    assert counts["orders"] >= 45_000
    assert counts["subscriptions"] >= 3_000


def test_duplicate_order_handling_and_unique_keys():
    checks = fetch_one(
        """
        SELECT
            (SELECT COUNT(*) - COUNT(DISTINCT customer_code) FROM customers) AS dup_cust_codes,
            (SELECT COUNT(*) - COUNT(DISTINCT order_code) FROM orders) AS dup_order_codes,
            (SELECT COUNT(*) FROM orders WHERE is_duplicate_attempt = TRUE) AS dup_attempts,
            (SELECT COUNT(*) FROM orders WHERE is_duplicate_attempt = TRUE AND order_status <> 'cancelled') AS uncancelled_dups;
        """
    )
    assert checks["dup_cust_codes"] == 0
    assert checks["dup_order_codes"] == 0
    assert checks["dup_attempts"] > 0
    assert checks["uncancelled_dups"] == 0


def test_funnel_monotonicity_and_reconciliation(client: TestClient):
    res = client.get("/api/funnel")
    assert res.status_code == 200
    data = res.json()
    stages = data["stages"]
    assert len(stages) == 7
    assert stages[0]["cumulative_rate_pct"] == 100.0
    for i in range(1, len(stages)):
        assert stages[i]["sessions"] <= stages[i - 1]["sessions"], f"Non-monotonic funnel at {stages[i]['stage_name']}"
        assert 0.0 <= stages[i]["step_conversion_pct"] <= 100.0
        assert round(stages[i]["step_conversion_pct"] + stages[i]["step_dropoff_pct"], 2) == 100.0

    # Reconcile interactive session orders against funnel step 6 & 7
    recon = data["reconciliation"]
    assert recon["interactive_orders_placed"] == stages[5]["sessions"]
    assert recon["interactive_orders_delivered"] == stages[6]["sessions"]
    assert recon["subscription_auto_refill_placed"] > 0


def test_cohort_matrix_denominators(client: TestClient):
    res = client.get("/api/cohorts")
    assert res.status_code == 200
    data = res.json()
    matrix = data["matrix"]
    assert len(matrix) == 14  # 2025-09 through 2026-10
    for idx, row in enumerate(matrix):
        assert row["cohort_size"] > 0
        assert row["retention"]["M0"] == 100.0
        max_expected_offset = min(12, len(matrix) - 1 - idx)
        for m in range(0, max_expected_offset + 1):
            assert f"M{m}" in row["retention"]
            assert 0.0 <= row["retention"][f"M{m}"] <= 100.0
        # Ensure unmatured future months are NOT populated
        for m in range(max_expected_offset + 1, 13):
            assert f"M{m}" not in row["retention"]


def test_retention_denominators_and_repeat_metrics(client: TestClient):
    res = client.get("/api/retention")
    assert res.status_code == 200
    k = res.json()["kpis"]
    assert k["d1_eligible_customers"] >= k["d7_eligible_customers"]
    assert k["d30_eligible_buyers"] >= k["d90_eligible_buyers"]
    assert 0.0 < k["d30_order_repeat_pct"] <= k["d60_order_repeat_pct"] <= k["d90_order_repeat_pct"] <= 100.0
    assert 0.0 < k["overall_repeat_purchase_rate_pct"] < 100.0
    assert k["avg_days_between_orders"] > 0


def test_subscription_and_category_metrics(client: TestClient):
    sub_res = client.get("/api/subscriptions")
    assert sub_res.status_code == 200
    sk = sub_res.json()["kpis"]
    assert sk["total_subscriptions"] == (
        sk["active_subscriptions"] + sk["paused_subscriptions"] + sk["cancelled_subscriptions"]
    )
    assert 0.0 < sk["cycle_renewal_rate_pct"] < 100.0
    assert sk["active_mrr"] > 0

    cat_res = client.get("/api/categories")
    assert cat_res.status_code == 200
    cats = cat_res.json()["categories"]
    assert len(cats) == 10
    assert abs(sum(c["revenue_share_pct"] for c in cats) - 100.0) <= 0.25


def test_filters_consistency(client: TestClient):
    all_exec = client.get("/api/executive").json()
    mumbai_exec = client.get("/api/executive", params={"city": "Mumbai"}).json()
    q1_exec = client.get(
        "/api/executive",
        params={"start_date": "2026-01-01", "end_date": "2026-03-31"},
    ).json()

    assert 0 < mumbai_exec["kpis"]["total_sessions"] < all_exec["kpis"]["total_sessions"]
    assert 0 < mumbai_exec["kpis"]["net_revenue"] < all_exec["kpis"]["net_revenue"]
    assert 0 < q1_exec["kpis"]["delivered_orders"] < all_exec["kpis"]["delivered_orders"]
    assert len(all_exec["insights"]) >= 5


def test_sql_vs_pandas_reconciliation():
    report = run_reconciliation()
    assert report["all_passed"] is True, f"Failed checks: {[c for c in report['checks'] if not c['passed']]}"


def test_sql_lab_catalog_and_security_guard(client: TestClient):
    cat = client.get("/api/sql-lab/catalog").json()["queries"]
    assert len(cat) >= 12
    # Execute first 3 catalog queries live against PostgreSQL
    for q in cat[:3]:
        r = client.post("/api/sql-lab/execute", json={"sql": q["sql"], "limit": 50, "include_explain": True})
        assert r.status_code == 200, f"Query {q['id']} failed: {r.text}"
        body = r.json()
        assert body["row_count"] > 0
        assert len(body["explain_plan"]) > 0

    # Verify write/DDL statements are strictly blocked
    for bad_sql in [
        "DROP TABLE customers;",
        "DELETE FROM orders WHERE order_id = 1",
        "UPDATE customers SET primary_city = 'Test'",
        "SELECT 1; DROP TABLE orders;",
    ]:
        bad_res = client.post("/api/sql-lab/execute", json={"sql": bad_sql})
        assert bad_res.status_code == 400


def test_excel_8_sheets_and_csv_exports(client: TestClient):
    # Generate 8-sheet Excel workbook
    ex_res = client.post(
        "/api/reports/excel",
        json={"start_date": "2025-09-01", "end_date": "2026-10-31"},
    )
    assert ex_res.status_code == 200
    run_info = ex_res.json()["run"]
    assert run_info["file_size_bytes"] > 10_000

    dl = client.get(f"/api/reports/download/{run_info['run_id']}")
    assert dl.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(dl.content))
    expected_sheets = [
        "Executive Summary",
        "Customer Funnel",
        "Customer Retention",
        "Cohort Analysis",
        "Product Category Performance",
        "Subscription Analytics",
        "Customer Segments",
        "Cancellation Analysis",
    ]
    assert wb.sheetnames == expected_sheets
    for sname in expected_sheets:
        assert wb[sname].max_row >= 6

    # Export filtered orders CSV and customers CSV
    for entity in ("orders", "customers"):
        csv_res = client.post(
            "/api/reports/csv",
            json={"start_date": "2026-01-01", "end_date": "2026-03-31", "city": "Bengaluru", "entity": entity},
        )
        assert csv_res.status_code == 200
        c_run = csv_res.json()["run"]
        assert c_run["row_count"] > 0
        c_dl = client.get(f"/api/reports/download/{c_run['run_id']}")
        assert c_dl.status_code == 200
        parsed = list(csv.reader(io.StringIO(c_dl.text)))
        assert len(parsed) == c_run["row_count"] + 1

    # Verify report history endpoint lists all runs
    runs = client.get("/api/reports/runs").json()["runs"]
    assert len(runs) >= 3
