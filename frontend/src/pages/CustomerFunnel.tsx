import React, { useEffect, useState } from "react";
import { apiGet, buildQueryParams, fmtInt, fmtPct } from "../api/client";
import { DataTable, type ColumnDef } from "../components/DataTable";
import { StatTestCard } from "../components/InsightCard";
import { MetricCard } from "../components/MetricCard";
import { CHART_COLORS, PlotlyChart } from "../components/PlotlyChart";
import { useFilters } from "../context/FilterContext";
import type { StatProportionTest } from "../types/analytics";

interface FunnelData {
  breakdown_by: string;
  breakdown_label: string;
  kpis: {
    total_sessions: number;
    active_customers: number;
    product_search_rate_pct: number;
    product_view_rate_pct: number;
    add_to_cart_rate_pct: number;
    checkout_initiation_rate_pct: number;
    checkout_conversion_pct: number;
    order_conversion_pct: number;
    completed_order_rate_pct: number;
    largest_dropoff_stage: string | null;
    largest_dropoff_pct: number;
  };
  stages: {
    step_order: number;
    stage_name: string;
    sessions: number;
    unique_customers: number;
    cumulative_rate_pct: number;
    step_conversion_pct: number;
    step_dropoff_pct: number;
    sessions_lost: number;
    denominator_formula: string;
  }[];
  reconciliation: {
    interactive_orders_placed: number;
    interactive_orders_delivered: number;
    subscription_auto_refill_placed: number;
    subscription_auto_refill_delivered: number;
    duplicate_attempts_excluded: number;
  };
  breakdown: {
    segment_value: string;
    sessions: number;
    active_customers: number;
    search_rate_pct: number;
    view_to_cart_pct: number;
    cart_to_checkout_pct: number;
    checkout_to_order_pct: number;
    session_to_order_pct: number;
    completed_order_rate_pct: number;
  }[];
  monthly_trend: {
    year_month: string;
    sessions: number;
    search_rate_pct: number;
    cart_rate_pct: number;
    cart_to_checkout_pct: number;
    order_conversion_pct: number;
    completed_order_rate_pct: number;
  }[];
  top_searches: {
    search_query: string;
    category_name: string;
    search_count: number;
    click_through_pct: number;
    avg_results: number;
  }[];
  statistical_tests: StatProportionTest[];
}

const BREAKDOWN_OPTIONS = [
  { key: "device_type", label: "Device Type" },
  { key: "customer_type", label: "New vs Repeat" },
  { key: "acquisition_channel", label: "Channel" },
  { key: "city_tier", label: "City Tier" },
  { key: "city", label: "City" },
  { key: "category_name", label: "Category" },
  { key: "year_month", label: "Activity Month" },
];

