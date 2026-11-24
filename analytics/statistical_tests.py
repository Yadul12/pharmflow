"""
PHARMFLOW — Statistical Hypothesis Testing & Inference Engine
=============================================================
Performs formal SciPy / Statsmodels statistical comparisons across key
commercial questions and explicitly distinguishes correlation from causation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from scipy import stats
from statsmodels.stats.proportion import proportions_ztest, confint_proportions_2indep

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pharmflow_user:pharmflow_pass@localhost:5460/pharmflow",
)
OUTPUT_DIR = Path(os.getenv("ANALYTICS_OUTPUT_DIR", "analytics_outputs"))


def _two_prop_test(
    test_id: str,
    title: str,
    group_a_label: str,
    k_a: int,
    n_a: int,
    group_b_label: str,
    k_b: int,
    n_b: int,
    causal_note: str,
) -> dict[str, Any]:
    rate_a = k_a / max(n_a, 1)
    rate_b = k_b / max(n_b, 1)
    z_stat, p_val = proportions_ztest([k_a, k_b], [n_a, n_b])
    ci_lo, ci_hi = confint_proportions_2indep(k_a, n_a, k_b, n_b, method="wald")
    diff_pp = (rate_a - rate_b) * 100.0
    return {
        "test_id": test_id,
        "title": title,
        "method": "Two-Proportion Z-Test (Two-Sided)",
        "group_a": {"label": group_a_label, "successes": int(k_a), "n": int(n_a), "rate_pct": round(rate_a * 100, 2)},
        "group_b": {"label": group_b_label, "successes": int(k_b), "n": int(n_b), "rate_pct": round(rate_b * 100, 2)},
        "difference_pp": round(diff_pp, 2),
        "ci_95_pp": [round(float(ci_lo) * 100, 2), round(float(ci_hi) * 100, 2)],
        "z_statistic": round(float(z_stat), 3),
        "p_value": float(f"{p_val:.4e}") if p_val < 0.0001 else round(float(p_val), 5),
        "statistically_significant_95": bool(p_val < 0.05),
        "evidence_type": "Observational Correlation (Non-Causal)",
        "causal_caveat": causal_note,
    }


def run_statistical_tests(database_url: str = DATABASE_URL) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(database_url) as conn:
        # 1. Subscription vs Non-Subscription 90-day repeat purchase rate (eligible first-time buyers <= 2026-07-31)
        sub_df = pd.read_sql_query(
            """
            SELECT
                is_subscriber,
                COUNT(*) AS n_buyers,
                COUNT(*) FILTER (WHERE delivered_orders >= 2) AS repeat_buyers,
                AVG(delivered_orders)::FLOAT AS avg_orders,
                AVG(lifetime_net_revenue)::FLOAT AS avg_ltv
            FROM mv_customer_lifecycle
            WHERE first_delivered_date IS NOT NULL
              AND first_delivered_date <= DATE '2026-07-31'
            GROUP BY is_subscriber;
            """,
            conn,
        )

        # Distribution for Mann-Whitney U on lifetime orders & AOV
        sub_orders_df = pd.read_sql_query(
            """
            SELECT is_subscriber, delivered_orders, avg_order_value
            FROM mv_customer_lifecycle
            WHERE first_delivered_date IS NOT NULL
              AND first_delivered_date <= DATE '2026-07-31';
            """,
            conn,
        )

        # 2. Mobile Web vs Native App Cart-to-Checkout conversion
        dev_df = pd.read_sql_query(
            """
            SELECT
                CASE WHEN device_type IN ('Android App', 'iOS App') THEN 'Native App' ELSE device_type END AS dev_group,
                SUM(reached_cart) AS cart_sessions,
                SUM(reached_checkout) AS checkout_sessions
            FROM mv_session_funnel
            WHERE device_type IN ('Android App', 'iOS App', 'Mobile Web')
            GROUP BY 1;
            """,
            conn,
        )

        # 3. Q2 2026 (Apr-Jun 2026) vs Baseline (Oct 2025 - Feb 2026) M1 cohort retention
        coh_df = pd.read_sql_query(
            """
            WITH cust_first AS (
                SELECT customer_id, cohort_month
                FROM mv_customer_lifecycle
                WHERE cohort_month IN ('2025-10','2025-11','2025-12','2026-01','2026-02','2026-04','2026-05','2026-06')
            ),
            m1_active AS (
                SELECT DISTINCT
                    cf.customer_id
                FROM cust_first cf
                JOIN orders o ON o.customer_id = cf.customer_id AND o.order_status = 'delivered'
                JOIN calendar_dimension cal ON cal.date_key = o.order_date
                WHERE (
                    (EXTRACT(YEAR FROM TO_DATE(cal.year_month || '-01', 'YYYY-MM-DD')) - EXTRACT(YEAR FROM TO_DATE(cf.cohort_month || '-01', 'YYYY-MM-DD'))) * 12
                    + (EXTRACT(MONTH FROM TO_DATE(cal.year_month || '-01', 'YYYY-MM-DD')) - EXTRACT(MONTH FROM TO_DATE(cf.cohort_month || '-01', 'YYYY-MM-DD')))
                ) = 1
            )
            SELECT
                CASE WHEN cf.cohort_month IN ('2026-04','2026-05','2026-06') THEN 'Q2_2026' ELSE 'Baseline' END AS cohort_group,
                COUNT(*) AS cohort_size,
                COUNT(m1.customer_id) AS m1_retained
            FROM cust_first cf
            LEFT JOIN m1_active m1 ON m1.customer_id = cf.customer_id
            GROUP BY 1;
            """,
            conn,
        )

        # 4. Tier 3 vs Tier 1 cancellation rates
        tier_df = pd.read_sql_query(
            """
            SELECT
                city_tier,
                COUNT(*) FILTER (WHERE NOT is_duplicate_attempt) AS total_orders,
                COUNT(*) FILTER (WHERE order_status = 'cancelled' AND NOT is_duplicate_attempt) AS cancelled_orders
            FROM orders
            WHERE city_tier IN ('Tier 1', 'Tier 3')
            GROUP BY city_tier;
            """,
            conn,
        )

        # 5. Chronic vs Non-Chronic first-order category repeat purchase rate
        cat_df = pd.read_sql_query(
            """
            SELECT
                mc.is_chronic_refill,
                COUNT(*) AS n_buyers,
                COUNT(*) FILTER (WHERE cl.delivered_orders >= 2) AS repeat_buyers
            FROM mv_customer_lifecycle cl
            JOIN medicine_categories mc ON mc.category_id = cl.first_order_category_id
            WHERE cl.first_delivered_date IS NOT NULL
              AND cl.first_delivered_date <= DATE '2026-07-31'
            GROUP BY mc.is_chronic_refill;
            """,
            conn,
        )

    tests_out: list[dict[str, Any]] = []

    # Test 1: Subscription vs Non-Subscription repeat rate
    sub_yes = sub_df[sub_df["is_subscriber"] == True].iloc[0]
    sub_no = sub_df[sub_df["is_subscriber"] == False].iloc[0]
    tests_out.append(
        _two_prop_test(
            "sub_vs_nonsub_repeat",
            "Subscription vs Non-Subscription Repeat Purchase Rate (Mature Buyers)",
            "Subscribers",
            int(sub_yes["repeat_buyers"]),
            int(sub_yes["n_buyers"]),
            "Non-Subscribers",
            int(sub_no["repeat_buyers"]),
            int(sub_no["n_buyers"]),
            "Strong selection bias exists: customers with ongoing chronic refill needs self-select into subscriptions. "
            "Observational parity proves association, not causal lift; run a randomized subscription-nudge holdout to measure causal incremental retention.",
        )
    )

    # Test 2: Mobile Web vs Native App Cart->Checkout conversion
    dev_app = dev_df[dev_df["dev_group"] == "Native App"].iloc[0]
    dev_mw = dev_df[dev_df["dev_group"] == "Mobile Web"].iloc[0]
    tests_out.append(
        _two_prop_test(
            "mobile_web_vs_app_checkout",
            "Native App vs Mobile Web Cart-to-Checkout Progression Rate",
            "Native App (Android/iOS)",
            int(dev_app["checkout_sessions"]),
            int(dev_app["cart_sessions"]),
            "Mobile Web",
            int(dev_mw["checkout_sessions"]),
            int(dev_mw["cart_sessions"]),
            "Partly reflects user intent mix (returning refillers skew toward Native App while paid/social new visitors skew toward Mobile Web), "
            "combined with Mobile Web authentication and checkout UX friction. Validate UX fixes via A/B test on Mobile Web checkout.",
        )
    )

    # Test 3: Q2 2026 vs Baseline M1 cohort retention
    q2 = coh_df[coh_df["cohort_group"] == "Q2_2026"].iloc[0]
    base = coh_df[coh_df["cohort_group"] == "Baseline"].iloc[0]
    tests_out.append(
        _two_prop_test(
            "q2_2026_vs_baseline_m1",
            "Q2 2026 Cohorts (Apr–Jun) vs Baseline (Oct–Feb) Month-1 Retention",
            "Q2 2026 Cohorts",
            int(q2["m1_retained"]),
            int(q2["cohort_size"]),
            "Baseline Cohorts (Oct–Feb)",
            int(base["m1_retained"]),
            int(base["cohort_size"]),
            "Coincides with aggressive Q2 Social Media (SPRINGBLITZ) and Affiliate (AFFILFLASH) 22–25% discount acquisition campaigns "
            "that shifted channel mix toward promo-sensitive one-time buyers.",
        )
    )

    # Test 4: Tier 3 vs Tier 1 Cancellation Rate
    t3 = tier_df[tier_df["city_tier"] == "Tier 3"].iloc[0]
    t1 = tier_df[tier_df["city_tier"] == "Tier 1"].iloc[0]
    tests_out.append(
        _two_prop_test(
            "tier3_vs_tier1_cancellations",
            "Tier 3 Cities (Lucknow, Indore) vs Tier 1 Cities Order Cancellation Rate",
            "Tier 3 Cities",
            int(t3["cancelled_orders"]),
            int(t3["total_orders"]),
            "Tier 1 Cities",
            int(t1["cancelled_orders"]),
            int(t1["total_orders"]),
            "Driven by longer promised and actual delivery SLAs (4+ days), higher Cash-on-Delivery share, and monsoon transit bottlenecks rather than city demand alone.",
        )
    )

    # Test 5: Chronic vs Non-Chronic First-Category Repeat Rate
    ch_y = cat_df[cat_df["is_chronic_refill"] == True].iloc[0]
    ch_n = cat_df[cat_df["is_chronic_refill"] == False].iloc[0]
    tests_out.append(
        _two_prop_test(
            "chronic_vs_nonchronic_repeat",
            "Chronic Refill Categories vs Non-Chronic First-Order Repeat Rate",
            "Chronic Refill First Category",
            int(ch_y["repeat_buyers"]),
            int(ch_y["n_buyers"]),
            "Acute / Wellness / Devices First Category",
            int(ch_n["repeat_buyers"]),
            int(ch_n["n_buyers"]),
            "Reflects intrinsic replenishment frequency of ongoing healthcare needs versus episodic acute purchases.",
        )
    )

    # Continuous comparison: Mann-Whitney U + Welch's t-test on Subscription vs Non-Subscription orders & AOV
    g_sub_ord = sub_orders_df.loc[sub_orders_df["is_subscriber"] == True, "delivered_orders"].to_numpy()
    g_non_ord = sub_orders_df.loc[sub_orders_df["is_subscriber"] == False, "delivered_orders"].to_numpy()
    u_stat, u_p = stats.mannwhitneyu(g_sub_ord, g_non_ord, alternative="two-sided")
    t_stat, t_p = stats.ttest_ind(g_sub_ord, g_non_ord, equal_var=False)

    continuous_tests = [
        {
            "test_id": "sub_vs_nonsub_orders_per_customer",
            "title": "Delivered Orders per Customer: Subscribers vs Non-Subscribers (Mature Buyers)",
            "method": "Mann-Whitney U & Welch's Two-Sample t-Test",
            "subscriber_mean": round(float(np.mean(g_sub_ord)), 2),
            "subscriber_median": round(float(np.median(g_sub_ord)), 2),
            "non_subscriber_mean": round(float(np.mean(g_non_ord)), 2),
            "non_subscriber_median": round(float(np.median(g_non_ord)), 2),
            "ratio_mean": round(float(np.mean(g_sub_ord) / max(np.mean(g_non_ord), 1e-9)), 2),
            "mann_whitney_u": round(float(u_stat), 1),
            "mann_whitney_p": float(f"{u_p:.4e}") if u_p < 0.0001 else round(float(u_p), 5),
            "welch_t": round(float(t_stat), 3),
            "welch_p": float(f"{t_p:.4e}") if t_p < 0.0001 else round(float(t_p), 5),
            "statistically_significant_95": bool(u_p < 0.05 and t_p < 0.05),
            "evidence_type": "Observational Association (Selection Bias Present)",
        }
    ]

    result = {
        "proportion_tests": tests_out,
        "continuous_tests": continuous_tests,
    }
    out_path = OUTPUT_DIR / "statistical_tests.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[stats] Executed {len(tests_out)} proportion Z-tests and {len(continuous_tests)} continuous comparisons.")
    return result


if __name__ == "__main__":
    run_statistical_tests()
