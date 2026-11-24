import React, { useEffect, useState } from "react";
import { apiGet, buildQueryParams, fmtDec, fmtInr, fmtInt, fmtPct } from "../api/client";
import { DataTable, type ColumnDef } from "../components/DataTable";
import { MetricCard } from "../components/MetricCard";
import { CHART_COLORS, PlotlyChart } from "../components/PlotlyChart";
import { useFilters } from "../context/FilterContext";

interface RetentionData {
  kpis: {
    d1_session_retention_pct: number;
    d1_eligible_customers: number;
    d7_session_retention_pct: number;
    d7_eligible_customers: number;
    d30_session_retention_pct: number;
    d30_order_repeat_pct: number;
    d30_eligible_buyers: number;
    d60_order_repeat_pct: number;
    d90_order_repeat_pct: number;
    d90_eligible_buyers: number;
    overall_repeat_purchase_rate_pct: number;
    total_buyers: number;
    repeat_buyers: number;
    inactivity_90d_pct: number;
    inactive_90d_buyers: number;
    avg_monthly_reactivation_rate_pct: number;
    avg_orders_per_customer: number;
    avg_days_between_orders: number;
    avg_order_value: number;
    avg_customer_ltv: number;
  };
  monthly_new_returning: {
    year_month: string;
    new_customers: number;
    returning_customers: number;
    returning_share_pct: number;
    new_customer_revenue: number;
    returning_customer_revenue: number;
    reactivated_customers: number;
    eligible_inactive_pool: number;
    reactivation_rate_pct: number | null;
  }[];
  order_frequency_distribution: {
    order_bucket: string;
    customers: number;
    customer_share_pct: number;
    total_revenue: number;
    revenue_share_pct: number;
  }[];
  inter_order_gaps: {
    gap_bucket: string;
    repeat_orders: number;
    share_pct: number;
  }[];
  channel_retention: {
    acquisition_channel: string;
    buyers: number;
    repeat_buyers: number;
    repeat_rate_pct: number;
    d30_repeat_pct: number;
    avg_orders: number;
    avg_ltv: number;
    subscriber_share_pct: number;
  }[];
}