export const CustomerFunnel: React.FC = () => {
  const { filters } = useFilters();
  const [breakdownBy, setBreakdownBy] = useState("device_type");
  const [data, setData] = useState<FunnelData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<FunnelData>(`/api/funnel${buildQueryParams(filters, { breakdown_by: breakdownBy })}`)
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
  }, [filters, breakdownBy]);

  if (loading && !data) return <div className="loading-state">Computing 7-stage funnel populations…</div>;
  if (error) return <div className="error-state">Failed to load Customer Funnel: {error}</div>;
  if (!data) return null;

  const { kpis, stages, reconciliation, breakdown, monthly_trend, top_searches, statistical_tests } = data;

  const stageCols: ColumnDef<FunnelData["stages"][number]>[] = [
    { key: "step_order", header: "#", align: "right" },
    { key: "stage_name", header: "Funnel Stage", render: (r) => <strong>{r.stage_name}</strong> },
    { key: "sessions", header: "Sessions", align: "right", render: (r) => fmtInt(r.sessions) },
    { key: "unique_customers", header: "Unique Users", align: "right", render: (r) => fmtInt(r.unique_customers) },
    { key: "cumulative_rate_pct", header: "Cumul. Rate", align: "right", render: (r) => fmtPct(r.cumulative_rate_pct) },
    { key: "step_conversion_pct", header: "Step Conv.", align: "right", render: (r) => fmtPct(r.step_conversion_pct) },
    {
      key: "step_dropoff_pct",
      header: "Step Drop-Off",
      align: "right",
      render: (r) => (
        <span className={r.step_dropoff_pct >= 30 ? "badge badge-red" : r.step_dropoff_pct >= 20 ? "badge badge-amber" : "badge badge-gray"}>
          {fmtPct(r.step_dropoff_pct)}
        </span>
      ),
    },
    { key: "denominator_formula", header: "Documented Denominator" },
  ];

  const breakCols: ColumnDef<FunnelData["breakdown"][number]>[] = [
    { key: "segment_value", header: data.breakdown_label, render: (r) => <strong>{r.segment_value}</strong> },
    { key: "sessions", header: "Sessions", align: "right", render: (r) => fmtInt(r.sessions) },
    { key: "search_rate_pct", header: "Search %", align: "right", render: (r) => fmtPct(r.search_rate_pct) },
    { key: "view_to_cart_pct", header: "View→Cart %", align: "right", render: (r) => fmtPct(r.view_to_cart_pct) },
    { key: "cart_to_checkout_pct", header: "Cart→Checkout %", align: "right", render: (r) => fmtPct(r.cart_to_checkout_pct) },
    { key: "checkout_to_order_pct", header: "Checkout→Order %", align: "right", render: (r) => fmtPct(r.checkout_to_order_pct) },
    { key: "session_to_order_pct", header: "Order Conv %", align: "right", render: (r) => fmtPct(r.session_to_order_pct) },
    { key: "completed_order_rate_pct", header: "Completed %", align: "right", render: (r) => <strong>{fmtPct(r.completed_order_rate_pct)}</strong> },
  ];

  const searchCols: ColumnDef<FunnelData["top_searches"][number]>[] = [
    { key: "search_query", header: "Search Query", render: (r) => <span className="mono">{r.search_query}</span> },
    { key: "category_name", header: "Matched Category" },
    { key: "search_count", header: "Searches", align: "right", render: (r) => fmtInt(r.search_count) },
    { key: "click_through_pct", header: "Product Click %", align: "right", render: (r) => fmtPct(r.click_through_pct) },
    { key: "avg_results", header: "Avg Results", align: "right", render: (r) => r.avg_results.toFixed(1) },
  ];

  return (
    <>
      <div className="callout">
        <div className="callout-title">Session-to-Order Population Reconciliation</div>
        <div>
          Interactive funnel Step 6 Placed (<strong>{fmtInt(stages[5]?.sessions)}</strong>) and Step 7 Delivered (
          <strong>{fmtInt(stages[6]?.sessions)}</strong>) reconcile 1:1 with non-duplicate interactive orders (
          <strong>{fmtInt(reconciliation.interactive_orders_placed)}</strong> placed /{" "}
          <strong>{fmtInt(reconciliation.interactive_orders_delivered)}</strong> delivered). Automated subscription refills (
          <strong>{fmtInt(reconciliation.subscription_auto_refill_delivered)}</strong> delivered) bypass interactive browsing sessions and are tracked separately.{" "}
          <strong>{fmtInt(reconciliation.duplicate_attempts_excluded)}</strong> cancelled duplicate submissions are excluded from net placed counts.
        </div>
      </div>

      <div className="kpi-grid">
        <MetricCard label="Total Sessions" value={fmtInt(kpis.total_sessions)} subtext={`${fmtInt(kpis.active_customers)} active customers`} formula="All filtered rows in sessions" />
        <MetricCard label="Product Search Rate" value={fmtPct(kpis.product_search_rate_pct)} subtext="Step 1 → Step 2" formula="Product Search Sessions / Total Sessions" />
        <MetricCard label="Add-to-Cart Rate" value={fmtPct(kpis.add_to_cart_rate_pct)} subtext="Step 3 → Step 4" formula="Add-to-Cart Sessions / Product Viewed Sessions" />
        <MetricCard label="Cart → Checkout" value={fmtPct(kpis.checkout_initiation_rate_pct)} subtext="Step 4 → Step 5" formula="Checkout Initiated Sessions / Add-to-Cart Sessions" />
        <MetricCard label="Checkout Conversion" value={fmtPct(kpis.checkout_conversion_pct)} subtext="Step 5 → Step 6" formula="Order Placed Sessions / Checkout Initiated Sessions" />
        <MetricCard label="Completed Order Rate" value={fmtPct(kpis.completed_order_rate_pct)} subtext={`Order conv ${fmtPct(kpis.order_conversion_pct)}`} formula="Order Delivered Sessions / Total Sessions" />
        <MetricCard label="Largest Drop-Off" value={fmtPct(kpis.largest_dropoff_pct)} subtext={kpis.largest_dropoff_stage || "—"} formula="Maximum step-to-step relative loss across stages 2..7" />
      </div>

      <div className="grid-2-1">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">7-Stage Interactive Order Funnel</h2>
              <p className="panel-subtitle">Session volume, cumulative conversion (% of visits) and step-to-step progression</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={320}
              data={[
                {
                  type: "funnel",
                  y: stages.map((s) => s.stage_name),
                  x: stages.map((s) => s.sessions),
                  textinfo: "value+percent initial+percent previous",
                  textposition: "inside",
                  marker: {
                    color: [
                      "#0F243D",
                      "#17375E",
                      "#1E56A0",
                      "#366EB2",
                      "#4E86C2",
                      "#1D6F72",
                      "#166534",
                    ],
                  },
                  connector: { line: { color: "#CBD5E1", width: 1 } },
                } as Plotly.Data,
              ]}
              layout={{ margin: { t: 10, r: 24, b: 14, l: 135 } }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Stage-Wise Drop-Off Magnitude</h2>
              <p className="panel-subtitle">Relative % of sessions lost transitioning into each stage</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={320}
              data={[
                {
                  type: "bar",
                  orientation: "h",
                  y: stages.slice(1).map((s) => s.stage_name).reverse(),
                  x: stages.slice(1).map((s) => s.step_dropoff_pct).reverse(),
                  text: stages.slice(1).map((s) => `${s.step_dropoff_pct.toFixed(1)}%`).reverse(),
                  textposition: "outside",
                  marker: {
                    color: stages
                      .slice(1)
                      .map((s) => (s.step_dropoff_pct >= 28 ? CHART_COLORS.red : CHART_COLORS.steel))
                      .reverse(),
                  },
                },
              ]}
              layout={{
                margin: { t: 12, r: 45, b: 36, l: 130 },
                xaxis: { title: { text: "Stage Drop-Off (%)", font: { size: 11 } }, ticksuffix: "%" },
              }}
            />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Funnel Stage Audit &amp; Denominator Documentation</h2>
            <p className="panel-subtitle">Monotonic session and unique customer counts with explicit rate denominators</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={stageCols} rows={stages} />
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Funnel Segmentation Breakdown — {data.breakdown_label}</h2>
            <p className="panel-subtitle">Compare step-level conversion bottlenecks across operational and customer dimensions</p>
          </div>
          <div className="seg-control">
            {BREAKDOWN_OPTIONS.map((opt) => (
              <button
                key={opt.key}
                type="button"
                className={`seg-btn ${breakdownBy === opt.key ? "active" : ""}`}
                onClick={() => setBreakdownBy(opt.key)}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        <div className="panel-body">
          <PlotlyChart
            height={280}
            data={[
              {
                type: "bar",
                name: "Cart → Checkout %",
                x: breakdown.map((b) => b.segment_value),
                y: breakdown.map((b) => b.cart_to_checkout_pct),
                marker: { color: CHART_COLORS.blue },
              },
              {
                type: "bar",
                name: "Checkout → Order %",
                x: breakdown.map((b) => b.segment_value),
                y: breakdown.map((b) => b.checkout_to_order_pct),
                marker: { color: CHART_COLORS.teal },
              },
              {
                type: "scatter",
                mode: "lines+markers",
                name: "Completed Order Rate %",
                x: breakdown.map((b) => b.segment_value),
                y: breakdown.map((b) => b.completed_order_rate_pct),
                line: { color: CHART_COLORS.navy, width: 2 },
              },
            ]}
            layout={{
              barmode: "group",
              margin: { t: 28, r: 20, b: 64, l: 48 },
              yaxis: { title: { text: "Conversion Rate (%)", font: { size: 11 } }, ticksuffix: "%" },
            }}
          />
        </div>
        <div className="panel-body-flush">
          <DataTable columns={breakCols} rows={breakdown} defaultSortKey="sessions" />
        </div>
      </section>

      {statistical_tests.map((t) => (
        <StatTestCard key={t.test_id} test={t} />
      ))}

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Monthly Funnel Conversion Trends</h2>
              <p className="panel-subtitle">Cart-to-checkout, order conversion, and completed order rate over time</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={265}
              data={[
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Cart → Checkout %",
                  x: monthly_trend.map((m) => m.year_month),
                  y: monthly_trend.map((m) => m.cart_to_checkout_pct),
                  line: { color: CHART_COLORS.blue, width: 2 },
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Order Conversion %",
                  x: monthly_trend.map((m) => m.year_month),
                  y: monthly_trend.map((m) => m.order_conversion_pct),
                  line: { color: CHART_COLORS.teal, width: 2 },
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Completed Order %",
                  x: monthly_trend.map((m) => m.year_month),
                  y: monthly_trend.map((m) => m.completed_order_rate_pct),
                  line: { color: CHART_COLORS.navy, width: 2 },
                },
              ]}
              layout={{
                margin: { t: 28, r: 16, b: 40, l: 48 },
                yaxis: { ticksuffix: "%" },
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Top Search Queries &amp; Product Click-Through</h2>
              <p className="panel-subtitle">Derived from `search_events` across filtered browsing sessions</p>
            </div>
          </div>
          <div className="panel-body-flush">
            <DataTable columns={searchCols} rows={top_searches} defaultSortKey="search_count" maxHeight={280} />
          </div>
        </section>
      </div>
    </>
  );
};
