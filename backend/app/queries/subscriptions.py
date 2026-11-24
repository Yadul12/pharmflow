from __future__ import annotations

import json
from typing import Any

from app.config import ANALYTICS_OUTPUT_DIR
from app.database import fetch_all, fetch_one
from app.queries.filters import AnalyticsFilter, build_customer_where


def get_subscription_analytics(f: AnalyticsFilter) -> dict[str, Any]:
    f = f.normalized()
    cw, cp = build_customer_where(f, alias="cl")

    # Build filtered subscription filter
    sub_clauses = ["s.start_date <= %s"]
    sub_params: list[Any] = [f.end_date]
    if f.city:
        sub_clauses.append("cl.primary_city = %s")
        sub_params.append(f.city)
    if f.city_tier:
        sub_clauses.append("cl.city_tier = %s")
        sub_params.append(f.city_tier)
    if f.channel:
        sub_clauses.append("cl.acquisition_channel = %s")
        sub_params.append(f.channel)
    if f.device:
        sub_clauses.append("cl.primary_device = %s")
        sub_params.append(f.device)
    if f.category_id is not None:
        sub_clauses.append("s.primary_category_id = %s")
        sub_params.append(f.category_id)
    sw = " AND ".join(sub_clauses)

    # 1. Core Subscription KPIs
    sub_kpis = fetch_one(
        f"""
        WITH filt_subs AS (
            SELECT s.*
            FROM subscriptions s
            JOIN mv_customer_lifecycle cl ON cl.customer_id = s.customer_id
            WHERE {sw}
        ),
        evt_stats AS (
            SELECT
                COUNT(*) FILTER (WHERE se.event_type = 'renewed' AND se.event_date BETWEEN %s AND %s)::INT AS renewals_in_period,
                COUNT(*) FILTER (WHERE se.event_type = 'cancelled' AND se.event_date BETWEEN %s AND %s)::INT AS cancellations_in_period,
                COUNT(*) FILTER (WHERE se.event_type = 'payment_retry_failed' AND se.event_date BETWEEN %s AND %s)::INT AS payment_failures_in_period,
                ROUND(AVG(se.days_since_prev_event) FILTER (WHERE se.event_type = 'renewed' AND se.days_since_prev_event IS NOT NULL)::NUMERIC, 1)::FLOAT AS avg_renewal_interval_days,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY se.days_since_prev_event) FILTER (WHERE se.event_type = 'renewed' AND se.days_since_prev_event IS NOT NULL)::NUMERIC, 1)::FLOAT AS median_renewal_interval_days
            FROM subscription_events se
            JOIN filt_subs fs ON fs.subscription_id = se.subscription_id
        ),
        ord_stats AS (
            SELECT
                COUNT(*) FILTER (WHERE o.order_status = 'delivered' AND o.subscription_id IS NOT NULL)::INT AS sub_refill_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'delivered')::INT AS total_delivered_orders,
                COALESCE(SUM(o.net_amount) FILTER (WHERE o.order_status = 'delivered' AND o.subscription_id IS NOT NULL), 0)::NUMERIC AS sub_refill_revenue,
                COALESCE(SUM(o.net_amount) FILTER (WHERE o.order_status = 'delivered'), 0)::NUMERIC AS total_delivered_revenue
            FROM orders o
            JOIN mv_customer_lifecycle cl ON cl.customer_id = o.customer_id
            WHERE {cw}
              AND o.order_date BETWEEN %s AND %s
              AND (%s::INT IS NULL OR o.primary_category_id = %s::INT)
        )
        SELECT
            (SELECT COUNT(*)::INT FROM filt_subs) AS total_subscriptions,
            (SELECT COUNT(*) FILTER (WHERE status = 'active')::INT FROM filt_subs) AS active_subscriptions,
            (SELECT COUNT(*) FILTER (WHERE status = 'paused')::INT FROM filt_subs) AS paused_subscriptions,
            (SELECT COUNT(*) FILTER (WHERE status = 'cancelled')::INT FROM filt_subs) AS cancelled_subscriptions,
            (SELECT ROUND(COALESCE(SUM(monthly_plan_value) FILTER (WHERE status = 'active'), 0)::NUMERIC, 2)::FLOAT FROM filt_subs) AS active_mrr,
            (SELECT ROUND(COALESCE(AVG(monthly_plan_value), 0)::NUMERIC, 2)::FLOAT FROM filt_subs) AS avg_monthly_plan_value,
            es.renewals_in_period,
            es.cancellations_in_period,
            es.payment_failures_in_period,
            es.avg_renewal_interval_days,
            es.median_renewal_interval_days,
            os.sub_refill_orders,
            ROUND(100.0 * os.sub_refill_orders / NULLIF(os.total_delivered_orders, 0), 2)::FLOAT AS sub_order_share_pct,
            ROUND(os.sub_refill_revenue::NUMERIC, 2)::FLOAT AS sub_refill_revenue,
            ROUND(100.0 * os.sub_refill_revenue / NULLIF(os.total_delivered_revenue, 0), 2)::FLOAT AS sub_revenue_share_pct
        FROM evt_stats es CROSS JOIN ord_stats os;
        """,
        tuple(
            sub_params
            + [f.start_date, f.end_date, f.start_date, f.end_date, f.start_date, f.end_date]
            + cp
            + [f.start_date, f.end_date, f.category_id, f.category_id]
        ),
    )

    renewals = int(sub_kpis.get("renewals_in_period") or 0)
    cancels_in_p = int(sub_kpis.get("cancellations_in_period") or 0)
    tot_subs = int(sub_kpis.get("total_subscriptions") or 0)
    tot_cancelled = int(sub_kpis.get("cancelled_subscriptions") or 0)
    sub_kpis["cycle_renewal_rate_pct"] = round(100.0 * renewals / max(renewals + cancels_in_p, 1), 2)
    sub_kpis["cumulative_cancellation_rate_pct"] = round(100.0 * tot_cancelled / max(tot_subs, 1), 2)

    # 2. Monthly Subscription Lifecycle Trend
    monthly_lifecycle = fetch_all(
        f"""
        WITH filt_subs AS (
            SELECT s.subscription_id
            FROM subscriptions s
            JOIN mv_customer_lifecycle cl ON cl.customer_id = s.customer_id
            WHERE {sw}
        )
        SELECT
            cal.year_month,
            COUNT(*) FILTER (WHERE se.event_type = 'created')::INT AS new_subscriptions,
            COUNT(*) FILTER (WHERE se.event_type = 'renewed')::INT AS renewals,
            COUNT(*) FILTER (WHERE se.event_type = 'paused')::INT AS pauses,
            COUNT(*) FILTER (WHERE se.event_type = 'cancelled')::INT AS cancellations,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE se.event_type = 'renewed') /
                NULLIF(COUNT(*) FILTER (WHERE se.event_type IN ('renewed', 'cancelled')), 0),
                2
            )::FLOAT AS monthly_renewal_rate_pct
        FROM subscription_events se
        JOIN filt_subs fs ON fs.subscription_id = se.subscription_id
        JOIN calendar_dimension cal ON cal.date_key = se.event_date
        WHERE se.event_date BETWEEN %s AND %s
        GROUP BY cal.year_month
        ORDER BY cal.year_month;
        """,
        tuple(sub_params + [f.start_date, f.end_date]),
    )

    # 3. Subscription vs Non-Subscription Retention Curve (M0..M6) on mature buyers
    retention_comparison = fetch_all(
        f"""
        WITH buyers AS (
            SELECT
                cl.customer_id,
                cl.is_subscriber,
                cl.cohort_month,
                TO_DATE(cl.cohort_month || '-01', 'YYYY-MM-DD') AS cohort_start
            FROM mv_customer_lifecycle cl
            WHERE {cw}
              AND cl.cohort_month IS NOT NULL
              AND cl.first_delivered_date BETWEEN %s AND %s
        ),
        offsets AS (
            SELECT generate_series(0, 6) AS month_offset
        ),
        elig AS (
            SELECT
                b.is_subscriber,
                o.month_offset,
                COUNT(*)::INT AS eligible_customers
            FROM buyers b
            CROSS JOIN offsets o
            WHERE (b.cohort_start + (o.month_offset || ' months')::INTERVAL)::DATE <= TO_DATE(%s || '-01', 'YYYY-MM-DD')
            GROUP BY b.is_subscriber, o.month_offset
        ),
        active AS (
            SELECT
                b.is_subscriber,
                (
                    (EXTRACT(YEAR FROM TO_DATE(cal.year_month || '-01', 'YYYY-MM-DD')) - EXTRACT(YEAR FROM b.cohort_start)) * 12
                    + (EXTRACT(MONTH FROM TO_DATE(cal.year_month || '-01', 'YYYY-MM-DD')) - EXTRACT(MONTH FROM b.cohort_start))
                )::INT AS month_offset,
                COUNT(DISTINCT ord.customer_id)::INT AS retained_customers
            FROM buyers b
            JOIN orders ord ON ord.customer_id = b.customer_id AND ord.order_status = 'delivered' AND ord.order_date <= %s
            JOIN calendar_dimension cal ON cal.date_key = ord.order_date
            GROUP BY 1, 2
        )
        SELECT
            e.month_offset,
            'M' || e.month_offset AS label,
            MAX(CASE WHEN e.is_subscriber THEN ROUND(100.0 * COALESCE(a.retained_customers, 0) / NULLIF(e.eligible_customers, 0), 2) END)::FLOAT AS subscriber_retention_pct,
            MAX(CASE WHEN NOT e.is_subscriber THEN ROUND(100.0 * COALESCE(a.retained_customers, 0) / NULLIF(e.eligible_customers, 0), 2) END)::FLOAT AS non_subscriber_retention_pct,
            MAX(CASE WHEN e.is_subscriber THEN e.eligible_customers END)::INT AS subscriber_n,
            MAX(CASE WHEN NOT e.is_subscriber THEN e.eligible_customers END)::INT AS non_subscriber_n
        FROM elig e
        LEFT JOIN active a
          ON a.is_subscriber = e.is_subscriber
         AND a.month_offset = e.month_offset
        GROUP BY e.month_offset
        ORDER BY e.month_offset;
        """,
        tuple(cp + [f.start_date, f.end_date, f.end_date.strftime("%Y-%m"), f.end_date]),
    )

    # 4. Subscriber vs Non-Subscriber Commercial Summary
    sub_vs_nonsub_summary = fetch_all(
        f"""
        SELECT
            CASE WHEN cl.is_subscriber THEN 'Subscribers' ELSE 'Non-Subscribers' END AS cohort_group,
            COUNT(*)::INT AS buyers,
            ROUND(100.0 * COUNT(*) FILTER (WHERE cl.delivered_orders >= 2) / NULLIF(COUNT(*), 0), 2)::FLOAT AS repeat_purchase_rate_pct,
            ROUND(AVG(cl.delivered_orders)::NUMERIC, 2)::FLOAT AS avg_orders_per_customer,
            ROUND(AVG(cl.avg_order_value)::NUMERIC, 2)::FLOAT AS avg_order_value,
            ROUND(AVG(cl.lifetime_net_revenue)::NUMERIC, 2)::FLOAT AS avg_ltv,
            ROUND(AVG(cl.avg_days_between_orders) FILTER (WHERE cl.avg_days_between_orders IS NOT NULL)::NUMERIC, 1)::FLOAT AS avg_days_between_orders
        FROM mv_customer_lifecycle cl
        WHERE {cw}
          AND cl.first_delivered_date BETWEEN %s AND %s
        GROUP BY 1
        ORDER BY avg_ltv DESC;
        """,
        tuple(cp + [f.start_date, f.end_date]),
    )

    # 5. Category Subscription Performance
    by_category = fetch_all(
        f"""
        SELECT
            mc.category_name,
            COUNT(*)::INT AS total_subscriptions,
            COUNT(*) FILTER (WHERE s.status = 'active')::INT AS active_subscriptions,
            COUNT(*) FILTER (WHERE s.status = 'cancelled')::INT AS cancelled_subscriptions,
            ROUND(100.0 * COUNT(*) FILTER (WHERE s.status = 'cancelled') / NULLIF(COUNT(*), 0), 2)::FLOAT AS cancel_rate_pct,
            ROUND(AVG(s.plan_cadence_days)::NUMERIC, 1)::FLOAT AS avg_cadence_days,
            ROUND(SUM(s.monthly_plan_value) FILTER (WHERE s.status = 'active')::NUMERIC, 2)::FLOAT AS active_mrr
        FROM subscriptions s
        JOIN medicine_categories mc ON mc.category_id = s.primary_category_id
        JOIN mv_customer_lifecycle cl ON cl.customer_id = s.customer_id
        WHERE {sw}
        GROUP BY mc.category_name
        ORDER BY active_subscriptions DESC;
        """,
        tuple(sub_params),
    )

    # 6. Renewal Timing vs Plan Cadence
    renewal_timing = fetch_all(
        f"""
        SELECT
            s.plan_cadence_days,
            COUNT(*)::INT AS renewal_events,
            ROUND(AVG(se.days_since_prev_event)::NUMERIC, 2)::FLOAT AS avg_actual_days,
            ROUND(AVG(se.days_since_prev_event - s.plan_cadence_days)::NUMERIC, 2)::FLOAT AS avg_variance_days,
            ROUND(100.0 * COUNT(*) FILTER (WHERE se.days_since_prev_event <= s.plan_cadence_days + 1) / NULLIF(COUNT(*), 0), 2)::FLOAT AS on_time_renewal_pct
        FROM subscription_events se
        JOIN subscriptions s ON s.subscription_id = se.subscription_id
        JOIN mv_customer_lifecycle cl ON cl.customer_id = s.customer_id
        WHERE {sw}
          AND se.event_type = 'renewed'
          AND se.days_since_prev_event IS NOT NULL
        GROUP BY s.plan_cadence_days
        ORDER BY s.plan_cadence_days;
        """,
        tuple(sub_params),
    )

    # 7. Subscription Cancel Reasons
    cancel_reasons = fetch_all(
        f"""
        SELECT
            COALESCE(s.cancel_reason, 'Unspecified') AS cancel_reason,
            COUNT(*)::INT AS cancellations,
            ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2)::FLOAT AS share_pct,
            ROUND(AVG(s.cancelled_date - s.start_date)::NUMERIC, 1)::FLOAT AS avg_tenure_days
        FROM subscriptions s
        JOIN mv_customer_lifecycle cl ON cl.customer_id = s.customer_id
        WHERE {sw}
          AND s.status = 'cancelled'
        GROUP BY 1
        ORDER BY cancellations DESC;
        """,
        tuple(sub_params),
    )

    # Attach SciPy statistical test evidence
    stats_file = ANALYTICS_OUTPUT_DIR / "statistical_tests.json"
    sub_stat_tests = []
    if stats_file.exists():
        raw_st = json.loads(stats_file.read_text(encoding="utf-8"))
        for t in raw_st.get("proportion_tests", []):
            if t["test_id"] == "sub_vs_nonsub_repeat":
                sub_stat_tests.append(t)
        for t in raw_st.get("continuous_tests", []):
            if t["test_id"] == "sub_vs_nonsub_orders_per_customer":
                sub_stat_tests.append(t)

    return {
        "filters": f.to_dict(),
        "kpis": sub_kpis,
        "monthly_lifecycle": monthly_lifecycle,
        "retention_comparison": retention_comparison,
        "subscriber_vs_non_subscriber": sub_vs_nonsub_summary,
        "by_category": by_category,
        "renewal_timing": renewal_timing,
        "cancel_reasons": cancel_reasons,
        "statistical_evidence": sub_stat_tests,
    }
