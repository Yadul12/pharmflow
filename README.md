# PHARMFLOW — Healthcare E-Commerce Customer, Order Funnel & Retention Analytics

PharmFlow is an internal commercial, product, and customer growth analytics platform built for a synthetic healthcare e-commerce business. It models the end-to-end commercial journey across **30,000 customers**, **131,733 browsing sessions**, **469,724 funnel events**, **47,746 orders**, **3,537 recurring refill subscriptions**, and **1,061,907 total rows across 18 core PostgreSQL tables** spanning **14 calendar months (September 2025 – October 2026)**.

> **Synthetic Data & Branding Disclaimer**
> All PharmFlow customer, session, order, payment, cancellation, refund, and subscription records are **100% synthetic** (`RANDOM_SEED=42`). Customer identifiers (`CUST-000001`) are non-identifying, and no real patient names, clinical diagnoses, or protected health information (PHI) exist anywhere in the schema or dataset. PharmFlow is an independent commercial analytics case study and does not use PharmEasy's official branding or internal datasets.

---

## 1. Business Problem

Product, growth, and commercial teams in healthcare e-commerce need unified answers to core unit-economics and lifecycle questions:

1. **Visitor-to-Customer Conversion:** How many registered browsing visitors convert into delivered buyers?
2. **Funnel Bottlenecks:** Which exact funnel stage and device/channel segment experiences the steepest drop-off?
3. **Repeat Purchasing & Refill Velocity:** What share of buyers place repeat orders, and how quickly do chronic vs acute customers reorder?
4. **Cohort Retention Dynamics:** Which acquisition cohorts retain best, and why did retention soften in Q2 2026?
5. **Category Economics:** Which healthcare categories drive durable repeat ordering versus one-off durable purchases?
6. **Subscription Impact:** How do recurring refill plans relate to order frequency, LTV, and retention — while separating observational self-selection from proven causal lift?
7. **Declining Engagement & Churn Risk:** Which accounts are inactive or at elevated 90-day churn risk?
8. **Cancellation & Refund Leakage:** What operational, geographic, payment, and inventory drivers cause cancelled orders and refunds?

---

## 2. System Architecture

PharmFlow cleanly separates storage, analytical SQL, Python statistical modeling, report automation, and the React UI:

```text
+-----------------------------------------------------------------------------+
| React 18 + TypeScript + Plotly Enterprise Analytics UI (10 Purpose Views)   |
|  Executive · Funnel · Retention · Cohorts · Segmentation · Subscriptions    |
|  Categories · Cancellations & Refunds · PostgreSQL SQL Lab · Reports        |
+--------------------------------------+--------------------------------------+
                                       | REST JSON + File Downloads (/api/*)
                                       v
+-----------------------------------------------------------------------------+
| FastAPI Backend (Python 3.12 · psycopg3)                                    |
|  - Parameterized SQL Query Modules (backend/app/queries/*.py)               |
|  - Automated Business Insight Engine (correlation vs causation tagged)      |
|  - Read-Only PostgreSQL SQL Lab Executor (READ ONLY tx + EXPLAIN ANALYZE)   |
|  - openpyxl 8-Worksheet Excel Builder & CSV Export Service                  |
+--------------------------------------+--------------------------------------+
                                       |
              +------------------------+------------------------+
              v                                                 v
+---------------------------------------+   +---------------------------------+
| PostgreSQL 16 (Local Docker / Neon)   |   | Offline Python Data Science     |
|  - 18 Relational Analytical Tables    |   | (analytics/*.py)                |
|  - 2 Materialized Views               |   |  - Deterministic Synthetic Seed |
|  - 25 Composite & Partial Indexes     |   |  - EDA Profiling & Outliers     |
|  - report_runs Audit + BYTEA Archive  |   |  - RFM + K-Means + 2D PCA       |
+---------------------------------------+   |  - SciPy Hypothesis Testing     |
                                            |  - Time-Aware Churn Classifier  |
                                            |  - 20-Check SQL/Pandas Parity   |
                                            +---------------------------------+
```

---

## 3. Database Design & Optimization

The PostgreSQL schema ([`db/schema.sql`](db/schema.sql)) models 18 normalized relational tables plus operational `report_runs` tracking, reinforced by two materialized views ([`db/analytical_views.sql`](db/analytical_views.sql)):

