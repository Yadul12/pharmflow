import React, { useEffect, useState } from "react";
import { apiGet, buildQueryParams, fmtInr, fmtInt, fmtPct } from "../api/client";
import { DataTable, type ColumnDef } from "../components/DataTable";
import { InsightCard } from "../components/InsightCard";
import { MetricCard } from "../components/MetricCard";
import { CHART_COLORS, PlotlyChart } from "../components/PlotlyChart";
import { useFilters } from "../context/FilterContext";
import type { BusinessInsight } from "../types/analytics";

interface ExecutiveData {
  comparison_label: string;
  kpis: {
    total_sessions: number;
    active_visitors: number;
    ordering_customers: number;
    visitor_to_customer_pct: number;
    session_completed_order_pct: number;
    total_placed_orders: number;
    delivered_orders: number;
    interactive_delivered_orders: number;
    sub_refill_delivered_orders: number;
    duplicate_attempts: number;
    net_revenue: number;
    avg_order_value: number;
    repeat_customers: number;
    repeat_purchase_rate_pct: number;
    cancelled_orders: number;
    cancellation_rate_pct: number;
    active_subscriptions: number;
    active_mrr: number;
  };
  deltas: Record<string, number | null>;
  monthly_trend: {
    year_month: string;
    sessions: number;
    delivered_orders: number;
    sub_refill_orders: number;
    net_revenue: number;
    new_buyers: number;
    returning_buyers: number;
    session_completion_pct: number;
    cancellation_rate_pct: number;
  }[];
  category_snapshot: {
    category_name: string;
    category_group: string;
    delivered_orders: number;
    net_revenue: number;
    aov: number;
    buyers: number;
    repeat_rate_pct: number;
    cancellation_rate_pct: number;
  }[];
  regional_snapshot: {
    city: string;
    city_tier: string;
    sessions: number;
    delivered_orders: number;
    net_revenue: number;
    funnel_completion_pct: number;
    cancellation_rate_pct: number;
  }[];
  insights: BusinessInsight[];
  validation_status: {
    eda?: {
      total_records_across_18_tables: number;
      integrity_checks: { all_passed: boolean; flagged_duplicate_order_attempts: number };
    };
    reconciliation?: {
      total_checks: number;
      passed_checks: number;
      all_passed: boolean;
    };
  };
}

