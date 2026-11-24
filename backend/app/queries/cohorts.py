from __future__ import annotations

from typing import Any

from app.database import fetch_all
from app.queries.filters import AnalyticsFilter, build_customer_where


def get_cohort_analytics(f: AnalyticsFilter) -> dict[str, Any]:
    f = f.normalized()
    cw, cp = build_customer_where(f, alias="cl")
    end_ym = f.end_date.strftime("%Y-%m")
    start_ym = f.start_date.strftime("%Y-%m")

    # 1. Triangular Monthly Cohort Retention Matrix (only matured month offsets!)
    rows = fetch_all(
        f"""
        WITH cohort_base AS (
            SELECT
                cl.customer_id,
                cl.cohort_month,
                TO_DATE(cl.cohort_month || '-01', 'YYYY-MM-DD') AS cohort_start
            FROM mv_customer_lifecycle cl
            WHERE {cw}
              AND cl.cohort_month IS NOT NULL
              AND cl.cohort_month BETWEEN %s AND %s
        ),
        cohort_sizes AS (
            SELECT
                cohort_month,
                cohort_start,
                COUNT(*)::INT AS cohort_size
            FROM cohort_base
            GROUP BY cohort_month, cohort_start
        ),
        activity AS (
            SELECT
                cb.cohort_month,
                (
                    (EXTRACT(YEAR FROM TO_DATE(cal.year_month || '-01', 'YYYY-MM-DD')) - EXTRACT(YEAR FROM cb.cohort_start)) * 12
                    + (EXTRACT(MONTH FROM TO_DATE(cal.year_month || '-01', 'YYYY-MM-DD')) - EXTRACT(MONTH FROM cb.cohort_start))
                )::INT AS month_offset,
                COUNT(DISTINCT o.customer_id)::INT AS retained_customers,
                ROUND(SUM(o.net_amount)::NUMERIC, 2)::FLOAT AS cohort_month_revenue
            FROM cohort_base cb
            JOIN orders o
              ON o.customer_id = cb.customer_id
             AND o.order_status = 'delivered'
             AND o.order_date <= %s
            JOIN calendar_dimension cal ON cal.date_key = o.order_date
            GROUP BY 1, 2
        ),
        grid AS (
            SELECT
                cs.cohort_month,
                cs.cohort_size,
                gs.month_offset
            FROM cohort_sizes cs
            CROSS JOIN generate_series(0, 12) AS gs(month_offset)
            WHERE (cs.cohort_start + (gs.month_offset || ' months')::INTERVAL)::DATE <= TO_DATE(%s || '-01', 'YYYY-MM-DD')
        )
        SELECT
            g.cohort_month,
            g.cohort_size,
            g.month_offset,
            COALESCE(a.retained_customers, 0) AS retained_customers,
            ROUND(100.0 * COALESCE(a.retained_customers, 0) / NULLIF(g.cohort_size, 0), 2)::FLOAT AS retention_pct,
            COALESCE(a.cohort_month_revenue, 0.0)::FLOAT AS month_revenue,
            ROUND(COALESCE(a.cohort_month_revenue, 0.0)::NUMERIC / NULLIF(g.cohort_size, 0), 2)::FLOAT AS rev_per_cohort_customer
        FROM grid g
        LEFT JOIN activity a
          ON a.cohort_month = g.cohort_month
         AND a.month_offset = g.month_offset
        ORDER BY g.cohort_month, g.month_offset;
        """,
        tuple(cp + [start_ym, end_ym, f.end_date, end_ym]),
    )

    # Pivot into clean cohort matrix structure + cumulative LTV
    cohorts_map: dict[str, dict[str, Any]] = {}
    for r in rows:
        cm = r["cohort_month"]
        if cm not in cohorts_map:
            cohorts_map[cm] = {
                "cohort_month": cm,
                "cohort_size": r["cohort_size"],
                "retention": {},
                "retained_counts": {},
                "cumulative_ltv": {},
                "_running_rev_per_cust": 0.0,
            }
        m_off = int(r["month_offset"])
        cohorts_map[cm]["retention"][f"M{m_off}"] = r["retention_pct"]
        cohorts_map[cm]["retained_counts"][f"M{m_off}"] = r["retained_customers"]
        cohorts_map[cm]["_running_rev_per_cust"] = round(
            cohorts_map[cm]["_running_rev_per_cust"] + float(r["rev_per_cohort_customer"]), 2
        )
        cohorts_map[cm]["cumulative_ltv"][f"M{m_off}"] = cohorts_map[cm]["_running_rev_per_cust"]

    matrix = []
    for cm in sorted(cohorts_map.keys()):
        entry = cohorts_map[cm]
        entry.pop("_running_rev_per_cust", None)
        matrix.append(entry)

    # Weighted average retention across eligible cohorts for each M0..M12
    weighted_curve = []
    for m_off in range(0, 13):
        key = f"M{m_off}"
        elig = [c for c in matrix if key in c["retention"]]
        if not elig:
            continue
        tot_size = sum(c["cohort_size"] for c in elig)
        tot_ret = sum(c["retained_counts"][key] for c in elig)
        weighted_curve.append(
            {
                "month_offset": m_off,
                "label": key,
                "eligible_cohorts": len(elig),
                "eligible_customers": tot_size,
                "retained_customers": tot_ret,
                "weighted_retention_pct": round(100.0 * tot_ret / max(tot_size, 1), 2),
            }
        )

    # Cohort channel-mix decomposition (explains Q2 2026 retention dip)
    cohort_mix = fetch_all(
        f"""
        SELECT
            cl.cohort_month,
            COUNT(*)::INT AS cohort_size,
            ROUND(100.0 * COUNT(*) FILTER (WHERE cl.acquisition_channel IN ('Social Media', 'Affiliate')) / NULLIF(COUNT(*), 0), 2)::FLOAT AS promo_channel_share_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE cl.is_subscriber) / NULLIF(COUNT(*), 0), 2)::FLOAT AS subscriber_share_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE cl.delivered_orders >= 2) / NULLIF(COUNT(*), 0), 2)::FLOAT AS lifetime_repeat_pct,
            ROUND(AVG(cl.lifetime_net_revenue)::NUMERIC, 2)::FLOAT AS avg_ltv
        FROM mv_customer_lifecycle cl
        WHERE {cw}
          AND cl.cohort_month IS NOT NULL
          AND cl.cohort_month BETWEEN %s AND %s
        GROUP BY cl.cohort_month
        ORDER BY cl.cohort_month;
        """,
        tuple(cp + [start_ym, end_ym]),
    )

    # Merge M1/M3 retention into cohort_mix for direct correlation inspection
    ret_lookup = {c["cohort_month"]: c["retention"] for c in matrix}
    for row in cohort_mix:
        rmap = ret_lookup.get(row["cohort_month"], {})
        row["m1_retention_pct"] = rmap.get("M1")
        row["m3_retention_pct"] = rmap.get("M3")
        row["m6_retention_pct"] = rmap.get("M6")

    return {
        "filters": f.to_dict(),
        "matrix": matrix,
        "weighted_curve": weighted_curve,
        "cohort_quality_summary": cohort_mix,
    }