| # | Table | Rows | Purpose |
|---:|---|---:|---|
| 1 | `calendar_dimension` | 426 | Calendar dates (Sep 2025 – Oct 2026), year-month, quarter, weekend flag, Indian seasons |
| 2 | `medicine_categories` | 10 | Commercial healthcare categories, chronic refill flags, typical refill cadence, margin % |
| 3 | `product_catalog` | 220 | Synthetic SKUs with brand tier, unit price, MRP, subscription eligibility, verification flag |
| 4 | `promotional_campaigns` | 12 | Acquisition, seasonal, refill, subscription, and win-back campaigns |
| 5 | `customers` | 30,000 | Non-identifying customer accounts, signup channel, primary device, city/tier, age band |
| 6 | `customer_addresses` | 36,072 | Home/Work/Family delivery zones and promised city-tier delivery SLAs |
| 7 | `sessions` | 131,733 | Interactive visits with duration, device, channel, city, new vs repeat flag |
| 8 | `user_events` | 469,724 | Granular 7-step funnel clickstream events (`app_visit` through `order_delivered`) |
| 9 | `search_events` | 96,824 | In-app search queries, matched categories, result counts, product click-through |
| 10 | `cart_events` | 66,792 | Cart additions, quantity updates, and cart removals |
| 11 | `subscriptions` | 3,537 | 30/45/60-day recurring refill plans, status (`active`/`paused`/`cancelled`), MRR |
| 12 | `subscription_events` | 17,675 | Subscription lifecycle log (`created`, `renewed`, `paused`, `resumed`, `cancelled`, `payment_retry_failed`) |
| 13 | `orders` | 47,746 | Interactive & subscription auto-refill orders, amounts, delivery SLAs, duplicate flags |
| 14 | `order_items` | 72,513 | Multi-SKU line items reconciled 1:1 to order totals |
| 15 | `payments` | 47,746 | Payment method (`UPI`, `Cards`, `COD`, `Wallet`, `Net Banking`), status, gateway latency |
| 16 | `cancellations` | 5,829 | Cancellation stage, reason code, initiator, and hours elapsed after placement |
| 17 | `refunds` | 5,048 | Full/partial refunds (`processed`/`pending`), refund reason, processing hours |
| 18 | `customer_segments` | 30,000 | RFM scores/segments, K-Means cluster IDs, 2D PCA coordinates, and 90-day churn risk scores |
| — | `report_runs` | Audit | Persists generated Excel/CSV run metadata, filter JSON, and `BYTEA` binary payloads |

### Indexing & Query Optimization Decisions
- **Composite Filter Indexes:** `idx_sessions_date_dims` and `idx_orders_date_status_dims` cover date-range + device + channel + city slicing without full table scans.
- **Window Partition Index:** `idx_orders_customer_status_date (customer_id, order_status, order_date)` accelerates `ROW_NUMBER()`, `LAG()`, `LEAD()`, and cohort first-order lookups.
- **Partial Indexes:** `idx_orders_session` and `idx_orders_subscription` index only non-null foreign keys (`WHERE session_id IS NOT NULL`, `WHERE subscription_id IS NOT NULL`) to keep index footprints small.
- **Materialized Views:** `mv_session_funnel` rolls up raw `user_events` into session-level monotonic funnel flags, and `mv_customer_lifecycle` pre-aggregates first/second/last delivered order dates and subscriber status—delivering sub-50ms multi-filter dashboard responses while reconciling 100% with raw transactional tables.

---

## 4. Funnel Definitions & Explicit Denominators

Interactive session funnel tracking follows seven strictly monotonic steps (`app_visit` → `product_search` → `product_view` → `add_to_cart` → `checkout_started` → `order_placed` → `order_delivered`):

| Metric | Numerator | Denominator | Observed Value |
|---|---|---|---|
| **Product Search Rate** | Sessions reaching `product_search` (96,824) | Total Interactive Sessions (131,733) | **73.50%** |
| **Product View Rate** | Sessions reaching `product_view` (78,558) | Search Sessions (96,824) | **81.13%** |
| **Add-to-Cart Rate** | Sessions reaching `add_to_cart` (54,700) | Product View Sessions (78,558) | **69.63%** |
| **Checkout Initiation Rate** | Sessions reaching `checkout_started` (41,404) | Add-to-Cart Sessions (54,700) | **75.69%** |
| **Checkout Conversion** | Sessions reaching `order_placed` (35,969) | Checkout Initiated Sessions (41,404) | **86.87%** |
| **Order Conversion (Session)** | Order Placed Sessions (35,969) | Total Interactive Sessions (131,733) | **27.30%** |
| **Completed Order Rate** | Order Delivered Sessions (30,536) | Total Interactive Sessions (131,733) | **23.18%** |
| **Visitor-to-Customer Rate** | Distinct Delivered Buyers (14,800) | Active Registered Visitors (30,000) | **49.33%** |

**Population Reconciliation:** Interactive Step 6 (`35,969` placed) and Step 7 (`30,536` delivered) reconcile 1:1 with non-duplicate interactive orders (`order_source = 'interactive_session'`). Automated recurring refills (`10,684` delivered orders from `subscription_auto_refill`) do not originate from interactive browsing sessions and are tracked explicitly alongside interactive orders (`30,536 + 10,684 = 41,220` total delivered orders). Accidental customer double-submits (`396` rows flagged `is_duplicate_attempt = TRUE`) are automatically cancelled and excluded from operational cancellation denominators.