export const ExecutiveOverview: React.FC = () => {
  const { filters } = useFilters();
  const [data, setData] = useState<ExecutiveData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<ExecutiveData>(`/api/executive${buildQueryParams(filters)}`)
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

  if (loading && !data) return <div className="loading-state">Computing executive commercial metrics from PostgreSQL…</div>;
  if (error) return <div className="error-state">Failed to load Executive Overview: {error}</div>;
  if (!data) return null;

  const { kpis, deltas, monthly_trend, category_snapshot, regional_snapshot, insights, validation_status } = data;

  const catCols: ColumnDef<ExecutiveData["category_snapshot"][number]>[] = [
    { key: "category_name", header: "Medicine Category" },
    { key: "category_group", header: "Group", render: (r) => <span className="badge badge-gray">{r.category_group}</span> },
    { key: "delivered_orders", header: "Delivered Orders", align: "right", render: (r) => fmtInt(r.delivered_orders) },
    { key: "net_revenue", header: "Net Revenue", align: "right", render: (r) => fmtInr(r.net_revenue) },
    { key: "aov", header: "AOV", align: "right", render: (r) => fmtInr(r.aov) },
    { key: "repeat_rate_pct", header: "Repeat Rate", align: "right", render: (r) => <strong>{fmtPct(r.repeat_rate_pct)}</strong> },
    { key: "cancellation_rate_pct", header: "Cancel Rate", align: "right", render: (r) => fmtPct(r.cancellation_rate_pct) },
  ];

  const months = monthly_trend.map((m) => m.year_month);

  return (
    <>
      <div className="kpi-grid">
        <MetricCard
          label="Delivered Net Revenue"
          value={fmtInr(kpis.net_revenue, true)}
          subtext={`AOV ${fmtInr(kpis.avg_order_value)}`}
          delta={deltas.net_revenue_pct}
          formula="SUM(net_amount) WHERE order_status = 'delivered'"
        />
        <MetricCard
          label="Delivered Orders"
          value={fmtInt(kpis.delivered_orders)}
          subtext={`${fmtInt(kpis.interactive_delivered_orders)} sess · ${fmtInt(kpis.sub_refill_delivered_orders)} auto-refill`}
          delta={deltas.delivered_orders_pct}
          formula="Delivered interactive session orders + subscription auto-refill orders"
        />
        <MetricCard
          label="Visitor → Customer"
          value={fmtPct(kpis.visitor_to_customer_pct)}
          subtext={`${fmtInt(kpis.ordering_customers)} / ${fmtInt(kpis.active_visitors)} visitors`}
          delta={deltas.visitor_to_customer_pp}
          deltaUnit=" pp"
          formula="Distinct Delivered Buyers / Distinct Active Session Visitors"
        />
        <MetricCard
          label="Repeat Purchase Rate"
          value={fmtPct(kpis.repeat_purchase_rate_pct)}
          subtext={`${fmtInt(kpis.repeat_customers)} repeat buyers in period`}
          delta={deltas.repeat_purchase_rate_pp}
          deltaUnit=" pp"
          formula="Buyers with >=2 Delivered Orders / Distinct Delivered Buyers in period"
        />
        <MetricCard
          label="Cancellation Rate"
          value={fmtPct(kpis.cancellation_rate_pct)}
          subtext={`${fmtInt(kpis.cancelled_orders)} excl. ${fmtInt(kpis.duplicate_attempts)} dups`}
          delta={deltas.cancellation_rate_pp}
          deltaUnit=" pp"
          invertDeltaColor
          formula="Non-Duplicate Cancelled Orders / Non-Duplicate Placed Orders"
        />
        <MetricCard
          label="Active Subscriptions"
          value={fmtInt(kpis.active_subscriptions)}
          subtext={`MRR ${fmtInr(kpis.active_mrr, true)}`}
          delta={deltas.active_subscriptions_pct}
          formula="Active subscription plans as of period end"
        />
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, fontSize: 11.5, color: "#64748B" }}>
        <span>Delta baseline: <strong>{data.comparison_label}</strong></span>
        {validation_status.reconciliation && validation_status.eda && (
          <span className="pill-muted">
            Data Audit: {fmtInt(validation_status.eda.total_records_across_18_tables)} records across 18 tables · SQL/Pandas parity{" "}
            <strong style={{ color: validation_status.reconciliation.all_passed ? "#166534" : "#B42318" }}>
              {validation_status.reconciliation.passed_checks}/{validation_status.reconciliation.total_checks} verified
            </strong>
          </span>
        )}
      </div>

      <div className="grid-2-1">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Monthly Net Revenue &amp; Delivered Order Trajectory</h2>
              <p className="panel-subtitle">Interactive vs subscription auto-refill order volume alongside delivered revenue</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={310}
              data={[
                {
                  type: "bar",
                  name: "Interactive Orders",
                  x: months,
                  y: monthly_trend.map((m) => m.delivered_orders - m.sub_refill_orders),
                  marker: { color: CHART_COLORS.steel },
                  yaxis: "y2",
                },
                {
                  type: "bar",
                  name: "Subscription Auto-Refills",
                  x: months,
                  y: monthly_trend.map((m) => m.sub_refill_orders),
                  marker: { color: CHART_COLORS.teal },
                  yaxis: "y2",
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Net Revenue (INR)",
                  x: months,
                  y: monthly_trend.map((m) => m.net_revenue),
                  line: { color: CHART_COLORS.navy, width: 2.5 },
                  marker: { size: 5, color: CHART_COLORS.navy },
                  yaxis: "y",
                },
              ]}
              layout={{
                barmode: "stack",
                margin: { t: 28, r: 58, b: 44, l: 64 },
                yaxis: { title: { text: "Net Revenue (INR)", font: { size: 11 } }, tickprefix: "₹" },
                yaxis2: {
                  title: { text: "Delivered Orders", font: { size: 11 } },
                  overlaying: "y",
                  side: "right",
                  showgrid: false,
                },
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Regional Conversion vs Cancellation Risk</h2>
              <p className="panel-subtitle">City funnel completion % vs operational cancellation % (bubble = sessions)</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={310}
              data={["Tier 1", "Tier 2", "Tier 3"].map((tier, idx) => {
                const sub = [...regional_snapshot]
                  .filter((r) => r.city_tier === tier)
                  .sort((a, b) => a.funnel_completion_pct - b.funnel_completion_pct);
                const colors = [CHART_COLORS.blue, CHART_COLORS.amber, CHART_COLORS.red];
                const cityPos: Record<string, string> = {
                  "Lucknow": "top right",
                  "Indore": "top center",
                  "Kolkata": "bottom center",
                  "Jaipur": "top center",
                  "Ahmedabad": "bottom left",
                  "Kochi": "top left",
                  "Delhi NCR": "top left",
                  "Chennai": "bottom left",
                  "Hyderabad": "top center",
                  "Mumbai": "bottom right",
                  "Pune": "middle right",
                  "Bengaluru": "top right",
                };
                return {
                  type: "scatter",
                  mode: "markers+text",
                  name: tier,
                  x: sub.map((r) => r.funnel_completion_pct),
                  y: sub.map((r) => r.cancellation_rate_pct),
                  text: sub.map((r) => r.city),
                  textposition: sub.map((r) => cityPos[r.city] || "top center"),
                  textfont: { size: 10, color: "#334155" },
                  marker: {
                    color: colors[idx],
                    size: sub.map((r) => Math.max(9, Math.sqrt(r.sessions) * 0.14)),
                    opacity: 0.85,
                    line: { width: 1, color: "#FFFFFF" },
                  },
                  hovertemplate: "<b>%{text}</b><br>Completion: %{x:.1f}%<br>Cancellation: %{y:.1f}%<extra></extra>",
                };
              })}
              layout={{
                margin: { t: 28, r: 28, b: 44, l: 54 },
                xaxis: {
                  title: { text: "Funnel Completed Order Rate (%)", font: { size: 11 } },
                  ticksuffix: "%",
                  range: [
                    Math.max(0, Math.min(...regional_snapshot.map((r) => r.funnel_completion_pct)) - 3),
                    Math.max(...regional_snapshot.map((r) => r.funnel_completion_pct)) + 3.5,
                  ],
                },
                yaxis: {
                  title: { text: "Cancellation Rate (%)", font: { size: 11 } },
                  ticksuffix: "%",
                  range: [
                    Math.max(0, Math.min(...regional_snapshot.map((r) => r.cancellation_rate_pct)) - 2),
                    Math.max(...regional_snapshot.map((r) => r.cancellation_rate_pct)) + 2.5,
                  ],
                },
              }}
            />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Category Commercial Performance Summary</h2>
            <p className="panel-subtitle">Revenue, repeat ordering, average order value and cancellation profile by product category</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={catCols} rows={category_snapshot} defaultSortKey="net_revenue" />
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Automated Business Insight Engine</h2>
            <p className="panel-subtitle">Computed dynamically from PostgreSQL metrics · Explicitly separates observational correlation from causation</p>
          </div>
          <span className="badge badge-blue">{insights.length} Live Insights</span>
        </div>
        <div className="panel-body">
          <div className="insight-grid">
            {insights.map((ins) => (
              <InsightCard key={ins.id} insight={ins} />
            ))}
          </div>
        </div>
      </section>
    </>
  );
};
