-- ============================================================================
-- PHARMFLOW — Analytical SQL Views & Materialized Views
-- Computed strictly from the normalized transactional tables.
-- Materialized views are refreshed after seeding to deliver sub-50ms multi-filter
-- dashboard queries while maintaining 100% row-level parity with raw tables.
-- ============================================================================

-- 1. Session-level funnel rollup derived directly from sessions + user_events
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_session_funnel AS
SELECT
    s.session_id,
    s.customer_id,
    s.session_date,
    c.year_month,
    s.acquisition_channel,
    s.device_type,
    s.city,
    s.city_tier,
    s.is_new_customer_session,
    s.primary_category_id,
    mc.category_name,
    s.duration_seconds,
    MAX(CASE WHEN ue.event_type = 'app_visit'        THEN 1 ELSE 0 END)::SMALLINT AS reached_visit,
    MAX(CASE WHEN ue.event_type = 'product_search'   THEN 1 ELSE 0 END)::SMALLINT AS reached_search,
    MAX(CASE WHEN ue.event_type = 'product_view'     THEN 1 ELSE 0 END)::SMALLINT AS reached_view,
    MAX(CASE WHEN ue.event_type = 'add_to_cart'      THEN 1 ELSE 0 END)::SMALLINT AS reached_cart,
    MAX(CASE WHEN ue.event_type = 'checkout_started' THEN 1 ELSE 0 END)::SMALLINT AS reached_checkout,
    MAX(CASE WHEN ue.event_type = 'order_placed'     THEN 1 ELSE 0 END)::SMALLINT AS reached_order_placed,
    MAX(CASE WHEN ue.event_type = 'order_delivered'  THEN 1 ELSE 0 END)::SMALLINT AS reached_order_delivered
FROM sessions s
JOIN calendar_dimension c ON c.date_key = s.session_date
LEFT JOIN medicine_categories mc ON mc.category_id = s.primary_category_id
LEFT JOIN user_events ue ON ue.session_id = s.session_id
GROUP BY
    s.session_id,
    s.customer_id,
    s.session_date,
    c.year_month,
    s.acquisition_channel,
    s.device_type,
    s.city,
    s.city_tier,
    s.is_new_customer_session,
    s.primary_category_id,
    mc.category_name,
    s.duration_seconds;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_session_funnel_pk
    ON mv_session_funnel (session_id);
CREATE INDEX IF NOT EXISTS idx_mv_session_funnel_dims
    ON mv_session_funnel (session_date, device_type, acquisition_channel, city, primary_category_id, is_new_customer_session);

-- 2. Customer first-order cohort & lifetime summary view
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_customer_lifecycle AS
WITH delivered_orders AS (
    SELECT
        o.customer_id,
        o.order_id,
        o.order_date,
        o.net_amount,
        o.subscription_id,
        o.primary_category_id,
        ROW_NUMBER() OVER (PARTITION BY o.customer_id ORDER BY o.order_ts, o.order_id) AS order_seq,
        LAG(o.order_date) OVER (PARTITION BY o.customer_id ORDER BY o.order_ts, o.order_id) AS prev_order_date
    FROM orders o
    WHERE o.order_status = 'delivered'
),
cust_agg AS (
    SELECT
        customer_id,
        MIN(order_date) AS first_delivered_date,
        MAX(order_date) AS last_delivered_date,
        COUNT(*) AS delivered_orders,
        SUM(net_amount) AS lifetime_net_revenue,
        AVG(net_amount) AS avg_order_value,
        AVG((order_date - prev_order_date)) FILTER (WHERE prev_order_date IS NOT NULL) AS avg_days_between_orders,
        BOOL_OR(subscription_id IS NOT NULL) AS has_subscription_order,
        MAX(CASE WHEN order_seq = 1 THEN primary_category_id END) AS first_order_category_id,
        MIN(CASE WHEN order_seq = 2 THEN order_date END) AS second_delivered_date
    FROM delivered_orders
    GROUP BY customer_id
),
sub_flags AS (
    SELECT
        customer_id,
        COUNT(*) AS subscription_count,
        BOOL_OR(status = 'active') AS has_active_subscription,
        MIN(start_date) AS first_subscription_date
    FROM subscriptions
    GROUP BY customer_id
)
SELECT
    cu.customer_id,
    cu.customer_code,
    cu.signup_date,
    cal_s.year_month AS signup_month,
    cu.acquisition_channel,
    cu.primary_device,
    cu.primary_city,
    cu.city_tier,
    cu.age_band,
    ca.first_delivered_date,
    cal_f.year_month AS cohort_month,
    ca.second_delivered_date,
    ca.last_delivered_date,
    COALESCE(ca.delivered_orders, 0) AS delivered_orders,
    COALESCE(ca.lifetime_net_revenue, 0)::NUMERIC(12,2) AS lifetime_net_revenue,
    COALESCE(ca.avg_order_value, 0)::NUMERIC(10,2) AS avg_order_value,
    ca.avg_days_between_orders::NUMERIC(8,2) AS avg_days_between_orders,
    ca.first_order_category_id,
    COALESCE(sf.subscription_count, 0) > 0 AS is_subscriber,
    COALESCE(sf.has_active_subscription, FALSE) AS has_active_subscription,
    sf.first_subscription_date
FROM customers cu
JOIN calendar_dimension cal_s ON cal_s.date_key = cu.signup_date
LEFT JOIN cust_agg ca ON ca.customer_id = cu.customer_id
LEFT JOIN calendar_dimension cal_f ON cal_f.date_key = ca.first_delivered_date
LEFT JOIN sub_flags sf ON sf.customer_id = cu.customer_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_customer_lifecycle_pk
    ON mv_customer_lifecycle (customer_id);
CREATE INDEX IF NOT EXISTS idx_mv_customer_lifecycle_cohort
    ON mv_customer_lifecycle (cohort_month, acquisition_channel, primary_city, primary_device, is_subscriber);
