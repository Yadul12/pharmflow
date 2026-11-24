import React, { useEffect, useState } from "react";
import { apiGet, buildQueryParams, fmtInr, fmtInt, fmtPct } from "../api/client";
import { DataTable, type ColumnDef } from "../components/DataTable";
import { StatTestCard } from "../components/InsightCard";
import { MetricCard } from "../components/MetricCard";
import { CHART_COLORS, PlotlyChart } from "../components/PlotlyChart";
import { useFilters } from "../context/FilterContext";
import type { StatProportionTest } from "../types/analytics";

interface CancellationData {
  kpis: {
    placed_orders_nondup: number;
    cancelled_orders_nondup: number;
    duplicate_attempts_caught: number;
    delivered_orders: number;
    returned_orders: number;
    cancelled_order_value: number;
    cancellation_rate_pct: number;
    return_rate_pct: number;
    sla_breach_rate_pct: number;
    total_refunds: number;
    total_refund_amount: number;
    avg_refund_processing_hours: number;
  };
  cancel_reasons: {
    cancellation_reason: string;
    cancellation_stage: string;
    initiated_by: string;
    cancellations: number;
    share_pct: number;
    lost_order_value: number;
    avg_hours_after_order: number;
  }[];
  refund_reasons: {
    refund_reason: string;
    refund_type: string;
    refund_count: number;
    share_pct: number;
    total_refund_amount: number;
    avg_refund_amount: number;
    avg_processing_hours: number;
  }[];
  monthly_trend: {
    year_month: string;
    season: string;
    placed_orders: number;
    cancelled_orders: number;
    cancellation_rate_pct: number;
    returned_orders: number;
    sla_breach_pct: number;
    refunds: number;
    refund_amount: number;
  }[];
  by_city: {
    city: string;
    city_tier: string;
    placed_orders: number;
    cancelled_orders: number;
    cancellation_rate_pct: number;
    avg_promised_days: number;
    avg_actual_days: number;
    sla_breach_pct: number;
    cancelled_value: number;
  }[];
  by_payment_device: {
    payment_method: string;
    device_type: string;
    orders: number;
    cancelled_orders: number;
    cancellation_rate_pct: number;
    avg_gateway_ms: number | null;
  }[];
  statistical_tests: StatProportionTest[];
}

