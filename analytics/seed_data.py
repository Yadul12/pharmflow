"""
PHARMFLOW — Deterministic Synthetic Healthcare E-Commerce Dataset Generator
===========================================================================
Generates 100% synthetic, non-identifying customer, session, funnel event,
search, cart, order, payment, cancellation, refund, and subscription records
and bulk-loads them into PostgreSQL via COPY.

Design principles:
- Fixed random seed (default 42) for reproducible analytics & SQL/Python parity.
- No personal health information (PHI), patient names, or clinical diagnoses.
- Causal behavioral relationships between customer archetypes, sessions,
  funnel drop-offs, device/city friction, seasonality, subscriptions,
  Q2 2026 promo-cohort retention dip, and cancellation/refund drivers.
"""

from __future__ import annotations

import io
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import psycopg

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------
SEED = int(os.getenv("RANDOM_SEED", "42"))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pharmflow_user:pharmflow_pass@localhost:5460/pharmflow",
)

START_DATE = date(2025, 9, 1)
END_DATE = date(2026, 10, 31)  # 14 complete calendar months
TOTAL_DAYS = (END_DATE - START_DATE).days + 1  # 426 days
N_CUSTOMERS = 30_000

IST = timezone(timedelta(hours=5, minutes=30))

CITIES = [
    # (city, state, tier, weight, base_sla_days, conv_mult, cancel_mult)
    ("Mumbai", "Maharashtra", "Tier 1", 0.145, 2, 1.08, 0.85),
    ("Bengaluru", "Karnataka", "Tier 1", 0.140, 2, 1.12, 0.82),
    ("Delhi NCR", "Delhi", "Tier 1", 0.135, 2, 1.03, 0.96),
    ("Hyderabad", "Telangana", "Tier 1", 0.095, 2, 1.05, 0.90),
    ("Chennai", "Tamil Nadu", "Tier 1", 0.080, 2, 1.02, 0.92),
    ("Pune", "Maharashtra", "Tier 1", 0.085, 2, 1.07, 0.86),
    ("Ahmedabad", "Gujarat", "Tier 2", 0.065, 3, 0.97, 1.06),
    ("Kolkata", "West Bengal", "Tier 2", 0.070, 3, 0.86, 1.32),
    ("Jaipur", "Rajasthan", "Tier 2", 0.050, 3, 0.94, 1.12),
    ("Kochi", "Kerala", "Tier 2", 0.040, 3, 1.00, 0.98),
    ("Lucknow", "Uttar Pradesh", "Tier 3", 0.050, 4, 0.78, 1.52),
    ("Indore", "Madhya Pradesh", "Tier 3", 0.045, 4, 0.81, 1.44),
]

CHANNELS = [
    "Organic Search",
    "Paid Search",
    "Social Media",
    "Referral",
    "Direct",
    "Email / CRM",
    "Affiliate",
]
CHANNEL_WEIGHTS = np.array([0.26, 0.19, 0.16, 0.11, 0.13, 0.08, 0.07])

DEVICES = ["Android App", "iOS App", "Mobile Web", "Desktop Web"]
DEVICE_WEIGHTS = np.array([0.46, 0.21, 0.22, 0.11])

AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
AGE_WEIGHTS = np.array([0.09, 0.27, 0.24, 0.19, 0.13, 0.08])

CATEGORIES = [
    # (code, name, group, refill_days, is_chronic, margin, avg_price, sub_eligible, verif_prob, search_terms)
    (
        "CAT-CHR", "Chronic Care Refills", "Chronic & Refill", 30, True, 24.5, 1140.0, True, 0.72,
        ["monthly refill pack", "chronic care 30 day", "daily maintenance pack", "refill bundle", "regular care tabs"],
    ),
    (
        "CAT-DIA", "Diabetes Care Supplies", "Chronic & Refill", 30, True, 26.0, 1320.0, True, 0.45,
        ["test strips 50", "lancets box", "glucometer refill", "sugar free nutrition", "glucose strips"],
    ),
    (
        "CAT-VIT", "Vitamins & Supplements", "Wellness & Preventive", 45, False, 34.0, 760.0, True, 0.05,
        ["vitamin d3 60", "multivitamin daily", "omega 3 capsules", "calcium tablets", "b12 supplement"],
    ),
    (
        "CAT-CAR", "Cardiac & Wellness Nutrition", "Chronic & Refill", 35, True, 27.5, 1080.0, True, 0.58,
        ["heart health supplement", "coq10 capsules", "bp care nutrition", "daily wellness pack", "cholesterol support"],
    ),
    (
        "CAT-OTC", "OTC Pain & Fever", "Acute & OTC", 75, False, 21.0, 330.0, False, 0.04,
        ["pain relief gel", "fever relief tabs", "cold flu relief", "headache balm", "throat lozenges"],
    ),
    (
        "CAT-DIG", "Digestive & Gut Health", "Acute & OTC", 60, False, 25.5, 460.0, False, 0.08,
        ["probiotic capsules", "antacid syrup", "electrolyte ors", "fiber powder", "digestive enzymes"],
    ),
    (
        "CAT-DER", "Dermatology & Skincare", "Wellness & Preventive", 45, False, 36.5, 890.0, True, 0.20,
        ["spf50 sunscreen", "ceramide moisturizer", "salicylic cleanser", "scalp serum", "barrier cream"],
    ),
    (
        "CAT-MAT", "Baby & Maternal Care", "Wellness & Preventive", 35, False, 29.0, 940.0, True, 0.06,
        ["baby gentle wash", "diaper rash cream", "prenatal multivitamin", "baby wipes pack", "lactation nutrition"],
    ),
    (
        "CAT-DEV", "Home Diagnostics & Devices", "Devices & Diagnostics", None, False, 31.0, 1680.0, False, 0.00,
        ["digital bp monitor", "pulse oximeter", "infrared thermometer", "nebulizer kit", "weighing scale"],
    ),
    (
        "CAT-AID", "First Aid & Personal Hygiene", "Acute & OTC", 90, False, 28.0, 310.0, False, 0.00,
        ["antiseptic liquid", "adhesive bandages", "cotton gauze roll", "hand sanitizer", "first aid kit"],
    ),
]

CAMPAIGNS = [
    ("WELCOME15", "New Member First Order 15% Off", "Paid Search", 15.0, 499.0, date(2025, 9, 1), date(2026, 10, 31), "Acquisition"),
    ("APPFIRST", "Mobile App First Checkout Bonus", "Direct", 12.0, 399.0, date(2025, 9, 1), date(2026, 10, 31), "Acquisition"),
    ("SUBSAVE20", "Subscribe & Save Chronic Refill", "Email / CRM", 18.0, 699.0, date(2025, 9, 15), date(2026, 10, 31), "Subscription"),
    ("DIWALIHEALTH", "Festive Wellness Basket Offer", "Social Media", 16.0, 799.0, date(2025, 10, 10), date(2025, 11, 15), "Seasonal"),
    ("WINTERSHIELD", "Winter Immunity & Cold Care", "Organic Search", 10.0, 349.0, date(2025, 11, 20), date(2026, 1, 31), "Seasonal"),
    ("NEWYEARFIT", "New Year Preventive Supplements", "Social Media", 15.0, 599.0, date(2026, 1, 1), date(2026, 2, 15), "Seasonal"),
    ("REFILL10", "Monthly Refill Loyalty Reminder", "Email / CRM", 10.0, 500.0, date(2025, 10, 1), date(2026, 10, 31), "Refill"),
    ("SPRINGBLITZ", "Q2 Aggressive Social Acquisition Blitz", "Social Media", 25.0, 299.0, date(2026, 4, 1), date(2026, 6, 30), "Acquisition"),
    ("AFFILFLASH", "Q2 Affiliate Cashback Flash Promo", "Affiliate", 22.0, 299.0, date(2026, 4, 1), date(2026, 6, 30), "Acquisition"),
    ("MONSOONCARE", "Monsoon Gut & First Aid Shield", "Paid Search", 12.0, 399.0, date(2026, 7, 1), date(2026, 8, 31), "Seasonal"),
    ("WINBACK15", "90-Day Inactive Customer Reactivation", "Email / CRM", 15.0, 499.0, date(2026, 2, 1), date(2026, 10, 31), "Reactivation"),
    ("REFERFRIEND", "Member Referral Credit", "Referral", 14.0, 450.0, date(2025, 9, 1), date(2026, 10, 31), "Acquisition"),
]

