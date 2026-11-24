import React, { useEffect, useState } from "react";
import { apiGet, buildQueryParams, fmtDec, fmtInr, fmtInt, fmtPct } from "../api/client";
import { DataTable, type ColumnDef } from "../components/DataTable";
import { StatTestCard } from "../components/InsightCard";
import { MetricCard } from "../components/MetricCard";
import { CHART_COLORS, PlotlyChart } from "../components/PlotlyChart";
import { useFilters } from "../context/FilterContext";
import type { StatProportionTest } from "../types/analytics";

interface SubscriptionData {
  kpis: {
    total_subscriptions: number;
    active_subscriptions: number;
    paused_subscriptions: number;
    cancelled_subscriptions: number;
    active_mrr: number;
    avg_monthly_plan_value: number;
    renewals_in_period: number;
    cancellations_in_period: number;
    payment_failures_in_period: number;
    avg_renewal_interval_days: number;
    median_renewal_interval_days: number;
    sub_refill_orders: number;
    sub_order_share_pct: number;
    sub_refill_revenue: number;
    sub_revenue_share_pct: number;
    cycle_renewal_rate_pct: number;
    cumulative_cancellation_rate_pct: number;
  };
  monthly_lifecycle: {
    year_month: string;
    new_subscriptions: number;
    renewals: number;
    pauses: number;
    cancellations: number;
    monthly_renewal_rate_pct: number | null;
  }[];
  retention_comparison: {
    month_offset: number;
    label: string;
    subscriber_retention_pct: number | null;
    non_subscriber_retention_pct: number | null;
    subscriber_n: number;
    non_subscriber_n: number;
  }[];
  subscriber_vs_non_subscriber: {
    cohort_group: string;
    buyers: number;
    repeat_purchase_rate_pct: number;
    avg_orders_per_customer: number;
    avg_order_value: number;
    avg_ltv: number;
    avg_days_between_orders: number | null;
  }[];
  by_category: {
    category_name: string;
    total_subscriptions: number;
    active_subscriptions: number;
    cancelled_subscriptions: number;
    cancel_rate_pct: number;
    avg_cadence_days: number;
    active_mrr: number;
  }[];
  renewal_timing: {
    plan_cadence_days: number;
    renewal_events: number;
    avg_actual_days: number;
    avg_variance_days: number;
    on_time_renewal_pct: number;
  }[];
  cancel_reasons: {
    cancel_reason: string;
    cancellations: number;
    share_pct: number;
    avg_tenure_days: number;
  }[];
  statistical_evidence: (StatProportionTest & Record<string, unknown>)[];
}

