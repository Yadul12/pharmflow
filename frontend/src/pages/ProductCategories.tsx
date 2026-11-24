import React, { useEffect, useState } from "react";
import { apiGet, buildQueryParams, fmtInr, fmtInt, fmtPct } from "../api/client";
import { DataTable, type ColumnDef } from "../components/DataTable";
import { StatTestCard } from "../components/InsightCard";
import { CHART_COLORS, PlotlyChart } from "../components/PlotlyChart";
import { useFilters } from "../context/FilterContext";
import type { StatProportionTest } from "../types/analytics";

interface CategoryData {
  categories: {
    category_id: number;
    category_code: string;
    category_name: string;
    category_group: string;
    is_chronic_refill: boolean;
    typical_refill_days: number | null;
    avg_margin_pct: number;
    delivered_orders: number;
    net_revenue: number;
    revenue_share_pct: number;
    est_gross_margin: number;
    aov: number;
    distinct_buyers: number;
    repeat_buyers: number;
    repeat_rate_pct: number;
    avg_reorder_days: number | null;
    sub_order_share_pct: number;
    sub_attach_rate_pct: number;
    cancellation_rate_pct: number;
    return_rate_pct: number;
  }[];
  monthly_seasonality: {
    year_month: string;
    season: string;
    category_name: string;
    category_group: string;
    delivered_orders: number;
    net_revenue: number;
  }[];
  top_skus: {
    sku_code: string;
    product_name: string;
    category_name: string;
    brand_tier: string;
    unit_price: number;
    is_subscription_eligible: boolean;
    verification_required: boolean;
    units_sold: number;
    delivered_orders: number;
    net_revenue: number;
    cancellation_rate_pct: number;
  }[];
  basket_pairs: {
    category_a: string;
    category_b: string;
    co_occurrence_orders: number;
  }[];
  statistical_tests: StatProportionTest[];
}

