-- ============================================================================
-- PHARMFLOW — Healthcare E-commerce Customer, Order Funnel & Retention Analytics
-- PostgreSQL Relational Schema (18 Core Analytical Tables + Report Runs Metadata)
-- All records are 100% synthetic. No personal health information (PHI) or diagnoses.
-- ============================================================================

-- 1. calendar_dimension
CREATE TABLE IF NOT EXISTS calendar_dimension (
    date_key        DATE PRIMARY KEY,
    year            SMALLINT NOT NULL,
    quarter         SMALLINT NOT NULL,
    month           SMALLINT NOT NULL,
    month_name      VARCHAR(12) NOT NULL,
    year_month      CHAR(7) NOT NULL,
    week_of_year    SMALLINT NOT NULL,
    day_of_week     SMALLINT NOT NULL,
    day_name        VARCHAR(10) NOT NULL,
    is_weekend      BOOLEAN NOT NULL,
    season          VARCHAR(16) NOT NULL
);

-- 2. medicine_categories
CREATE TABLE IF NOT EXISTS medicine_categories (
    category_id         SERIAL PRIMARY KEY,
    category_code       VARCHAR(24) UNIQUE NOT NULL,
    category_name       VARCHAR(80) UNIQUE NOT NULL,
    category_group      VARCHAR(40) NOT NULL,
    typical_refill_days INT,
    is_chronic_refill   BOOLEAN NOT NULL DEFAULT FALSE,
    avg_margin_pct      NUMERIC(5,2) NOT NULL
);

-- 3. product_catalog
CREATE TABLE IF NOT EXISTS product_catalog (
    product_id              SERIAL PRIMARY KEY,
    sku_code                VARCHAR(32) UNIQUE NOT NULL,
    product_name            VARCHAR(140) NOT NULL,
    category_id             INT NOT NULL REFERENCES medicine_categories(category_id),
    brand_tier              VARCHAR(24) NOT NULL,
    unit_price              NUMERIC(10,2) NOT NULL CHECK (unit_price > 0),
    mrp                     NUMERIC(10,2) NOT NULL CHECK (mrp >= unit_price),
    pack_size               VARCHAR(40) NOT NULL,
    is_subscription_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    verification_required   BOOLEAN NOT NULL DEFAULT FALSE,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE
);

-- 4. promotional_campaigns
CREATE TABLE IF NOT EXISTS promotional_campaigns (
    campaign_id     SERIAL PRIMARY KEY,
    campaign_code   VARCHAR(32) UNIQUE NOT NULL,
    campaign_name   VARCHAR(120) NOT NULL,
    channel         VARCHAR(40) NOT NULL,
    discount_pct    NUMERIC(5,2) NOT NULL CHECK (discount_pct >= 0 AND discount_pct <= 50),
    min_order_value NUMERIC(10,2) NOT NULL DEFAULT 0,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    campaign_type   VARCHAR(32) NOT NULL
);

-- 5. customers
CREATE TABLE IF NOT EXISTS customers (
    customer_id         BIGINT PRIMARY KEY,
    customer_code       VARCHAR(24) UNIQUE NOT NULL,
    signup_date         DATE NOT NULL REFERENCES calendar_dimension(date_key),
    signup_ts           TIMESTAMPTZ NOT NULL,
    acquisition_channel VARCHAR(40) NOT NULL,
    primary_device      VARCHAR(32) NOT NULL,
    primary_city        VARCHAR(48) NOT NULL,
    city_tier           VARCHAR(16) NOT NULL,
    age_band            VARCHAR(16) NOT NULL,
    signup_campaign_id  INT REFERENCES promotional_campaigns(campaign_id),
    is_email_verified   BOOLEAN NOT NULL DEFAULT TRUE,
    is_active_account   BOOLEAN NOT NULL DEFAULT TRUE
);