BRAND_TIERS = ["National", "Clinical", "Value"]
PACK_SIZES = ["Pack of 30", "Pack of 60", "100 ml", "200 ml", "50 Strips", "1 Unit", "Pack of 10", "500 g"]

CANCELLATION_REASONS = [
    ("Delivery Delay / SLA Breach", "in_transit", "customer"),
    ("Out of Stock After Order", "pre_dispatch", "operations"),
    ("Verification Pending Timeout", "pre_verification", "system"),
    ("Payment Failure / Timeout", "pre_verification", "payment_gateway"),
    ("Customer Changed Mind", "pre_dispatch", "customer"),
    ("Price Comparison Elsewhere", "pre_dispatch", "customer"),
    ("Duplicate Order Placed", "pre_verification", "customer"),
    ("Address / Recipient Unavailable", "at_delivery", "operations"),
]

SUB_CANCEL_REASONS = [
    "Switched to Ad-hoc Buying",
    "Stock / Refill Delay",
    "Price Sensitivity",
    "Regimen Schedule Changed",
    "Auto-Debit Payment Failure",
    "Delivery Timing Mismatch",
]


def _season_for_month(m: int) -> str:
    if m in (7, 8, 9):
        return "Monsoon"
    if m in (10, 11):
        return "Autumn"
    if m in (12, 1, 2):
        return "Winter"
    if m in (3, 4):
        return "Spring"
    return "Summer"


