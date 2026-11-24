from __future__ import annotations

from typing import Any

from app.database import fetch_all, fetch_one
from app.queries.filters import AnalyticsFilter, build_order_where, build_session_where

ALLOWED_BREAKDOWN_DIMS = {
    "device_type": ("sf.device_type", "Device Type"),
    "acquisition_channel": ("sf.acquisition_channel", "Acquisition Channel"),
    "city": ("sf.city", "City"),
    "city_tier": ("sf.city_tier", "City Tier"),
    "category_name": ("COALESCE(sf.category_name, 'Bounced (No Search)')", "Medicine Category"),
    "customer_type": ("CASE WHEN sf.is_new_customer_session THEN 'New Customer' ELSE 'Repeat Customer' END", "Customer Type"),
    "year_month": ("sf.year_month", "Activity Month"),
}


def get_funnel_analytics(f: AnalyticsFilter, breakdown_by: str = "device_type") -> dict[str, Any]:
    f = f.normalized()
    dim_key = breakdown_by if breakdown_by in ALLOWED_BREAKDOWN_DIMS else "device_type"
    dim_expr, dim_label = ALLOWED_BREAKDOWN_DIMS[dim_key]

    sw, sp = build_session_where(f, alias="sf")
    ow, op = build_order_where(f, alias="o")

    totals = fetch_one(
        f"""
        SELECT
            COUNT(*)::BIGINT AS total_sessions,
            COUNT(DISTINCT customer_id)::BIGINT AS active_customers,
            COALESCE(SUM(reached_visit), 0)::BIGINT AS s1_visit,
            COALESCE(SUM(reached_search), 0)::BIGINT AS s2_search,
            COALESCE(SUM(reached_view), 0)::BIGINT AS s3_view,
            COALESCE(SUM(reached_cart), 0)::BIGINT AS s4_cart,
            COALESCE(SUM(reached_checkout), 0)::BIGINT AS s5_checkout,
            COALESCE(SUM(reached_order_placed), 0)::BIGINT AS s6_placed,
            COALESCE(SUM(reached_order_delivered), 0)::BIGINT AS s7_delivered,
            COUNT(DISTINCT customer_id) FILTER (WHERE reached_search = 1)::BIGINT AS c2_search,
            COUNT(DISTINCT customer_id) FILTER (WHERE reached_view = 1)::BIGINT AS c3_view,
            COUNT(DISTINCT customer_id) FILTER (WHERE reached_cart = 1)::BIGINT AS c4_cart,
            COUNT(DISTINCT customer_id) FILTER (WHERE reached_checkout = 1)::BIGINT AS c5_checkout,
            COUNT(DISTINCT customer_id) FILTER (WHERE reached_order_placed = 1)::BIGINT AS c6_placed,
            COUNT(DISTINCT customer_id) FILTER (WHERE reached_order_delivered = 1)::BIGINT AS c7_delivered
        FROM mv_session_funnel sf
        WHERE {sw};
        """,
        tuple(sp),
    )

    # Order population reconciliation (Interactive Session Orders vs Subscription Auto-Refills)
    recon = fetch_one(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE order_source = 'interactive_session' AND NOT is_duplicate_attempt)::BIGINT AS interactive_orders_placed,
            COUNT(*) FILTER (WHERE order_source = 'interactive_session' AND order_status = 'delivered')::BIGINT AS interactive_orders_delivered,
            COUNT(*) FILTER (WHERE order_source = 'subscription_auto_refill' AND NOT is_duplicate_attempt)::BIGINT AS subscription_auto_refill_placed,
            COUNT(*) FILTER (WHERE order_source = 'subscription_auto_refill' AND order_status = 'delivered')::BIGINT AS subscription_auto_refill_delivered,
            COUNT(*) FILTER (WHERE is_duplicate_attempt)::BIGINT AS duplicate_attempts_excluded
        FROM orders o
        WHERE {ow};
        """,
        tuple(op),
    )

    s1 = int(totals.get("s1_visit") or 0)
    s2 = int(totals.get("s2_search") or 0)
    s3 = int(totals.get("s3_view") or 0)
    s4 = int(totals.get("s4_cart") or 0)
    s5 = int(totals.get("s5_checkout") or 0)
    s6 = int(totals.get("s6_placed") or 0)
    s7 = int(totals.get("s7_delivered") or 0)
    ac = int(totals.get("active_customers") or 0)

    stage_defs = [
        (1, "Application Visit", s1, ac, "All filtered interactive sessions (Denominator = Total Sessions)"),
        (2, "Product Search", s2, int(totals.get("c2_search") or 0), "Product Search Sessions / Application Visit Sessions"),
        (3, "Product Viewed", s3, int(totals.get("c3_view") or 0), "Product View Sessions / Product Search Sessions"),
        (4, "Added to Cart", s4, int(totals.get("c4_cart") or 0), "Add-to-Cart Sessions / Product View Sessions"),
        (5, "Checkout Initiated", s5, int(totals.get("c5_checkout") or 0), "Checkout Initiated Sessions / Add-to-Cart Sessions"),
        (6, "Order Placed", s6, int(totals.get("c6_placed") or 0), "Order Placed Sessions / Checkout Initiated Sessions"),
        (7, "Order Delivered", s7, int(totals.get("c7_delivered") or 0), "Net Delivered Sessions / Order Placed Sessions (excludes cancelled & returned)"),
    ]

    stages = []
    prev_cnt = s1
    for step_num, name, cnt, uniq_c, formula in stage_defs:
        cum_rate = round(100.0 * cnt / max(s1, 1), 2) if s1 > 0 else 0.0
        step_conv = 100.0 if step_num == 1 else (round(100.0 * cnt / max(prev_cnt, 1), 2) if prev_cnt > 0 else 0.0)
        step_drop = 0.0 if step_num == 1 else round(100.0 - step_conv, 2)
        lost = 0 if step_num == 1 else max(0, prev_cnt - cnt)
        stages.append(
            {
                "step_order": step_num,
                "stage_name": name,
                "sessions": cnt,
                "unique_customers": uniq_c,
                "cumulative_rate_pct": cum_rate,
                "step_conversion_pct": step_conv,
                "step_dropoff_pct": step_drop,
                "sessions_lost": lost,
                "denominator_formula": formula,
            }
        )
        prev_cnt = cnt

    # Largest relative drop-off stage (excluding step 1)
    biggest_drop = max(stages[1:], key=lambda x: x["step_dropoff_pct"]) if len(stages) > 1 else None

    kpis = {
        "total_sessions": s1,
        "active_customers": ac,
        "product_search_rate_pct": round(100.0 * s2 / max(s1, 1), 2),
        "product_view_rate_pct": round(100.0 * s3 / max(s2, 1), 2),
        "add_to_cart_rate_pct": round(100.0 * s4 / max(s3, 1), 2),
        "checkout_initiation_rate_pct": round(100.0 * s5 / max(s4, 1), 2),
        "checkout_conversion_pct": round(100.0 * s6 / max(s5, 1), 2),
        "order_conversion_pct": round(100.0 * s6 / max(s1, 1), 2),
        "completed_order_rate_pct": round(100.0 * s7 / max(s1, 1), 2),
        "largest_dropoff_stage": biggest_drop["stage_name"] if biggest_drop else None,
        "largest_dropoff_pct": biggest_drop["step_dropoff_pct"] if biggest_drop else 0.0,
    }

    # Segmented breakdown table
    breakdown = fetch_all(
        f"""
        SELECT
            {dim_expr} AS segment_value,
            COUNT(*)::INT AS sessions,
            COUNT(DISTINCT sf.customer_id)::INT AS active_customers,
            SUM(sf.reached_search)::INT AS search_sessions,
            SUM(sf.reached_view)::INT AS view_sessions,
            SUM(sf.reached_cart)::INT AS cart_sessions,
            SUM(sf.reached_checkout)::INT AS checkout_sessions,
            SUM(sf.reached_order_placed)::INT AS placed_sessions,
            SUM(sf.reached_order_delivered)::INT AS delivered_sessions,
            ROUND(100.0 * SUM(sf.reached_search) / NULLIF(COUNT(*), 0), 2)::FLOAT AS search_rate_pct,
            ROUND(100.0 * SUM(sf.reached_cart) / NULLIF(SUM(sf.reached_view), 0), 2)::FLOAT AS view_to_cart_pct,
            ROUND(100.0 * SUM(sf.reached_checkout) / NULLIF(SUM(sf.reached_cart), 0), 2)::FLOAT AS cart_to_checkout_pct,
            ROUND(100.0 * SUM(sf.reached_order_placed) / NULLIF(SUM(sf.reached_checkout), 0), 2)::FLOAT AS checkout_to_order_pct,
            ROUND(100.0 * SUM(sf.reached_order_placed) / NULLIF(COUNT(*), 0), 2)::FLOAT AS session_to_order_pct,
            ROUND(100.0 * SUM(sf.reached_order_delivered) / NULLIF(COUNT(*), 0), 2)::FLOAT AS completed_order_rate_pct
        FROM mv_session_funnel sf
        WHERE {sw}
        GROUP BY 1
        ORDER BY sessions DESC;
        """,
        tuple(sp),
    )

    # Monthly funnel conversion trend
    monthly_funnel = fetch_all(
        f"""
        SELECT
            sf.year_month,
            COUNT(*)::INT AS sessions,
            ROUND(100.0 * SUM(sf.reached_search) / NULLIF(COUNT(*), 0), 2)::FLOAT AS search_rate_pct,
            ROUND(100.0 * SUM(sf.reached_cart) / NULLIF(COUNT(*), 0), 2)::FLOAT AS cart_rate_pct,
            ROUND(100.0 * SUM(sf.reached_checkout) / NULLIF(SUM(sf.reached_cart), 0), 2)::FLOAT AS cart_to_checkout_pct,
            ROUND(100.0 * SUM(sf.reached_order_placed) / NULLIF(COUNT(*), 0), 2)::FLOAT AS order_conversion_pct,
            ROUND(100.0 * SUM(sf.reached_order_delivered) / NULLIF(COUNT(*), 0), 2)::FLOAT AS completed_order_rate_pct
        FROM mv_session_funnel sf
        WHERE {sw}
        GROUP BY sf.year_month
        ORDER BY sf.year_month;
        """,
        tuple(sp),
    )

    # Top search terms & cart abandonment rate using search_events & cart_events
    top_searches = fetch_all(
        f"""
        SELECT
            se.search_query,
            mc.category_name,
            COUNT(*)::INT AS search_count,
            ROUND(100.0 * COUNT(se.clicked_product_id) / NULLIF(COUNT(*), 0), 2)::FLOAT AS click_through_pct,
            ROUND(AVG(se.results_count)::NUMERIC, 1)::FLOAT AS avg_results
        FROM search_events se
        JOIN mv_session_funnel sf ON sf.session_id = se.session_id
        LEFT JOIN medicine_categories mc ON mc.category_id = se.matched_category_id
        WHERE {sw}
        GROUP BY se.search_query, mc.category_name
        ORDER BY search_count DESC
        LIMIT 12;
        """,
        tuple(sp),
    )

    return {
        "filters": f.to_dict(),
        "breakdown_by": dim_key,
        "breakdown_label": dim_label,
        "kpis": kpis,
        "stages": stages,
        "reconciliation": recon,
        "breakdown": breakdown,
        "monthly_trend": monthly_funnel,
        "top_searches": top_searches,
    }
