"""
PHARMFLOW — Idempotent Local-to-Remote PostgreSQL Sync Utility (Neon / Vercel)
==============================================================================
Creates an isolated PostgreSQL schema (default `pharmflow`) on the remote
database, applies `db/schema.sql`, streams all 18 core tables from the local
seeded PostgreSQL instance via COPY, applies `db/analytical_views.sql`,
refreshes materialized views, and verifies exact row-count parity.

Usage:
    REMOTE_DATABASE_URL="postgresql://..." REMOTE_DB_SCHEMA="pharmflow" \
        python -m analytics.sync_to_remote
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import psycopg

LOCAL_DATABASE_URL = os.getenv(
    "LOCAL_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql://pharmflow_user:pharmflow_pass@db:5432/pharmflow"),
)
REMOTE_DATABASE_URL = os.getenv("REMOTE_DATABASE_URL", "").strip()
REMOTE_DB_SCHEMA = os.getenv("REMOTE_DB_SCHEMA", "pharmflow").strip() or "pharmflow"

TABLES_IN_ORDER = [
    "calendar_dimension",
    "medicine_categories",
    "product_catalog",
    "promotional_campaigns",
    "customers",
    "customer_addresses",
    "sessions",
    "user_events",
    "search_events",
    "cart_events",
    "subscriptions",
    "subscription_events",
    "orders",
    "order_items",
    "payments",
    "cancellations",
    "refunds",
    "customer_segments",
]

SEQ_TABLES = [
    ("medicine_categories", "category_id"),
    ("product_catalog", "product_id"),
    ("promotional_campaigns", "campaign_id"),
    ("customer_addresses", "address_id"),
    ("user_events", "event_id"),
    ("search_events", "search_id"),
    ("cart_events", "cart_event_id"),
    ("subscription_events", "sub_event_id"),
    ("order_items", "order_item_id"),
    ("payments", "payment_id"),
    ("cancellations", "cancellation_id"),
    ("refunds", "refund_id"),
]


def _normalize_url(raw: str) -> str:
    if raw.startswith("postgres://"):
        return "postgresql://" + raw[len("postgres://") :]
    return raw


def sync_to_remote() -> None:
    if not REMOTE_DATABASE_URL:
        raise SystemExit("REMOTE_DATABASE_URL environment variable is required.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", REMOTE_DB_SCHEMA):
        raise SystemExit(f"Invalid REMOTE_DB_SCHEMA: {REMOTE_DB_SCHEMA}")

    t0 = time.perf_counter()
    root_dir = Path(__file__).resolve().parent.parent
    schema_sql = (root_dir / "db" / "schema.sql").read_text(encoding="utf-8")
    views_sql = (root_dir / "db" / "analytical_views.sql").read_text(encoding="utf-8")

    remote_url = _normalize_url(REMOTE_DATABASE_URL)

    with (
        psycopg.connect(LOCAL_DATABASE_URL) as src_conn,
        psycopg.connect(remote_url, autocommit=False) as dst_conn,
    ):
        with dst_conn.cursor() as dcur:
            dcur.execute("SELECT pg_size_pretty(pg_database_size(current_database()));")
            print(f"[sync] Remote DB size before sync: {dcur.fetchone()[0]}")

            print(f"[sync] Ensuring isolated schema `{REMOTE_DB_SCHEMA}` and applying schema.sql...")
            dcur.execute(f"CREATE SCHEMA IF NOT EXISTS {REMOTE_DB_SCHEMA};")
            dcur.execute(f"SET search_path TO {REMOTE_DB_SCHEMA}, public;")
            dcur.execute(schema_sql)
            dst_conn.commit()

            # Truncate in case of re-sync so operation is idempotent
            dcur.execute(f"SET search_path TO {REMOTE_DB_SCHEMA}, public;")
            dcur.execute(
                f"TRUNCATE TABLE {', '.join(reversed(TABLES_IN_ORDER))} RESTART IDENTITY CASCADE;"
            )
            dst_conn.commit()

        # Stream each table via COPY TO STDOUT -> COPY FROM STDIN
        for tbl in TABLES_IN_ORDER:
            t_tbl = time.perf_counter()
            with src_conn.cursor() as scur, dst_conn.cursor() as dcur:
                dcur.execute(f"SET search_path TO {REMOTE_DB_SCHEMA}, public;")
                with (
                    scur.copy(f"COPY {tbl} TO STDOUT (FORMAT BINARY)") as src_copy,
                    dcur.copy(f"COPY {tbl} FROM STDIN (FORMAT BINARY)") as dst_copy,
                ):
                    for chunk in src_copy:
                        dst_copy.write(chunk)
            dst_conn.commit()

            with src_conn.cursor() as scur, dst_conn.cursor() as dcur:
                scur.execute(f"SELECT COUNT(*) FROM {tbl};")
                src_cnt = int(scur.fetchone()[0])
                dcur.execute(f"SET search_path TO {REMOTE_DB_SCHEMA}, public;")
                dcur.execute(f"SELECT COUNT(*) FROM {tbl};")
                dst_cnt = int(dcur.fetchone()[0])
                if src_cnt != dst_cnt:
                    raise RuntimeError(f"Row mismatch on {tbl}: src={src_cnt} vs dst={dst_cnt}")
            print(f"  - {tbl:24s}: {dst_cnt:>9,} rows synced in {time.perf_counter() - t_tbl:.1f}s")

        with dst_conn.cursor() as dcur:
            dcur.execute(f"SET search_path TO {REMOTE_DB_SCHEMA}, public;")
            for tbl, col in SEQ_TABLES:
                dcur.execute(
                    f"SELECT setval(pg_get_serial_sequence('{REMOTE_DB_SCHEMA}.{tbl}', '{col}'), "
                    f"COALESCE((SELECT MAX({col}) FROM {REMOTE_DB_SCHEMA}.{tbl}), 1));"
                )
            print("[sync] Creating & refreshing analytical materialized views on remote...")
            dcur.execute(views_sql)
            dcur.execute("REFRESH MATERIALIZED VIEW mv_session_funnel;")
            dcur.execute("REFRESH MATERIALIZED VIEW mv_customer_lifecycle;")
            dcur.execute("ANALYZE;")
            dst_conn.commit()

            dcur.execute("SELECT pg_size_pretty(pg_database_size(current_database()));")
            print(f"[sync] Remote DB size after sync: {dcur.fetchone()[0]}")

    print(f"[sync] Complete! All 18 tables + 2 materialized views synced in {time.perf_counter() - t0:.1f}s.")


if __name__ == "__main__":
    sync_to_remote()
