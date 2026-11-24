"""
PHARMFLOW — RFM Business Segmentation & K-Means Behavioral Clustering
=====================================================================
1. Computes deterministic RFM scores and mutually-exclusive business segments
   across all 30,000 customers as of 2026-10-31.
2. Runs K-Means clustering on standardized behavioral features for ordering
   customers (frequency >= 1), scanning k in [3..7] with Silhouette &
   Calinski-Harabasz scores, projecting into 2D via PCA, and deriving dynamic
   human-readable cluster characterizations.
3. Persists results to PostgreSQL `customer_segments` and saves evaluation
   metadata to `analytics_outputs/segmentation_summary.json`.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import calinski_harabasz_score, silhouette_score
from sklearn.preprocessing import StandardScaler

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pharmflow_user:pharmflow_pass@localhost:5460/pharmflow",
)
OUTPUT_DIR = Path(os.getenv("ANALYTICS_OUTPUT_DIR", "analytics_outputs"))
AS_OF_DATE = date(2026, 10, 31)
SEED = int(os.getenv("RANDOM_SEED", "42"))


def score_recency(days: float | None) -> int:
    if pd.isna(days):
        return 0
    d = int(days)
    if d <= 20:
        return 5
    if d <= 45:
        return 4
    if d <= 80:
        return 3
    if d <= 140:
        return 2
    return 1


def score_frequency(freq: int) -> int:
    if freq <= 0:
        return 0
    if freq == 1:
        return 1
    if freq == 2:
        return 2
    if freq <= 4:
        return 3
    if freq <= 7:
        return 4
    return 5


def score_monetary(val: float) -> int:
    if val <= 0:
        return 0
    if val < 800:
        return 1
    if val < 2000:
        return 2
    if val < 4500:
        return 3
    if val < 9000:
        return 4
    return 5


def assign_business_segment(recency: float | None, freq: int, monetary: float) -> str:
    """Mutually exclusive, collectively exhaustive business segments."""
    if freq == 0 or pd.isna(recency):
        return "Registered Non-Buyers"
    r = int(recency)
    if freq >= 5 and r <= 45 and monetary >= 4000:
        return "High-Value Repeat"
    if freq >= 2 and r <= 60:
        return "Regular Customers"
    if freq == 1 and r <= 45:
        return "New Customers"
    if (freq >= 2 and 61 <= r <= 120) or (freq == 1 and 46 <= r <= 90):
        return "At-Risk Customers"
    return "Inactive Customers"


def _label_clusters_from_centroids(profiles: list[dict[str, Any]]) -> dict[int, str]:
    """Deterministically assign business-meaningful names based on cluster centroids."""
    assigned: dict[int, str] = {}
    remaining = list(profiles)

    # 1. Highest subscription & frequency -> Chronic Refill Loyalists
    c_sub = max(remaining, key=lambda p: (p["subscriber_share"], p["avg_frequency"]))
    assigned[c_sub["cluster_id"]] = "Chronic Auto-Refill Loyalists"
    remaining = [p for p in remaining if p["cluster_id"] != c_sub["cluster_id"]]

    # 2. Highest monetary among remaining -> High-Spend Repeat Shoppers
    if remaining:
        c_hi = max(remaining, key=lambda p: (p["avg_monetary"], p["avg_frequency"]))
        assigned[c_hi["cluster_id"]] = "High-Spend Repeat Shoppers"
        remaining = [p for p in remaining if p["cluster_id"] != c_hi["cluster_id"]]

    # 3. Highest recency (most lapsed) -> Lapsed Occasional Buyers
    if remaining:
        c_lap = max(remaining, key=lambda p: p["avg_recency_days"])
        assigned[c_lap["cluster_id"]] = "Lapsed Occasional Buyers"
        remaining = [p for p in remaining if p["cluster_id"] != c_lap["cluster_id"]]

    # 4. Lowest frequency & recent -> Recent First-Time / Light Buyers
    if remaining:
        c_new = min(remaining, key=lambda p: (p["avg_frequency"], p["avg_recency_days"]))
        assigned[c_new["cluster_id"]] = "Recent Single-Order & Light Buyers"
        remaining = [p for p in remaining if p["cluster_id"] != c_new["cluster_id"]]

    # Any extra cluster
    for idx, p in enumerate(remaining, start=1):
        assigned[p["cluster_id"]] = f"Mid-Tier Periodic Buyers {idx}"

    return assigned


def run_segmentation(database_url: str = DATABASE_URL) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    query = """
    WITH delivered AS (
        SELECT
            o.customer_id,
            o.order_id,
            o.order_date,
            o.net_amount,
            mc.is_chronic_refill,
            LAG(o.order_date) OVER (PARTITION BY o.customer_id ORDER BY o.order_ts, o.order_id) AS prev_date
        FROM orders o
        JOIN medicine_categories mc ON mc.category_id = o.primary_category_id
        WHERE o.order_status = 'delivered'
          AND o.order_date <= %s
    ),
    cust_orders AS (
        SELECT
            customer_id,
            COUNT(*) AS frequency_orders,
            SUM(net_amount)::FLOAT AS monetary_value,
            AVG(net_amount)::FLOAT AS avg_order_value,
            (%s::DATE - MAX(order_date))::INT AS recency_days,
            AVG((order_date - prev_date)) FILTER (WHERE prev_date IS NOT NULL)::FLOAT AS avg_gap_days,
            AVG(CASE WHEN is_chronic_refill THEN 1.0 ELSE 0.0 END)::FLOAT AS chronic_share
        FROM delivered
        GROUP BY customer_id
    ),
    sub_flag AS (
        SELECT
            customer_id,
            BOOL_OR(status IN ('active', 'paused')) AS active_sub,
            COUNT(*) > 0 AS ever_sub
        FROM subscriptions
        GROUP BY customer_id
    )
    SELECT
        c.customer_id,
        c.customer_code,
        c.primary_city,
        c.city_tier,
        c.acquisition_channel,
        c.primary_device,
        co.recency_days,
        COALESCE(co.frequency_orders, 0) AS frequency_orders,
        COALESCE(co.monetary_value, 0.0) AS monetary_value,
        COALESCE(co.avg_order_value, 0.0) AS avg_order_value,
        co.avg_gap_days,
        COALESCE(co.chronic_share, 0.0) AS chronic_share,
        COALESCE(sf.ever_sub, FALSE) AS is_subscriber
    FROM customers c
    LEFT JOIN cust_orders co ON co.customer_id = c.customer_id
    LEFT JOIN sub_flag sf ON sf.customer_id = c.customer_id
    ORDER BY c.customer_id;
    """

    with psycopg.connect(database_url) as conn:
        df = pd.read_sql_query(query, conn, params=(AS_OF_DATE, AS_OF_DATE))

    # Deterministic RFM scoring & business segment assignment
    df["r_score"] = df["recency_days"].apply(score_recency)
    df["f_score"] = df["frequency_orders"].apply(score_frequency)
    df["m_score"] = df["monetary_value"].apply(score_monetary)
    df["rfm_code"] = (
        df["r_score"].astype(str) + df["f_score"].astype(str) + df["m_score"].astype(str)
    )
    df["business_segment"] = [
        assign_business_segment(r, int(f), float(m))
        for r, f, m in zip(df["recency_days"], df["frequency_orders"], df["monetary_value"])
    ]

    # K-Means behavioral clustering on ordering customers (frequency >= 1)
    buyers_mask = df["frequency_orders"] >= 1
    buyers = df.loc[buyers_mask].copy()

    # Handle missing avg_gap_days (single-order buyers have no inter-order gap)
    # Keep all buyers by imputing with median gap + explicit missingness indicator
    gap_median = float(buyers["avg_gap_days"].median())
    buyers["is_single_order"] = buyers["avg_gap_days"].isna().astype(float)
    buyers["gap_filled"] = buyers["avg_gap_days"].fillna(gap_median)

    feature_df = pd.DataFrame(
        {
            "log_recency": np.log1p(buyers["recency_days"].astype(float)),
            "log_frequency": np.log1p(buyers["frequency_orders"].astype(float)),
            "log_monetary": np.log1p(buyers["monetary_value"].astype(float)),
            "is_single_order": buyers["is_single_order"],
            "is_subscriber": buyers["is_subscriber"].astype(float),
            "chronic_share": buyers["chronic_share"].astype(float),
        },
        index=buyers.index,
    )

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(feature_df)

    # Scan k in [3, 4, 5, 6, 7] and evaluate Silhouette & Calinski-Harabasz
    # Use a deterministic 8,000-row subsample for silhouette_score speed (O(n^2))
    rng = np.random.default_rng(SEED)
    sample_idx = rng.choice(len(X_scaled), size=min(8000, len(X_scaled)), replace=False)

    k_scan = []
    models: dict[int, KMeans] = {}
    for k in range(3, 8):
        km = KMeans(n_clusters=k, n_init=15, random_state=SEED)
        labels = km.fit_predict(X_scaled)
        sil = float(silhouette_score(X_scaled[sample_idx], labels[sample_idx]))
        ch = float(calinski_harabasz_score(X_scaled, labels))
        k_scan.append(
            {
                "k": k,
                "silhouette_score": round(sil, 4),
                "calinski_harabasz": round(ch, 2),
                "inertia": round(float(km.inertia_), 2),
            }
        )
        models[k] = km

    # Select optimal k by highest silhouette score (favoring 4 or 5 if within 0.015 for actionability)
    best_entry = max(k_scan, key=lambda x: x["silhouette_score"])
    selected_k = int(best_entry["k"])
    best_model = models[selected_k]
    cluster_ids = best_model.labels_

    # 2D PCA projection for interpretable cluster scatter plot
    pca = PCA(n_components=2, random_state=SEED)
    coords = pca.fit_transform(X_scaled)
    buyers["kmeans_cluster"] = cluster_ids
    buyers["pca_x"] = np.round(coords[:, 0], 4)
    buyers["pca_y"] = np.round(coords[:, 1], 4)

    # Summarize cluster profiles
    raw_profiles = []
    for cid in range(selected_k):
        sub = buyers[buyers["kmeans_cluster"] == cid]
        raw_profiles.append(
            {
                "cluster_id": int(cid),
                "customer_count": int(len(sub)),
                "share_of_buyers_pct": round(100.0 * len(sub) / len(buyers), 2),
                "avg_recency_days": round(float(sub["recency_days"].mean()), 1),
                "avg_frequency": round(float(sub["frequency_orders"].mean()), 2),
                "avg_monetary": round(float(sub["monetary_value"].mean()), 2),
                "avg_aov": round(float(sub["avg_order_value"].mean()), 2),
                "subscriber_share": round(float(sub["is_subscriber"].mean()), 4),
                "chronic_share": round(float(sub["chronic_share"].mean()), 4),
                "centroid_pca_x": round(float(sub["pca_x"].mean()), 3),
                "centroid_pca_y": round(float(sub["pca_y"].mean()), 3),
            }
        )

    label_map = _label_clusters_from_centroids(raw_profiles)
    for p in raw_profiles:
        p["cluster_label"] = label_map[p["cluster_id"]]
        p["description"] = (
            f"Avg {p['avg_frequency']:.1f} delivered orders, "
            f"INR {p['avg_monetary']:,.0f} lifetime spend, "
            f"{p['avg_recency_days']:.0f}d recency, "
            f"{p['subscriber_share']*100:.1f}% subscription rate, "
            f"{p['chronic_share']*100:.1f}% chronic category share."
        )

    buyers["kmeans_label"] = buyers["kmeans_cluster"].map(label_map)

    # Merge cluster results back to full customer frame
    df["kmeans_cluster"] = None
    df["kmeans_label"] = None
    df["pca_x"] = None
    df["pca_y"] = None
    df.loc[buyers_mask, "kmeans_cluster"] = buyers["kmeans_cluster"].astype(int)
    df.loc[buyers_mask, "kmeans_label"] = buyers["kmeans_label"]
    df.loc[buyers_mask, "pca_x"] = buyers["pca_x"]
    df.loc[buyers_mask, "pca_y"] = buyers["pca_y"]

    # Upsert into PostgreSQL customer_segments
    with psycopg.connect(database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE customer_segments;")
            rows = []
            for row in df.itertuples(index=False):
                rows.append(
                    (
                        int(row.customer_id),
                        AS_OF_DATE,
                        None if pd.isna(row.recency_days) else int(row.recency_days),
                        int(row.frequency_orders),
                        round(float(row.monetary_value), 2),
                        int(row.r_score),
                        int(row.f_score),
                        int(row.m_score),
                        str(row.rfm_code),
                        str(row.business_segment),
                        None if pd.isna(row.kmeans_cluster) else int(row.kmeans_cluster),
                        None if pd.isna(row.kmeans_label) else str(row.kmeans_label),
                        None if pd.isna(row.pca_x) else float(row.pca_x),
                        None if pd.isna(row.pca_y) else float(row.pca_y),
                        None,
                        None,
                    )
                )
            cur.executemany(
                """
                INSERT INTO customer_segments (
                    customer_id, as_of_date, recency_days, frequency_orders, monetary_value,
                    r_score, f_score, m_score, rfm_code, business_segment,
                    kmeans_cluster, kmeans_label, pca_x, pca_y, churn_risk_score, churn_risk_band
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                );
                """,
                rows,
            )
            cur.execute("ANALYZE customer_segments;")
        conn.commit()

    # Sample 1,200 points for PCA scatter plot payload in UI
    scatter_sample = buyers.sample(n=min(1200, len(buyers)), random_state=SEED)
    scatter_points = [
        {
            "customer_code": str(r.customer_code),
            "pca_x": float(r.pca_x),
            "pca_y": float(r.pca_y),
            "kmeans_cluster": int(r.kmeans_cluster),
            "kmeans_label": str(r.kmeans_label),
            "business_segment": str(r.business_segment),
            "frequency_orders": int(r.frequency_orders),
            "monetary_value": round(float(r.monetary_value), 2),
            "recency_days": int(r.recency_days),
        }
        for r in scatter_sample.itertuples(index=False)
    ]

    summary = {
        "as_of_date": AS_OF_DATE.isoformat(),
        "total_customers": int(len(df)),
        "ordering_customers_clustered": int(len(buyers)),
        "non_buyers_excluded_from_kmeans": int((~buyers_mask).sum()),
        "features_used": list(feature_df.columns),
        "missing_value_strategy": (
            f"Single-order buyers ({int(buyers['is_single_order'].sum()):,}) lack an inter-order gap; "
            f"retained via binary indicator `is_single_order` and median imputation ({gap_median:.1f} days) "
            f"rather than dropping single-order buyers."
        ),
        "selected_k": selected_k,
        "selected_silhouette_score": best_entry["silhouette_score"],
        "pca_explained_variance_ratio": [round(float(v), 4) for v in pca.explained_variance_ratio_],
        "pca_total_explained_variance": round(float(pca.explained_variance_ratio_.sum()), 4),
        "k_scan": k_scan,
        "cluster_profiles": sorted(raw_profiles, key=lambda x: x["avg_monetary"], reverse=True),
        "pca_scatter_sample": scatter_points,
    }

    out_path = OUTPUT_DIR / "segmentation_summary.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[segmentation] Populated customer_segments ({len(df):,} rows). Optimal k={selected_k} (silhouette={best_entry['silhouette_score']:.4f}).")
    return summary


if __name__ == "__main__":
    run_segmentation()
