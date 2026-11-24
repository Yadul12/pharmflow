from __future__ import annotations

import re
import time
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import DATABASE_URL, DB_SCHEMA, IS_VERCEL

_pool: ConnectionPool | None = None
_SAFE_SCHEMA = DB_SCHEMA if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", DB_SCHEMA) else "public"


def init_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        kwargs: dict[str, Any] = {"row_factory": dict_row}
        if IS_VERCEL:
            kwargs["prepare_threshold"] = None
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=0 if IS_VERCEL else 2,
            max_size=6 if IS_VERCEL else 12,
            open=True,
            check=ConnectionPool.check_connection,
            kwargs=kwargs,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Generator[psycopg.Connection, None, None]:
    pool = init_pool()
    with pool.connection() as conn:
        yield conn


def _apply_schema(cur: psycopg.Cursor) -> None:
    if _SAFE_SCHEMA != "public":
        cur.execute(f"SET LOCAL search_path TO {_SAFE_SCHEMA}, public;")


def _serialize_val(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def fetch_all(sql: str, params: tuple[Any, ...] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _apply_schema(cur)
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [{k: _serialize_val(v) for k, v in r.items()} for r in rows]


def fetch_one(sql: str, params: tuple[Any, ...] | dict[str, Any] | None = None) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _apply_schema(cur)
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
                _apply_schema(cur)

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
                    truncated = False
                else:
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
        "truncated": bool(truncated),
        "execution_ms": elapsed_ms,
        "explain_plan": explain_lines,
    }