export const CustomerRetention: React.FC = () => {
  const { filters } = useFilters();
  const [data, setData] = useState<RetentionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<RetentionData>(`/api/retention${buildQueryParams(filters)}`)
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

  if (loading && !data) return <div className="loading-state">Computing retention milestones and inter-order velocity…</div>;
  if (error) return <div className="error-state">Failed to load Customer Retention: {error}</div>;
  if (!data) return null;

  const { kpis, monthly_new_returning, order_frequency_distribution, inter_order_gaps, channel_retention } = data;

  const chanCols: ColumnDef<RetentionData["channel_retention"][number]>[] = [
    { key: "acquisition_channel", header: "Acquisition Channel", render: (r) => <strong>{r.acquisition_channel}</strong> },
    { key: "buyers", header: "Delivered Buyers", align: "right", render: (r) => fmtInt(r.buyers) },
    { key: "repeat_buyers", header: "Repeat Buyers", align: "right", render: (r) => fmtInt(r.repeat_buyers) },
    { key: "repeat_rate_pct", header: "Repeat Rate", align: "right", render: (r) => <strong>{fmtPct(r.repeat_rate_pct)}</strong> },
    { key: "d30_repeat_pct", header: "D30 Repeat", align: "right", render: (r) => fmtPct(r.d30_repeat_pct) },
    { key: "avg_orders", header: "Orders / Buyer", align: "right", render: (r) => fmtDec(r.avg_orders) },
    { key: "avg_ltv", header: "Avg LTV", align: "right", render: (r) => fmtInr(r.avg_ltv) },
    { key: "subscriber_share_pct", header: "Subscriber %", align: "right", render: (r) => fmtPct(r.subscriber_share_pct) },
  ];

  const months = monthly_new_returning.map((m) => m.year_month);

  return (
    <>
      <div className="kpi-grid">
        <MetricCard
          label="D1 Session Return"
          value={fmtPct(kpis.d1_session_retention_pct)}
          subtext={`Eligible N = ${fmtInt(kpis.d1_eligible_customers)}`}
          formula="Returned for session on signup_date + 1 / Eligible signups"
        />
        <MetricCard
          label="D7 Session Return"
          value={fmtPct(kpis.d7_session_retention_pct)}
          subtext={`D30 session ${fmtPct(kpis.d30_session_retention_pct)}`}
          formula="Returned for session in days 1..7 post-signup / Eligible signups"
        />
        <MetricCard
          label="D30 First-Order Repeat"
          value={fmtPct(kpis.d30_order_repeat_pct)}
          subtext={`D60 ${fmtPct(kpis.d60_order_repeat_pct)} · D90 ${fmtPct(kpis.d90_order_repeat_pct)}`}
          formula="2nd delivered order within 30 days / Matured first-time buyers"
        />
        <MetricCard
          label="Overall Repeat Rate"
          value={fmtPct(kpis.overall_repeat_purchase_rate_pct)}
          subtext={`${fmtInt(kpis.repeat_buyers)} / ${fmtInt(kpis.total_buyers)} buyers`}
          formula="Buyers with >=2 delivered orders / All filtered buyers"
        />
        <MetricCard
          label="90-Day Inactivity Rate"
          value={fmtPct(kpis.inactivity_90d_pct)}
          subtext={`${fmtInt(kpis.inactive_90d_buyers)} lapsed buyers`}
          formula="Mature buyers with zero orders in final 90 days / Eligible mature buyers"
        />
        <MetricCard
          label="Avg Monthly Reactivation"
          value={fmtPct(kpis.avg_monthly_reactivation_rate_pct)}
          subtext="≥90d inactive returning"
          formula="Buyers ordering after >=90d gap / Prior-month inactive buyer pool"
        />
        <MetricCard
          label="Avg Inter-Order Gap"
          value={`${kpis.avg_days_between_orders.toFixed(1)}d`}
          subtext={`${fmtDec(kpis.avg_orders_per_customer)} orders/buyer`}
          formula="Mean days between consecutive delivered orders"
        />
      </div>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">New vs Returning Ordering Customers</h2>
              <p className="panel-subtitle">Monthly composition of first-time buyers versus returning repeat buyers</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={300}
              data={[
                {
                  type: "bar",
                  name: "New Buyers (1st Order)",
                  x: months,
                  y: monthly_new_returning.map((m) => m.new_customers),
                  marker: { color: CHART_COLORS.lightBlue },
                },
                {
                  type: "bar",
                  name: "Returning Buyers (2+ Orders)",
                  x: months,
                  y: monthly_new_returning.map((m) => m.returning_customers),
                  marker: { color: CHART_COLORS.navy },
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Returning Share %",
                  x: months,
                  y: monthly_new_returning.map((m) => m.returning_share_pct),
                  yaxis: "y2",
                  line: { color: CHART_COLORS.teal, width: 2.2 },
                },
              ]}
              layout={{
                barmode: "stack",
                margin: { t: 28, r: 52, b: 42, l: 54 },
                yaxis: { title: { text: "Ordering Customers", font: { size: 11 } } },
                yaxis2: { title: { text: "Returning Share (%)", font: { size: 11 } }, overlaying: "y", side: "right", ticksuffix: "%", showgrid: false },
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">90-Day Customer Reactivation &amp; Inactive Pool</h2>
              <p className="panel-subtitle">Lapsed buyers (≥90 days since prior order) reactivated each month</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={300}
              data={[
                {
                  type: "bar",
                  name: "Reactivated Buyers",
                  x: months,
                  y: monthly_new_returning.map((m) => m.reactivated_customers),
                  marker: { color: CHART_COLORS.blue },
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Reactivation Rate %",
                  x: months,
                  y: monthly_new_returning.map((m) => m.reactivation_rate_pct),
                  yaxis: "y2",
                  line: { color: CHART_COLORS.amber, width: 2.2 },
                },
              ]}
              layout={{
                margin: { t: 28, r: 52, b: 42, l: 54 },
                yaxis: { title: { text: "Reactivated Buyers", font: { size: 11 } } },
                yaxis2: { title: { text: "Reactivation Rate (%)", font: { size: 11 } }, overlaying: "y", side: "right", ticksuffix: "%", showgrid: false },
              }}
            />
          </div>
        </section>
      </div>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Repeat-Order Frequency Distribution (Customers vs Revenue Share)</h2>
              <p className="panel-subtitle">Highlights revenue concentration among multi-order repeat buyers</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={280}
              data={[
                {
                  type: "bar",
                  name: "% of Buyers",
                  x: order_frequency_distribution.map((d) => d.order_bucket),
                  y: order_frequency_distribution.map((d) => d.customer_share_pct),
                  marker: { color: CHART_COLORS.lightBlue },
                },
                {
                  type: "bar",
                  name: "% of Net Revenue",
                  x: order_frequency_distribution.map((d) => d.order_bucket),
                  y: order_frequency_distribution.map((d) => d.revenue_share_pct),
                  marker: { color: CHART_COLORS.navy },
                },
              ]}
              layout={{
                barmode: "group",
                margin: { t: 28, r: 16, b: 42, l: 48 },
                yaxis: { title: { text: "Share (%)", font: { size: 11 } }, ticksuffix: "%" },
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Inter-Order Replenishment Interval Distribution</h2>
              <p className="panel-subtitle">Days elapsed between consecutive delivered orders (peaks at 16–45d chronic refill window)</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={280}
              data={[
                {
                  type: "bar",
                  name: "Repeat Orders",
                  x: inter_order_gaps.map((g) => g.gap_bucket),
                  y: inter_order_gaps.map((g) => g.share_pct),
                  text: inter_order_gaps.map((g) => `${g.share_pct.toFixed(1)}%`),
                  textposition: "outside",
                  marker: { color: CHART_COLORS.teal },
                },
              ]}
              layout={{
                margin: { t: 20, r: 16, b: 42, l: 48 },
                yaxis: { title: { text: "Share of Repeat Orders (%)", font: { size: 11 } }, ticksuffix: "%" },
              }}
            />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Retention Quality &amp; Lifetime Value by Acquisition Channel</h2>
            <p className="panel-subtitle">Compares long-term repeat conversion and subscription attach rate across acquisition sources</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={chanCols} rows={channel_retention} defaultSortKey="repeat_rate_pct" />
        </div>
      </section>
    </>
  );
};
