from __future__ import annotations

from typing import Any

from app.database import fetch_all, fetch_one
from app.queries.filters import AnalyticsFilter, build_order_where


def get_cancellation_analytics(f: AnalyticsFilter) -> dict[str, Any]:
    f = f.normalized()
    ow, op = build_order_where(f, alias="o")

    # 1. Core Cancellation & Refund KPIs
    kpis = fetch_one(
        f"""
        WITH ord AS (
            SELECT *
            FROM orders o
            WHERE {ow}
        ),
        ref AS (
            SELECT r.*
            FROM refunds r
            JOIN orders o ON o.order_id = r.order_id
            WHERE {ow}
        )
        SELECT
            COUNT(*) FILTER (WHERE NOT is_duplicate_attempt)::INT AS placed_orders_nondup,
            COUNT(*) FILTER (WHERE order_status = 'cancelled' AND NOT is_duplicate_attempt)::INT AS cancelled_orders_nondup,
            COUNT(*) FILTER (WHERE is_duplicate_attempt)::INT AS duplicate_attempts_caught,
            COUNT(*) FILTER (WHERE order_status = 'delivered')::INT AS delivered_orders,
            COUNT(*) FILTER (WHERE order_status = 'returned')::INT AS returned_orders,
            ROUND(COALESCE(SUM(net_amount) FILTER (WHERE order_status = 'cancelled' AND NOT is_duplicate_attempt), 0)::NUMERIC, 2)::FLOAT AS cancelled_order_value,
            ROUND(100.0 * COUNT(*) FILTER (WHERE order_status = 'cancelled' AND NOT is_duplicate_attempt) /
                NULLIF(COUNT(*) FILTER (WHERE NOT is_duplicate_attempt), 0), 2)::FLOAT AS cancellation_rate_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE order_status = 'returned') /
                NULLIF(COUNT(*) FILTER (WHERE order_status IN ('delivered', 'returned')), 0), 2)::FLOAT AS return_rate_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE actual_delivery_days IS NOT NULL AND actual_delivery_days > promised_delivery_days) /
                NULLIF(COUNT(*) FILTER (WHERE actual_delivery_days IS NOT NULL), 0), 2)::FLOAT AS sla_breach_rate_pct,
            (SELECT COUNT(*)::INT FROM ref) AS total_refunds,
            (SELECT ROUND(COALESCE(SUM(refund_amount), 0)::NUMERIC, 2)::FLOAT FROM ref) AS total_refund_amount,
            (SELECT ROUND(COALESCE(AVG(processing_hours), 0)::NUMERIC, 1)::FLOAT FROM ref) AS avg_refund_processing_hours
        FROM ord;
        """,
        tuple(op + op),
    )

    # 2. Cancellation Reasons Pareto (including duplicate attempts cleanly tagged)
    cancel_reasons = fetch_all(
        f"""
        SELECT
            c.cancellation_reason,
            c.cancellation_stage,
            c.initiated_by,
            COUNT(*)::INT AS cancellations,
            ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2)::FLOAT AS share_pct,
            ROUND(SUM(o.net_amount)::NUMERIC, 2)::FLOAT AS lost_order_value,
            ROUND(AVG(c.hours_after_order)::NUMERIC, 1)::FLOAT AS avg_hours_after_order
        FROM cancellations c
        JOIN orders o ON o.order_id = c.order_id
        WHERE {ow}
        GROUP BY c.cancellation_reason, c.cancellation_stage, c.initiated_by
        ORDER BY cancellations DESC;
        """,
        tuple(op),
    )

    # 3. Refund Reasons & Full vs Partial Breakdown
    refund_reasons = fetch_all(
        f"""
        SELECT
            r.refund_reason,
            r.refund_type,
            COUNT(*)::INT AS refund_count,
            ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2)::FLOAT AS share_pct,
            ROUND(SUM(r.refund_amount)::NUMERIC, 2)::FLOAT AS total_refund_amount,
            ROUND(AVG(r.refund_amount)::NUMERIC, 2)::FLOAT AS avg_refund_amount,
            ROUND(AVG(r.processing_hours)::NUMERIC, 1)::FLOAT AS avg_processing_hours
        FROM refunds r
        JOIN orders o ON o.order_id = r.order_id
        WHERE {ow}
        GROUP BY r.refund_reason, r.refund_type
        ORDER BY total_refund_amount DESC;
        """,
        tuple(op),
    )

    # 4. Monthly Cancellation & Refund Rate Trend (shows Monsoon Jul-Aug logistics surge)
    monthly_trend = fetch_all(
        f"""
        WITH m_ord AS (
            SELECT
                cal.year_month,
                cal.season,
                COUNT(*) FILTER (WHERE NOT o.is_duplicate_attempt)::INT AS placed_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt)::INT AS cancelled_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'returned')::INT AS returned_orders,
                ROUND(100.0 * COUNT(*) FILTER (WHERE o.actual_delivery_days > o.promised_delivery_days) /
                    NULLIF(COUNT(*) FILTER (WHERE o.actual_delivery_days IS NOT NULL), 0), 2)::FLOAT AS sla_breach_pct
            FROM orders o
            JOIN calendar_dimension cal ON cal.date_key = o.order_date
            WHERE {ow}
            GROUP BY cal.year_month, cal.season
        ),
        m_ref AS (
            SELECT
                cal.year_month,
                COUNT(*)::INT AS refunds,
                ROUND(SUM(r.refund_amount)::NUMERIC, 2)::FLOAT AS refund_amount
            FROM refunds r
            JOIN orders o ON o.order_id = r.order_id
            JOIN calendar_dimension cal ON cal.date_key = r.refund_date
            WHERE {ow}
            GROUP BY cal.year_month
        )
        SELECT
            mo.year_month,
            mo.season,
            mo.placed_orders,
            mo.cancelled_orders,
            ROUND(100.0 * mo.cancelled_orders / NULLIF(mo.placed_orders, 0), 2)::FLOAT AS cancellation_rate_pct,
            mo.returned_orders,
            mo.sla_breach_pct,
            COALESCE(mr.refunds, 0) AS refunds,
            COALESCE(mr.refund_amount, 0.0)::FLOAT AS refund_amount
        FROM m_ord mo
        LEFT JOIN m_ref mr ON mr.year_month = mo.year_month
        ORDER BY mo.year_month;
        """,
        tuple(op + op),
    )

    # 5. Geographic (City & City Tier) Cancellation & SLA Matrix
    by_city = fetch_all(
        f"""
        SELECT
            o.city,
            o.city_tier,
            COUNT(*) FILTER (WHERE NOT o.is_duplicate_attempt)::INT AS placed_orders,
            COUNT(*) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt)::INT AS cancelled_orders,
            ROUND(100.0 * COUNT(*) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt) /
                NULLIF(COUNT(*) FILTER (WHERE NOT o.is_duplicate_attempt), 0), 2)::FLOAT AS cancellation_rate_pct,
            ROUND(AVG(o.promised_delivery_days)::NUMERIC, 1)::FLOAT AS avg_promised_days,
            ROUND(AVG(o.actual_delivery_days) FILTER (WHERE o.actual_delivery_days IS NOT NULL)::NUMERIC, 2)::FLOAT AS avg_actual_days,
            ROUND(100.0 * COUNT(*) FILTER (WHERE o.actual_delivery_days > o.promised_delivery_days) /
                NULLIF(COUNT(*) FILTER (WHERE o.actual_delivery_days IS NOT NULL), 0), 2)::FLOAT AS sla_breach_pct,
            ROUND(COALESCE(SUM(o.net_amount) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt), 0)::NUMERIC, 2)::FLOAT AS cancelled_value
        FROM orders o
        WHERE {ow}
        GROUP BY o.city, o.city_tier
        ORDER BY cancellation_rate_pct DESC;
        """,
        tuple(op),
    )

    # 6. Payment Method & Device Friction Matrix
    by_payment_device = fetch_all(
        f"""
        SELECT
            p.payment_method,
            o.device_type,
            COUNT(*) FILTER (WHERE NOT o.is_duplicate_attempt)::INT AS orders,
            COUNT(*) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt)::INT AS cancelled_orders,
            ROUND(100.0 * COUNT(*) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt) /
                NULLIF(COUNT(*) FILTER (WHERE NOT o.is_duplicate_attempt), 0), 2)::FLOAT AS cancellation_rate_pct,
            ROUND(AVG(p.gateway_latency_ms) FILTER (WHERE p.gateway_latency_ms IS NOT NULL)::NUMERIC, 0)::FLOAT AS avg_gateway_ms
        FROM orders o
        JOIN payments p ON p.order_id = o.order_id
        WHERE {ow}
        GROUP BY p.payment_method, o.device_type
        ORDER BY cancellation_rate_pct DESC;
        """,
        tuple(op),
    )

    return {
        "filters": f.to_dict(),
        "kpis": kpis,
        "cancel_reasons": cancel_reasons,
        "refund_reasons": refund_reasons,
        "monthly_trend": monthly_trend,
        "by_city": by_city,
        "by_payment_device": by_payment_device,
    }
