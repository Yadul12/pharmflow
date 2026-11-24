from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.config import DATASET_START
from app.database import fetch_all, fetch_one
from app.queries.filters import AnalyticsFilter, build_order_where, build_session_where


def _pct_change(curr: float, prev: float) -> float | None:
    if prev is None or prev == 0:
        return None
    return round(((curr - prev) / abs(prev)) * 100.0, 2)


def _pp_change(curr: float, prev: float) -> float | None:
    if prev is None:
        return None
    return round(curr - prev, 2)


def _compute_period_kpis(f: AnalyticsFilter, start_d: date, end_d: date) -> dict[str, Any]:
    sw, sp = build_session_where(f, alias="sf", start_override=start_d, end_override=end_d)
    ow, op = build_order_where(f, alias="o", start_override=start_d, end_override=end_d)

    sess_row = fetch_one(
        f"""
        SELECT
            COUNT(*)::BIGINT AS total_sessions,
            COUNT(DISTINCT customer_id)::BIGINT AS active_visitors,
            COALESCE(SUM(reached_order_placed), 0)::BIGINT AS session_orders_placed,
            COALESCE(SUM(reached_order_delivered), 0)::BIGINT AS session_orders_delivered
        FROM mv_session_funnel sf
        WHERE {sw};
        """,
        tuple(sp),
    )

    ord_row = fetch_one(
        f"""
        WITH filtered_orders AS (
            SELECT *
            FROM orders o
            WHERE {ow}
        ),
        buyer_counts AS (
            SELECT
                customer_id,
                COUNT(*) AS deliv_cnt
            FROM filtered_orders
            WHERE order_status = 'delivered'
            GROUP BY customer_id
        )
        SELECT
            COUNT(*) FILTER (WHERE NOT is_duplicate_attempt)::BIGINT AS total_placed_orders,
            COUNT(*) FILTER (WHERE order_status = 'delivered')::BIGINT AS delivered_orders,
            COUNT(*) FILTER (WHERE order_status = 'delivered' AND order_source = 'interactive_session')::BIGINT AS interactive_delivered_orders,
            COUNT(*) FILTER (WHERE order_status = 'delivered' AND order_source = 'subscription_auto_refill')::BIGINT AS sub_refill_delivered_orders,
            COUNT(*) FILTER (WHERE order_status = 'cancelled' AND NOT is_duplicate_attempt)::BIGINT AS cancelled_orders,
            COUNT(*) FILTER (WHERE order_status = 'returned')::BIGINT AS returned_orders,
            COUNT(*) FILTER (WHERE is_duplicate_attempt)::BIGINT AS duplicate_attempts,
            COALESCE(SUM(net_amount) FILTER (WHERE order_status = 'delivered'), 0)::FLOAT AS net_revenue,
            COALESCE(AVG(net_amount) FILTER (WHERE order_status = 'delivered'), 0)::FLOAT AS avg_order_value,
            (SELECT COUNT(*) FROM buyer_counts)::BIGINT AS ordering_customers,
            (SELECT COUNT(*) FROM buyer_counts WHERE deliv_cnt >= 2)::BIGINT AS repeat_customers_in_period
        FROM filtered_orders;
        """,
        tuple(op),
    )

    # Active subscriptions as of period end_d (filtered by city/channel/device/category if set)
    sub_clauses = ["s.start_date <= %s", "(s.cancelled_date IS NULL OR s.cancelled_date > %s)", "s.status IN ('active', 'paused')"]
    sub_params: list[Any] = [end_d, end_d]
    if f.city:
        sub_clauses.append("c.primary_city = %s")
        sub_params.append(f.city)
    if f.city_tier:
        sub_clauses.append("c.city_tier = %s")
        sub_params.append(f.city_tier)
    if f.channel:
        sub_clauses.append("c.acquisition_channel = %s")
        sub_params.append(f.channel)
    if f.device:
        sub_clauses.append("c.primary_device = %s")
        sub_params.append(f.device)
    if f.category_id is not None:
        sub_clauses.append("s.primary_category_id = %s")
        sub_params.append(f.category_id)

    sub_row = fetch_one(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE s.status = 'active')::BIGINT AS active_subscriptions,
            COALESCE(SUM(s.monthly_plan_value) FILTER (WHERE s.status = 'active'), 0)::FLOAT AS active_mrr
        FROM subscriptions s
        JOIN customers c ON c.customer_id = s.customer_id
        WHERE {' AND '.join(sub_clauses)};
        """,
        tuple(sub_params),
    )

    total_sessions = int(sess_row.get("total_sessions") or 0)
    active_visitors = int(sess_row.get("active_visitors") or 0)
    ordering_customers = int(ord_row.get("ordering_customers") or 0)
    delivered_orders = int(ord_row.get("delivered_orders") or 0)
    total_placed = int(ord_row.get("total_placed_orders") or 0)
    cancelled_orders = int(ord_row.get("cancelled_orders") or 0)
    repeat_cust = int(ord_row.get("repeat_customers_in_period") or 0)

    visitor_to_cust = round(100.0 * ordering_customers / max(active_visitors, 1), 2) if active_visitors > 0 else 0.0
    sess_to_deliv = round(100.0 * int(sess_row.get("session_orders_delivered") or 0) / max(total_sessions, 1), 2) if total_sessions > 0 else 0.0
    repeat_rate = round(100.0 * repeat_cust / max(ordering_customers, 1), 2) if ordering_customers > 0 else 0.0
    cancel_rate = round(100.0 * cancelled_orders / max(total_placed, 1), 2) if total_placed > 0 else 0.0

    return {
        "total_sessions": total_sessions,
        "active_visitors": active_visitors,
        "ordering_customers": ordering_customers,
        "visitor_to_customer_pct": visitor_to_cust,
        "session_completed_order_pct": sess_to_deliv,
        "total_placed_orders": total_placed,
        "delivered_orders": delivered_orders,
        "interactive_delivered_orders": int(ord_row.get("interactive_delivered_orders") or 0),
        "sub_refill_delivered_orders": int(ord_row.get("sub_refill_delivered_orders") or 0),
        "duplicate_attempts": int(ord_row.get("duplicate_attempts") or 0),
        "net_revenue": round(float(ord_row.get("net_revenue") or 0.0), 2),
        "avg_order_value": round(float(ord_row.get("avg_order_value") or 0.0), 2),
        "repeat_customers": repeat_cust,
        "repeat_purchase_rate_pct": repeat_rate,
        "cancelled_orders": cancelled_orders,
        "cancellation_rate_pct": cancel_rate,
        "active_subscriptions": int(sub_row.get("active_subscriptions") or 0),
        "active_mrr": round(float(sub_row.get("active_mrr") or 0.0), 2),
    }


def get_executive_overview(f: AnalyticsFilter) -> dict[str, Any]:
    f = f.normalized()
    curr = _compute_period_kpis(f, f.start_date, f.end_date)

    # Compare against prior equal-length period if available, else compare last half vs first half of selected range
    prev_start, prev_end = f.prior_period()
    if prev_start >= DATASET_START:
        comparison_label = f"vs prior period ({prev_start.isoformat()} to {prev_end.isoformat()})"
        prev = _compute_period_kpis(f, prev_start, prev_end)
    else:
        span_days = (f.end_date - f.start_date).days + 1
        mid_date = f.start_date + timedelta(days=span_days // 2)
        if mid_date > f.start_date and mid_date < f.end_date:
            comparison_label = f"2nd half ({mid_date.isoformat()}–{f.end_date.isoformat()}) vs 1st half"
            h2 = _compute_period_kpis(f, mid_date, f.end_date)
            h1 = _compute_period_kpis(f, f.start_date, mid_date - timedelta(days=1))
            prev = h1
            curr_for_delta = h2
        else:
            comparison_label = "Full dataset window"
            prev = None
            curr_for_delta = curr
    if prev_start >= DATASET_START:
        curr_for_delta = curr

    deltas: dict[str, float | None] = {}
    if prev:
        deltas = {
            "net_revenue_pct": _pct_change(curr_for_delta["net_revenue"], prev["net_revenue"]),
            "delivered_orders_pct": _pct_change(curr_for_delta["delivered_orders"], prev["delivered_orders"]),
            "total_sessions_pct": _pct_change(curr_for_delta["total_sessions"], prev["total_sessions"]),
            "avg_order_value_pct": _pct_change(curr_for_delta["avg_order_value"], prev["avg_order_value"]),
            "visitor_to_customer_pp": _pp_change(curr_for_delta["visitor_to_customer_pct"], prev["visitor_to_customer_pct"]),
            "repeat_purchase_rate_pp": _pp_change(curr_for_delta["repeat_purchase_rate_pct"], prev["repeat_purchase_rate_pct"]),
            "cancellation_rate_pp": _pp_change(curr_for_delta["cancellation_rate_pct"], prev["cancellation_rate_pct"]),
            "active_subscriptions_pct": _pct_change(curr_for_delta["active_subscriptions"], prev["active_subscriptions"]),
        }

    # Monthly commercial performance trend
    ow, op = build_order_where(f, alias="o")
    sw, sp = build_session_where(f, alias="sf")

    monthly_trend = fetch_all(
        f"""
        WITH m_orders AS (
            SELECT
                cal.year_month,
                COUNT(*) FILTER (WHERE o.order_status = 'delivered')::INT AS delivered_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'delivered' AND o.order_source = 'subscription_auto_refill')::INT AS sub_refill_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt)::INT AS cancelled_orders,
                COUNT(*) FILTER (WHERE NOT o.is_duplicate_attempt)::INT AS placed_orders,
                COALESCE(SUM(o.net_amount) FILTER (WHERE o.order_status = 'delivered'), 0)::FLOAT AS net_revenue,
                COUNT(DISTINCT o.customer_id) FILTER (WHERE o.order_status = 'delivered' AND o.is_first_order)::INT AS new_buyers,
                COUNT(DISTINCT o.customer_id) FILTER (WHERE o.order_status = 'delivered' AND NOT o.is_first_order)::INT AS returning_buyers
            FROM orders o
            JOIN calendar_dimension cal ON cal.date_key = o.order_date
            WHERE {ow}
            GROUP BY cal.year_month
        ),
        m_sessions AS (
            SELECT
                sf.year_month,
                COUNT(*)::INT AS sessions,
                SUM(sf.reached_order_delivered)::INT AS session_delivered
            FROM mv_session_funnel sf
            WHERE {sw}
            GROUP BY sf.year_month
        )
        SELECT
            COALESCE(mo.year_month, ms.year_month) AS year_month,
            COALESCE(ms.sessions, 0) AS sessions,
            COALESCE(mo.delivered_orders, 0) AS delivered_orders,
            COALESCE(mo.sub_refill_orders, 0) AS sub_refill_orders,
            ROUND(COALESCE(mo.net_revenue, 0)::NUMERIC, 2)::FLOAT AS net_revenue,
            COALESCE(mo.new_buyers, 0) AS new_buyers,
            COALESCE(mo.returning_buyers, 0) AS returning_buyers,
            ROUND(100.0 * COALESCE(ms.session_delivered, 0) / NULLIF(ms.sessions, 0), 2)::FLOAT AS session_completion_pct,
            ROUND(100.0 * COALESCE(mo.cancelled_orders, 0) / NULLIF(mo.placed_orders, 0), 2)::FLOAT AS cancellation_rate_pct
        FROM m_orders mo
        FULL OUTER JOIN m_sessions ms ON ms.year_month = mo.year_month
        ORDER BY 1;
        """,
        tuple(op + sp),
    )

    # Category summary snapshot
    category_snapshot = fetch_all(
        f"""
        WITH cat_orders AS (
            SELECT
                mc.category_id,
                mc.category_name,
                mc.category_group,
                COUNT(*) FILTER (WHERE o.order_status = 'delivered')::INT AS delivered_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt)::INT AS cancelled_orders,
                COUNT(*) FILTER (WHERE NOT o.is_duplicate_attempt)::INT AS placed_orders,
                COALESCE(SUM(o.net_amount) FILTER (WHERE o.order_status = 'delivered'), 0)::FLOAT AS net_revenue,
                COALESCE(AVG(o.net_amount) FILTER (WHERE o.order_status = 'delivered'), 0)::FLOAT AS aov,
                COUNT(DISTINCT o.customer_id) FILTER (WHERE o.order_status = 'delivered')::INT AS buyers
            FROM orders o
            JOIN medicine_categories mc ON mc.category_id = o.primary_category_id
            WHERE {ow}
            GROUP BY mc.category_id, mc.category_name, mc.category_group
        ),
        cat_repeat AS (
            SELECT
                primary_category_id AS category_id,
                COUNT(*) FILTER (WHERE cnt >= 2)::INT AS repeat_buyers
            FROM (
                SELECT primary_category_id, customer_id, COUNT(*) AS cnt
                FROM orders o
                WHERE {ow} AND o.order_status = 'delivered'
                GROUP BY primary_category_id, customer_id
            ) x
            GROUP BY primary_category_id
        )
        SELECT
            co.category_name,
            co.category_group,
            co.delivered_orders,
            ROUND(co.net_revenue::NUMERIC, 2)::FLOAT AS net_revenue,
            ROUND(co.aov::NUMERIC, 2)::FLOAT AS aov,
            co.buyers,
            ROUND(100.0 * COALESCE(cr.repeat_buyers, 0) / NULLIF(co.buyers, 0), 2)::FLOAT AS repeat_rate_pct,
            ROUND(100.0 * co.cancelled_orders / NULLIF(co.placed_orders, 0), 2)::FLOAT AS cancellation_rate_pct
        FROM cat_orders co
        LEFT JOIN cat_repeat cr ON cr.category_id = co.category_id
        ORDER BY co.net_revenue DESC;
        """,
        tuple(op + op),
    )

    # City performance snapshot
    regional_snapshot = fetch_all(
        f"""
        WITH city_sess AS (
            SELECT
                sf.city,
                sf.city_tier,
                COUNT(*)::INT AS sessions,
                SUM(sf.reached_order_delivered)::INT AS sess_delivered
            FROM mv_session_funnel sf
            WHERE {sw}
            GROUP BY sf.city, sf.city_tier
        ),
        city_ord AS (
            SELECT
                o.city,
                COUNT(*) FILTER (WHERE o.order_status = 'delivered')::INT AS delivered_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt)::INT AS cancelled_orders,
                COUNT(*) FILTER (WHERE NOT o.is_duplicate_attempt)::INT AS placed_orders,
                COALESCE(SUM(o.net_amount) FILTER (WHERE o.order_status = 'delivered'), 0)::FLOAT AS net_revenue
            FROM orders o
            WHERE {ow}
            GROUP BY o.city
        )
        SELECT
            cs.city,
            cs.city_tier,
            cs.sessions,
            COALESCE(co.delivered_orders, 0) AS delivered_orders,
            ROUND(COALESCE(co.net_revenue, 0)::NUMERIC, 2)::FLOAT AS net_revenue,
            ROUND(100.0 * cs.sess_delivered / NULLIF(cs.sessions, 0), 2)::FLOAT AS funnel_completion_pct,
            ROUND(100.0 * COALESCE(co.cancelled_orders, 0) / NULLIF(co.placed_orders, 0), 2)::FLOAT AS cancellation_rate_pct
        FROM city_sess cs
        LEFT JOIN city_ord co ON co.city = cs.city
        ORDER BY net_revenue DESC;
        """,
        tuple(sp + op),
    )

    return {
        "filters": f.to_dict(),
        "comparison_label": comparison_label,
        "kpis": curr,
        "deltas": deltas,
        "monthly_trend": monthly_trend,
        "category_snapshot": category_snapshot,
        "regional_snapshot": regional_snapshot,
    }
