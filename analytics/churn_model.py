"""
PHARMFLOW — Time-Aware Churn Risk Model (Zero Target Leakage)
=============================================================
Optional predictive extension built strictly after core analytics:
- Uses two disjoint chronological feature/outcome snapshots:
    * Train cutoff: 2026-04-30 -> Target: zero delivered orders in 2026-05-01..2026-07-31 (92d)
    * Test cutoff : 2026-07-31 -> Target: zero delivered orders in 2026-08-01..2026-10-31 (92d)
- Strict featurization ordering: preprocessing pipelines are fit ONLY on training split.
- Compares Naive Baseline, Logistic Regression (L2), and HistGradientBoostingClassifier.
- Reports Precision, Recall, F1, ROC-AUC (with 95% bootstrap CI), PR-AUC, Brier score,
  confusion matrix, slice-based error analysis, feature drivers, and model limitations.
- Scores active buyers as of 2026-10-31 and updates `customer_segments.churn_risk_score`.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pharmflow_user:pharmflow_pass@localhost:5460/pharmflow",
)
OUTPUT_DIR = Path(os.getenv("ANALYTICS_OUTPUT_DIR", "analytics_outputs"))
SEED = int(os.getenv("RANDOM_SEED", "42"))

TRAIN_CUTOFF = date(2026, 4, 30)
TEST_CUTOFF = date(2026, 7, 31)
SCORE_CUTOFF = date(2026, 10, 31)
OUTCOME_DAYS = 92

NUMERIC_FEATURES = [
    "recency_days",
    "order_count",
    "lifetime_spend",
    "avg_order_value",
    "tenure_days",
    "sessions_90d",
    "cancel_rate",
    "chronic_share",
    "has_active_sub",
    "orders_last_90d",
]
CATEGORICAL_FEATURES = ["city_tier", "acquisition_channel", "primary_device", "age_band"]


def _extract_snapshot(conn: psycopg.Connection, cutoff: date, with_target: bool) -> pd.DataFrame:
    outcome_start = cutoff + timedelta(days=1)
    outcome_end = cutoff + timedelta(days=OUTCOME_DAYS)
    sess_window_start = cutoff - timedelta(days=90)

    sql = """
    WITH hist_orders AS (
        SELECT
            o.customer_id,
            COUNT(*) FILTER (WHERE o.order_status = 'delivered') AS order_count,
            COUNT(*) FILTER (WHERE o.order_status = 'delivered' AND o.order_date > %s) AS orders_last_90d,
            COUNT(*) FILTER (WHERE o.order_status = 'cancelled') AS cancelled_count,
            COUNT(*) AS total_placed,
            COALESCE(SUM(o.net_amount) FILTER (WHERE o.order_status = 'delivered'), 0)::FLOAT AS lifetime_spend,
            COALESCE(AVG(o.net_amount) FILTER (WHERE o.order_status = 'delivered'), 0)::FLOAT AS avg_order_value,
            MAX(o.order_date) FILTER (WHERE o.order_status = 'delivered') AS last_order_date,
            COALESCE(AVG(CASE WHEN mc.is_chronic_refill THEN 1.0 ELSE 0.0 END) FILTER (WHERE o.order_status = 'delivered'), 0)::FLOAT AS chronic_share
        FROM orders o
        JOIN medicine_categories mc ON mc.category_id = o.primary_category_id
        WHERE o.order_date <= %s
        GROUP BY o.customer_id
        HAVING COUNT(*) FILTER (WHERE o.order_status = 'delivered') >= 1
    ),
    hist_sessions AS (
        SELECT
            customer_id,
            COUNT(*) AS sessions_90d
        FROM sessions
        WHERE session_date > %s AND session_date <= %s
        GROUP BY customer_id
    ),
    hist_subs AS (
        SELECT
            customer_id,
            BOOL_OR(start_date <= %s AND (cancelled_date IS NULL OR cancelled_date > %s)) AS has_active_sub
        FROM subscriptions
        WHERE start_date <= %s
        GROUP BY customer_id
    ),
    future_orders AS (
        SELECT
            customer_id,
            COUNT(*) AS future_delivered
        FROM orders
        WHERE order_status = 'delivered'
          AND order_date BETWEEN %s AND %s
        GROUP BY customer_id
    )
    SELECT
        c.customer_id,
        (%s::DATE - ho.last_order_date)::INT AS recency_days,
        ho.order_count,
        ho.orders_last_90d,
        ho.lifetime_spend,
        ho.avg_order_value,
        (%s::DATE - c.signup_date)::INT AS tenure_days,
        COALESCE(hs.sessions_90d, 0) AS sessions_90d,
        CASE WHEN ho.total_placed > 0 THEN ho.cancelled_count::FLOAT / ho.total_placed ELSE 0.0 END AS cancel_rate,
        ho.chronic_share,
        CASE WHEN COALESCE(hsub.has_active_sub, FALSE) THEN 1.0 ELSE 0.0 END AS has_active_sub,
        c.city_tier,
        c.acquisition_channel,
        c.primary_device,
        c.age_band,
        CASE WHEN COALESCE(fo.future_delivered, 0) = 0 THEN 1 ELSE 0 END AS churned_90d
    FROM hist_orders ho
    JOIN customers c ON c.customer_id = ho.customer_id
    LEFT JOIN hist_sessions hs ON hs.customer_id = ho.customer_id
    LEFT JOIN hist_subs hsub ON hsub.customer_id = ho.customer_id
    LEFT JOIN future_orders fo ON fo.customer_id = ho.customer_id
    ORDER BY c.customer_id;
    """
    params = (
        sess_window_start,
        cutoff,
        sess_window_start,
        cutoff,
        cutoff,
        cutoff,
        cutoff,
        outcome_start,
        outcome_end,
        cutoff,
        cutoff,
    )
    df = pd.read_sql_query(sql, conn, params=params)
    if not with_target:
        df = df.drop(columns=["churned_90d"])
    return df


def _bootstrap_auc_ci(y_true: np.ndarray, y_prob: np.ndarray, n_boot: int = 300) -> list[float]:
    rng = np.random.default_rng(SEED)
    aucs = []
    n = len(y_true)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        yt = y_true[idx]
        if len(np.unique(yt)) < 2:
            continue
        aucs.append(roc_auc_score(yt, y_prob[idx]))
    lo, hi = np.percentile(aucs, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


def _evaluate_predictions(name: str, y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5) -> dict[str, Any]:
    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    return {
        "model_name": name,
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4),
        "roc_auc_ci_95": _bootstrap_auc_ci(y_true, y_prob),
        "pr_auc": round(float(average_precision_score(y_true, y_prob)), 4),
        "brier_score": round(float(brier_score_loss(y_true, y_prob)), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def run_churn_model(database_url: str = DATABASE_URL) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(database_url) as conn:
        train_df = _extract_snapshot(conn, TRAIN_CUTOFF, with_target=True)
        test_df = _extract_snapshot(conn, TEST_CUTOFF, with_target=True)
        score_df = _extract_snapshot(conn, SCORE_CUTOFF, with_target=False)

    X_train = train_df[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    y_train = train_df["churned_90d"].to_numpy()
    X_test = test_df[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    y_test = test_df["churned_90d"].to_numpy()

    # Check missing values explicitly
    null_counts = {col: int(X_train[col].isna().sum()) for col in X_train.columns}

    # Strict featurization ordering: pipeline fit ONLY on X_train
    pre_linear = ColumnTransformer(
        transformers=[
            ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
        ]
    )

    pre_tree = ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="median"), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
        ]
    )

    # 1. Naive majority baseline
    base_rate = float(y_train.mean())
    naive_prob = np.full(len(y_test), base_rate)
    naive_metrics = _evaluate_predictions("Naive Majority Baseline", y_test, naive_prob)

    # 2. Regularized Logistic Regression
    lr_pipe = Pipeline(
        [
            ("prep", pre_linear),
            ("clf", LogisticRegression(C=0.5, max_iter=500, random_state=SEED)),
        ]
    )
    lr_pipe.fit(X_train, y_train)
    lr_prob = lr_pipe.predict_proba(X_test)[:, 1]
    lr_metrics = _evaluate_predictions("Logistic Regression (L2)", y_test, lr_prob)

    # 3. Regularized HistGradientBoostingClassifier
    hgb_pipe = Pipeline(
        [
            ("prep", pre_tree),
            (
                "clf",
                HistGradientBoostingClassifier(
                    max_depth=4,
                    learning_rate=0.06,
                    max_iter=180,
                    l2_regularization=2.0,
                    min_samples_leaf=40,
                    random_state=SEED,
                ),
            ),
        ]
    )
    hgb_pipe.fit(X_train, y_train)
    hgb_prob = hgb_pipe.predict_proba(X_test)[:, 1]
    hgb_metrics = _evaluate_predictions("HistGradientBoosting (Regularized)", y_test, hgb_prob)

    # Pick winning model by out-of-time ROC-AUC
    best_pipe = hgb_pipe if hgb_metrics["roc_auc"] >= lr_metrics["roc_auc"] else lr_pipe
    best_name = hgb_metrics["model_name"] if best_pipe is hgb_pipe else lr_metrics["model_name"]
    best_prob = hgb_prob if best_pipe is hgb_pipe else lr_prob

    # Interpretable standardized coefficients from Logistic Regression
    lr_feature_names = list(lr_pipe.named_steps["prep"].get_feature_names_out())
    lr_coefs = lr_pipe.named_steps["clf"].coef_[0]
    top_drivers = sorted(
        [
            {
                "feature": fn.replace("num__", "").replace("cat__", ""),
                "log_odds_coef": round(float(c), 4),
                "direction": "Increases Churn Risk" if c > 0 else "Reduces Churn Risk",
            }
            for fn, c in zip(lr_feature_names, lr_coefs)
        ],
        key=lambda x: abs(x["log_odds_coef"]),
        reverse=True,
    )[:10]

    # Slice-based error analysis on test set
    test_eval = test_df[["city_tier", "has_active_sub"]].copy()
    test_eval["y_true"] = y_test
    test_eval["y_prob"] = best_prob
    test_eval["y_pred"] = (best_prob >= 0.5).astype(int)

    slice_metrics = []
    for tier, grp in test_eval.groupby("city_tier"):
        if grp["y_true"].nunique() < 2:
            continue
        slice_metrics.append(
            {
                "slice": f"City Tier: {tier}",
                "n": int(len(grp)),
                "actual_churn_rate": round(float(grp["y_true"].mean()), 4),
                "roc_auc": round(float(roc_auc_score(grp["y_true"], grp["y_prob"])), 4),
                "precision": round(float(precision_score(grp["y_true"], grp["y_pred"], zero_division=0)), 4),
                "recall": round(float(recall_score(grp["y_true"], grp["y_pred"], zero_division=0)), 4),
            }
        )
    for sub_val, grp in test_eval.groupby("has_active_sub"):
        if grp["y_true"].nunique() < 2:
            continue
        slice_metrics.append(
            {
                "slice": "Active Subscriber" if sub_val == 1.0 else "Non-Subscriber",
                "n": int(len(grp)),
                "actual_churn_rate": round(float(grp["y_true"].mean()), 4),
                "roc_auc": round(float(roc_auc_score(grp["y_true"], grp["y_prob"])), 4),
                "precision": round(float(precision_score(grp["y_true"], grp["y_pred"], zero_division=0)), 4),
                "recall": round(float(recall_score(grp["y_true"], grp["y_pred"], zero_division=0)), 4),
            }
        )

    # Score current ordering customers as of 2026-10-31 and update customer_segments
    score_probs = best_pipe.predict_proba(score_df[NUMERIC_FEATURES + CATEGORICAL_FEATURES])[:, 1]
    score_df["churn_risk_score"] = np.round(score_probs, 4)
    score_df["churn_risk_band"] = np.where(
        score_probs >= 0.70, "High", np.where(score_probs >= 0.40, "Medium", "Low")
    )

    with psycopg.connect(database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE customer_segments
                SET churn_risk_score = %s, churn_risk_band = %s
                WHERE customer_id = %s;
                """,
                [
                    (float(r.churn_risk_score), str(r.churn_risk_band), int(r.customer_id))
                    for r in score_df.itertuples(index=False)
                ],
            )
            cur.execute("ANALYZE customer_segments;")
        conn.commit()

    risk_dist = score_df["churn_risk_band"].value_counts().to_dict()
    report = {
        "train_cutoff": TRAIN_CUTOFF.isoformat(),
        "train_outcome_window": "2026-05-01 to 2026-07-31 (92 days)",
        "test_cutoff": TEST_CUTOFF.isoformat(),
        "test_outcome_window": "2026-08-01 to 2026-10-31 (92 days)",
        "score_as_of_date": SCORE_CUTOFF.isoformat(),
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "scored_buyers": int(len(score_df)),
        "train_churn_rate": round(float(y_train.mean()), 4),
        "test_churn_rate": round(float(y_test.mean()), 4),
        "null_feature_counts_train": null_counts,
        "selected_model": best_name,
        "model_comparison": [naive_metrics, lr_metrics, hgb_metrics],
        "top_logistic_drivers": top_drivers,
        "slice_analysis": slice_metrics,
        "current_risk_distribution": {k: int(v) for k, v in risk_dist.items()},
        "limitations": [
            "Correlational risk scoring only: strong predictors (such as subscription status and chronic-category share) reflect customer self-selection and underlying refill cadence rather than a causal retention lift.",
            "Seasonal acute categories (OTC Pain & Fever, Monsoon Digestive Care) have naturally episodic >90-day purchase gaps that the 90-day churn definition flags as inactive even when customers remain loyal during next seasonal need.",
            "Trained on synthetic data with stationary macro conditions; production deployment requires monthly drift monitoring, calibration checks, and randomized uplift testing before automating discount spend.",
        ],
    }

    out_path = OUTPUT_DIR / "churn_model_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"[churn] Out-of-time evaluation complete ({best_name}): "
        f"ROC-AUC={hgb_metrics['roc_auc'] if best_pipe is hgb_pipe else lr_metrics['roc_auc']:.4f}, "
        f"PR-AUC={hgb_metrics['pr_auc'] if best_pipe is hgb_pipe else lr_metrics['pr_auc']:.4f}"
    )
    return report


if __name__ == "__main__":
    run_churn_model()