-- 6. customer_addresses
CREATE TABLE IF NOT EXISTS customer_addresses (
    address_id        BIGSERIAL PRIMARY KEY,
    customer_id       BIGINT NOT NULL REFERENCES customers(customer_id),
    city              VARCHAR(48) NOT NULL,
    state             VARCHAR(48) NOT NULL,
    city_tier         VARCHAR(16) NOT NULL,
    postal_zone       VARCHAR(16) NOT NULL,
    address_type      VARCHAR(20) NOT NULL,
    is_default        BOOLEAN NOT NULL DEFAULT TRUE,
    delivery_sla_days SMALLINT NOT NULL CHECK (delivery_sla_days BETWEEN 1 AND 10)
);

-- 7. sessions
CREATE TABLE IF NOT EXISTS sessions (
    session_id              BIGINT PRIMARY KEY,
    customer_id             BIGINT NOT NULL REFERENCES customers(customer_id),
    session_date            DATE NOT NULL REFERENCES calendar_dimension(date_key),
    session_start           TIMESTAMPTZ NOT NULL,
    session_end             TIMESTAMPTZ NOT NULL,
    duration_seconds        INT NOT NULL CHECK (duration_seconds >= 0),
    acquisition_channel     VARCHAR(40) NOT NULL,
    device_type             VARCHAR(32) NOT NULL,
    city                    VARCHAR(48) NOT NULL,
    city_tier               VARCHAR(16) NOT NULL,
    is_new_customer_session BOOLEAN NOT NULL,
    primary_category_id     INT REFERENCES medicine_categories(category_id),
    campaign_id             INT REFERENCES promotional_campaigns(campaign_id)
);

-- 8. user_events
CREATE TABLE IF NOT EXISTS user_events (
    event_id    BIGSERIAL PRIMARY KEY,
    session_id  BIGINT NOT NULL REFERENCES sessions(session_id),
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    event_type  VARCHAR(32) NOT NULL CHECK (
        event_type IN (
            'app_visit',
            'product_search',
            'product_view',
            'add_to_cart',
            'checkout_started',
            'order_placed',
            'order_delivered'
        )
    ),
    event_ts    TIMESTAMPTZ NOT NULL,
    event_date  DATE NOT NULL REFERENCES calendar_dimension(date_key),
    category_id INT REFERENCES medicine_categories(category_id),
    product_id  INT REFERENCES product_catalog(product_id),
    step_order  SMALLINT NOT NULL CHECK (step_order BETWEEN 1 AND 7)
);

-- 9. search_events
CREATE TABLE IF NOT EXISTS search_events (
    search_id           BIGSERIAL PRIMARY KEY,
    session_id          BIGINT NOT NULL REFERENCES sessions(session_id),
    customer_id         BIGINT NOT NULL REFERENCES customers(customer_id),
    search_ts           TIMESTAMPTZ NOT NULL,
    search_query        VARCHAR(100) NOT NULL,
    matched_category_id INT REFERENCES medicine_categories(category_id),
    results_count       INT NOT NULL CHECK (results_count >= 0),
    clicked_product_id  INT REFERENCES product_catalog(product_id)
);

-- 10. cart_events
CREATE TABLE IF NOT EXISTS cart_events (
    cart_event_id BIGSERIAL PRIMARY KEY,
    session_id    BIGINT NOT NULL REFERENCES sessions(session_id),
    customer_id   BIGINT NOT NULL REFERENCES customers(customer_id),
    product_id    INT NOT NULL REFERENCES product_catalog(product_id),
    category_id   INT NOT NULL REFERENCES medicine_categories(category_id),
    action_type   VARCHAR(20) NOT NULL CHECK (action_type IN ('add', 'quantity_update', 'remove')),
    quantity      SMALLINT NOT NULL CHECK (quantity > 0),
    unit_price    NUMERIC(10,2) NOT NULL,
    event_ts      TIMESTAMPTZ NOT NULL
);

