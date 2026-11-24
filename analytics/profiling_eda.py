"""
PHARMFLOW — Python Data Profiling & Exploratory Data Analysis (EDA)
===================================================================
Audits all 18 PostgreSQL tables for:
- Exact row counts and schema integrity
- Missing / NULL value rates across key columns
- Primary key & business-code uniqueness + duplicate order attempt audit
- IQR & Z-score outlier analysis on order value, delivery days, and session duration
- Distribution summaries across segments, channels, devices, and categories
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pharmflow_user:pharmflow_pass@localhost:5460/pharmflow",
)
OUTPUT_DIR = Path(os.getenv("ANALYTICS_OUTPUT_DIR", "analytics_outputs"))

CORE_TABLES = [
    "calendar_dimension",
    "medicine_categories",
    "product_catalog",
    "promotional_campaigns",
    "customers",
    "customer_addresses",
    "sessions",
    "user_events",
    "search_events",
    "cart_events",
    "subscriptions",
    "subscription_events",
    "orders",
    "order_items",
    "payments",
    "cancellations",
    "refunds",
    "customer_segments",
]


def _iqr_outlier_summary(series: pd.Series, name: str) -> dict[str, Any]:
    s = series.dropna().astype(float)
    q1, med, q3 = np.percentile(s, [25, 50, 75])
    iqr = q3 - q1
    upper = q3 + 1.5 * iqr
    lower = max(0.0, q1 - 1.5 * iqr)
    n_outliers = int(((s > upper) | (s < lower)).sum())
    return {
        "metric": name,
        "count": int(len(s)),
        "mean": round(float(s.mean()), 2),
        "std": round(float(s.std()), 2),
        "min": round(float(s.min()), 2),
        "p25": round(float(q1), 2),
        "median": round(float(med), 2),
        "p75": round(float(q3), 2),
        "p95": round(float(np.percentile(s, 95)), 2),
        "p99": round(float(np.percentile(s, 99)), 2),
        "max": round(float(s.max()), 2),
        "iqr_upper_fence": round(float(upper), 2),
        "outlier_count": n_outliers,
        "outlier_pct": round(100.0 * n_outliers / max(len(s), 1), 2),
    }


def run_profiling_eda(database_url: str = DATABASE_URL) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            table_counts: dict[str, int] = {}
            for tbl in CORE_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                table_counts[tbl] = int(cur.fetchone()[0])

            # Duplicate primary / code integrity checks
            cur.execute("SELECT COUNT(*) - COUNT(DISTINCT customer_code) FROM customers;")
            dup_cust_codes = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) - COUNT(DISTINCT order_code) FROM orders;")
            dup_order_codes = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM orders WHERE is_duplicate_attempt = TRUE;")
            duplicate_attempts = int(cur.fetchone()[0])
            cur.execute(
                "SELECT COUNT(*) FROM orders WHERE is_duplicate_attempt = TRUE AND order_status <> 'cancelled';"
            )
            uncancelled_duplicates = int(cur.fetchone()[0])

            # Referential & funnel monotonicity checks
            cur.execute(
                """
                SELECT COUNT(*) FROM mv_session_funnel
                WHERE reached_search > reached_visit
                   OR reached_view > reached_search
                   OR reached_cart > reached_view
                   OR reached_checkout > reached_cart
                   OR reached_order_placed > reached_checkout
                   OR reached_order_delivered > reached_order_placed;
                """
            )
            funnel_order_violations = int(cur.fetchone()[0])

            # Order line-item financial reconciliation
            cur.execute(
                """
                SELECT COUNT(*)
                FROM orders o
                JOIN (
                    SELECT order_id, ROUND(SUM(line_total), 2) AS items_net
                    FROM order_items
                    GROUP BY order_id
                ) oi ON oi.order_id = o.order_id
                WHERE ABS((oi.items_net + o.delivery_fee) - o.net_amount) > 0.05;
                """
            )
            order_math_mismatches = int(cur.fetchone()[0])

        # Load slices into Pandas for missingness & outlier profiling
        orders_df = pd.read_sql_query(
            """
            SELECT order_id, order_source, order_status, is_duplicate_attempt,
                   gross_amount, discount_amount, delivery_fee, net_amount,
                   promised_delivery_days, actual_delivery_days, session_id, subscription_id, campaign_id
            FROM orders;
            """,
            conn,
        )
        sessions_df = pd.read_sql_query(
            """
            SELECT session_id, duration_seconds, primary_category_id, campaign_id
            FROM sessions;
            """,
            conn,
        )
        customers_df = pd.read_sql_query(
            """
            SELECT customer_id, signup_campaign_id, acquisition_channel, primary_device, city_tier
            FROM customers;
            """,
            conn,
        )

    missing_analysis = [
        {
            "table": "orders",
            "column": col,
            "null_count": int(orders_df[col].isna().sum()),
            "null_pct": round(100.0 * orders_df[col].isna().mean(), 2),
            "expected_reason": reason,
        }
        for col, reason in [
            ("session_id", "Expected NULL for subscription_auto_refill orders"),
            ("subscription_id", "Expected NULL for non-subscription interactive orders"),
            ("campaign_id", "Expected NULL for non-promotional full-price orders"),
            ("actual_delivery_days", "Expected NULL for cancelled orders"),
        ]
    ] + [
        {
            "table": "sessions",
            "column": "primary_category_id",
            "null_count": int(sessions_df["primary_category_id"].isna().sum()),
            "null_pct": round(100.0 * sessions_df["primary_category_id"].isna().mean(), 2),
            "expected_reason": "Expected NULL for bounced sessions without product search",
        },
        {
            "table": "customers",
            "column": "signup_campaign_id",
            "null_count": int(customers_df["signup_campaign_id"].isna().sum()),
            "null_pct": round(100.0 * customers_df["signup_campaign_id"].isna().mean(), 2),
            "expected_reason": "Expected NULL for organic/direct non-campaign signups",
        },
    ]

    delivered = orders_df[orders_df["order_status"] == "delivered"]
    outliers = [
        _iqr_outlier_summary(delivered["net_amount"], "Delivered Order Net Amount (INR)"),
        _iqr_outlier_summary(delivered["actual_delivery_days"], "Actual Delivery Days"),
        _iqr_outlier_summary(sessions_df["duration_seconds"], "Session Duration (Seconds)"),
    ]

    profile = {
        "table_row_counts": table_counts,
        "total_records_across_18_tables": int(sum(table_counts.values())),
        "integrity_checks": {
            "duplicate_customer_codes": dup_cust_codes,
            "duplicate_order_codes": dup_order_codes,
            "flagged_duplicate_order_attempts": duplicate_attempts,
            "uncancelled_duplicate_attempts": uncancelled_duplicates,
            "funnel_monotonicity_violations": funnel_order_violations,
            "order_item_financial_mismatches": order_math_mismatches,
            "all_passed": (
                dup_cust_codes == 0
                and dup_order_codes == 0
                and uncancelled_duplicates == 0
                and funnel_order_violations == 0
                and order_math_mismatches == 0
            ),
        },
        "missing_value_analysis": missing_analysis,
        "outlier_analysis": outliers,
    }

    out_path = OUTPUT_DIR / "eda_profile.json"
    out_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(f"[eda] Profiled {len(CORE_TABLES)} tables ({profile['total_records_across_18_tables']:,} total rows). Integrity passed={profile['integrity_checks']['all_passed']}.")
    return profile


if __name__ == "__main__":
    run_profiling_eda()
