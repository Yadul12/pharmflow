from __future__ import annotations

import json
from typing import Any

from app.config import ANALYTICS_OUTPUT_DIR
from app.database import fetch_all
from app.queries.filters import AnalyticsFilter, build_customer_where


def _load_json(filename: str) -> dict[str, Any] | None:
    p = ANALYTICS_OUTPUT_DIR / filename
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_segmentation_analytics(
    f: AnalyticsFilter,
    selected_segment: str | None = None,
    churn_band: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    f = f.normalized()
    cw, cp = build_customer_where(f, alias="cl")

    # 1. RFM Business Segment Performance Summary
    segments = fetch_all(
        f"""
        WITH base AS (
            SELECT
                cs.customer_id,
                cs.business_segment,
                cs.recency_days,
                cs.frequency_orders,
                cs.monetary_value,
                cs.churn_risk_score,
                cs.churn_risk_band,
                cl.avg_order_value,
                cl.is_subscriber,
                cl.has_active_subscription
            FROM customer_segments cs
            JOIN mv_customer_lifecycle cl ON cl.customer_id = cs.customer_id
            WHERE {cw}
        )
        SELECT
            business_segment,
            COUNT(*)::INT AS customer_count,
            ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2)::FLOAT AS customer_share_pct,
            ROUND(COALESCE(SUM(monetary_value), 0)::NUMERIC, 2)::FLOAT AS total_revenue,
            ROUND(100.0 * COALESCE(SUM(monetary_value), 0) / NULLIF(SUM(SUM(monetary_value)) OVER (), 0), 2)::FLOAT AS revenue_share_pct,
            ROUND(COALESCE(AVG(monetary_value), 0)::NUMERIC, 2)::FLOAT AS avg_ltv,
            ROUND(COALESCE(AVG(avg_order_value) FILTER (WHERE frequency_orders > 0), 0)::NUMERIC, 2)::FLOAT AS avg_aov,
            ROUND(COALESCE(AVG(frequency_orders), 0)::NUMERIC, 2)::FLOAT AS avg_frequency,
            ROUND(COALESCE(AVG(recency_days) FILTER (WHERE recency_days IS NOT NULL), 0)::NUMERIC, 1)::FLOAT AS avg_recency_days,
            ROUND(100.0 * COUNT(*) FILTER (WHERE is_subscriber) / NULLIF(COUNT(*), 0), 2)::FLOAT AS subscriber_share_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE churn_risk_band = 'High') / NULLIF(COUNT(*) FILTER (WHERE frequency_orders > 0), 0), 2)::FLOAT AS high_churn_risk_pct
        FROM base
        GROUP BY business_segment
        ORDER BY total_revenue DESC;
        """,
        tuple(cp),
    )

    # 2. RFM Score Matrix (R score 1..5 x F score 1..5 for ordering buyers)
    rfm_matrix = fetch_all(
        f"""
        SELECT
            cs.r_score,
            cs.f_score,
            COUNT(*)::INT AS customers,
            ROUND(AVG(cs.monetary_value)::NUMERIC, 2)::FLOAT AS avg_monetary,
            ROUND(SUM(cs.monetary_value)::NUMERIC, 2)::FLOAT AS total_revenue
        FROM customer_segments cs
        JOIN mv_customer_lifecycle cl ON cl.customer_id = cs.customer_id
        WHERE {cw}
          AND cs.frequency_orders >= 1
        GROUP BY cs.r_score, cs.f_score
        ORDER BY cs.r_score, cs.f_score;
        """,
        tuple(cp),
    )

    # 3. Live K-Means Cluster Rollup (filtered dynamically by city/channel/device!)
    kmeans_live = fetch_all(
        f"""
        SELECT
            cs.kmeans_cluster AS cluster_id,
            cs.kmeans_label AS cluster_label,
            COUNT(*)::INT AS customer_count,
            ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2)::FLOAT AS share_of_buyers_pct,
            ROUND(AVG(cs.recency_days)::NUMERIC, 1)::FLOAT AS avg_recency_days,
            ROUND(AVG(cs.frequency_orders)::NUMERIC, 2)::FLOAT AS avg_frequency,
            ROUND(AVG(cs.monetary_value)::NUMERIC, 2)::FLOAT AS avg_monetary,
            ROUND(AVG(cl.avg_order_value)::NUMERIC, 2)::FLOAT AS avg_aov,
            ROUND(100.0 * COUNT(*) FILTER (WHERE cl.is_subscriber) / NULLIF(COUNT(*), 0), 2)::FLOAT AS subscriber_share_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE cs.churn_risk_band = 'High') / NULLIF(COUNT(*), 0), 2)::FLOAT AS high_churn_risk_pct
        FROM customer_segments cs
        JOIN mv_customer_lifecycle cl ON cl.customer_id = cs.customer_id
        WHERE {cw}
          AND cs.kmeans_cluster IS NOT NULL
        GROUP BY cs.kmeans_cluster, cs.kmeans_label
        ORDER BY avg_monetary DESC;
        """,
        tuple(cp),
    )

    # 4. Customer Drill-Down Table (filterable by segment / churn band)
    drill_clauses = [cw]
    drill_params = list(cp)
    if selected_segment:
        drill_clauses.append("cs.business_segment = %s")
        drill_params.append(selected_segment)
    if churn_band in ("High", "Medium", "Low"):
        drill_clauses.append("cs.churn_risk_band = %s")
        drill_params.append(churn_band)

    drill_limit = max(10, min(limit, 200))
    customer_sample = fetch_all(
        f"""
        SELECT
            cl.customer_code,
            cl.primary_city,
            cl.city_tier,
            cl.acquisition_channel,
            cl.primary_device,
            cs.business_segment,
            cs.rfm_code,
            cs.recency_days,
            cs.frequency_orders,
            cs.monetary_value,
            cl.avg_order_value,
            cl.is_subscriber,
            cs.kmeans_label,
            cs.churn_risk_score,
            cs.churn_risk_band
        FROM customer_segments cs
        JOIN mv_customer_lifecycle cl ON cl.customer_id = cs.customer_id
        WHERE {' AND '.join(drill_clauses)}
        ORDER BY cs.monetary_value DESC, cs.frequency_orders DESC
        LIMIT %s;
        """,
        tuple(drill_params + [drill_limit]),
    )

    kmeans_meta = _load_json("segmentation_summary.json") or {}
    churn_meta = _load_json("churn_model_report.json") or {}

    return {
        "filters": f.to_dict(),
        "business_segments": segments,
        "rfm_matrix": rfm_matrix,
        "kmeans_live_profiles": kmeans_live,
        "kmeans_evaluation": {
            "selected_k": kmeans_meta.get("selected_k"),
            "selected_silhouette_score": kmeans_meta.get("selected_silhouette_score"),
            "pca_explained_variance_ratio": kmeans_meta.get("pca_explained_variance_ratio", []),
            "pca_total_explained_variance": kmeans_meta.get("pca_total_explained_variance"),
            "missing_value_strategy": kmeans_meta.get("missing_value_strategy"),
            "k_scan": kmeans_meta.get("k_scan", []),
            "cluster_descriptions": {
                p["cluster_label"]: p["description"]
                for p in kmeans_meta.get("cluster_profiles", [])
            },
            "pca_scatter_sample": kmeans_meta.get("pca_scatter_sample", []),
        },
        "churn_model": churn_meta,
        "customer_drilldown": customer_sample,
    }