-- 11. subscriptions
CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id     BIGINT PRIMARY KEY,
    customer_id         BIGINT NOT NULL REFERENCES customers(customer_id),
    primary_category_id INT NOT NULL REFERENCES medicine_categories(category_id),
    product_id          INT NOT NULL REFERENCES product_catalog(product_id),
    plan_cadence_days   SMALLINT NOT NULL CHECK (plan_cadence_days IN (30, 45, 60)),
    start_date          DATE NOT NULL REFERENCES calendar_dimension(date_key),
    next_renewal_date   DATE,
    cancelled_date      DATE,
    status              VARCHAR(20) NOT NULL CHECK (status IN ('active', 'paused', 'cancelled', 'expired')),
    cancel_reason       VARCHAR(64),
    discount_pct        NUMERIC(5,2) NOT NULL DEFAULT 10.00,
    monthly_plan_value  NUMERIC(10,2) NOT NULL CHECK (monthly_plan_value > 0)
);

-- 12. subscription_events
CREATE TABLE IF NOT EXISTS subscription_events (
    sub_event_id          BIGSERIAL PRIMARY KEY,
    subscription_id       BIGINT NOT NULL REFERENCES subscriptions(subscription_id),
    customer_id           BIGINT NOT NULL REFERENCES customers(customer_id),
    event_type            VARCHAR(28) NOT NULL CHECK (
        event_type IN ('created', 'renewed', 'paused', 'resumed', 'cancelled', 'payment_retry_failed')
    ),
    event_date            DATE NOT NULL REFERENCES calendar_dimension(date_key),
    event_ts              TIMESTAMPTZ NOT NULL,
    cycle_number          SMALLINT NOT NULL CHECK (cycle_number >= 0),
    days_since_prev_event INT
);

-- 13. orders
CREATE TABLE IF NOT EXISTS orders (
    order_id               BIGINT PRIMARY KEY,
    order_code             VARCHAR(24) UNIQUE NOT NULL,
    customer_id            BIGINT NOT NULL REFERENCES customers(customer_id),
    session_id             BIGINT REFERENCES sessions(session_id),
    address_id             BIGINT NOT NULL REFERENCES customer_addresses(address_id),
    subscription_id        BIGINT REFERENCES subscriptions(subscription_id),
    campaign_id            INT REFERENCES promotional_campaigns(campaign_id),
    order_source           VARCHAR(32) NOT NULL CHECK (order_source IN ('interactive_session', 'subscription_auto_refill')),
    order_date             DATE NOT NULL REFERENCES calendar_dimension(date_key),
    order_ts               TIMESTAMPTZ NOT NULL,
    delivered_ts           TIMESTAMPTZ,
    order_status           VARCHAR(24) NOT NULL CHECK (order_status IN ('delivered', 'cancelled', 'returned')),
    is_first_order         BOOLEAN NOT NULL,
    is_duplicate_attempt   BOOLEAN NOT NULL DEFAULT FALSE,
    device_type            VARCHAR(32) NOT NULL,
    acquisition_channel    VARCHAR(40) NOT NULL,
    city                   VARCHAR(48) NOT NULL,
    city_tier              VARCHAR(16) NOT NULL,
    primary_category_id    INT NOT NULL REFERENCES medicine_categories(category_id),
    gross_amount           NUMERIC(10,2) NOT NULL CHECK (gross_amount >= 0),
    discount_amount        NUMERIC(10,2) NOT NULL CHECK (discount_amount >= 0),
    delivery_fee           NUMERIC(8,2) NOT NULL CHECK (delivery_fee >= 0),
    net_amount             NUMERIC(10,2) NOT NULL CHECK (net_amount >= 0),
    promised_delivery_days SMALLINT NOT NULL,
    actual_delivery_days   SMALLINT
);

-- 14. order_items
CREATE TABLE IF NOT EXISTS order_items (
    order_item_id BIGSERIAL PRIMARY KEY,
    order_id      BIGINT NOT NULL REFERENCES orders(order_id),
    product_id    INT NOT NULL REFERENCES product_catalog(product_id),
    category_id   INT NOT NULL REFERENCES medicine_categories(category_id),
    quantity      SMALLINT NOT NULL CHECK (quantity > 0),
    unit_price    NUMERIC(10,2) NOT NULL,
    line_discount NUMERIC(10,2) NOT NULL DEFAULT 0,
    line_total    NUMERIC(10,2) NOT NULL
);