def _copy_rows(cur: psycopg.Cursor, table: str, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
    """Fast PostgreSQL COPY bulk insert."""
    if not rows:
        return
    cols_sql = ", ".join(columns)
    buf = io.StringIO()
    for r in rows:
        parts = []
        for val in r:
            if val is None:
                parts.append(r"\N")
            elif isinstance(val, bool):
                parts.append("t" if val else "f")
            elif isinstance(val, (datetime, date)):
                parts.append(val.isoformat())
            else:
                s = str(val).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ").replace("\r", " ")
                parts.append(s)
        buf.write("\t".join(parts) + "\n")
    buf.seek(0)
    with cur.copy(f"COPY {table} ({cols_sql}) FROM STDIN") as copy:
        while data := buf.read(1024 * 1024):
            copy.write(data)


def _seasonal_multiplier(d: date, cat_idx: int) -> float:
    m = d.month
    # Winter boost for OTC Pain & Fever (4), Vitamins (2)
    if m in (11, 12, 1) and cat_idx in (4, 2):
        return 1.32
    # Monsoon boost for OTC (4), Digestive (5), First Aid (9)
    if m in (7, 8) and cat_idx in (4, 5, 9):
        return 1.38
    # Spring wellness/derma bump (3, 4)
    if m in (3, 4) and cat_idx in (2, 6):
        return 1.18
    # Festival October boost across wellness & devices
    if m == 10 and cat_idx in (2, 6, 8):
        return 1.15
    return 1.0


def seed_database(database_url: str = DATABASE_URL, force: bool = False) -> dict[str, int]:
    t0 = time.perf_counter()
    rng = np.random.default_rng(SEED)

    with psycopg.connect(database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM customers;")
            existing = cur.fetchone()[0]
            if existing > 0 and not force:
                print(f"[seed] Database already populated with {existing:,} customers. Skipping seed.")
                return {"customers": existing}

            if force:
                print("[seed] Truncating existing tables for clean deterministic seed...")
                cur.execute(
                    """
                    TRUNCATE TABLE
                        report_runs, customer_segments, refunds, cancellations,
                        payments, order_items, orders, subscription_events,
                        subscriptions, cart_events, search_events, user_events,
                        sessions, customer_addresses, customers,
                        promotional_campaigns, product_catalog, medicine_categories,
                        calendar_dimension
                    RESTART IDENTITY CASCADE;
                    """
                )

            # ------------------------------------------------------------------
            # 1. Calendar Dimension
            # ------------------------------------------------------------------
            cal_rows = []
            for offset in range(TOTAL_DAYS):
                d = START_DATE + timedelta(days=offset)
                cal_rows.append(
                    (
                        d,
                        d.year,
                        (d.month - 1) // 3 + 1,
                        d.month,
                        d.strftime("%B"),
                        d.strftime("%Y-%m"),
                        d.isocalendar().week,
                        d.weekday(),
                        d.strftime("%A"),
                        d.weekday() >= 5,
                        _season_for_month(d.month),
                    )
                )
            _copy_rows(
                cur,
                "calendar_dimension",
                [
                    "date_key", "year", "quarter", "month", "month_name", "year_month",
                    "week_of_year", "day_of_week", "day_name", "is_weekend", "season",
                ],
                cal_rows,
            )

            # ------------------------------------------------------------------
            # 2. Medicine Categories (10 commercial categories)
            # ------------------------------------------------------------------
            cat_rows = []
            for idx, c in enumerate(CATEGORIES, start=1):
                cat_rows.append((idx, c[0], c[1], c[2], c[3], c[4], c[5]))
            _copy_rows(
                cur,
                "medicine_categories",
                [
                    "category_id", "category_code", "category_name", "category_group",
                    "typical_refill_days", "is_chronic_refill", "avg_margin_pct",
                ],
                cat_rows,
            )
            cur.execute("SELECT setval('medicine_categories_category_id_seq', (SELECT MAX(category_id) FROM medicine_categories));")

            # ------------------------------------------------------------------
            # 3. Product Catalog (220 synthetic commercial SKUs)
            # ------------------------------------------------------------------
            prod_rows = []
            cat_products: dict[int, list[dict[str, Any]]] = {i: [] for i in range(1, len(CATEGORIES) + 1)}
            sku_descriptors = [
                "Essential", "Plus", "Daily", "Pro", "Advance", "Ultra",
                "Care", "Relief", "Active", "Balance", "Complete", "Classic",
                "Gentle", "Shield", "Max", "Pure", "Smart", "Lite",
                "Vital", "Guard", "Prime", "Core",
            ]
            prod_id = 1
            for cat_id, c in enumerate(CATEGORIES, start=1):
                base_price = c[6]
                sub_elig = c[7]
                verif_prob = c[8]
                terms = c[9]
                for j in range(22):
                    brand_tier = BRAND_TIERS[j % 3]
                    tier_mult = 1.18 if brand_tier == "Clinical" else (1.0 if brand_tier == "National" else 0.78)
                    unit_price = round(float(base_price * tier_mult * rng.uniform(0.65, 1.38)), 2)
                    mrp = round(float(unit_price * rng.uniform(1.08, 1.24)), 2)
                    pack = PACK_SIZES[(cat_id + j) % len(PACK_SIZES)]
                    term_base = terms[j % len(terms)].title()
                    pname = f"{term_base} {sku_descriptors[j]} ({pack})"
                    sku_code = f"PF-{cat_id:02d}-{prod_id:04d}"
                    is_sub = bool(sub_elig and (j % 5 != 4))
                    needs_verif = bool(rng.random() < verif_prob)
                    prod_rows.append(
                        (
                            prod_id, sku_code, pname, cat_id, brand_tier,
                            unit_price, mrp, pack, is_sub, needs_verif, True,
                        )
                    )
                    cat_products[cat_id].append(
                        {
                            "product_id": prod_id,
                            "category_id": cat_id,
                            "unit_price": unit_price,
                            "is_sub": is_sub,
                            "needs_verif": needs_verif,
                            "stock_issue_prone": (cat_id in (1, 7) and j < 5),
                        }
                    )
                    prod_id += 1

            _copy_rows(
                cur,
                "product_catalog",
                [
                    "product_id", "sku_code", "product_name", "category_id", "brand_tier",
                    "unit_price", "mrp", "pack_size", "is_subscription_eligible",
                    "verification_required", "is_active",
                ],
                prod_rows,
            )
            cur.execute("SELECT setval('product_catalog_product_id_seq', (SELECT MAX(product_id) FROM product_catalog));")

            # ------------------------------------------------------------------
            # 4. Promotional Campaigns
            # ------------------------------------------------------------------
            camp_rows = []
            for idx, cm in enumerate(CAMPAIGNS, start=1):
                camp_rows.append((idx, *cm))
            _copy_rows(
                cur,
                "promotional_campaigns",
                [
                    "campaign_id", "campaign_code", "campaign_name", "channel",
                    "discount_pct", "min_order_value", "start_date", "end_date", "campaign_type",
                ],
                camp_rows,
            )
            cur.execute("SELECT setval('promotional_campaigns_campaign_id_seq', (SELECT MAX(campaign_id) FROM promotional_campaigns));")

            # ------------------------------------------------------------------
            # 5 & 6. Customers (30,000) & Customer Addresses (~36,000)
            # ------------------------------------------------------------------
            print("[seed] Generating 30,000 customers and addresses...")
            city_weights = np.array([c[3] for c in CITIES])
            city_weights = city_weights / city_weights.sum()

            # Signup distribution: realistic gradual growth + Q2 2026 promo surge (Apr-Jun 2026)
            day_weights = np.ones(TOTAL_DAYS, dtype=float)
            for d_off in range(TOTAL_DAYS):
                d = START_DATE + timedelta(days=d_off)
                # Steady acquisition ramp
                day_weights[d_off] *= 0.85 + 0.35 * (d_off / TOTAL_DAYS)
                # Initial launch base (Sep-Oct 2025 slightly higher to give mature cohorts)
                if d.year == 2025 and d.month in (9, 10):
                    day_weights[d_off] *= 1.35
                # Q2 2026 aggressive social/affiliate promo acquisition surge
                if d.year == 2026 and d.month in (4, 5, 6):
                    day_weights[d_off] *= 1.38
            day_weights /= day_weights.sum()

            signup_offsets = rng.choice(TOTAL_DAYS, size=N_CUSTOMERS, p=day_weights)
            city_indices = rng.choice(len(CITIES), size=N_CUSTOMERS, p=city_weights)
            age_indices = rng.choice(len(AGE_BANDS), size=N_CUSTOMERS, p=AGE_WEIGHTS)

            cust_rows = []
            addr_rows = []
            # Per-customer metadata kept compact in Python lists for fast simulation
            cust_meta: list[dict[str, Any]] = []
            addr_id = 1

            for cid in range(1, N_CUSTOMERS + 1):
                s_off = int(signup_offsets[cid - 1])
                s_date = START_DATE + timedelta(days=s_off)
                s_ts = datetime(
                    s_date.year, s_date.month, s_date.day,
                    int(rng.integers(7, 23)), int(rng.integers(0, 60)), int(rng.integers(0, 60)),
                    tzinfo=IST,
                )
                c_idx = int(city_indices[cid - 1])
                city_name, state_name, city_tier, _, base_sla, city_conv_mult, city_cancel_mult = CITIES[c_idx]
                age_idx = int(age_indices[cid - 1])
                age_band = AGE_BANDS[age_idx]

                # Q2 2026 promo surge skews channel toward Social Media / Affiliate and archetype toward Promo One-Timer
                is_q2_2026 = (s_date.year == 2026 and s_date.month in (4, 5, 6))
                if is_q2_2026:
                    ch_probs = np.array([0.19, 0.16, 0.27, 0.08, 0.09, 0.05, 0.16])
                else:
                    ch_probs = CHANNEL_WEIGHTS
                channel = str(CHANNELS[int(rng.choice(len(CHANNELS), p=ch_probs))])

                # Device skew: Tier 1 has more iOS/Android App; Tier 3 & Social/Affiliate have more Mobile Web
                dev_probs = DEVICE_WEIGHTS.copy()
                if city_tier == "Tier 3":
                    dev_probs = np.array([0.44, 0.08, 0.38, 0.10])
                elif city_tier == "Tier 2":
                    dev_probs = np.array([0.46, 0.14, 0.28, 0.12])
                if channel in ("Social Media", "Affiliate"):
                    dev_probs = dev_probs * np.array([0.85, 0.85, 1.45, 0.90])
                    dev_probs /= dev_probs.sum()
                device = str(DEVICES[int(rng.choice(len(DEVICES), p=dev_probs))])

                # Assign latent behavioral archetype
                # 0=Chronic Refiller, 1=Wellness Regular, 2=Acute/Seasonal, 3=Promo One-Timer, 4=Window Shopper
                if is_q2_2026 and channel in ("Social Media", "Affiliate"):
                    arch_probs = np.array([0.07, 0.10, 0.16, 0.44, 0.23])
                elif age_idx >= 3:  # 45+
                    arch_probs = np.array([0.36, 0.22, 0.18, 0.09, 0.15])
                else:
                    arch_probs = np.array([0.14, 0.26, 0.27, 0.14, 0.19])
                archetype = int(rng.choice(5, p=arch_probs))

                # Optional signup campaign
                signup_camp = None
                if is_q2_2026 and channel == "Social Media" and rng.random() < 0.72:
                    signup_camp = 8  # SPRINGBLITZ
                elif is_q2_2026 and channel == "Affiliate" and rng.random() < 0.75:
                    signup_camp = 9  # AFFILFLASH
                elif channel == "Paid Search" and rng.random() < 0.45:
                    signup_camp = 1  # WELCOME15
                elif channel == "Referral" and rng.random() < 0.65:
                    signup_camp = 12  # REFERFRIEND
                elif device in ("Android App", "iOS App") and rng.random() < 0.25:
                    signup_camp = 2  # APPFIRST

                cust_rows.append(
                    (
                        cid,
                        f"CUST-{cid:06d}",
                        s_date,
                        s_ts,
                        channel,
                        device,
                        city_name,
                        city_tier,
                        age_band,
                        signup_camp,
                        bool(rng.random() < 0.96),
                        True,
                    )
                )

                # Primary address
                primary_addr_id = addr_id
                postal_zone = f"{11 + c_idx:02d}{int(rng.integers(1000, 9999))}"
                addr_rows.append(
                    (addr_id, cid, city_name, state_name, city_tier, postal_zone, "Home", True, base_sla)
                )
                addr_id += 1
                # ~20% add a secondary Work/Family address
                if rng.random() < 0.20:
                    postal_zone2 = f"{11 + c_idx:02d}{int(rng.integers(1000, 9999))}"
                    addr_rows.append(
                        (
                            addr_id, cid, city_name, state_name, city_tier, postal_zone2,
                            "Work" if rng.random() < 0.6 else "Family", False, base_sla,
                        )
                    )
                    addr_id += 1

                cust_meta.append(
                    {
                        "cid": cid,
                        "signup_date": s_date,
                        "signup_off": s_off,
                        "channel": channel,
                        "device": device,
                        "city": city_name,
                        "city_tier": city_tier,
                        "base_sla": base_sla,
                        "city_conv_mult": city_conv_mult,
                        "city_cancel_mult": city_cancel_mult,
                        "age_idx": age_idx,
                        "archetype": archetype,
                        "primary_addr_id": primary_addr_id,
                        "signup_camp": signup_camp,
                    }
                )

            _copy_rows(
                cur,
                "customers",
                [
                    "customer_id", "customer_code", "signup_date", "signup_ts",
                    "acquisition_channel", "primary_device", "primary_city", "city_tier",
                    "age_band", "signup_campaign_id", "is_email_verified", "is_active_account",
                ],
                cust_rows,
            )
            _copy_rows(
                cur,
                "customer_addresses",
                [
                    "address_id", "customer_id", "city", "state", "city_tier",
                    "postal_zone", "address_type", "is_default", "delivery_sla_days",
                ],
                addr_rows,
            )
            cur.execute("SELECT setval('customer_addresses_address_id_seq', (SELECT MAX(address_id) FROM customer_addresses));")
            del cust_rows, addr_rows

            # ------------------------------------------------------------------
            # 7..17. Simulate Customer Lifecycle: Sessions, Funnel, Orders, Subs
            # ------------------------------------------------------------------
            print("[seed] Simulating sessions, funnel events, orders, subscriptions, cancellations, and refunds...")

            session_rows: list[tuple[Any, ...]] = []
            event_rows: list[tuple[Any, ...]] = []
            search_rows: list[tuple[Any, ...]] = []
            cart_rows: list[tuple[Any, ...]] = []
            order_rows: list[tuple[Any, ...]] = []
            order_item_rows: list[tuple[Any, ...]] = []
            payment_rows: list[tuple[Any, ...]] = []
            cancel_rows: list[tuple[Any, ...]] = []
            refund_rows: list[tuple[Any, ...]] = []
            sub_rows: list[tuple[Any, ...]] = []
            sub_event_rows: list[tuple[Any, ...]] = []

            session_id = 1
            order_id = 1
            payment_id = 1
            sub_id = 1

            # Archetype category affinity distributions (over 10 categories)
            arch_cat_probs = {
                0: np.array([0.38, 0.25, 0.11, 0.16, 0.02, 0.02, 0.02, 0.01, 0.02, 0.01]),  # Chronic Refiller
                1: np.array([0.05, 0.04, 0.28, 0.08, 0.08, 0.10, 0.17, 0.12, 0.04, 0.04]),  # Wellness Regular
                2: np.array([0.04, 0.04, 0.12, 0.04, 0.28, 0.20, 0.07, 0.04, 0.07, 0.10]),  # Acute / Seasonal
                3: np.array([0.05, 0.04, 0.22, 0.04, 0.21, 0.13, 0.11, 0.05, 0.07, 0.08]),  # Promo One-Timer
                4: np.array([0.08, 0.06, 0.19, 0.06, 0.16, 0.11, 0.13, 0.06, 0.09, 0.06]),  # Window Shopper
            }

            # Base device stage conversion multipliers (Mobile Web has clear cart->checkout friction!)
            device_checkout_prob = {
                "Android App": 0.77,
                "iOS App": 0.80,
                "Desktop Web": 0.72,
                "Mobile Web": 0.51,  # Intentional realistic bottleneck on Mobile Web
            }
            device_order_prob = {
                "Android App": 0.89,
                "iOS App": 0.91,
                "Desktop Web": 0.85,
                "Mobile Web": 0.76,
            }

            def flush_batches(force_flush: bool = False) -> None:
                if not force_flush and len(event_rows) < 120_000:
                    return
                _copy_rows(
                    cur,
                    "sessions",
                    [
                        "session_id", "customer_id", "session_date", "session_start", "session_end",
                        "duration_seconds", "acquisition_channel", "device_type", "city", "city_tier",
                        "is_new_customer_session", "primary_category_id", "campaign_id",
                    ],
                    session_rows,
                )
                session_rows.clear()

                _copy_rows(
                    cur,
                    "user_events",
                    [
                        "session_id", "customer_id", "event_type", "event_ts", "event_date",
                        "category_id", "product_id", "step_order",
                    ],
                    event_rows,
                )
                event_rows.clear()

                _copy_rows(
                    cur,
                    "search_events",
                    [
                        "session_id", "customer_id", "search_ts", "search_query",
                        "matched_category_id", "results_count", "clicked_product_id",
                    ],
                    search_rows,
                )
                search_rows.clear()

                _copy_rows(
                    cur,
                    "cart_events",
                    [
                        "session_id", "customer_id", "product_id", "category_id",
                        "action_type", "quantity", "unit_price", "event_ts",
                    ],
                    cart_rows,
                )
                cart_rows.clear()

                _copy_rows(
                    cur,
                    "subscriptions",
                    [
                        "subscription_id", "customer_id", "primary_category_id", "product_id",
                        "plan_cadence_days", "start_date", "next_renewal_date", "cancelled_date",
                        "status", "cancel_reason", "discount_pct", "monthly_plan_value",
                    ],
                    sub_rows,
                )
                sub_rows.clear()

                _copy_rows(
                    cur,
                    "subscription_events",
                    [
                        "subscription_id", "customer_id", "event_type", "event_date",
                        "event_ts", "cycle_number", "days_since_prev_event",
                    ],
                    sub_event_rows,
                )
                sub_event_rows.clear()

                _copy_rows(
                    cur,
                    "orders",
                    [
                        "order_id", "order_code", "customer_id", "session_id", "address_id",
                        "subscription_id", "campaign_id", "order_source", "order_date", "order_ts",
                        "delivered_ts", "order_status", "is_first_order", "is_duplicate_attempt",
                        "device_type", "acquisition_channel", "city", "city_tier",
                        "primary_category_id", "gross_amount", "discount_amount", "delivery_fee",
                        "net_amount", "promised_delivery_days", "actual_delivery_days",
                    ],
                    order_rows,
                )
                order_rows.clear()

                _copy_rows(
                    cur,
                    "order_items",
                    [
                        "order_id", "product_id", "category_id", "quantity",
                        "unit_price", "line_discount", "line_total",
                    ],
                    order_item_rows,
                )
                order_item_rows.clear()

                _copy_rows(
                    cur,
                    "payments",
                    [
                        "payment_id", "order_id", "customer_id", "payment_method",
                        "payment_status", "amount", "payment_ts", "gateway_latency_ms",
                    ],
                    payment_rows,
                )
                payment_rows.clear()

                _copy_rows(
                    cur,
                    "cancellations",
                    [
                        "order_id", "customer_id", "cancelled_date", "cancelled_ts",
                        "cancellation_stage", "cancellation_reason", "initiated_by",
                        "hours_after_order",
                    ],
                    cancel_rows,
                )
                cancel_rows.clear()

                _copy_rows(
                    cur,
                    "refunds",
                    [
                        "order_id", "payment_id", "customer_id", "refund_date", "refund_ts",
                        "refund_amount", "refund_type", "refund_reason", "refund_status",
                        "processing_hours",
                    ],
                    refund_rows,
                )
                refund_rows.clear()

            def pick_payment_method(city_tier: str, device: str, is_sub_refill: bool) -> str:
                if is_sub_refill:
                    return str(rng.choice(["UPI", "Credit Card", "Debit Card", "Wallet"], p=[0.52, 0.28, 0.14, 0.06]))
                if city_tier == "Tier 3":
                    p = [0.36, 0.08, 0.11, 0.37, 0.04, 0.04]
                elif city_tier == "Tier 2":
                    p = [0.42, 0.14, 0.12, 0.23, 0.05, 0.04]
                else:
                    p = [0.48, 0.23, 0.11, 0.09, 0.05, 0.04]
                if device == "Mobile Web":
                    p[3] += 0.06
                    p[0] -= 0.03
                    p[1] -= 0.03
                p_arr = np.maximum(np.array(p), 0.01)
                p_arr /= p_arr.sum()
                return str(rng.choice(["UPI", "Credit Card", "Debit Card", "Cash on Delivery", "Net Banking", "Wallet"], p=p_arr))

            def pick_campaign_for_order(
                o_date: date, channel: str, is_first: bool, is_sub: bool, signup_camp: int | None, days_gap: int | None
            ) -> tuple[int | None, float]:
                if is_sub:
                    return (3, 12.0)  # SUBSAVE20
                if is_first and signup_camp is not None:
                    return (signup_camp, float(CAMPAIGNS[signup_camp - 1][3]))
                if days_gap is not None and days_gap >= 90 and o_date >= date(2026, 2, 1) and rng.random() < 0.45:
                    return (11, 15.0)  # WINBACK15
                if date(2026, 7, 1) <= o_date <= date(2026, 8, 31) and rng.random() < 0.28:
                    return (10, 12.0)  # MONSOONCARE
                if date(2025, 11, 20) <= o_date <= date(2026, 1, 31) and rng.random() < 0.25:
                    return (5, 10.0)  # WINTERSHIELD
                if date(2025, 10, 10) <= o_date <= date(2025, 11, 15) and rng.random() < 0.30:
                    return (4, 16.0)  # DIWALIHEALTH
                if not is_first and rng.random() < 0.22:
                    return (7, 10.0)  # REFILL10
                return (None, 0.0)

            def create_order_record(
                cm: dict[str, Any],
                o_date: date,
                o_ts: datetime,
                sess_id: int | None,
                cur_sub_id: int | None,
                cat_id: int,
                primary_prod: dict[str, Any],
                is_first_placed: bool,
                days_since_prev: int | None,
                device_used: str,
                is_duplicate: bool = False,
            ) -> tuple[str, int, datetime | None]:
                nonlocal order_id, payment_id
                oid = order_id
                order_id += 1

                is_sub_order = cur_sub_id is not None
                order_source = "subscription_auto_refill" if is_sub_order else "interactive_session"

                # Build 1-3 line items (chronic/wellness often basket-build with 2-3 items)
                n_items = 1 if is_sub_order else int(rng.choice([1, 2, 3], p=[0.48, 0.36, 0.16]))
                chosen_prods = [primary_prod]
                if n_items > 1:
                    # 60% same category, 40% cross-sell OTC/Vitamins/First Aid
                    for _ in range(n_items - 1):
                        if rng.random() < 0.60:
                            c_pick = cat_id
                        else:
                            c_pick = int(rng.choice([3, 5, 6, 10]))
                        p_pool = cat_products[c_pick]
                        chosen_prods.append(p_pool[int(rng.integers(0, len(p_pool)))])

                camp_id, disc_pct = pick_campaign_for_order(
                    o_date, cm["channel"], is_first_placed, is_sub_order, cm["signup_camp"], days_since_prev
                )

                gross = 0.0
                disc_total = 0.0
                temp_items = []
                needs_verif = False
                stock_prone = False
                for p in chosen_prods:
                    qty = int(rng.choice([1, 2, 3], p=[0.74, 0.20, 0.06]))
                    line_gross = round(p["unit_price"] * qty, 2)
                    line_disc = round(line_gross * (disc_pct / 100.0), 2) if disc_pct > 0 else 0.0
                    line_tot = round(line_gross - line_disc, 2)
                    gross += line_gross
                    disc_total += line_disc
                    needs_verif = needs_verif or p["needs_verif"]
                    stock_prone = stock_prone or p["stock_issue_prone"]
                    temp_items.append((oid, p["product_id"], p["category_id"], qty, p["unit_price"], line_disc, line_tot))

                gross = round(gross, 2)
                disc_total = round(disc_total, 2)
                delivery_fee = 0.0 if (is_sub_order or (gross - disc_total) >= 600.0) else (49.0 if cm["city_tier"] == "Tier 1" else 59.0)
                net_amount = round(gross - disc_total + delivery_fee, 2)

                pay_method = pick_payment_method(cm["city_tier"], device_used, is_sub_order)

                # Determine cancellation probability with realistic commercial drivers
                if is_duplicate:
                    is_cancelled = True
                else:
                    base_cancel = 0.042 if is_sub_order else 0.118
                    base_cancel *= cm["city_cancel_mult"]
                    if o_date.month in (7, 8):  # Monsoon logistics delays
                        base_cancel *= 1.24
                    if device_used == "Mobile Web":
                        base_cancel *= 1.22
                    if pay_method == "Cash on Delivery":
                        base_cancel *= 1.18
                    if stock_prone:
                        base_cancel *= 1.32
                    if needs_verif and not is_sub_order:
                        base_cancel *= 1.15
                    is_cancelled = bool(rng.random() < min(base_cancel, 0.42))

                promised_sla = cm["base_sla"]
                delivered_ts = None
                actual_days = None

                if is_cancelled:
                    status = "cancelled"
                    # Pick cancellation reason weighted by actual drivers
                    if is_duplicate:
                        r_name, r_stage, r_init = CANCELLATION_REASONS[6]
                        hrs = round(float(rng.uniform(0.05, 0.65)), 2)
                    else:
                        r_weights = np.array([
                            0.25 * cm["city_cancel_mult"] * (1.45 if o_date.month in (7, 8) else 1.0),  # Delivery Delay
                            0.18 * (1.85 if stock_prone else 0.9),                                      # Out of Stock
                            0.14 * (1.90 if needs_verif else 0.15),                                     # Verification Timeout
                            0.12 * (1.65 if device_used == "Mobile Web" and pay_method != "Cash on Delivery" else 0.8),  # Payment Failure
                            0.14,                                                                       # Changed Mind
                            0.08,                                                                       # Price Comparison
                            0.02,                                                                       # Duplicate
                            0.07 * (1.50 if pay_method == "Cash on Delivery" else 0.7),                 # Address Unavailable
                        ])
                        r_weights /= r_weights.sum()
                        r_idx = int(rng.choice(len(CANCELLATION_REASONS), p=r_weights))
                        r_name, r_stage, r_init = CANCELLATION_REASONS[r_idx]
                        if r_stage == "pre_verification":
                            hrs = round(float(rng.uniform(0.2, 6.0)), 2)
                        elif r_stage == "pre_dispatch":
                            hrs = round(float(rng.uniform(1.5, 22.0)), 2)
                        elif r_stage == "in_transit":
                            hrs = round(float(rng.uniform(28.0, 96.0)), 2)
                        else:
                            hrs = round(float(rng.uniform(36.0, 110.0)), 2)

                    c_ts = o_ts + timedelta(hours=hrs)
                    c_date = min(c_ts.date(), END_DATE)
                    if c_ts.date() > END_DATE:
                        c_ts = datetime(END_DATE.year, END_DATE.month, END_DATE.day, 23, 30, tzinfo=IST)

                    if pay_method == "Cash on Delivery":
                        pay_status = "cod_cancelled"
                    elif r_name == "Payment Failure / Timeout":
                        pay_status = "failed"
                    else:
                        pay_status = "refunded"

                    pid = payment_id
                    payment_id += 1
                    payment_rows.append(
                        (
                            pid, oid, cm["cid"], pay_method, pay_status, net_amount,
                            o_ts + timedelta(seconds=int(rng.integers(8, 95))),
                            int(rng.integers(180, 1450)) if pay_method != "Cash on Delivery" else None,
                        )
                    )
                    cancel_rows.append(
                        (oid, cm["cid"], c_date, c_ts, r_stage, r_name, r_init, hrs)
                    )
                    # Prepaid captured then cancelled -> auto full refund
                    if pay_status == "refunded":
                        ref_hrs = round(float(rng.uniform(4.0, 48.0)), 2)
                        ref_ts = c_ts + timedelta(hours=ref_hrs)
                        ref_date = min(ref_ts.date(), END_DATE)
                        ref_reason = (
                            "Delayed Delivery Refusal"
                            if r_name == "Delivery Delay / SLA Breach"
                            else "Order Cancelled Pre-Shipment"
                        )
                        refund_rows.append(
                            (
                                oid, pid, cm["cid"], ref_date, ref_ts, net_amount,
                                "full", ref_reason,
                                "processed" if ref_date < END_DATE else "pending",
                                ref_hrs,
                            )
                        )
                else:
                    # Fulfilled -> delivered (or small fraction returned post-delivery)
                    delay_extra = 0
                    if cm["city_tier"] == "Tier 3" and rng.random() < 0.28:
                        delay_extra = int(rng.integers(1, 3))
                    elif o_date.month in (7, 8) and rng.random() < 0.22:
                        delay_extra = int(rng.integers(1, 3))
                    elif rng.random() < 0.08:
                        delay_extra = 1
                    actual_days = promised_sla + delay_extra
                    del_ts = o_ts + timedelta(days=actual_days, hours=int(rng.integers(1, 8)))
                    if del_ts.date() > END_DATE:
                        del_ts = datetime(END_DATE.year, END_DATE.month, END_DATE.day, 21, 0, tzinfo=IST)
                    delivered_ts = del_ts

                    # Post-delivery returns (higher for Home Diagnostics & Devices = cat 9)
                    ret_prob = 0.058 if cat_id == 9 else (0.028 if cat_id == 7 else 0.014)
                    is_returned = bool(rng.random() < ret_prob)
                    status = "returned" if is_returned else "delivered"

                    pay_status = "refunded" if is_returned else ("cod_collected" if pay_method == "Cash on Delivery" else "captured")
                    pid = payment_id
                    payment_id += 1
                    payment_rows.append(
                        (
                            pid, oid, cm["cid"], pay_method, pay_status, net_amount,
                            o_ts + timedelta(seconds=int(rng.integers(6, 75))),
                            int(rng.integers(140, 820)) if pay_method != "Cash on Delivery" else None,
                        )
                    )

                    if is_returned:
                        ref_reason = str(
                            rng.choice(
                                [
                                    "Damaged / Packaging Issue",
                                    "Wrong Item Dispatched",
                                    "Device / Quality Defect",
                                    "Partial Stock Fulfillment",
                                ],
                                p=[0.34, 0.28, 0.26 if cat_id == 9 else 0.14, 0.12 if cat_id == 9 else 0.24],
                            )
                        )
                        is_partial = (ref_reason == "Partial Stock Fulfillment")
                        ref_amt = round(net_amount * float(rng.uniform(0.35, 0.70)), 2) if is_partial else net_amount
                        ref_hrs = round(float(rng.uniform(24.0, 96.0)), 2)
                        ref_ts = del_ts + timedelta(hours=ref_hrs)
                        ref_date = min(ref_ts.date(), END_DATE)
                        refund_rows.append(
                            (
                                oid, pid, cm["cid"], ref_date, ref_ts, ref_amt,
                                "partial" if is_partial else "full",
                                ref_reason,
                                "processed" if ref_date < END_DATE else "pending",
                                ref_hrs,
                            )
                        )

                order_rows.append(
                    (
                        oid, f"ORD-{oid:06d}", cm["cid"], sess_id, cm["primary_addr_id"],
                        cur_sub_id, camp_id, order_source, o_date, o_ts, delivered_ts,
                        status, is_first_placed, is_duplicate, device_used, cm["channel"],
                        cm["city"], cm["city_tier"], cat_id, gross, disc_total,
                        delivery_fee, net_amount, promised_sla, actual_days,
                    )
                )
                order_item_rows.extend(temp_items)
                return (status, oid, delivered_ts)

            # Simulate each of the 30,000 customers chronologically
            for cm in cust_meta:
                cid = cm["cid"]
                arch = cm["archetype"]
                s_off = cm["signup_off"]
                remaining_days = TOTAL_DAYS - 1 - s_off
                if remaining_days < 0:
                    continue

                # Determine number of interactive sessions over customer lifetime
                months_alive = max(0.35, remaining_days / 30.0)
                if arch == 0:  # Chronic Refiller
                    mean_sess = 1.6 + 0.78 * months_alive
                elif arch == 1:  # Wellness Regular
                    mean_sess = 1.5 + 0.65 * months_alive
                elif arch == 2:  # Acute / Seasonal
                    mean_sess = 1.3 + 0.42 * months_alive
                elif arch == 3:  # Promo One-Timer
                    mean_sess = 1.6 + 0.14 * months_alive
                else:  # Window Shopper
                    mean_sess = 1.4 + 0.22 * months_alive

                n_sess = int(np.clip(rng.poisson(mean_sess), 1, 24))

                # Generate ordered session offsets starting from day 0 (signup day)
                sess_offsets = [s_off]
                if n_sess > 1 and remaining_days > 0:
                    if arch in (0, 1):
                        # Cadenced repeat visits + early D1/D7 engagement
                        cur_off = s_off
                        # Early D1 or D7 return chance
                        if rng.random() < 0.34 and cur_off + 1 <= TOTAL_DAYS - 1:
                            delta_early = int(rng.choice([1, 2, 3, 5, 7], p=[0.42, 0.16, 0.14, 0.14, 0.14]))
                            sess_offsets.append(min(cur_off + delta_early, TOTAL_DAYS - 1))
                        while len(sess_offsets) < n_sess:
                            step = int(np.clip(rng.normal(28 if arch == 0 else 40, 12), 4, 95))
                            cur_off += step
                            if cur_off >= TOTAL_DAYS:
                                break
                            sess_offsets.append(cur_off)
                    elif arch == 2:
                        # Episodic + occasional reactivation after 90+ days
                        extras = sorted(rng.integers(s_off, TOTAL_DAYS, size=n_sess - 1).tolist())
                        sess_offsets.extend(extras)
                    elif arch == 3:
                        # Front-loaded near signup, mostly drops off after 1st month
                        max_span = min(remaining_days, 40 if rng.random() < 0.80 else remaining_days)
                        extras = sorted(rng.integers(s_off, s_off + max(1, max_span) + 1, size=n_sess - 1).tolist())
                        sess_offsets.extend([min(x, TOTAL_DAYS - 1) for x in extras])
                    else:
                        extras = sorted(rng.integers(s_off, TOTAL_DAYS, size=n_sess - 1).tolist())
                        sess_offsets.extend(extras)
                sess_offsets = sorted(min(int(x), TOTAL_DAYS - 1) for x in sess_offsets)

                placed_orders_count = 0
                last_order_date: date | None = None
                has_subscription = False
                cust_sub_info: dict[str, Any] | None = None

                for s_idx, off in enumerate(sess_offsets):
                    sid = session_id
                    session_id += 1
                    d = START_DATE + timedelta(days=int(off))
                    hour = int(rng.choice(range(7, 24), p=[0.02, 0.04, 0.06, 0.07, 0.07, 0.06, 0.06, 0.05, 0.05, 0.06, 0.07, 0.08, 0.09, 0.08, 0.06, 0.05, 0.03]))
                    s_start = datetime(d.year, d.month, d.day, hour, int(rng.integers(0, 60)), int(rng.integers(0, 60)), tzinfo=IST)

                    # Device occasionally switches (85% primary device)
                    device_used = cm["device"] if rng.random() < 0.85 else str(DEVICES[int(rng.choice(len(DEVICES), p=DEVICE_WEIGHTS))])

                    # Pick target category with seasonality
                    cat_w = arch_cat_probs[arch].copy()
                    for ci in range(10):
                        cat_w[ci] *= _seasonal_multiplier(d, ci)
                    cat_w /= cat_w.sum()
                    cat_id = int(rng.choice(10, p=cat_w)) + 1

                    p_pool = cat_products[cat_id]
                    chosen_prod = p_pool[int(rng.integers(0, len(p_pool)))]

                    is_new_sess = (placed_orders_count == 0)

                    # Funnel progression probabilities (strictly sequential!)
                    # Step 1: app_visit (100% of sessions)
                    arch_intent = {0: 1.24, 1: 1.12, 2: 0.96, 3: (1.28 if is_new_sess else 0.42), 4: 0.34}[arch]
                    repeat_boost = 1.0 if is_new_sess else 1.16

                    p_search = float(np.clip(0.73 * (1.05 if not is_new_sess else 0.96) * (0.85 if arch == 4 else 1.03), 0.35, 0.94))
                    p_view = float(np.clip(0.81 * (0.76 if arch == 4 else 1.03), 0.45, 0.95))
                    p_cart = float(np.clip(0.66 * arch_intent * cm["city_conv_mult"] * (0.52 if arch == 4 else 1.0), 0.14, 0.92))
                    p_checkout = float(np.clip(device_checkout_prob[device_used] * cm["city_conv_mult"] * repeat_boost * (0.45 if arch == 4 else 1.0), 0.10, 0.94))
                    p_order = float(np.clip(device_order_prob[device_used] * (0.12 if arch == 4 else 1.0) * (1.04 if not is_new_sess else 0.97), 0.04, 0.96))

                    reached_search = bool(rng.random() < p_search)
                    reached_view = reached_search and bool(rng.random() < p_view)
                    reached_cart = reached_view and bool(rng.random() < p_cart)
                    reached_checkout = reached_cart and bool(rng.random() < p_checkout)
                    reached_order = reached_checkout and bool(rng.random() < p_order)

                    # Build chronological event timestamps within session
                    t_cursor = s_start
                    event_rows.append((sid, cid, "app_visit", t_cursor, d, cat_id if reached_search else None, None, 1))

                    if reached_search:
                        t_cursor = t_cursor + timedelta(seconds=int(rng.integers(12, 55)))
                        event_rows.append((sid, cid, "product_search", t_cursor, d, cat_id, None, 2))
                        terms = CATEGORIES[cat_id - 1][9]
                        q_text = terms[int(rng.integers(0, len(terms)))]
                        search_rows.append(
                            (
                                sid, cid, t_cursor, q_text, cat_id,
                                int(rng.integers(6, 42)),
                                chosen_prod["product_id"] if reached_view else None,
                            )
                        )

                    if reached_view:
                        t_cursor = t_cursor + timedelta(seconds=int(rng.integers(18, 95)))
                        event_rows.append((sid, cid, "product_view", t_cursor, d, cat_id, chosen_prod["product_id"], 3))

                    if reached_cart:
                        t_cursor = t_cursor + timedelta(seconds=int(rng.integers(15, 70)))
                        event_rows.append((sid, cid, "add_to_cart", t_cursor, d, cat_id, chosen_prod["product_id"], 4))
                        cart_rows.append(
                            (sid, cid, chosen_prod["product_id"], cat_id, "add", 1, chosen_prod["unit_price"], t_cursor)
                        )
                        if rng.random() < 0.22:
                            cart_rows.append(
                                (
                                    sid, cid, chosen_prod["product_id"], cat_id,
                                    "quantity_update" if reached_checkout else "remove",
                                    2 if reached_checkout else 1,
                                    chosen_prod["unit_price"],
                                    t_cursor + timedelta(seconds=12),
                                )
                            )

                    if reached_checkout:
                        t_cursor = t_cursor + timedelta(seconds=int(rng.integers(25, 110)))
                        event_rows.append((sid, cid, "checkout_started", t_cursor, d, cat_id, chosen_prod["product_id"], 5))

                    if reached_order:
                        t_cursor = t_cursor + timedelta(seconds=int(rng.integers(20, 90)))
                        event_rows.append((sid, cid, "order_placed", t_cursor, d, cat_id, chosen_prod["product_id"], 6))

                        days_gap = (d - last_order_date).days if last_order_date is not None else None
                        is_first = (placed_orders_count == 0)
                        o_status, _, del_ts = create_order_record(
                            cm=cm,
                            o_date=d,
                            o_ts=t_cursor,
                            sess_id=sid,
                            cur_sub_id=None,
                            cat_id=cat_id,
                            primary_prod=chosen_prod,
                            is_first_placed=is_first,
                            days_since_prev=days_gap,
                            device_used=device_used,
                            is_duplicate=False,
                        )
                        placed_orders_count += 1
                        last_order_date = d

                        if o_status == "delivered" and del_ts is not None:
                            event_rows.append((sid, cid, "order_delivered", del_ts, del_ts.date(), cat_id, chosen_prod["product_id"], 7))

                        # ~1.1% chance of accidental customer double-submit duplicate order (cancelled immediately)
                        if rng.random() < 0.011:
                            create_order_record(
                                cm=cm,
                                o_date=d,
                                o_ts=t_cursor + timedelta(seconds=int(rng.integers(15, 120))),
                                sess_id=sid,
                                cur_sub_id=None,
                                cat_id=cat_id,
                                primary_prod=chosen_prod,
                                is_first_placed=False,
                                days_since_prev=0,
                                device_used=device_used,
                                is_duplicate=True,
                            )

                        # Subscription enrollment eligibility on delivered chronic/wellness order
                        if (
                            not has_subscription
                            and o_status == "delivered"
                            and chosen_prod["is_sub"]
                            and d <= END_DATE - timedelta(days=15)
                        ):
                            sub_prob = {0: 0.42, 1: 0.16, 2: 0.03, 3: 0.02, 4: 0.0}[arch]
                            if cm["city_tier"] == "Tier 1":
                                sub_prob *= 1.15
                            if rng.random() < sub_prob:
                                has_subscription = True
                                cur_sid = sub_id
                                sub_id += 1
                                cadence = 30 if cat_id in (1, 2) else int(rng.choice([30, 45, 60], p=[0.45, 0.35, 0.20]))
                                cust_sub_info = {
                                    "sub_id": cur_sid,
                                    "cat_id": cat_id,
                                    "prod": chosen_prod,
                                    "cadence": cadence,
                                    "start_date": d,
                                    "device": device_used,
                                }

                    s_end = t_cursor + timedelta(seconds=int(rng.integers(10, 65)))
                    dur = int((s_end - s_start).total_seconds())
                    session_rows.append(
                        (
                            sid, cid, d, s_start, s_end, dur,
                            cm["channel"], device_used, cm["city"], cm["city_tier"],
                            is_new_sess, cat_id if reached_search else None,
                            cm["signup_camp"] if s_idx == 0 else None,
                        )
                    )

                # Simulate Subscription Renewal Cycles & Auto-Refill Orders
                if cust_sub_info is not None:
                    cur_sid = cust_sub_info["sub_id"]
                    s_cat = cust_sub_info["cat_id"]
                    s_prod = cust_sub_info["prod"]
                    cadence = cust_sub_info["cadence"]
                    st_date: date = cust_sub_info["start_date"]
                    st_ts = datetime(st_date.year, st_date.month, st_date.day, 10, 0, tzinfo=IST)

                    sub_event_rows.append((cur_sid, cid, "created", st_date, st_ts, 0, None))

                    # Monthly/cycle churn probability (lower for Chronic Refillers, higher in Tier 3)
                    base_cycle_cancel = 0.085 if arch == 0 else 0.145
                    if cm["city_tier"] == "Tier 3":
                        base_cycle_cancel *= 1.25

                    cur_date = st_date
                    cycle_num = 0
                    sub_status = "active"
                    cancelled_date: date | None = None
                    cancel_reason: str | None = None
                    next_renewal: date | None = st_date + timedelta(days=cadence)

                    while True:
                        jitter = int(rng.choice([-2, -1, 0, 0, 0, 1, 2, 3, 5], p=[0.05, 0.10, 0.35, 0.15, 0.10, 0.10, 0.07, 0.05, 0.03]))
                        step_days = max(20, cadence + jitter)
                        nxt_date = cur_date + timedelta(days=step_days)
                        if nxt_date > END_DATE:
                            next_renewal = nxt_date
                            break

                        cycle_num += 1
                        nxt_ts = datetime(nxt_date.year, nxt_date.month, nxt_date.day, 8, int(rng.integers(0, 59)), 0, tzinfo=IST)

                        # Occasional pause & resume
                        if rng.random() < 0.05 and nxt_date + timedelta(days=20) <= END_DATE:
                            sub_event_rows.append((cur_sid, cid, "paused", nxt_date, nxt_ts, cycle_num, step_days))
                            pause_days = int(rng.integers(12, 26))
                            res_date = nxt_date + timedelta(days=pause_days)
                            if res_date > END_DATE:
                                sub_status = "paused"
                                next_renewal = res_date
                                break
                            sub_event_rows.append(
                                (
                                    cur_sid, cid, "resumed", res_date,
                                    datetime(res_date.year, res_date.month, res_date.day, 9, 15, tzinfo=IST),
                                    cycle_num, pause_days,
                                )
                            )
                            cur_date = res_date
                            continue

                        # Cancel check
                        if rng.random() < base_cycle_cancel:
                            sub_status = "cancelled"
                            cancelled_date = nxt_date
                            next_renewal = None
                            cancel_reason = str(
                                rng.choice(SUB_CANCEL_REASONS, p=[0.24, 0.22, 0.19, 0.15, 0.12, 0.08])
                            )
                            if cancel_reason == "Auto-Debit Payment Failure":
                                sub_event_rows.append((cur_sid, cid, "payment_retry_failed", nxt_date, nxt_ts, cycle_num, step_days))
                            sub_event_rows.append((cur_sid, cid, "cancelled", nxt_date, nxt_ts + timedelta(hours=2), cycle_num, step_days))
                            break

                        # Successful renewal -> generates subscription_auto_refill order
                        sub_event_rows.append((cur_sid, cid, "renewed", nxt_date, nxt_ts, cycle_num, step_days))
                        create_order_record(
                            cm=cm,
                            o_date=nxt_date,
                            o_ts=nxt_ts + timedelta(minutes=5),
                            sess_id=None,
                            cur_sub_id=cur_sid,
                            cat_id=s_cat,
                            primary_prod=s_prod,
                            is_first_placed=False,
                            days_since_prev=step_days,
                            device_used=cust_sub_info["device"],
                            is_duplicate=False,
                        )
                        cur_date = nxt_date
                        next_renewal = cur_date + timedelta(days=cadence)

                    monthly_val = round(float(s_prod["unit_price"] * (30.0 / cadence) * 0.88), 2)
                    sub_rows.append(
                        (
                            cur_sid, cid, s_cat, s_prod["product_id"], cadence,
                            st_date, next_renewal, cancelled_date, sub_status,
                            cancel_reason, 12.00, monthly_val,
                        )
                    )

                flush_batches(force_flush=False)

            flush_batches(force_flush=True)

            # Reset sequences for serial columns after explicit/copy inserts
            cur.execute("SELECT setval('payments_payment_id_seq', COALESCE((SELECT MAX(payment_id) FROM payments), 1));")

            # Refresh materialized views & analyze statistics
            print("[seed] Refreshing analytical materialized views & running ANALYZE...")
            cur.execute("REFRESH MATERIALIZED VIEW mv_session_funnel;")
            cur.execute("REFRESH MATERIALIZED VIEW mv_customer_lifecycle;")
            cur.execute("ANALYZE;")

            conn.commit()

            # Print exact row counts
            tables = [
                "calendar_dimension", "medicine_categories", "product_catalog", "promotional_campaigns",
                "customers", "customer_addresses", "sessions", "user_events", "search_events",
                "cart_events", "subscriptions", "subscription_events", "orders", "order_items",
                "payments", "cancellations", "refunds",
            ]
            counts: dict[str, int] = {}
            for tbl in tables:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                counts[tbl] = int(cur.fetchone()[0])

    elapsed = time.perf_counter() - t0
    print(f"[seed] Complete in {elapsed:.1f}s:")
    for k, v in counts.items():
        print(f"  - {k:24s}: {v:>9,}")
    return counts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed PharmFlow PostgreSQL database")
    parser.add_argument("--force", action="store_true", help="Truncate and re-seed all tables")
    args = parser.parse_args()
    seed_database(force=args.force)