---

## 5. Customer Retention & Cohort Methodology

- **D1 / D7 / D30 Session Engagement:** Evaluated strictly over signups whose `signup_date <= period_end - window_days` (`D1 = 7.04%` across 29,919 eligible signups; `D7 = 21.72%` across 29,473 eligible signups; `D30 = 46.77%`).
- **D30 / D60 / D90 First-Order Repeat Rates:** Measured from first delivered order to second delivered order over matured first-time buyers (`D30 = 20.27%` across 13,567 eligible; `D60 = 39.30%`; `D90 = 48.55%` across 11,199 eligible).
- **Monthly Cohort Matrix (`M0`–`M12`):** Cohorts are anchored on the calendar month of a customer's **first delivered order**. Unmatured future month offsets are rendered blank (`NULL`, never zero-padded) to eliminate right-censoring bias.
- **90-Day Reactivation Rate:** Numerator counts buyers placing an order in Month $M$ whose immediately prior delivered order occurred $>90$ days before the start of Month $M$ (`prev_order_date < month_start - 90 days`), divided by the exact entering-month inactive buyer pool (`avg = 11.12%` across matured months Jan–Oct 2026).

---

## 6. Python Analysis Methodology & Validation

All offline Python analytics live under `analytics/`:

1. **Data Profiling & EDA (`analytics/profiling_eda.py`):**
   - Audits all 18 tables (`1,061,907` rows), verifies zero duplicate `customer_code` or `order_code` keys, confirms `396` flagged duplicate order attempts are 100% cancelled, confirms `0` funnel monotonicity violations and `0` order-item financial mismatches, profiles expected NULLs, and runs IQR outlier analysis (`Delivered Order Net Amount` median `₹1,258.18`, mean `₹1,610.99`, IQR upper fence `₹4,009.68`, `4.79%` high-basket tail).
2. **RFM Segmentation & K-Means Clustering (`analytics/segmentation_kmeans.py`):**
   - Partitions all `30,000` customers into 6 mutually exclusive RFM business segments (`High-Value Repeat`, `Regular Customers`, `New Customers`, `At-Risk Customers`, `Inactive Customers`, `Registered Non-Buyers`).
   - Runs K-Means across `14,800` ordering buyers on standardized `log_recency`, `log_frequency`, `log_monetary`, `is_single_order`, `is_subscriber`, and `chronic_share` (retaining `6,704` single-order buyers via median inter-order gap imputation + binary missingness indicator rather than dropping them). Optimal $k=4$ selected by Silhouette score (`0.4413`); 2D PCA explains `71.88%` of variance (`57.36%` PC1 + `14.52%` PC2).
3. **Statistical Testing (`analytics/statistical_tests.py`):**
   - Executes two-proportion Z-tests with 95% Wald confidence intervals plus Mann-Whitney U and Welch's $t$-tests, explicitly annotating observational confounding and self-selection caveats.
4. **Time-Aware Churn Risk Model (`analytics/churn_model.py`):**
   - Strictly chronological splits with zero target leakage: Train cutoff `2026-04-30` (outcome window `2026-05-01`..`2026-07-31`, $n=7,093$), Out-of-Time Test cutoff `2026-07-31` (outcome window `2026-08-01`..`2026-10-31`, $n=11,135$). Preprocessing fit exclusively on training data.
   - Regularized `HistGradientBoostingClassifier` achieves **ROC-AUC `0.7967`** (95% CI `[0.7890, 0.8044]`) and **PR-AUC `0.8464`** vs Logistic Regression (`ROC-AUC 0.7870`) and Naive Majority Baseline (`ROC-AUC 0.5000`).
5. **SQL vs Pandas Parity (`analytics/reconciliation.py`):**
   - **20/20 independent reconciliation checks pass** with `0.0000` discrepancy across customer counts, all 7 funnel stages, repeat purchase rate (`54.70%`), M1 cohort retention (`26.41%`), active subscriptions (`2,253`), delivered net revenue (`₹66,404,942.94`), and refunds (`₹8,552,044.33`).

---

## 7. Key Business Findings (Observed From PostgreSQL)