export const SubscriptionPerformance: React.FC = () => {
  const { filters } = useFilters();
  const [data, setData] = useState<SubscriptionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<SubscriptionData>(`/api/subscriptions${buildQueryParams(filters)}`)
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

  if (loading && !data) return <div className="loading-state">Analyzing subscription renewal timing and cohort retention…</div>;
  if (error) return <div className="error-state">Failed to load Subscription Performance: {error}</div>;
  if (!data) return null;

  const {
    kpis,
    monthly_lifecycle,
    retention_comparison,
    subscriber_vs_non_subscriber,
    by_category,
    renewal_timing,
    cancel_reasons,
    statistical_evidence,
  } = data;

  const cmpCols: ColumnDef<SubscriptionData["subscriber_vs_non_subscriber"][number]>[] = [
    { key: "cohort_group", header: "Customer Cohort", render: (r) => <strong>{r.cohort_group}</strong> },
    { key: "buyers", header: "Delivered Buyers", align: "right", render: (r) => fmtInt(r.buyers) },
    { key: "repeat_purchase_rate_pct", header: "Repeat Rate", align: "right", render: (r) => <strong>{fmtPct(r.repeat_purchase_rate_pct)}</strong> },
    { key: "avg_orders_per_customer", header: "Orders / Buyer", align: "right", render: (r) => fmtDec(r.avg_orders_per_customer) },
    { key: "avg_order_value", header: "Avg AOV", align: "right", render: (r) => fmtInr(r.avg_order_value) },
    { key: "avg_ltv", header: "Avg LTV", align: "right", render: (r) => <strong>{fmtInr(r.avg_ltv)}</strong> },
    { key: "avg_days_between_orders", header: "Avg Gap", align: "right", render: (r) => (r.avg_days_between_orders ? `${r.avg_days_between_orders.toFixed(1)}d` : "—") },
  ];

  const catCols: ColumnDef<SubscriptionData["by_category"][number]>[] = [
    { key: "category_name", header: "Category", render: (r) => <strong>{r.category_name}</strong> },
    { key: "total_subscriptions", header: "Total Started", align: "right", render: (r) => fmtInt(r.total_subscriptions) },
    { key: "active_subscriptions", header: "Active", align: "right", render: (r) => fmtInt(r.active_subscriptions) },
    { key: "cancelled_subscriptions", header: "Cancelled", align: "right", render: (r) => fmtInt(r.cancelled_subscriptions) },
    { key: "cancel_rate_pct", header: "Cancel Rate", align: "right", render: (r) => fmtPct(r.cancel_rate_pct) },
    { key: "avg_cadence_days", header: "Avg Cadence", align: "right", render: (r) => `${r.avg_cadence_days.toFixed(0)}d` },
    { key: "active_mrr", header: "Active MRR", align: "right", render: (r) => fmtInr(r.active_mrr) },
  ];

  const timingCols: ColumnDef<SubscriptionData["renewal_timing"][number]>[] = [
    { key: "plan_cadence_days", header: "Plan Cadence", render: (r) => <strong>{r.plan_cadence_days}-Day Plan</strong> },
    { key: "renewal_events", header: "Renewals", align: "right", render: (r) => fmtInt(r.renewal_events) },
    { key: "avg_actual_days", header: "Avg Actual Interval", align: "right", render: (r) => `${r.avg_actual_days.toFixed(1)}d` },
    {
      key: "avg_variance_days",
      header: "Mean Variance",
      align: "right",
      render: (r) => `${r.avg_variance_days > 0 ? "+" : ""}${r.avg_variance_days.toFixed(2)}d`,
    },
    { key: "on_time_renewal_pct", header: "On-Time (≤+1d)", align: "right", render: (r) => fmtPct(r.on_time_renewal_pct) },
  ];

  const propTest = statistical_evidence.find((e) => "group_a" in e) as StatProportionTest | undefined;

  return (
    <>
      <div className="kpi-grid">
        <MetricCard
          label="Active Subscriptions"
          value={fmtInt(kpis.active_subscriptions)}
          subtext={`${fmtInt(kpis.paused_subscriptions)} paused · ${fmtInt(kpis.total_subscriptions)} started`}
          formula="Subscriptions with status = 'active'"
        />
        <MetricCard
          label="Active MRR"
          value={fmtInr(kpis.active_mrr, true)}
          subtext={`Avg plan ${fmtInr(kpis.avg_monthly_plan_value)}/mo`}
          formula="SUM(monthly_plan_value) for active subscriptions"
        />
        <MetricCard
          label="Cycle Renewal Rate"
          value={fmtPct(kpis.cycle_renewal_rate_pct)}
          subtext={`${fmtInt(kpis.renewals_in_period)} renewals in period`}
          formula="Renewed Cycles / (Renewed + Cancelled Cycles) in period"
        />
        <MetricCard
          label="Cumulative Cancel Rate"
          value={fmtPct(kpis.cumulative_cancellation_rate_pct)}
          subtext={`${fmtInt(kpis.cancelled_subscriptions)} cancelled`}
          formula="Cancelled Subscriptions / Total Subscriptions Started"
        />
        <MetricCard
          label="Avg Renewal Interval"
          value={`${(kpis.avg_renewal_interval_days || 0).toFixed(1)}d`}
          subtext={`Median ${(kpis.median_renewal_interval_days || 0).toFixed(1)}d`}
          formula="Mean days_since_prev_event for subscription renewals"
        />
        <MetricCard
          label="Refill Orders Share"
          value={fmtPct(kpis.sub_order_share_pct)}
          subtext={`${fmtInt(kpis.sub_refill_orders)} orders · ${fmtPct(kpis.sub_revenue_share_pct)} rev`}
          formula="Subscription Auto-Refill Delivered Orders / All Delivered Orders"
        />
      </div>

      {propTest && <StatTestCard test={propTest} />}

      <div className="grid-2-1">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Subscriber vs Non-Subscriber Cohort Retention (M0–M6)</h2>
              <p className="panel-subtitle">Matured eligible monthly buyer retention · Association reflects both auto-refill convenience and self-selection</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={300}
              data={[
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Subscribers",
                  x: retention_comparison.map((r) => r.label),
                  y: retention_comparison.map((r) => r.subscriber_retention_pct),
                  line: { color: CHART_COLORS.teal, width: 2.8 },
                  marker: { size: 7 },
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Non-Subscribers",
                  x: retention_comparison.map((r) => r.label),
                  y: retention_comparison.map((r) => r.non_subscriber_retention_pct),
                  line: { color: CHART_COLORS.slate, width: 2.2, dash: "dash" },
                  marker: { size: 6 },
                },
              ]}
              layout={{
                margin: { t: 28, r: 20, b: 38, l: 48 },
                yaxis: { title: { text: "Cohort Retention (%)", font: { size: 11 } }, ticksuffix: "%", range: [0, 105] },
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Subscription Cancellation Drivers</h2>
              <p className="panel-subtitle">Reported cancellation reasons across ended plans</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={300}
              data={[
                {
                  type: "bar",
                  orientation: "h",
                  y: cancel_reasons.map((c) => c.cancel_reason).reverse(),
                  x: cancel_reasons.map((c) => c.cancellations).reverse(),
                  text: cancel_reasons.map((c) => `${c.share_pct.toFixed(1)}%`).reverse(),
                  textposition: "outside",
                  cliponaxis: false,
                  marker: { color: CHART_COLORS.red },
                },
              ]}
              layout={{
                margin: { t: 28, r: 58, b: 36, l: 175 },
                xaxis: {
                  title: { text: "Cancelled Plans", font: { size: 11 } },
                  range: [0, Math.max(10, ...cancel_reasons.map((c) => c.cancellations)) * 1.35],
                },
              }}
            />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Commercial Unit Economics: Subscribers vs Non-Subscribers</h2>
            <p className="panel-subtitle">Repeat rate, order velocity, AOV, and lifetime value across filtered delivered buyers</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={cmpCols} rows={subscriber_vs_non_subscriber} />
        </div>
      </section>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Monthly Subscription Lifecycle Activity</h2>
              <p className="panel-subtitle">New enrollments, recurring renewals, cancellations, and monthly renewal rate</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={280}
              data={[
                {
                  type: "bar",
                  name: "Renewals",
                  x: monthly_lifecycle.map((m) => m.year_month),
                  y: monthly_lifecycle.map((m) => m.renewals),
                  marker: { color: CHART_COLORS.blue },
                },
                {
                  type: "bar",
                  name: "New Starts",
                  x: monthly_lifecycle.map((m) => m.year_month),
                  y: monthly_lifecycle.map((m) => m.new_subscriptions),
                  marker: { color: CHART_COLORS.teal },
                },
                {
                  type: "bar",
                  name: "Cancellations",
                  x: monthly_lifecycle.map((m) => m.year_month),
                  y: monthly_lifecycle.map((m) => m.cancellations),
                  marker: { color: CHART_COLORS.red },
                },
              ]}
              layout={{
                barmode: "group",
                margin: { t: 28, r: 16, b: 42, l: 48 },
                yaxis: { title: { text: "Subscription Events", font: { size: 11 } } },
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Renewal Timing Adherence by Plan Cadence</h2>
              <p className="panel-subtitle">Actual inter-renewal days vs 30 / 45 / 60-day schedule</p>
            </div>
          </div>
          <div className="panel-body-flush">
            <DataTable columns={timingCols} rows={renewal_timing} />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Subscription Performance by Medicine Category</h2>
            <p className="panel-subtitle">Chronic refill categories drive the majority of recurring subscription MRR</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={catCols} rows={by_category} defaultSortKey="active_mrr" />
        </div>
      </section>
    </>
  );
};