export const ProductCategories: React.FC = () => {
  const { filters } = useFilters();
  const [data, setData] = useState<CategoryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<CategoryData>(`/api/categories${buildQueryParams(filters)}`)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filters]);

  if (loading && !data) return <div className="loading-state">Aggregating category performance, seasonality &amp; basket pairs…</div>;
  if (error) return <div className="error-state">Failed to load Product Categories: {error}</div>;
  if (!data) return null;

  const { categories, monthly_seasonality, top_skus, basket_pairs, statistical_tests } = data;

  // Build seasonality lines by category_group
  const months = Array.from(new Set(monthly_seasonality.map((m) => m.year_month))).sort();
  const groups = ["Chronic & Refill", "Wellness & Preventive", "Acute & OTC", "Devices & Diagnostics"];
  const grpColors = [CHART_COLORS.navy, CHART_COLORS.teal, CHART_COLORS.amber, CHART_COLORS.slate];
  const groupSeries = groups.map((g, idx) => ({
    type: "scatter" as const,
    mode: "lines+markers" as const,
    name: g,
    x: months,
    y: months.map((ym) =>
      monthly_seasonality
        .filter((r) => r.year_month === ym && r.category_group === g)
        .reduce((sum, r) => sum + r.net_revenue, 0)
    ),
    line: { color: grpColors[idx], width: 2.3 },
    marker: { size: 5 },
  }));

  const catCols: ColumnDef<CategoryData["categories"][number]>[] = [
    { key: "category_name", header: "Medicine Category", render: (r) => <strong>{r.category_name}</strong> },
    { key: "category_group", header: "Group", render: (r) => <span className="badge badge-gray">{r.category_group}</span> },
    { key: "delivered_orders", header: "Orders", align: "right", render: (r) => fmtInt(r.delivered_orders) },
    { key: "net_revenue", header: "Net Revenue", align: "right", render: (r) => fmtInr(r.net_revenue) },
    { key: "revenue_share_pct", header: "Rev Share", align: "right", render: (r) => fmtPct(r.revenue_share_pct) },
    { key: "aov", header: "AOV", align: "right", render: (r) => fmtInr(r.aov) },
    { key: "repeat_rate_pct", header: "Repeat Rate", align: "right", render: (r) => <strong>{fmtPct(r.repeat_rate_pct)}</strong> },
    { key: "avg_reorder_days", header: "Reorder Gap", align: "right", render: (r) => (r.avg_reorder_days ? `${r.avg_reorder_days.toFixed(0)}d` : "—") },
    { key: "sub_attach_rate_pct", header: "Sub Attach", align: "right", render: (r) => fmtPct(r.sub_attach_rate_pct) },
    { key: "cancellation_rate_pct", header: "Cancel %", align: "right", render: (r) => fmtPct(r.cancellation_rate_pct) },
    { key: "return_rate_pct", header: "Return %", align: "right", render: (r) => fmtPct(r.return_rate_pct) },
  ];

  const skuCols: ColumnDef<CategoryData["top_skus"][number]>[] = [
    { key: "sku_code", header: "SKU", render: (r) => <span className="mono">{r.sku_code}</span> },
    { key: "product_name", header: "Product" },
    { key: "category_name", header: "Category" },
    { key: "brand_tier", header: "Tier", render: (r) => <span className="badge badge-gray">{r.brand_tier}</span> },
    { key: "units_sold", header: "Units", align: "right", render: (r) => fmtInt(r.units_sold) },
    { key: "net_revenue", header: "Revenue", align: "right", render: (r) => fmtInr(r.net_revenue) },
    { key: "cancellation_rate_pct", header: "Cancel %", align: "right", render: (r) => fmtPct(r.cancellation_rate_pct) },
  ];

  const pairCols: ColumnDef<CategoryData["basket_pairs"][number]>[] = [
    { key: "category_a", header: "Primary Category", render: (r) => <strong>{r.category_a}</strong> },
    { key: "category_b", header: "Co-Purchased Category" },
    { key: "co_occurrence_orders", header: "Joint Delivered Orders", align: "right", render: (r) => fmtInt(r.co_occurrence_orders) },
  ];

  return (
    <>
      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Category Repeat Rate vs Delivered Revenue Matrix</h2>
              <p className="panel-subtitle">Bubble size represents AOV · Chronic &amp; refill categories lead repeat ordering</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={320}
              data={groups.map((grp, idx) => {
                const shortLabel: Record<string, string> = {
                  "Chronic Care Refills": "Chronic Refills",
                  "Diabetes Care Supplies": "Diabetes Care",
                  "Vitamins & Supplements": "Vitamins",
                  "Cardiac & Wellness Nutrition": "Cardiac Care",
                  "Dermatology & Skincare": "Dermatology",
                  "Home Diagnostics & Devices": "Devices",
                  "Baby & Maternal Care": "Baby & Maternal",
                  "Digestive & Gut Health": "Digestive",
                  "OTC Pain & Fever": "OTC Pain/Fever",
                  "First Aid & Personal Hygiene": "First Aid",
                };
                const posMap: Record<string, string> = {
                  "Chronic Care Refills": "middle left",
                  "Diabetes Care Supplies": "top center",
                  "Vitamins & Supplements": "bottom center",
                  "Cardiac & Wellness Nutrition": "top center",
                  "Dermatology & Skincare": "top center",
                  "Home Diagnostics & Devices": "bottom right",
                  "Baby & Maternal Care": "top right",
                  "Digestive & Gut Health": "middle right",
                  "OTC Pain & Fever": "top right",
                  "First Aid & Personal Hygiene": "bottom right",
                };
                const sub = categories.filter((c) => c.category_group === grp);
                return {
                  type: "scatter",
                  mode: "markers+text",
                  name: grp,
                  x: sub.map((c) => c.net_revenue),
                  y: sub.map((c) => c.repeat_rate_pct),
                  text: sub.map((c) => shortLabel[c.category_name] || c.category_name),
                  customdata: sub.map((c) => c.category_name),
                  textposition: sub.map((c) => posMap[c.category_name] || "top center"),
                  textfont: { size: 9.5, color: "#334155" },
                  marker: {
                    color: grpColors[idx],
                    size: sub.map((c) => Math.max(10, Math.sqrt(c.aov) * 0.58)),
                    opacity: 0.85,
                    line: { width: 1, color: "#FFFFFF" },
                  },
                  hovertemplate: "<b>%{customdata}</b><br>Revenue: ₹%{x:,.0f}<br>Repeat Rate: %{y:.1f}%<extra></extra>",
                };
              })}
              layout={{
                margin: { t: 28, r: 34, b: 44, l: 58 },
                xaxis: {
                  title: { text: "Delivered Net Revenue (INR)", font: { size: 11 } },
                  tickprefix: "₹",
                  range: [
                    Math.min(0, ...categories.map((c) => c.net_revenue)) - 1200000,
                    Math.max(1000000, ...categories.map((c) => c.net_revenue)) * 1.12,
                  ],
                },
                yaxis: {
                  title: { text: "Category Repeat Buyer Rate (%)", font: { size: 11 } },
                  ticksuffix: "%",
                  range: [
                    Math.min(0, ...categories.map((c) => c.repeat_rate_pct)) - 4,
                    Math.max(10, ...categories.map((c) => c.repeat_rate_pct)) + 6,
                  ],
                },
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Monthly Revenue Seasonality by Category Group</h2>
              <p className="panel-subtitle">Highlights Winter immunity/OTC lift (Nov–Jan) and Monsoon acute/gut surge (Jul–Aug)</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={320}
              data={groupSeries}
              layout={{
                margin: { t: 28, r: 16, b: 42, l: 60 },
                yaxis: { title: { text: "Delivered Revenue (INR)", font: { size: 11 } }, tickprefix: "₹" },
              }}
            />
          </div>
        </section>
      </div>

      {statistical_tests.map((t) => (
        <StatTestCard key={t.test_id} test={t} />
      ))}

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Complete 10-Category Commercial &amp; Operations Scorecard</h2>
            <p className="panel-subtitle">Revenue share, AOV, category repeat rate, reorder interval, subscription attach, cancellation &amp; return rates</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={catCols} rows={categories} defaultSortKey="net_revenue" />
        </div>
      </section>

      <div className="grid-2-1">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Top 25 Synthetic SKUs by Delivered Net Revenue</h2>
              <p className="panel-subtitle">SKU-level commercial volume and operational cancellation exposure</p>
            </div>
          </div>
          <div className="panel-body-flush">
            <DataTable columns={skuCols} rows={top_skus} defaultSortKey="net_revenue" maxHeight={340} />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Cross-Category Basket Co-Occurrence</h2>
              <p className="panel-subtitle">Most frequent multi-category pairings inside the same delivered order</p>
            </div>
          </div>
          <div className="panel-body-flush">
            <DataTable columns={pairCols} rows={basket_pairs} defaultSortKey="co_occurrence_orders" maxHeight={340} />
          </div>
        </section>
      </div>
    </>
  );
};
