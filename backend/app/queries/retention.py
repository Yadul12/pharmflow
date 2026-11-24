from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.database import fetch_all, fetch_one
from app.queries.filters import AnalyticsFilter, build_customer_where, build_order_where


def get_retention_analytics(f: AnalyticsFilter) -> dict[str, Any]:
    f = f.normalized()
    cw, cp = build_customer_where(f, alias="cl")
    ow, op = build_order_where(f, alias="o")

    end_d = f.end_date
    d1_cutoff = end_d - timedelta(days=1)
    d7_cutoff = end_d - timedelta(days=7)
    d30_cutoff = end_d - timedelta(days=30)
    d60_cutoff = end_d - timedelta(days=60)
    d90_cutoff = end_d - timedelta(days=90)

    # 1. D1 / D7 Session Engagement Retention (eligible signed-up customers)
    sess_ret = fetch_one(
        f"""
        WITH elig AS (
            SELECT
                cl.customer_id,
                cl.signup_date
            FROM mv_customer_lifecycle cl
            WHERE {cw}
              AND cl.signup_date BETWEEN %s AND %s
        ),
        ret_flags AS (
            SELECT
                e.customer_id,
                e.signup_date,
                BOOL_OR(s.session_date = e.signup_date + 1) AS returned_d1,
                BOOL_OR(s.session_date BETWEEN e.signup_date + 1 AND e.signup_date + 7) AS returned_d7,
                BOOL_OR(s.session_date BETWEEN e.signup_date + 1 AND e.signup_date + 30) AS returned_d30
            FROM elig e
            LEFT JOIN sessions s
                ON s.customer_id = e.customer_id
               AND s.session_date BETWEEN e.signup_date + 1 AND e.signup_date + 30
               AND s.session_date <= %s
            GROUP BY e.customer_id, e.signup_date
        )
        SELECT
            COUNT(*) FILTER (WHERE signup_date <= %s)::INT AS d1_eligible,
            COUNT(*) FILTER (WHERE signup_date <= %s AND returned_d1)::INT AS d1_retained,
            COUNT(*) FILTER (WHERE signup_date <= %s)::INT AS d7_eligible,
            COUNT(*) FILTER (WHERE signup_date <= %s AND returned_d7)::INT AS d7_retained,
            COUNT(*) FILTER (WHERE signup_date <= %s)::INT AS d30_sess_eligible,
            COUNT(*) FILTER (WHERE signup_date <= %s AND returned_d30)::INT AS d30_sess_retained
        FROM ret_flags;
        """,
        tuple(cp + [f.start_date, end_d, end_d, d1_cutoff, d1_cutoff, d7_cutoff, d7_cutoff, d30_cutoff, d30_cutoff]),
    )

    # 2. D30 / D60 / D90 First-Order Repeat Rates + Overall Repeat Purchase Rate + Inactivity
    ord_ret = fetch_one(
        f"""
        WITH buyers AS (
            SELECT
                cl.customer_id,
                cl.first_delivered_date,
                cl.second_delivered_date,
                cl.last_delivered_date,
                cl.delivered_orders,
                cl.avg_days_between_orders,
                cl.avg_order_value,
                cl.lifetime_net_revenue
            FROM mv_customer_lifecycle cl
            WHERE {cw}
              AND cl.first_delivered_date IS NOT NULL
              AND cl.first_delivered_date BETWEEN %s AND %s
        )
        SELECT
            COUNT(*)::INT AS total_buyers,
            COUNT(*) FILTER (WHERE delivered_orders >= 2)::INT AS repeat_buyers,
            COUNT(*) FILTER (WHERE first_delivered_date <= %s)::INT AS d30_eligible,
            COUNT(*) FILTER (WHERE first_delivered_date <= %s AND second_delivered_date IS NOT NULL AND (second_delivered_date - first_delivered_date) <= 30)::INT AS d30_repeat,
            COUNT(*) FILTER (WHERE first_delivered_date <= %s)::INT AS d60_eligible,
            COUNT(*) FILTER (WHERE first_delivered_date <= %s AND second_delivered_date IS NOT NULL AND (second_delivered_date - first_delivered_date) <= 60)::INT AS d60_repeat,
            COUNT(*) FILTER (WHERE first_delivered_date <= %s)::INT AS d90_eligible,
            COUNT(*) FILTER (WHERE first_delivered_date <= %s AND second_delivered_date IS NOT NULL AND (second_delivered_date - first_delivered_date) <= 90)::INT AS d90_repeat,
            COUNT(*) FILTER (WHERE first_delivered_date <= %s AND last_delivered_date < %s)::INT AS inactive_90d_buyers,
            COALESCE(AVG(delivered_orders), 0)::FLOAT AS avg_orders_per_customer,
            COALESCE(AVG(avg_days_between_orders) FILTER (WHERE avg_days_between_orders IS NOT NULL), 0)::FLOAT AS avg_days_between_orders,
            COALESCE(AVG(avg_order_value), 0)::FLOAT AS avg_order_value,
            COALESCE(AVG(lifetime_net_revenue), 0)::FLOAT AS avg_customer_ltv
        FROM buyers;
        """,
        tuple(
            cp
            + [
                f.start_date, end_d,
                d30_cutoff, d30_cutoff,
                d60_cutoff, d60_cutoff,
                d90_cutoff, d90_cutoff,
                d90_cutoff, d90_cutoff,
            ]
        ),
    )

    # 3. Monthly New vs Returning Buyers + Monthly Reactivation (prior gap >= 90 days)
    monthly_new_returning = fetch_all(
        f"""
        WITH ordered_deliv AS (
            SELECT
                o.customer_id,
                o.order_date,
                cal.year_month,
                o.net_amount,
                ROW_NUMBER() OVER (PARTITION BY o.customer_id ORDER BY o.order_ts, o.order_id) AS ord_seq,
                LAG(o.order_date) OVER (PARTITION BY o.customer_id ORDER BY o.order_ts, o.order_id) AS prev_order_date
            FROM orders o
            JOIN calendar_dimension cal ON cal.date_key = o.order_date
            WHERE o.order_status = 'delivered'
              AND ({ow.replace('o.order_date BETWEEN %s AND %s', '1=1')})
        ),
        in_range AS (
            SELECT *
            FROM ordered_deliv
            WHERE order_date BETWEEN %s AND %s
        ),
        monthly_react AS (
            SELECT
                year_month,
                COUNT(DISTINCT customer_id) FILTER (WHERE ord_seq = 1)::INT AS new_customers,
                COUNT(DISTINCT customer_id) FILTER (WHERE ord_seq > 1)::INT AS returning_customers,
                COUNT(DISTINCT customer_id) FILTER (
                    WHERE prev_order_date IS NOT NULL
                      AND prev_order_date < (DATE_TRUNC('month', order_date)::DATE - INTERVAL '90 days')
                )::INT AS reactivated_customers,
                ROUND(COALESCE(SUM(net_amount) FILTER (WHERE ord_seq = 1), 0)::NUMERIC, 2)::FLOAT AS new_customer_revenue,
                ROUND(COALESCE(SUM(net_amount) FILTER (WHERE ord_seq > 1), 0)::NUMERIC, 2)::FLOAT AS returning_customer_revenue
            FROM in_range
            GROUP BY year_month
        ),
        months AS (
            SELECT DISTINCT year_month, MIN(date_key) AS month_start
            FROM calendar_dimension
            WHERE date_key BETWEEN %s AND %s
            GROUP BY year_month
        ),
        inactive_pool AS (
            SELECT
                m.year_month,
                COUNT(DISTINCT cl.customer_id)::INT AS eligible_inactive_pool
            FROM months m
            JOIN mv_customer_lifecycle cl
              ON cl.first_delivered_date < (m.month_start - INTERVAL '90 days')
             AND ({cw})
            WHERE NOT EXISTS (
                SELECT 1
                FROM orders ox
                WHERE ox.customer_id = cl.customer_id
                  AND ox.order_status = 'delivered'
                  AND ox.order_date >= (m.month_start - INTERVAL '90 days')
                  AND ox.order_date < m.month_start
            )
            GROUP BY m.year_month
        )
        SELECT
            mr.year_month,
            mr.new_customers,
            mr.returning_customers,
            ROUND(100.0 * mr.returning_customers / NULLIF(mr.new_customers + mr.returning_customers, 0), 2)::FLOAT AS returning_share_pct,
            mr.new_customer_revenue,
            mr.returning_customer_revenue,
            mr.reactivated_customers,
            COALESCE(ip.eligible_inactive_pool, 0) AS eligible_inactive_pool,
            CASE
                WHEN COALESCE(ip.eligible_inactive_pool, 0) >= 25
                THEN ROUND(100.0 * mr.reactivated_customers / ip.eligible_inactive_pool, 2)::FLOAT
                ELSE NULL
            END AS reactivation_rate_pct
        FROM monthly_react mr
        LEFT JOIN inactive_pool ip ON ip.year_month = mr.year_month
        ORDER BY mr.year_month;
        """,
        tuple(op[2:] + [f.start_date, end_d, f.start_date, end_d] + cp),
    )

    # 4. Repeat-order frequency distribution
    order_freq_dist = fetch_all(
        f"""
        WITH buyers AS (
            SELECT
                cl.customer_id,
                cl.delivered_orders,
                cl.lifetime_net_revenue
            FROM mv_customer_lifecycle cl
            WHERE {cw}
              AND cl.first_delivered_date BETWEEN %s AND %s
        )
        SELECT
            CASE
                WHEN delivered_orders = 1 THEN '1 Order'
                WHEN delivered_orders = 2 THEN '2 Orders'
                WHEN delivered_orders = 3 THEN '3 Orders'
                WHEN delivered_orders = 4 THEN '4 Orders'
                WHEN delivered_orders BETWEEN 5 AND 7 THEN '5–7 Orders'
                ELSE '8+ Orders'
            END AS order_bucket,
            MIN(delivered_orders) AS sort_key,
            COUNT(*)::INT AS customers,
            ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2)::FLOAT AS customer_share_pct,
            ROUND(SUM(lifetime_net_revenue)::NUMERIC, 2)::FLOAT AS total_revenue,
            ROUND(100.0 * SUM(lifetime_net_revenue) / NULLIF(SUM(SUM(lifetime_net_revenue)) OVER (), 0), 2)::FLOAT AS revenue_share_pct
        FROM buyers
        GROUP BY 1
        ORDER BY sort_key;
        """,
        tuple(cp + [f.start_date, end_d]),
    )

    # 5. Inter-order gap distribution (days between consecutive delivered orders)
    inter_order_gaps = fetch_all(
        f"""
        WITH gaps AS (
            SELECT
                (o.order_date - LAG(o.order_date) OVER (PARTITION BY o.customer_id ORDER BY o.order_ts, o.order_id))::INT AS gap_days
            FROM orders o
            WHERE o.order_status = 'delivered'
              AND {ow}
        )
        SELECT
            CASE
                WHEN gap_days <= 15 THEN '0–15 Days'
                WHEN gap_days <= 30 THEN '16–30 Days'
                WHEN gap_days <= 45 THEN '31–45 Days'
                WHEN gap_days <= 60 THEN '46–60 Days'
                WHEN gap_days <= 90 THEN '61–90 Days'
                ELSE '91+ Days'
            END AS gap_bucket,
            MIN(gap_days) AS sort_key,
            COUNT(*)::INT AS repeat_orders,
            ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2)::FLOAT AS share_pct
        FROM gaps
        WHERE gap_days IS NOT NULL
        GROUP BY 1
        ORDER BY sort_key;
        """,
        tuple(op),
    )

    # 6. Retention comparison by acquisition channel
    channel_retention = fetch_all(
        f"""
        SELECT
            cl.acquisition_channel,
            COUNT(*)::INT AS buyers,
            COUNT(*) FILTER (WHERE cl.delivered_orders >= 2)::INT AS repeat_buyers,
            ROUND(100.0 * COUNT(*) FILTER (WHERE cl.delivered_orders >= 2) / NULLIF(COUNT(*), 0), 2)::FLOAT AS repeat_rate_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE cl.first_delivered_date <= %s AND cl.second_delivered_date IS NOT NULL AND (cl.second_delivered_date - cl.first_delivered_date) <= 30) /
                NULLIF(COUNT(*) FILTER (WHERE cl.first_delivered_date <= %s), 0), 2)::FLOAT AS d30_repeat_pct,
            ROUND(AVG(cl.delivered_orders)::NUMERIC, 2)::FLOAT AS avg_orders,
            ROUND(AVG(cl.lifetime_net_revenue)::NUMERIC, 2)::FLOAT AS avg_ltv,
            ROUND(100.0 * COUNT(*) FILTER (WHERE cl.is_subscriber) / NULLIF(COUNT(*), 0), 2)::FLOAT AS subscriber_share_pct
        FROM mv_customer_lifecycle cl
        WHERE {cw}
          AND cl.first_delivered_date BETWEEN %s AND %s
        GROUP BY cl.acquisition_channel
        ORDER BY repeat_rate_pct DESC;
        """,
        tuple(cp + [d30_cutoff, d30_cutoff, f.start_date, end_d]),
    )

    d1_el = int(sess_ret.get("d1_eligible") or 0)
    d7_el = int(sess_ret.get("d7_eligible") or 0)
    d30s_el = int(sess_ret.get("d30_sess_eligible") or 0)
    d30_el = int(ord_ret.get("d30_eligible") or 0)
    d60_el = int(ord_ret.get("d60_eligible") or 0)
    d90_el = int(ord_ret.get("d90_eligible") or 0)
    tot_buyers = int(ord_ret.get("total_buyers") or 0)

    react_rates = [r["reactivation_rate_pct"] for r in monthly_new_returning if r.get("reactivation_rate_pct") is not None and r["eligible_inactive_pool"] > 0]
    avg_react = round(sum(react_rates) / len(react_rates), 2) if react_rates else 0.0

    kpis = {
        "d1_session_retention_pct": round(100.0 * int(sess_ret.get("d1_retained") or 0) / max(d1_el, 1), 2),
        "d1_eligible_customers": d1_el,
        "d7_session_retention_pct": round(100.0 * int(sess_ret.get("d7_retained") or 0) / max(d7_el, 1), 2),
        "d7_eligible_customers": d7_el,
        "d30_session_retention_pct": round(100.0 * int(sess_ret.get("d30_sess_retained") or 0) / max(d30s_el, 1), 2),
        "d30_order_repeat_pct": round(100.0 * int(ord_ret.get("d30_repeat") or 0) / max(d30_el, 1), 2),
        "d30_eligible_buyers": d30_el,
        "d60_order_repeat_pct": round(100.0 * int(ord_ret.get("d60_repeat") or 0) / max(d60_el, 1), 2),
        "d90_order_repeat_pct": round(100.0 * int(ord_ret.get("d90_repeat") or 0) / max(d90_el, 1), 2),
        "d90_eligible_buyers": d90_el,
        "overall_repeat_purchase_rate_pct": round(100.0 * int(ord_ret.get("repeat_buyers") or 0) / max(tot_buyers, 1), 2),
        "total_buyers": tot_buyers,
        "repeat_buyers": int(ord_ret.get("repeat_buyers") or 0),
        "inactivity_90d_pct": round(100.0 * int(ord_ret.get("inactive_90d_buyers") or 0) / max(d90_el, 1), 2),
        "inactive_90d_buyers": int(ord_ret.get("inactive_90d_buyers") or 0),
        "avg_monthly_reactivation_rate_pct": avg_react,
        "avg_orders_per_customer": round(float(ord_ret.get("avg_orders_per_customer") or 0.0), 2),
        "avg_days_between_orders": round(float(ord_ret.get("avg_days_between_orders") or 0.0), 1),
        "avg_order_value": round(float(ord_ret.get("avg_order_value") or 0.0), 2),
        "avg_customer_ltv": round(float(ord_ret.get("avg_customer_ltv") or 0.0), 2),
    }

    return {
        "filters": f.to_dict(),
        "kpis": kpis,
        "monthly_new_returning": monthly_new_returning,
        "order_frequency_distribution": order_freq_dist,
        "inter_order_gaps": inter_order_gaps,
        "channel_retention": channel_retention,
    }
