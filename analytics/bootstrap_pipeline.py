"""
PHARMFLOW — End-to-End Database Bootstrap & Analytics Pipeline
==============================================================
Runs deterministic database seeding, RFM + K-Means segmentation, time-aware
churn model training/scoring, data profiling EDA, statistical testing, and
full SQL vs Pandas reconciliation.
"""

from __future__ import annotations

import argparse
import os
import time

from analytics.churn_model import run_churn_model
from analytics.profiling_eda import run_profiling_eda
from analytics.reconciliation import run_reconciliation
from analytics.seed_data import seed_database
from analytics.segmentation_kmeans import run_segmentation
from analytics.statistical_tests import run_statistical_tests


def run_bootstrap(force: bool = False) -> None:
    t0 = time.perf_counter()
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://pharmflow_user:pharmflow_pass@localhost:5460/pharmflow",
    )
    print("=== PHARMFLOW BOOTSTRAP PIPELINE ===")
    seed_database(database_url=db_url, force=force)
    run_segmentation(database_url=db_url)
    run_churn_model(database_url=db_url)
    run_profiling_eda(database_url=db_url)
    run_statistical_tests(database_url=db_url)
    rec = run_reconciliation(database_url=db_url)
    if not rec["all_passed"]:
        raise RuntimeError("SQL vs Pandas reconciliation failed!")
    print(f"=== PHARMFLOW BOOTSTRAP COMPLETE in {time.perf_counter() - t0:.1f}s ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap PharmFlow DB and Analytics")
    parser.add_argument("--force", action="store_true", help="Truncate and re-seed from scratch")
    args = parser.parse_args()
    run_bootstrap(force=args.force)