export const CancellationRefunds: React.FC = () => {
  const { filters } = useFilters();
  const [data, setData] = useState<CancellationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<CancellationData>(`/api/cancellations${buildQueryParams(filters)}`)
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

  if (loading && !data) return <div className="loading-state">Auditing cancellation drivers, refunds &amp; SLA breaches…</div>;
  if (error) return <div className="error-state">Failed to load Cancellation Analysis: {error}</div>;
  if (!data) return null;

  const { kpis, cancel_reasons, refund_reasons, monthly_trend, by_city, by_payment_device, statistical_tests } = data;

  // Compute Pareto cumulative share on cancel reasons
  const totalCancels = cancel_reasons.reduce((s, r) => s + r.cancellations, 0);
  let running = 0;
  const paretoCum = cancel_reasons.map((r) => {
    running += r.cancellations;
    return Number(((100 * running) / Math.max(totalCancels, 1)).toFixed(1));
  });

  const reasonCols: ColumnDef<CancellationData["cancel_reasons"][number]>[] = [
    { key: "cancellation_reason", header: "Cancellation Reason", render: (r) => <strong>{r.cancellation_reason}</strong> },
    { key: "cancellation_stage", header: "Stage", render: (r) => <span className="badge badge-gray">{r.cancellation_stage}</span> },
    { key: "initiated_by", header: "Initiated By" },
    { key: "cancellations", header: "Orders", align: "right", render: (r) => fmtInt(r.cancellations) },
    { key: "share_pct", header: "Share", align: "right", render: (r) => fmtPct(r.share_pct) },
    { key: "lost_order_value", header: "Lost Value", align: "right", render: (r) => fmtInr(r.lost_order_value) },
    { key: "avg_hours_after_order", header: "Avg Hrs", align: "right", render: (r) => `${r.avg_hours_after_order.toFixed(1)}h` },
  ];

  const refundCols: ColumnDef<CancellationData["refund_reasons"][number]>[] = [
    { key: "refund_reason", header: "Refund Reason", render: (r) => <strong>{r.refund_reason}</strong> },
    { key: "refund_type", header: "Type", render: (r) => <span className={`badge ${r.refund_type === "full" ? "badge-blue" : "badge-amber"}`}>{r.refund_type}</span> },
    { key: "refund_count", header: "Refunds", align: "right", render: (r) => fmtInt(r.refund_count) },
    { key: "share_pct", header: "Share", align: "right", render: (r) => fmtPct(r.share_pct) },
    { key: "total_refund_amount", header: "Total Refunded", align: "right", render: (r) => fmtInr(r.total_refund_amount) },
    { key: "avg_refund_amount", header: "Avg Refund", align: "right", render: (r) => fmtInr(r.avg_refund_amount) },
    { key: "avg_processing_hours", header: "Processing Hrs", align: "right", render: (r) => `${r.avg_processing_hours.toFixed(1)}h` },
  ];

  const cityCols: ColumnDef<CancellationData["by_city"][number]>[] = [
    { key: "city", header: "City", render: (r) => <strong>{r.city}</strong> },
    { key: "city_tier", header: "Tier", render: (r) => <span className="badge badge-gray">{r.city_tier}</span> },
    { key: "placed_orders", header: "Placed Orders", align: "right", render: (r) => fmtInt(r.placed_orders) },
    { key: "cancelled_orders", header: "Cancelled", align: "right", render: (r) => fmtInt(r.cancelled_orders) },
    {
      key: "cancellation_rate_pct",
      header: "Cancel Rate",
      align: "right",
      render: (r) => (
        <span className={r.cancellation_rate_pct >= 14 ? "badge badge-red" : r.cancellation_rate_pct >= 11 ? "badge badge-amber" : "badge badge-green"}>
          {fmtPct(r.cancellation_rate_pct)}
        </span>
      ),
    },
    { key: "avg_promised_days", header: "Promised", align: "right", render: (r) => `${r.avg_promised_days.toFixed(1)}d` },
    { key: "avg_actual_days", header: "Actual", align: "right", render: (r) => (r.avg_actual_days ? `${r.avg_actual_days.toFixed(2)}d` : "—") },
    { key: "sla_breach_pct", header: "SLA Breach", align: "right", render: (r) => fmtPct(r.sla_breach_pct) },
    { key: "cancelled_value", header: "Cancelled Value", align: "right", render: (r) => fmtInr(r.cancelled_value) },
  ];

  const payCols: ColumnDef<CancellationData["by_payment_device"][number]>[] = [
    { key: "payment_method", header: "Payment Method", render: (r) => <strong>{r.payment_method}</strong> },
    { key: "device_type", header: "Device" },
    { key: "orders", header: "Orders", align: "right", render: (r) => fmtInt(r.orders) },
    { key: "cancelled_orders", header: "Cancelled", align: "right", render: (r) => fmtInt(r.cancelled_orders) },
    { key: "cancellation_rate_pct", header: "Cancel %", align: "right", render: (r) => fmtPct(r.cancellation_rate_pct) },
    { key: "avg_gateway_ms", header: "Avg Gateway", align: "right", render: (r) => (r.avg_gateway_ms ? `${Math.round(r.avg_gateway_ms)} ms` : "COD") },
  ];

  return (
    <>
      <div className="kpi-grid">
        <MetricCard
          label="Cancellation Rate"
          value={fmtPct(kpis.cancellation_rate_pct)}
          subtext={`${fmtInt(kpis.cancelled_orders_nondup)} / ${fmtInt(kpis.placed_orders_nondup)} non-dup`}
          formula="Non-Duplicate Cancelled Orders / Non-Duplicate Placed Orders"
        />
        <MetricCard
          label="Cancelled Order Value"
          value={fmtInr(kpis.cancelled_order_value, true)}
          subtext="Gross commercial leakage"
          formula="SUM(net_amount) for non-duplicate cancelled orders"
        />
        <MetricCard
          label="Duplicate Attempts Caught"
          value={fmtInt(kpis.duplicate_attempts_caught)}
          subtext="Auto-cancelled & excluded"
          formula="Orders flagged is_duplicate_attempt = TRUE (100% cancelled)"
        />
        <MetricCard
          label="Post-Delivery Return Rate"
          value={fmtPct(kpis.return_rate_pct)}
          subtext={`${fmtInt(kpis.returned_orders)} returned orders`}
          formula="Returned Orders / (Delivered + Returned Orders)"
        />
        <MetricCard
          label="Total Refunds Issued"
          value={fmtInr(kpis.total_refund_amount, true)}
          subtext={`${fmtInt(kpis.total_refunds)} refunds · ${(kpis.avg_refund_processing_hours || 0).toFixed(1)}h avg`}
          formula="SUM(refund_amount) across full & partial refunds"
        />
        <MetricCard
          label="Delivery SLA Breach Rate"
          value={fmtPct(kpis.sla_breach_rate_pct)}
          subtext="Actual > promised SLA"
          formula="Orders with actual_delivery_days > promised_delivery_days"
        />
      </div>

      {statistical_tests.map((t) => (
        <StatTestCard key={t.test_id} test={t} />
      ))}

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Cancellation Reasons Pareto</h2>
              <p className="panel-subtitle">Order volume per root cause and cumulative percentage share</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={305}
              data={[
                {
                  type: "bar",
                  name: "Cancelled Orders",
                  x: cancel_reasons.map((r) => r.cancellation_reason),
                  y: cancel_reasons.map((r) => r.cancellations),
                  marker: { color: CHART_COLORS.red },
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Cumulative %",
                  x: cancel_reasons.map((r) => r.cancellation_reason),
                  y: paretoCum,
                  yaxis: "y2",
                  line: { color: CHART_COLORS.navy, width: 2.2 },
                },
              ]}
              layout={{
                margin: { t: 28, r: 50, b: 92, l: 52 },
                xaxis: { tickangle: -25 },
                yaxis: { title: { text: "Cancelled Orders", font: { size: 11 } } },
                yaxis2: { title: { text: "Cumulative (%)", font: { size: 11 } }, overlaying: "y", side: "right", ticksuffix: "%", range: [0, 105], showgrid: false },
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Monthly Cancellation Rate &amp; Delivery SLA Breaches</h2>
              <p className="panel-subtitle">Monsoon corridor disruption (Jul–Aug 2026) drives synchronized SLA and cancellation spikes</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={305}
              data={[
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Cancellation Rate %",
                  x: monthly_trend.map((m) => m.year_month),
                  y: monthly_trend.map((m) => m.cancellation_rate_pct),
                  line: { color: CHART_COLORS.red, width: 2.4 },
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Delivery SLA Breach %",
                  x: monthly_trend.map((m) => m.year_month),
                  y: monthly_trend.map((m) => m.sla_breach_pct),
                  line: { color: CHART_COLORS.amber, width: 2.2, dash: "dot" },
                },
              ]}
              layout={{
                margin: { t: 28, r: 20, b: 42, l: 48 },
                yaxis: { title: { text: "Rate (%)", font: { size: 11 } }, ticksuffix: "%" },
              }}
            />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Cancellation Drivers Breakdown (With Stage &amp; Commercial Loss)</h2>
            <p className="panel-subtitle">Includes all tracked cancellations; duplicate attempts are explicitly isolated in reason code</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={reasonCols} rows={cancel_reasons} defaultSortKey="cancellations" />
        </div>
      </section>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Geographic Cancellation &amp; SLA Performance</h2>
              <p className="panel-subtitle">Tier 3 hubs and Kolkata exhibit elevated transit slippage and cancellations</p>
            </div>
          </div>
          <div className="panel-body-flush">
            <DataTable columns={cityCols} rows={by_city} defaultSortKey="cancellation_rate_pct" maxHeight={340} />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Payment Method × Device Friction Matrix</h2>
              <p className="panel-subtitle">Highlights COD and Mobile Web payment timeout cancellation pressure</p>
            </div>
          </div>
          <div className="panel-body-flush">
            <DataTable columns={payCols} rows={by_payment_device} defaultSortKey="cancellation_rate_pct" maxHeight={340} />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Refund Reasons, Type &amp; Processing SLA</h2>
            <p className="panel-subtitle">Pre-shipment prepaid auto-refunds versus post-delivery returns and partial stock refunds</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={refundCols} rows={refund_reasons} defaultSortKey="total_refund_amount" />
        </div>
      </section>
    </>
  );
};
