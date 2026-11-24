from __future__ import annotations

import os
from datetime import date
from pathlib import Path


def _normalize_pg_url(raw: str) -> str:
    url = raw.strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


_RAW_DB_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or "postgresql://pharmflow_user:pharmflow_pass@localhost:5460/pharmflow"
)
DATABASE_URL = _normalize_pg_url(_RAW_DB_URL)
DB_SCHEMA = os.getenv("DB_SCHEMA", "public").strip() or "public"
IS_VERCEL = bool(os.getenv("VERCEL"))

if IS_VERCEL:
    REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "/tmp/pharmflow_reports"))
else:
    REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "generated_reports"))

_BUNDLED_ANALYTICS_DIR = Path(__file__).resolve().parent.parent / "analytics_outputs"
if os.getenv("ANALYTICS_OUTPUT_DIR"):
    ANALYTICS_OUTPUT_DIR = Path(os.environ["ANALYTICS_OUTPUT_DIR"])
elif _BUNDLED_ANALYTICS_DIR.exists():
    ANALYTICS_OUTPUT_DIR = _BUNDLED_ANALYTICS_DIR
else:
    ANALYTICS_OUTPUT_DIR = Path("analytics_outputs")

DATASET_START = date(2025, 9, 1)
DATASET_END = date(2026, 10, 31)

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
if not IS_VERCEL:
    ANALYTICS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