-- 15. payments
CREATE TABLE IF NOT EXISTS payments (
    payment_id         BIGSERIAL PRIMARY KEY,
    order_id           BIGINT UNIQUE NOT NULL REFERENCES orders(order_id),
    customer_id        BIGINT NOT NULL REFERENCES customers(customer_id),
    payment_method     VARCHAR(32) NOT NULL,
    payment_status     VARCHAR(24) NOT NULL CHECK (
        payment_status IN ('captured', 'failed', 'refunded', 'cod_collected', 'cod_cancelled')
    ),
    amount             NUMERIC(10,2) NOT NULL,
    payment_ts         TIMESTAMPTZ NOT NULL,
    gateway_latency_ms INT
);

-- 16. cancellations
CREATE TABLE IF NOT EXISTS cancellations (
    cancellation_id    BIGSERIAL PRIMARY KEY,
    order_id           BIGINT UNIQUE NOT NULL REFERENCES orders(order_id),
    customer_id        BIGINT NOT NULL REFERENCES customers(customer_id),
    cancelled_date     DATE NOT NULL REFERENCES calendar_dimension(date_key),
    cancelled_ts       TIMESTAMPTZ NOT NULL,
    cancellation_stage VARCHAR(32) NOT NULL,
    cancellation_reason VARCHAR(64) NOT NULL,
    initiated_by       VARCHAR(24) NOT NULL,
    hours_after_order  NUMERIC(8,2) NOT NULL CHECK (hours_after_order >= 0)
);

-- 17. refunds
CREATE TABLE IF NOT EXISTS refunds (
    refund_id        BIGSERIAL PRIMARY KEY,
    order_id         BIGINT NOT NULL REFERENCES orders(order_id),
    payment_id       BIGINT NOT NULL REFERENCES payments(payment_id),
    customer_id      BIGINT NOT NULL REFERENCES customers(customer_id),
    refund_date      DATE NOT NULL REFERENCES calendar_dimension(date_key),
    refund_ts        TIMESTAMPTZ NOT NULL,
    refund_amount    NUMERIC(10,2) NOT NULL CHECK (refund_amount > 0),
    refund_type      VARCHAR(24) NOT NULL CHECK (refund_type IN ('full', 'partial')),
    refund_reason    VARCHAR(64) NOT NULL,
    refund_status    VARCHAR(24) NOT NULL CHECK (refund_status IN ('processed', 'pending')),
    processing_hours NUMERIC(8,2) NOT NULL CHECK (processing_hours >= 0)
);

-- 18. customer_segments
CREATE TABLE IF NOT EXISTS customer_segments (
    customer_id       BIGINT PRIMARY KEY REFERENCES customers(customer_id),
    as_of_date        DATE NOT NULL,
    recency_days      INT,
    frequency_orders  INT NOT NULL DEFAULT 0,
    monetary_value    NUMERIC(12,2) NOT NULL DEFAULT 0,
    r_score           SMALLINT NOT NULL CHECK (r_score BETWEEN 0 AND 5),
    f_score           SMALLINT NOT NULL CHECK (f_score BETWEEN 0 AND 5),
    m_score           SMALLINT NOT NULL CHECK (m_score BETWEEN 0 AND 5),
    rfm_code          CHAR(3) NOT NULL,
    business_segment  VARCHAR(40) NOT NULL,
    kmeans_cluster    SMALLINT,
    kmeans_label      VARCHAR(48),
    pca_x             NUMERIC(10,4),
    pca_y             NUMERIC(10,4),
    churn_risk_score  NUMERIC(6,4),
    churn_risk_band   VARCHAR(16)
);