- **Headline Scale & Repeat Economics:** Across 14 months, PharmFlow processed **₹6.64 Cr** (`₹66,404,942.94`) in net delivered revenue across **41,220 delivered orders** (`AOV ₹1,610.99`), achieving a **54.70%** repeat purchase rate (`8,096` of `14,800` buyers) and an average inter-order interval of **59.5 days** (`45.1 days` across individual repeat transitions). High-Value Repeat buyers (`1,650` customers, `5.5%` of total accounts) generate **33.96% (`₹2.26 Cr`)** of all net revenue.
- **Primary Funnel Bottleneck (Mobile Web Checkout Friction):** Overall **Add-to-Cart** represents the largest relative drop-off (`30.37%` loss from Product View). Across devices, **Mobile Web** suffers a severe **Cart-to-Checkout** bottleneck (`53.52%` progression vs `84.46%` on Native Apps; $-30.94$ pp, $z = 72.15$, $p < 0.0001$), driven by a mix of checkout UX/OTP friction and higher paid/social visitor mix.
- **Category Repeat Leadership:** **Chronic Care Refills** leads repeat purchasing (`43.27%` category repeat buyer rate, `₹1.72 Cr` revenue) followed by **Diabetes Care Supplies** (`33.66%`, `₹1.25 Cr`), whereas **Home Diagnostics & Devices** (`4.22%` repeat rate, `₹3,077` AOV) behaves as a durable entry category. Mature buyers starting in chronic categories repeat at **77.21%** vs **57.96%** for non-chronic categories ($+19.25$ pp, $z = 19.91$).
- **Q2 2026 Cohort Retention Decline:** Cohorts acquired in **Apr–Jun 2026** dropped to **23.68%** Month-1 retention ($n=3,987$) compared to **29.83%** for the Oct 2025–Feb 2026 baseline ($n=4,204$; $-6.15$ pp, $z = -6.28$, $p = 3.38 \times 10^{-10}$), coinciding with aggressive Q2 Social Media (`SPRINGBLITZ` 25% off) and Affiliate (`AFFILFLASH` 22% off) promos.
- **Subscriptions & Selection Bias:** Subscriptions contribute **25.92%** of delivered orders (`10,684` auto-refills), **₹19.00 L** active MRR (`2,253` active plans), and **89.88%** cycle renewal rate. Mature subscribers repeat at **98.43%** (`6.81` avg orders) vs **51.31%** (`1.91` avg orders) for non-subscribers ($z = 46.36$)—an observational association heavily influenced by chronic-need self-selection rather than pure causal lift.
- **Cancellation & Refund Drivers:** Operational cancellation rate is **11.47%** (`5,433` non-duplicate cancelled orders worth **₹92.86 L**), with **₹85.52 L** refunded across `5,048` refunds (`30.8h` avg processing). **Delivery Delay / SLA Breach** (`26.39%` share, `1,538` orders) and **Out of Stock After Order** (`17.36%`, `1,012` orders) are the top preventable drivers; **Tier 3 cities** cancel at **18.46%** vs **10.38%** in Tier 1 ($+8.08$ pp, $z = 12.34$, $p = 5.66 \times 10^{-35}$).

---

## 8. Setup Instructions

### Option A: Local Full Stack (Docker Compose)

```bash
git clone https://github.com/Yadul12/pharmflow.git
cd pharmflow
docker compose up -d --build
```

Run the deterministic seeding, ML clustering, churn evaluation, EDA, and reconciliation pipeline:

```bash
docker exec pharmflow-backend python -m analytics.bootstrap_pipeline --force
```

Run the 10-test automated validation suite:

```bash
docker exec pharmflow-backend pytest -v /app/tests/test_analytics.py
```

Access the application:
- **Frontend UI:** `http://localhost:3060`
- **FastAPI Docs:** `http://localhost:8060/docs`
- **PostgreSQL:** `localhost:5460` (`pharmflow_user` / `pharmflow_pass` / `pharmflow`)

### Option B: Vercel Serverless + Neon Postgres

PharmFlow deploys via [`vercel.json`](vercel.json) using Vercel Services (`frontend` Vite SPA + `backend` FastAPI ASGI) connected to a Neon PostgreSQL database using `DB_SCHEMA=pharmflow`.

1. Link the project and connect a Neon Postgres integration (`DATABASE_URL` + `DB_SCHEMA=pharmflow`).
2. Load `db/schema.sql`, `db/analytical_views.sql`, and seed data into the `pharmflow` schema.
3. Deploy with `npx vercel deploy --prod`.

---

## 9. Automated Verification Summary

- **SQL vs Pandas Reconciliation:** `20 / 20` checks passing (`analytics_outputs/reconciliation_report.json`).
- **Backend Pytest Suite:** `10 / 10` tests passing (`backend/tests/test_analytics.py`) covering scale, duplicate handling, funnel monotonicity, cohort maturation, retention denominators, subscription/category metrics, filters, SQL Lab read-only security, 8-sheet `openpyxl` Excel generation, and Customer/Order CSV exports.
- **Visual & Browser Verification:** All 10 pages (`/`, `/funnel`, `/retention`, `/cohorts`, `/segmentation`, `/subscriptions`, `/categories`, `/cancellations`, `/sql-lab`, `/reports`) and the Metric Definitions drawer verified in headless browser with zero console errors and zero HTTP `>= 400` API responses.
