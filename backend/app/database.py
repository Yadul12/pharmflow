from __future__ import annotations

import re
import time
from contextlib import contextmanager
from decimal import Decimal
from datetime import date, datetime
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import DATABASE_URL, DB_SCHEMA, IS_VERCEL

_pool: ConnectionPool | None = None


def init_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=2,
            max_size=12,
            kwargs={"row_factory": dict_row},
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Generator[psycopg.Connection, None, None]:
    if IS_VERCEL:
        with psycopg.connect(
            DATABASE_URL,
            row_factory=dict_row,
            prepare_threshold=None,
        ) as conn:
            if DB_SCHEMA and DB_SCHEMA != "public":
                conn.execute(f"SET search_path TO {DB_SCHEMA}, public;")
                conn.commit()
            yield conn
        return
    pool = init_pool()
    with pool.connection() as conn:
        if DB_SCHEMA and DB_SCHEMA != "public":
            conn.execute(f"SET search_path TO {DB_SCHEMA}, public;")
            conn.commit()
        yield conn


def _serialize_val(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def fetch_all(sql: str, params: tuple[Any, ...] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [{k: _serialize_val(v) for k, v in r.items()} for r in rows]


def fetch_one(sql: str, params: tuple[Any, ...] | dict[str, Any] | None = None) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return {}
            return {k: _serialize_val(v) for k, v in row.items()}


_FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|VACUUM|REINDEX|CLUSTER|CALL|DO|SET\s+ROLE|EXECUTE)\b",
    re.IGNORECASE,
)


def execute_readonly_sql(
    sql: str,
    limit: int = 250,
    include_explain: bool = False,
) -> dict[str, Any]:
    """Safely execute read-only analytical SQL inside a READ ONLY PostgreSQL transaction."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("SQL query cannot be empty.")

    # Reject multi-statement batches
    # Strip string literals & comments before checking semicolons/keywords
    scrubbed = re.sub(r"'[^']*'", "''", cleaned)
    scrubbed = re.sub(r"--[^\n]*", "", scrubbed)
    scrubbed = re.sub(r"/\*.*?\*/", "", scrubbed, flags=re.DOTALL)
    if ";" in scrubbed:
        raise ValueError("Only a single SQL statement is permitted in SQL Lab.")

    first_token = scrubbed.lstrip().split(None, 1)[0].upper() if scrubbed.strip() else ""
    if first_token not in ("SELECT", "WITH", "EXPLAIN"):
        raise ValueError("SQL Lab only supports read-only SELECT, WITH (CTE), or EXPLAIN queries.")

    if _FORBIDDEN_SQL_PATTERN.search(scrubbed):
        raise ValueError("Write or DDL statements are blocked in SQL Lab read-only mode.")

    capped_limit = max(1, min(limit, 500))
    t0 = time.perf_counter()

    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN TRANSACTION READ ONLY;")
                cur.execute("SET LOCAL statement_timeout = '8000ms';")

                explain_lines: list[str] = []
                if include_explain and first_token != "EXPLAIN":
                    cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {cleaned}")
                    explain_rows = cur.fetchall()
                    explain_lines = [list(r.values())[0] for r in explain_rows]

                if first_token == "EXPLAIN":
                    cur.execute(cleaned)
                    raw_rows = cur.fetchall()
                    cols = [desc.name for desc in cur.description] if cur.description else []
                    rows = [{k: _serialize_val(v) for k, v in r.items()} for r in raw_rows[:capped_limit]]
                    total_fetched = len(raw_rows)
                else:
                    # Wrap query to cap rows without breaking LIMIT inside user SQL
                    wrapped = f"SELECT * FROM ({cleaned}) AS _sql_lab_sub LIMIT {capped_limit + 1}"
                    cur.execute(wrapped)
                    raw_rows = cur.fetchall()
                    cols = [desc.name for desc in cur.description] if cur.description else []
                    truncated = len(raw_rows) > capped_limit
                    raw_rows = raw_rows[:capped_limit]
                    rows = [{k: _serialize_val(v) for k, v in r.items()} for r in raw_rows]
                    total_fetched = len(rows)

                cur.execute("ROLLBACK;")
        except Exception:
            conn.rollback()
            raise

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {
        "columns": cols,
        "rows": rows,
        "row_count": total_fetched,
        "truncated": bool(first_token != "EXPLAIN" and truncated),
        "execution_ms": elapsed_ms,
        "explain_plan": explain_lines,
    }
