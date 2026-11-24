"""
PHARMFLOW — Curated SQL Lab Analytical Catalog
==============================================
12 production-grade PostgreSQL analytical queries demonstrating:
  - Multi-table joins & CTE pipelines
  - Window functions (ROW_NUMBER, RANK, DENSE_RANK, LAG, LEAD, running totals)
  - Conditional aggregation (FILTER / CASE)
  - Cohort retention matrices & date arithmetic
  - Funnel drop-off & stage denominators
  - Repeat-purchase timing, subscription renewal lag, RFM ranking, and basket affinity
"""

from __future__ import annotations

SQL_LAB_CATALOG = [
    {
        "id": "funnel_device_dropoff",
        "category": "Funnel Analysis",
        "title": "7-Stage Interactive Funnel & Stage Drop-Off by Device",
        "business_question": "Which device type experiences the sharpest stage-to-stage funnel drop-off from application visit through delivered order?",
        "sql_features": ["CTE", "Multi-Table Join", "Conditional Aggregation", "Raw user_events"],
        "sql": """WITH session_stages AS (
    SELECT
        s.session_id,
        s.device_type,
        MAX(CASE WHEN ue.event_type = 'app_visit'        THEN 1 ELSE 0 END) AS s1_visit,
        MAX(CASE WHEN ue.event_type = 'product_search'   THEN 1 ELSE 0 END) AS s2_search,
        MAX(CASE WHEN ue.event_type = 'product_view'     THEN 1 ELSE 0 END) AS s3_view,
        MAX(CASE WHEN ue.event_type = 'add_to_cart'      THEN 1 ELSE 0 END) AS s4_cart,
        MAX(CASE WHEN ue.event_type = 'checkout_started' THEN 1 ELSE 0 END) AS s5_checkout,
        MAX(CASE WHEN ue.event_type = 'order_placed'     THEN 1 ELSE 0 END) AS s6_placed,
        MAX(CASE WHEN ue.event_type = 'order_delivered'  THEN 1 ELSE 0 END) AS s7_delivered
    FROM sessions s
    JOIN user_events ue ON ue.session_id = s.session_id
    GROUP BY s.session_id, s.device_type
)
SELECT
    device_type,
    COUNT(*) AS total_sessions,
    ROUND(100.0 * SUM(s2_search) / NULLIF(COUNT(*), 0), 2) AS search_rate_pct,
    ROUND(100.0 * SUM(s4_cart) / NULLIF(SUM(s3_view), 0), 2) AS view_to_cart_pct,
    ROUND(100.0 * SUM(s5_checkout) / NULLIF(SUM(s4_cart), 0), 2) AS cart_to_checkout_pct,
    ROUND(100.0 * (SUM(s4_cart) - SUM(s5_checkout)) / NULLIF(SUM(s4_cart), 0), 2) AS cart_dropoff_pct,
    ROUND(100.0 * SUM(s6_placed) / NULLIF(SUM(s5_checkout), 0), 2) AS checkout_conv_pct,
    ROUND(100.0 * SUM(s7_delivered) / NULLIF(COUNT(*), 0), 2) AS completed_order_pct
FROM session_stages
GROUP BY device_type
ORDER BY completed_order_pct DESC;""",
        "query_explanation": "Aggregates raw `user_events` to session granularity inside a CTE using conditional `MAX(CASE ...)` flags, then computes step-to-step conversion and Cart-to-Checkout drop-off per `device_type`.",
        "optimization_notes": "Uses composite index `idx_user_events_session_step (session_id, step_order)` for efficient hash/group aggregation; dashboard queries further accelerate via `mv_session_funnel`.",
        "business_conclusion": "Mobile Web exhibits the largest Cart-to-Checkout drop-off (~49%+), substantially worse than iOS and Android Apps. Prioritizing streamlined Mobile Web OTP/guest checkout and UPI deep-links targets the single highest-leverage funnel bottleneck.",
    },
    {
        "id": "monthly_cohort_retention",
        "category": "Cohort Retention",
        "title": "Monthly Customer Acquisition Cohort Retention (M0–M6)",
        "business_question": "Which monthly customer cohorts retain best and where did retention decline across the 14-month window?",
        "sql_features": ["CTE", "Window Functions", "Date Arithmetic", "Conditional Aggregation"],
        "sql": """WITH first_order AS (
    SELECT
        o.customer_id,
        MIN(DATE_TRUNC('month', o.order_date)::DATE) AS cohort_month_dt
    FROM orders o
    WHERE o.order_status = 'delivered'
    GROUP BY o.customer_id
),
cohort_activity AS (
    SELECT
        fo.cohort_month_dt,
        fo.customer_id,
        (
            (EXTRACT(YEAR FROM o.order_date) - EXTRACT(YEAR FROM fo.cohort_month_dt)) * 12
            + (EXTRACT(MONTH FROM o.order_date) - EXTRACT(MONTH FROM fo.cohort_month_dt))
        )::INT AS month_offset
    FROM first_order fo
    JOIN orders o
      ON o.customer_id = fo.customer_id
     AND o.order_status = 'delivered'
    GROUP BY 1, 2, 3
),
cohort_sizes AS (
    SELECT cohort_month_dt, COUNT(*) AS cohort_size
    FROM first_order
    GROUP BY cohort_month_dt
)
SELECT
    TO_CHAR(cs.cohort_month_dt, 'YYYY-MM') AS cohort_month,
    cs.cohort_size,
    ROUND(100.0 * COUNT(DISTINCT ca.customer_id) FILTER (WHERE ca.month_offset = 1) / cs.cohort_size, 2) AS m1_pct,
    CASE WHEN cs.cohort_month_dt <= DATE '2026-08-01'
         THEN ROUND(100.0 * COUNT(DISTINCT ca.customer_id) FILTER (WHERE ca.month_offset = 2) / cs.cohort_size, 2) END AS m2_pct,
    CASE WHEN cs.cohort_month_dt <= DATE '2026-07-01'
         THEN ROUND(100.0 * COUNT(DISTINCT ca.customer_id) FILTER (WHERE ca.month_offset = 3) / cs.cohort_size, 2) END AS m3_pct,
    CASE WHEN cs.cohort_month_dt <= DATE '2026-04-01'
         THEN ROUND(100.0 * COUNT(DISTINCT ca.customer_id) FILTER (WHERE ca.month_offset = 6) / cs.cohort_size, 2) END AS m6_pct
FROM cohort_sizes cs
LEFT JOIN cohort_activity ca ON ca.cohort_month_dt = cs.cohort_month_dt
WHERE cs.cohort_month_dt <= DATE '2026-09-01'
GROUP BY cs.cohort_month_dt, cs.cohort_size
ORDER BY cs.cohort_month_dt;""",
        "query_explanation": "Defines each customer's cohort from their first delivered order (`MIN(DATE_TRUNC('month', order_date))`), calculates exact calendar-month offsets, and guards unmatured cells with explicit date eligibility `CASE` clauses.",
        "optimization_notes": "Leverages `idx_orders_customer_status_date (customer_id, order_status, order_date)` so PostgreSQL performs an index-only/index scan on delivered orders.",
        "business_conclusion": "Q2 2026 cohorts (2026-04 to 2026-06) show a measurable drop in M1–M3 retention relative to the Oct 2025–Feb 2026 baseline, coinciding with aggressive Social Media and Affiliate promo campaigns that attracted lower-intent one-time buyers.",
    },
    {
        "id": "repeat_purchase_lag_lead",
        "category": "Repeat Purchase",
        "title": "Customer Inter-Order Refill Intervals Using LAG & LEAD",
        "business_question": "What is the exact time gap between first, second, and third delivered orders across medicine categories?",
        "sql_features": ["LAG", "LEAD", "ROW_NUMBER", "CTE", "Date Calculations"],
        "sql": """WITH ordered_deliv AS (
    SELECT
        o.customer_id,
        o.order_id,
        o.order_date,
        mc.category_name,
        ROW_NUMBER() OVER (PARTITION BY o.customer_id ORDER BY o.order_ts, o.order_id) AS order_seq,
        LAG(o.order_date) OVER (PARTITION BY o.customer_id ORDER BY o.order_ts, o.order_id) AS prev_order_date,
        LEAD(o.order_date) OVER (PARTITION BY o.customer_id ORDER BY o.order_ts, o.order_id) AS next_order_date
    FROM orders o
    JOIN medicine_categories mc ON mc.category_id = o.primary_category_id
    WHERE o.order_status = 'delivered'
),
first_cat AS (
    SELECT customer_id, category_name AS first_category
    FROM ordered_deliv
    WHERE order_seq = 1
)
SELECT
    fc.first_category,
    COUNT(DISTINCT od.customer_id) AS total_buyers,
    COUNT(DISTINCT od.customer_id) FILTER (WHERE od.order_seq = 2) AS buyers_with_2nd_order,
    ROUND(100.0 * COUNT(DISTINCT od.customer_id) FILTER (WHERE od.order_seq = 2) / NULLIF(COUNT(DISTINCT od.customer_id), 0), 2) AS repeat_conversion_pct,
    ROUND(AVG(od.order_date - od.prev_order_date) FILTER (WHERE od.order_seq = 2), 1) AS avg_days_1st_to_2nd,
    ROUND(AVG(od.next_order_date - od.order_date) FILTER (WHERE od.order_seq = 2 AND od.next_order_date IS NOT NULL), 1) AS avg_days_2nd_to_3rd
FROM ordered_deliv od
JOIN first_cat fc ON fc.customer_id = od.customer_id
GROUP BY fc.first_category
ORDER BY repeat_conversion_pct DESC;""",
        "query_explanation": "Uses `ROW_NUMBER`, `LAG`, and `LEAD` partitioned by `customer_id` ordered by `(order_ts, order_id)` to trace exact transition intervals from 1st→2nd and 2nd→3rd delivered orders by initial purchase category.",
        "optimization_notes": "Deterministic sort on `(order_ts, order_id)` avoids tie ambiguity and reuses `idx_orders_customer_status_date`.",
        "business_conclusion": "Chronic Care Refills, Diabetes Care Supplies, and Cardiac & Wellness Nutrition lead repeat conversion with tight ~30–35 day intervals, whereas Home Diagnostics & Devices has low repeat conversion and long inter-order intervals.",
    },
    {
        "id": "subscription_vs_nonsub_retention",
        "category": "Subscriptions",
        "title": "Subscription vs Non-Subscription Lifetime Value & Order Velocity",
        "business_question": "How do repeat order frequency, AOV, and lifetime revenue differ between subscribers and non-subscribers among mature buyers?",
        "sql_features": ["CTE", "Multi-Table Join", "Conditional Aggregation", "Percentile"],
        "sql": """WITH mature_buyers AS (
    SELECT
        cl.customer_id,
        cl.is_subscriber,
        cl.delivered_orders,
        cl.avg_order_value,
        cl.lifetime_net_revenue,
        cl.avg_days_between_orders
    FROM mv_customer_lifecycle cl
    WHERE cl.first_delivered_date IS NOT NULL
      AND cl.first_delivered_date <= DATE '2026-07-31'
)
SELECT
    CASE WHEN is_subscriber THEN 'Subscribers' ELSE 'Non-Subscribers' END AS customer_group,
    COUNT(*) AS mature_buyers,
    ROUND(100.0 * COUNT(*) FILTER (WHERE delivered_orders >= 2) / COUNT(*), 2) AS repeat_rate_pct,
    ROUND(AVG(delivered_orders), 2) AS avg_delivered_orders,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY delivered_orders)::NUMERIC, 1) AS median_orders,
    ROUND(AVG(avg_order_value), 2) AS avg_aov_inr,
    ROUND(AVG(lifetime_net_revenue), 2) AS avg_ltv_inr,
    ROUND(AVG(avg_days_between_orders) FILTER (WHERE avg_days_between_orders IS NOT NULL), 1) AS avg_gap_days
FROM mature_buyers
GROUP BY 1
ORDER BY avg_ltv_inr DESC;""",
        "query_explanation": "Restricts to mature buyers (first delivered order at least 90 days prior to dataset end) to avoid right-censoring bias, then compares mean/median orders, repeat rate, and LTV across subscribers vs non-subscribers.",
        "optimization_notes": "Scans `mv_customer_lifecycle` with index `idx_mv_customer_lifecycle_cohort` in <10ms.",
        "business_conclusion": "Subscribers demonstrate markedly higher repeat rates and lifetime revenue than non-subscribers. However, because chronic-need customers self-select into subscriptions, treat this as a strong positive association rather than pure causal lift until validated via an enrollment experiment.",
    },
    {
        "id": "customer_ranking_top_revenue",
        "category": "Customer Rankings",
        "title": "Top Customers per City Tier Ranked with DENSE_RANK & Revenue Share",
        "business_question": "Who are the highest-value repeat customers within each city tier, and what share of their city tier's revenue do they represent?",
        "sql_features": ["DENSE_RANK", "ROW_NUMBER", "Window SUM", "CTE"],
        "sql": """WITH customer_rev AS (
    SELECT
        c.customer_code,
        c.primary_city,
        c.city_tier,
        cs.business_segment,
        COUNT(o.order_id) AS delivered_orders,
        ROUND(SUM(o.net_amount), 2) AS lifetime_revenue,
        ROUND(AVG(o.net_amount), 2) AS avg_order_value
    FROM customers c
    JOIN orders o ON o.customer_id = c.customer_id AND o.order_status = 'delivered'
    JOIN customer_segments cs ON cs.customer_id = c.customer_id
    GROUP BY c.customer_code, c.primary_city, c.city_tier, cs.business_segment
),
ranked AS (
    SELECT
        *,
        DENSE_RANK() OVER (PARTITION BY city_tier ORDER BY lifetime_revenue DESC) AS tier_rank,
        ROUND(100.0 * lifetime_revenue / SUM(lifetime_revenue) OVER (PARTITION BY city_tier), 4) AS pct_of_tier_revenue
    FROM customer_rev
)
SELECT
    city_tier,
    tier_rank,
    customer_code,
    primary_city,
    business_segment,
    delivered_orders,
    lifetime_revenue,
    avg_order_value,
    pct_of_tier_revenue
FROM ranked
WHERE tier_rank <= 5
ORDER BY city_tier, tier_rank;""",
        "query_explanation": "Combines `DENSE_RANK() OVER (PARTITION BY city_tier ORDER BY lifetime_revenue DESC)` with a partitioned window `SUM` to surface top-5 customers per city tier and their exact revenue share.",
        "optimization_notes": "Joins indexed PKs across `customers`, `orders`, and `customer_segments`.",
        "business_conclusion": "Top accounts across every tier are concentrated in High-Value Repeat segments with 8+ chronic refill orders, underscoring why protecting stock availability and SLA reliability for high-frequency refillers directly safeguards top-line revenue.",
    },
    {
        "id": "regional_conversion_cancellations",
        "category": "Geographic Performance",
        "title": "Regional Conversion, SLA Breach & Cancellation Rate Benchmark",
        "business_question": "Which cities have unusually low funnel conversion and elevated order cancellation rates compared to the network average?",
        "sql_features": ["CTE", "Window AVG Benchmark", "Multi-Table Join"],
        "sql": """WITH city_funnel AS (
    SELECT
        city,
        city_tier,
        COUNT(*) AS sessions,
        ROUND(100.0 * SUM(reached_checkout) / NULLIF(SUM(reached_cart), 0), 2) AS cart_to_checkout_pct,
        ROUND(100.0 * SUM(reached_order_delivered) / NULLIF(COUNT(*), 0), 2) AS funnel_completion_pct
    FROM mv_session_funnel
    GROUP BY city, city_tier
),
city_ops AS (
    SELECT
        city,
        COUNT(*) FILTER (WHERE NOT is_duplicate_attempt) AS placed_orders,
        ROUND(100.0 * COUNT(*) FILTER (WHERE order_status = 'cancelled' AND NOT is_duplicate_attempt) /
              NULLIF(COUNT(*) FILTER (WHERE NOT is_duplicate_attempt), 0), 2) AS cancel_rate_pct,
        ROUND(100.0 * COUNT(*) FILTER (WHERE actual_delivery_days > promised_delivery_days) /
              NULLIF(COUNT(*) FILTER (WHERE actual_delivery_days IS NOT NULL), 0), 2) AS sla_breach_pct
    FROM orders
    GROUP BY city
)
SELECT
    cf.city,
    cf.city_tier,
    cf.sessions,
    cf.cart_to_checkout_pct,
    cf.funnel_completion_pct,
    ROUND(cf.funnel_completion_pct - AVG(cf.funnel_completion_pct) OVER (), 2) AS conv_vs_avg_pp,
    co.placed_orders,
    co.cancel_rate_pct,
    ROUND(co.cancel_rate_pct - AVG(co.cancel_rate_pct) OVER (), 2) AS cancel_vs_avg_pp,
    co.sla_breach_pct
FROM city_funnel cf
JOIN city_ops co ON co.city = cf.city
ORDER BY cf.funnel_completion_pct ASC;""",
        "query_explanation": "Joins city-level funnel conversion with fulfillment cancellation and SLA breach metrics, computing exact percentage-point deviations from the cross-city network average via unpartitioned window `AVG() OVER ()`.",
        "optimization_notes": "Separating session aggregation and order aggregation into independent CTEs prevents Cartesian fan-out between sessions and orders.",
        "business_conclusion": "Lucknow, Indore (Tier 3), and Kolkata trail the network average in both funnel completion and cancellation control, driven by longer promised/actual delivery SLAs and higher Cash-on-Delivery share.",
    },
    {
        "id": "cancellation_drivers_pareto",
        "category": "Cancellations & Refunds",
        "title": "Cancellation Drivers Pareto with Cumulative Revenue Impact",
        "business_question": "What are the leading cancellation reasons, how much order value do they erode, and what cumulative share do the top drivers explain?",
        "sql_features": ["Window Running SUM", "Multi-Table Join", "CTE"],
        "sql": """WITH reason_agg AS (
    SELECT
        c.cancellation_reason,
        c.cancellation_stage,
        c.initiated_by,
        COUNT(*) AS cancelled_orders,
        ROUND(SUM(o.net_amount), 2) AS lost_revenue_inr,
        ROUND(AVG(c.hours_after_order), 1) AS avg_hours_to_cancel
    FROM cancellations c
    JOIN orders o ON o.order_id = c.order_id
    GROUP BY c.cancellation_reason, c.cancellation_stage, c.initiated_by
)
SELECT
    cancellation_reason,
    cancellation_stage,
    initiated_by,
    cancelled_orders,
    ROUND(100.0 * cancelled_orders / SUM(cancelled_orders) OVER (), 2) AS share_pct,
    ROUND(100.0 * SUM(cancelled_orders) OVER (ORDER BY cancelled_orders DESC) / SUM(cancelled_orders) OVER (), 2) AS cumulative_share_pct,
    lost_revenue_inr,
    avg_hours_to_cancel
FROM reason_agg
ORDER BY cancelled_orders DESC;""",
        "query_explanation": "Calculates exact order count, revenue at risk, average hours from placement to cancellation, and a Pareto running cumulative share using `SUM(...) OVER (ORDER BY cancelled_orders DESC)`.",
        "optimization_notes": "Uses `idx_cancellations_date_reason` and primary key lookup on `orders`.",
        "business_conclusion": "Delivery Delay / SLA Breach, Out of Stock After Order, and Verification Pending Timeout represent the majority of preventable cancellations—pointing directly to regional courier SLAs, real-time inventory sync, and automated verification reminders.",
    },
    {
        "id": "rfm_segment_economics",
        "category": "Customer Segmentation",
        "title": "RFM Business Segment Economics & Churn Exposure",
        "business_question": "How do revenue contribution, AOV, repeat frequency, and high churn-risk exposure vary across RFM business segments?",
        "sql_features": ["Multi-Table Join", "Window Share", "Conditional Aggregation"],
        "sql": """SELECT
    cs.business_segment,
    COUNT(*) AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS customer_share_pct,
    ROUND(SUM(cs.monetary_value), 2) AS total_revenue_inr,
    ROUND(100.0 * SUM(cs.monetary_value) / NULLIF(SUM(SUM(cs.monetary_value)) OVER (), 0), 2) AS revenue_share_pct,
    ROUND(AVG(cs.monetary_value), 2) AS avg_ltv_inr,
    ROUND(AVG(cl.avg_order_value) FILTER (WHERE cs.frequency_orders > 0), 2) AS avg_aov_inr,
    ROUND(AVG(cs.frequency_orders), 2) AS avg_orders,
    ROUND(100.0 * COUNT(*) FILTER (WHERE cl.is_subscriber) / COUNT(*), 2) AS subscriber_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE cs.churn_risk_band = 'High') / NULLIF(COUNT(*) FILTER (WHERE cs.frequency_orders > 0), 0), 2) AS high_churn_risk_pct
FROM customer_segments cs
JOIN mv_customer_lifecycle cl ON cl.customer_id = cs.customer_id
GROUP BY cs.business_segment
ORDER BY total_revenue_inr DESC;""",
        "query_explanation": "Joins computed RFM/K-Means/Churn outputs in `customer_segments` with `mv_customer_lifecycle` to evaluate revenue concentration, AOV, subscription adoption, and churn exposure by business segment.",
        "optimization_notes": "Backed by `idx_customer_segments_business` and unique PK join.",
        "business_conclusion": "High-Value Repeat and Regular Customers generate the dominant share of net revenue despite being a smaller slice of total registered accounts, while At-Risk Customers hold high recoverable LTV for targeted refill reminders.",
    },
    {
        "id": "subscription_renewal_timing",
        "category": "Subscriptions",
        "title": "Subscription Renewal Cadence Adherence & Cycle Churn Analysis",
        "business_question": "How closely do actual subscription renewals match promised 30/45/60-day cadences, and at which renewal cycle do most cancellations occur?",
        "sql_features": ["CTE", "LAG", "Conditional Aggregation", "Date Arithmetic"],
        "sql": """WITH cycle_events AS (
    SELECT
        s.plan_cadence_days,
        se.subscription_id,
        se.cycle_number,
        se.event_type,
        se.days_since_prev_event
    FROM subscription_events se
    JOIN subscriptions s ON s.subscription_id = se.subscription_id
    WHERE se.cycle_number BETWEEN 1 AND 6
)
SELECT
    plan_cadence_days,
    cycle_number,
    COUNT(*) FILTER (WHERE event_type = 'renewed') AS renewals,
    COUNT(*) FILTER (WHERE event_type = 'cancelled') AS cancellations,
    ROUND(100.0 * COUNT(*) FILTER (WHERE event_type = 'renewed') /
          NULLIF(COUNT(*) FILTER (WHERE event_type IN ('renewed', 'cancelled')), 0), 2) AS cycle_renewal_rate_pct,
    ROUND(AVG(days_since_prev_event) FILTER (WHERE event_type = 'renewed'), 2) AS avg_actual_days,
    ROUND(AVG(days_since_prev_event - plan_cadence_days) FILTER (WHERE event_type = 'renewed'), 2) AS avg_slip_days
FROM cycle_events
GROUP BY plan_cadence_days, cycle_number
ORDER BY plan_cadence_days, cycle_number;""",
        "query_explanation": "Evaluates renewal rate and schedule variance (`days_since_prev_event - plan_cadence_days`) broken down by plan cadence and renewal cycle number (1 through 6).",
        "optimization_notes": "Uses `idx_sub_events_sub_date` and primary key join on `subscriptions`.",
        "business_conclusion": "Early cycles (Cycles 1–2) represent the critical subscription retention hurdle; customers who survive past Cycle 3 exhibit steady renewal adherence within ±1 day of scheduled cadence.",
    },
    {
        "id": "monthly_reactivation_pool",
        "category": "Customer Retention",
        "title": "Monthly 90-Day Customer Reactivation & Win-Back Velocity",
        "business_question": "How many previously lapsed buyers (90+ days inactive) reactivate each month, and what revenue do they contribute?",
        "sql_features": ["LAG", "CTE", "Window Functions", "Date Calculations"],
        "sql": """WITH deliv_seq AS (
    SELECT
        o.customer_id,
        o.order_date,
        cal.year_month,
        o.net_amount,
        LAG(o.order_date) OVER (PARTITION BY o.customer_id ORDER BY o.order_ts, o.order_id) AS prev_order_date
    FROM orders o
    JOIN calendar_dimension cal ON cal.date_key = o.order_date
    WHERE o.order_status = 'delivered'
)
SELECT
    year_month,
    COUNT(DISTINCT customer_id) AS active_buyers,
    COUNT(DISTINCT customer_id) FILTER (WHERE prev_order_date IS NULL) AS first_time_buyers,
    COUNT(DISTINCT customer_id) FILTER (WHERE prev_order_date IS NOT NULL AND (order_date - prev_order_date) < 90) AS retained_active_buyers,
    COUNT(DISTINCT customer_id) FILTER (WHERE prev_order_date IS NOT NULL AND (order_date - prev_order_date) >= 90) AS reactivated_90d_buyers,
    ROUND(COALESCE(SUM(net_amount) FILTER (WHERE prev_order_date IS NOT NULL AND (order_date - prev_order_date) >= 90), 0), 2) AS reactivated_revenue_inr
FROM deliv_seq
GROUP BY year_month
ORDER BY year_month;""",
        "query_explanation": "Computes exact days since prior delivered order for every transaction via `LAG(order_date)`, partitioning monthly active buyers into First-Time, Retained Active (<90d gap), and Reactivated (≥90d gap).",
        "optimization_notes": "Single pass over delivered orders ordered by `(customer_id, order_ts, order_id)` via `idx_orders_customer_status_date`.",
        "business_conclusion": "Reactivated buyers become a steadily growing revenue contributor from Month 4 onward, demonstrating strong payoff from automated 90-day win-back CRM triggers (`WINBACK15`).",
    },
    {
        "id": "promo_campaign_quality",
        "category": "Marketing & Acquisition",
        "title": "Promotional Campaign ROI & Post-Acquisition Repeat Quality",
        "business_question": "Which promotional campaigns drive high-LTV repeat buyers versus one-time discount hunters?",
        "sql_features": ["Multi-Table Join", "CTE", "Conditional Aggregation"],
        "sql": """WITH camp_customers AS (
    SELECT
        pc.campaign_code,
        pc.campaign_name,
        pc.campaign_type,
        pc.discount_pct,
        cl.customer_id,
        cl.delivered_orders,
        cl.lifetime_net_revenue,
        cl.is_subscriber
    FROM promotional_campaigns pc
    JOIN customers c ON c.signup_campaign_id = pc.campaign_id
    JOIN mv_customer_lifecycle cl ON cl.customer_id = c.customer_id
)
SELECT
    campaign_code,
    campaign_name,
    campaign_type,
    discount_pct,
    COUNT(*) AS acquired_signups,
    COUNT(*) FILTER (WHERE delivered_orders >= 1) AS converted_buyers,
    ROUND(100.0 * COUNT(*) FILTER (WHERE delivered_orders >= 2) / NULLIF(COUNT(*) FILTER (WHERE delivered_orders >= 1), 0), 2) AS repeat_buyer_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_subscriber) / NULLIF(COUNT(*) FILTER (WHERE delivered_orders >= 1), 0), 2) AS subscriber_attach_pct,
    ROUND(AVG(lifetime_net_revenue) FILTER (WHERE delivered_orders >= 1), 2) AS avg_buyer_ltv_inr
FROM camp_customers
GROUP BY campaign_code, campaign_name, campaign_type, discount_pct
ORDER BY avg_buyer_ltv_inr DESC;""",
        "query_explanation": "Links signup promotional campaigns through `customers` to lifetime delivered order and subscription performance in `mv_customer_lifecycle`.",
        "optimization_notes": "Compact dimension join over 30,000 customers executing in <15ms.",
        "business_conclusion": "Deep-discount Q2 blitz campaigns (`SPRINGBLITZ` at 25% off and `AFFILFLASH` at 22% off) yield noticeably lower repeat buyer rates and LTV than `REFERFRIEND`, `APPFIRST`, and `WELCOME15`, supporting reallocation of acquisition spend toward referral and app-first channels.",
    },
    {
        "id": "cross_category_basket_affinity",
        "category": "Category & Merchandising",
        "title": "Cross-Category Basket Co-Occurrence & Multi-Category Lift",
        "business_question": "Which healthcare product categories are most frequently purchased together in the same basket, and how does multi-category ordering affect AOV?",
        "sql_features": ["Self-Join", "CTE", "Multi-Table Join"],
        "sql": """WITH order_cats AS (
    SELECT DISTINCT
        oi.order_id,
        mc.category_name,
        o.net_amount
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    JOIN medicine_categories mc ON mc.category_id = oi.category_id
    WHERE o.order_status = 'delivered'
)
SELECT
    a.category_name AS primary_category,
    b.category_name AS paired_category,
    COUNT(*) AS co_purchased_orders,
    ROUND(AVG(a.net_amount), 2) AS avg_combined_basket_inr
FROM order_cats a
JOIN order_cats b
  ON a.order_id = b.order_id
 AND a.category_name < b.category_name
GROUP BY a.category_name, b.category_name
ORDER BY co_purchased_orders DESC
LIMIT 15;""",
        "query_explanation": "Builds distinct `(order_id, category_name)` tuples for delivered orders and performs an asymmetric self-join (`a.category_name < b.category_name`) to identify top category basket pairings without double-counting.",
        "optimization_notes": "Uses `idx_order_items_order` and `idx_order_items_category_product` for fast join execution.",
        "business_conclusion": "Chronic Care Refills and Vitamins & Supplements frequently pair with OTC Pain & Fever, Digestive Health, and First Aid items—creating high-margin checkout cross-sell opportunities that also help buyers cross the free-delivery threshold.",
    },
]