-- Application Operational Metadata: Report Runs History
CREATE TABLE IF NOT EXISTS report_runs (
    run_id          SERIAL PRIMARY KEY,
    report_type     VARCHAR(32) NOT NULL,
    filename        VARCHAR(160) NOT NULL,
    file_path       VARCHAR(260) NOT NULL,
    start_date      DATE,
    end_date        DATE,
    filters_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_count       INT NOT NULL DEFAULT 0,
    file_size_bytes BIGINT NOT NULL DEFAULT 0,
    file_bytes      BYTEA,
    status          VARCHAR(24) NOT NULL DEFAULT 'completed',
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- ANALYTICAL INDEX STRATEGY
-- ============================================================================
-- 1. Time-series & filter slice indexes on sessions and orders
CREATE INDEX IF NOT EXISTS idx_sessions_date_dims
    ON sessions (session_date, device_type, acquisition_channel, city);
CREATE INDEX IF NOT EXISTS idx_sessions_customer_date
    ON sessions (customer_id, session_date);
CREATE INDEX IF NOT EXISTS idx_sessions_category
    ON sessions (primary_category_id, session_date);

-- 2. Event funnel aggregation indexes
CREATE INDEX IF NOT EXISTS idx_user_events_session_step
    ON user_events (session_id, step_order);
CREATE INDEX IF NOT EXISTS idx_user_events_date_type
    ON user_events (event_date, event_type);
CREATE INDEX IF NOT EXISTS idx_user_events_customer_date
    ON user_events (customer_id, event_date);

-- 3. Search & cart behavioral lookup indexes
CREATE INDEX IF NOT EXISTS idx_search_events_session
    ON search_events (session_id);
CREATE INDEX IF NOT EXISTS idx_search_events_category
    ON search_events (matched_category_id);
CREATE INDEX IF NOT EXISTS idx_cart_events_session
    ON cart_events (session_id);
CREATE INDEX IF NOT EXISTS idx_cart_events_category
    ON cart_events (category_id);

-- 4. Orders, cohorts, retention & revenue slicing indexes
CREATE INDEX IF NOT EXISTS idx_orders_date_status_dims
    ON orders (order_date, order_status, city, acquisition_channel, device_type);
CREATE INDEX IF NOT EXISTS idx_orders_customer_status_date
    ON orders (customer_id, order_status, order_date);
CREATE INDEX IF NOT EXISTS idx_orders_category_date
    ON orders (primary_category_id, order_date);
CREATE INDEX IF NOT EXISTS idx_orders_session
    ON orders (session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_orders_subscription
    ON orders (subscription_id) WHERE subscription_id IS NOT NULL;

-- 5. Order items, payments, cancellations & refunds
CREATE INDEX IF NOT EXISTS idx_order_items_order
    ON order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_category_product
    ON order_items (category_id, product_id);
CREATE INDEX IF NOT EXISTS idx_payments_status_method
    ON payments (payment_status, payment_method);
CREATE INDEX IF NOT EXISTS idx_cancellations_date_reason
    ON cancellations (cancelled_date, cancellation_reason);
CREATE INDEX IF NOT EXISTS idx_refunds_date_reason
    ON refunds (refund_date, refund_reason);
CREATE INDEX IF NOT EXISTS idx_refunds_order
    ON refunds (order_id);

-- 6. Subscriptions & customer dimensions
CREATE INDEX IF NOT EXISTS idx_subscriptions_customer_status
    ON subscriptions (customer_id, status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_category_start
    ON subscriptions (primary_category_id, start_date);
CREATE INDEX IF NOT EXISTS idx_sub_events_sub_date
    ON subscription_events (subscription_id, event_date);
CREATE INDEX IF NOT EXISTS idx_customers_signup_dims
    ON customers (signup_date, acquisition_channel, primary_city, primary_device);
CREATE INDEX IF NOT EXISTS idx_customer_addresses_customer
    ON customer_addresses (customer_id);
CREATE INDEX IF NOT EXISTS idx_customer_segments_business
    ON customer_segments (business_segment, kmeans_cluster);
CREATE INDEX IF NOT EXISTS idx_calendar_year_month
    ON calendar_dimension (year_month);
