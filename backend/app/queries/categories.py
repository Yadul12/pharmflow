from __future__ import annotations

from typing import Any

from app.database import fetch_all
from app.queries.filters import AnalyticsFilter, build_order_where


def get_category_analytics(f: AnalyticsFilter) -> dict[str, Any]:
    f = f.normalized()
    ow, op = build_order_where(f, alias="o")

    # 1. Full 10-Category Performance Matrix
    categories = fetch_all(
        f"""
        WITH cat_orders AS (
            SELECT
                mc.category_id,
                mc.category_code,
                mc.category_name,
                mc.category_group,
                mc.is_chronic_refill,
                mc.typical_refill_days,
                mc.avg_margin_pct,
                COUNT(*) FILTER (WHERE NOT o.is_duplicate_attempt)::INT AS placed_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'delivered')::INT AS delivered_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt)::INT AS cancelled_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'returned')::INT AS returned_orders,
                COUNT(*) FILTER (WHERE o.order_status = 'delivered' AND o.subscription_id IS NOT NULL)::INT AS sub_refill_orders,
                COALESCE(SUM(o.net_amount) FILTER (WHERE o.order_status = 'delivered'), 0)::NUMERIC AS net_revenue,
                COALESCE(AVG(o.net_amount) FILTER (WHERE o.order_status = 'delivered'), 0)::NUMERIC AS aov,
                COUNT(DISTINCT o.customer_id) FILTER (WHERE o.order_status = 'delivered')::INT AS distinct_buyers
            FROM medicine_categories mc
            LEFT JOIN orders o
              ON o.primary_category_id = mc.category_id
             AND ({ow})
            GROUP BY mc.category_id, mc.category_code, mc.category_name, mc.category_group,
                     mc.is_chronic_refill, mc.typical_refill_days, mc.avg_margin_pct
        ),
        cust_cat_seq AS (
            SELECT
                o.primary_category_id AS category_id,
                o.customer_id,
                o.order_date,
                LAG(o.order_date) OVER (PARTITION BY o.primary_category_id, o.customer_id ORDER BY o.order_ts, o.order_id) AS prev_date,
                COUNT(*) OVER (PARTITION BY o.primary_category_id, o.customer_id) AS cust_cat_orders
            FROM orders o
            WHERE {ow}
              AND o.order_status = 'delivered'
        ),
        cat_repeat AS (
            SELECT
                category_id,
                COUNT(DISTINCT customer_id) FILTER (WHERE cust_cat_orders >= 2)::INT AS repeat_buyers,
                ROUND(AVG((order_date - prev_date)) FILTER (WHERE prev_date IS NOT NULL)::NUMERIC, 1)::FLOAT AS avg_reorder_days
            FROM cust_cat_seq
            GROUP BY category_id
        ),
        cat_subs AS (
            SELECT
                primary_category_id AS category_id,
                COUNT(DISTINCT customer_id)::INT AS subscribed_customers
            FROM subscriptions
            GROUP BY primary_category_id
        )
        SELECT
            co.category_id,
            co.category_code,
            co.category_name,
            co.category_group,
            co.is_chronic_refill,
            co.typical_refill_days,
            co.avg_margin_pct,
            co.delivered_orders,
            ROUND(co.net_revenue::NUMERIC, 2)::FLOAT AS net_revenue,
            ROUND(100.0 * co.net_revenue / NULLIF(SUM(co.net_revenue) OVER (), 0), 2)::FLOAT AS revenue_share_pct,
            ROUND((co.net_revenue * co.avg_margin_pct / 100.0)::NUMERIC, 2)::FLOAT AS est_gross_margin,
            ROUND(co.aov::NUMERIC, 2)::FLOAT AS aov,
            co.distinct_buyers,
            COALESCE(cr.repeat_buyers, 0) AS repeat_buyers,
            ROUND(100.0 * COALESCE(cr.repeat_buyers, 0) / NULLIF(co.distinct_buyers, 0), 2)::FLOAT AS repeat_rate_pct,
            cr.avg_reorder_days,
            ROUND(100.0 * co.sub_refill_orders / NULLIF(co.delivered_orders, 0), 2)::FLOAT AS sub_order_share_pct,
            ROUND(100.0 * COALESCE(cs.subscribed_customers, 0) / NULLIF(co.distinct_buyers, 0), 2)::FLOAT AS sub_attach_rate_pct,
            ROUND(100.0 * co.cancelled_orders / NULLIF(co.placed_orders, 0), 2)::FLOAT AS cancellation_rate_pct,
            ROUND(100.0 * co.returned_orders / NULLIF(co.delivered_orders + co.returned_orders, 0), 2)::FLOAT AS return_rate_pct
        FROM cat_orders co
        LEFT JOIN cat_repeat cr ON cr.category_id = co.category_id
        LEFT JOIN cat_subs cs ON cs.category_id = co.category_id
        WHERE co.delivered_orders > 0 OR %s::INT IS NULL
        ORDER BY co.net_revenue DESC;
        """,
        tuple(op + op + [f.category_id]),
    )

    # 2. Monthly Category Revenue Seasonality
    monthly_seasonality = fetch_all(
        f"""
        SELECT
            cal.year_month,
            cal.season,
            mc.category_name,
            mc.category_group,
            COUNT(*) FILTER (WHERE o.order_status = 'delivered')::INT AS delivered_orders,
            ROUND(COALESCE(SUM(o.net_amount) FILTER (WHERE o.order_status = 'delivered'), 0)::NUMERIC, 2)::FLOAT AS net_revenue
        FROM orders o
        JOIN calendar_dimension cal ON cal.date_key = o.order_date
        JOIN medicine_categories mc ON mc.category_id = o.primary_category_id
        WHERE {ow}
        GROUP BY cal.year_month, cal.season, mc.category_name, mc.category_group
        ORDER BY cal.year_month, net_revenue DESC;
        """,
        tuple(op),
    )

    # 3. Top 25 SKUs by Net Revenue
    top_skus = fetch_all(
        f"""
        SELECT
            pc.sku_code,
            pc.product_name,
            mc.category_name,
            pc.brand_tier,
            pc.unit_price,
            pc.is_subscription_eligible,
            pc.verification_required,
            SUM(oi.quantity) FILTER (WHERE o.order_status = 'delivered')::INT AS units_sold,
            COUNT(DISTINCT o.order_id) FILTER (WHERE o.order_status = 'delivered')::INT AS delivered_orders,
            ROUND(COALESCE(SUM(oi.line_total) FILTER (WHERE o.order_status = 'delivered'), 0)::NUMERIC, 2)::FLOAT AS net_revenue,
            ROUND(
                100.0 * COUNT(DISTINCT o.order_id) FILTER (WHERE o.order_status = 'cancelled' AND NOT o.is_duplicate_attempt) /
                NULLIF(COUNT(DISTINCT o.order_id) FILTER (WHERE NOT o.is_duplicate_attempt), 0),
                2
            )::FLOAT AS cancellation_rate_pct
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        JOIN product_catalog pc ON pc.product_id = oi.product_id
        JOIN medicine_categories mc ON mc.category_id = oi.category_id
        WHERE {ow}
        GROUP BY pc.sku_code, pc.product_name, mc.category_name, pc.brand_tier,
                 pc.unit_price, pc.is_subscription_eligible, pc.verification_required
        HAVING COUNT(DISTINCT o.order_id) FILTER (WHERE o.order_status = 'delivered') > 0
        ORDER BY net_revenue DESC
        LIMIT 25;
        """,
        tuple(op),
    )

    # 4. Cross-Category Basket Co-Occurrence (top category pairs bought together)
    basket_pairs = fetch_all(
        f"""
        WITH order_cats AS (
            SELECT DISTINCT
                oi.order_id,
                mc.category_name
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            JOIN medicine_categories mc ON mc.category_id = oi.category_id
            WHERE {ow}
              AND o.order_status = 'delivered'
        )
        SELECT
            a.category_name AS category_a,
            b.category_name AS category_b,
            COUNT(*)::INT AS co_occurrence_orders
        FROM order_cats a
        JOIN order_cats b
          ON a.order_id = b.order_id
         AND a.category_name < b.category_name
        GROUP BY a.category_name, b.category_name
        ORDER BY co_occurrence_orders DESC
        LIMIT 12;
        """,
        tuple(op),
    )

    return {
        "filters": f.to_dict(),
        "categories": categories,
        "monthly_seasonality": monthly_seasonality,
        "top_skus": top_skus,
        "basket_pairs": basket_pairs,
    }
