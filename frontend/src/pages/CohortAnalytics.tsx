import React, { useEffect, useState } from "react";
import { apiGet, buildQueryParams, fmtInr, fmtInt, fmtPct } from "../api/client";
import { DataTable, type ColumnDef } from "../components/DataTable";
import { StatTestCard } from "../components/InsightCard";
import { CHART_COLORS, PlotlyChart } from "../components/PlotlyChart";
import { useFilters } from "../context/FilterContext";
import type { StatProportionTest } from "../types/analytics";

interface CohortRow {
  cohort_month: string;
  cohort_size: number;
  retention: Record<string, number>;
  retained_counts: Record<string, number>;
  cumulative_ltv: Record<string, number>;
}

interface CohortData {
  matrix: CohortRow[];
  weighted_curve: {
    month_offset: number;
    label: string;
    eligible_cohorts: number;
    eligible_customers: number;
    retained_customers: number;
    weighted_retention_pct: number;
  }[];
  cohort_quality_summary: {
    cohort_month: string;
    cohort_size: number;
    promo_channel_share_pct: number;
    subscriber_share_pct: number;
    lifetime_repeat_pct: number;
    avg_ltv: number;
    m1_retention_pct: number | null;
    m3_retention_pct: number | null;
    m6_retention_pct: number | null;
  }[];
  statistical_tests: StatProportionTest[];
}

function heatBg(val: number | undefined, mode: "retention" | "ltv"): string {
  if (val === undefined) return "#F8FAFC";
  if (mode === "ltv") {
    const ratio = Math.min(1, val / 6500);
    return `rgba(29, 111, 114, ${0.08 + ratio * 0.45})`;
  }
  if (val === 100) return "#0F243D";
  const ratio = Math.min(1, val / 55);
  return `rgba(30, 86, 160, ${0.07 + ratio * 0.58})`;
}

export const CohortAnalytics: React.FC = () => {
  const { filters } = useFilters();
  const [data, setData] = useState<CohortData | null>(null);
  const [mode, setMode] = useState<"retention" | "ltv">("retention");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<CohortData>(`/api/cohorts${buildQueryParams(filters)}`)
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

  if (loading && !data) return <div className="loading-state">Building monthly acquisition cohort matrix…</div>;
  if (error) return <div className="error-state">Failed to load Cohort Analytics: {error}</div>;
  if (!data) return null;

  const { matrix, weighted_curve, cohort_quality_summary, statistical_tests } = data;
  const maxOffset = Math.min(12, Math.max(0, matrix.length - 1));
  const offsets = Array.from({ length: maxOffset + 1 }, (_, i) => `M${i}`);

  // Compare Baseline cohorts (2025-10..2026-02) vs Q2 2026 Surge (2026-04..2026-06)
  const baselineCohorts = matrix.filter((c) => ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02"].includes(c.cohort_month));
  const q2Cohorts = matrix.filter((c) => ["2026-04", "2026-05", "2026-06"].includes(c.cohort_month));
  const avgCurve = (list: CohortRow[], mKeys: string[]) =>
    mKeys.map((k) => {
      const valid = list.filter((c) => c.retention[k] !== undefined);
      if (!valid.length) return null;
      const totSize = valid.reduce((s, c) => s + c.cohort_size, 0);
      const totRet = valid.reduce((s, c) => s + (c.retained_counts[k] || 0), 0);
      return Number(((100 * totRet) / Math.max(totSize, 1)).toFixed(2));
    });
  const cmpOffsets = ["M0", "M1", "M2", "M3", "M4"];

  const qualityCols: ColumnDef<CohortData["cohort_quality_summary"][number]>[] = [
    { key: "cohort_month", header: "Cohort Month", render: (r) => <strong>{r.cohort_month}</strong> },
    { key: "cohort_size", header: "Cohort Size", align: "right", render: (r) => fmtInt(r.cohort_size) },
    {
      key: "promo_channel_share_pct",
      header: "Social + Affiliate %",
      align: "right",
      render: (r) => (
        <span className={r.promo_channel_share_pct >= 35 ? "badge badge-amber" : ""}>{fmtPct(r.promo_channel_share_pct)}</span>
      ),
    },
    { key: "subscriber_share_pct", header: "Subscriber %", align: "right", render: (r) => fmtPct(r.subscriber_share_pct) },
    { key: "m1_retention_pct", header: "M1 Retention", align: "right", render: (r) => (r.m1_retention_pct !== null ? <strong>{fmtPct(r.m1_retention_pct)}</strong> : "—") },
    { key: "m3_retention_pct", header: "M3 Retention", align: "right", render: (r) => (r.m3_retention_pct !== null ? fmtPct(r.m3_retention_pct) : "—") },
    { key: "m6_retention_pct", header: "M6 Retention", align: "right", render: (r) => (r.m6_retention_pct !== null ? fmtPct(r.m6_retention_pct) : "—") },
    { key: "lifetime_repeat_pct", header: "Repeat Buyer %", align: "right", render: (r) => fmtPct(r.lifetime_repeat_pct) },
    { key: "avg_ltv", header: "Avg LTV", align: "right", render: (r) => fmtInr(r.avg_ltv) },
  ];

  return (
    <>
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">
              {mode === "retention"
                ? "Monthly Acquisition Cohort Retention Matrix (% Active Buyers)"
                : "Monthly Acquisition Cohort Cumulative LTV per Buyer (INR)"}
            </h2>
            <p className="panel-subtitle">
              Cohort defined by calendar month of first delivered order · Unmatured future cells remain blank (never zero-padded)
            </p>
          </div>
          <div className="seg-control">
            <button type="button" className={`seg-btn ${mode === "retention" ? "active" : ""}`} onClick={() => setMode("retention")}>
              Retention %
            </button>
            <button type="button" className={`seg-btn ${mode === "ltv" ? "active" : ""}`} onClick={() => setMode("ltv")}>
              Cumulative LTV (₹)
            </button>
          </div>
        </div>
        <div className="panel-body">
          <div className="table-wrap">
            <table className="cohort-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Cohort</th>
                  <th style={{ textAlign: "right" }}>Buyers</th>
                  {offsets.map((m) => (
                    <th key={m}>{m}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.map((row) => (
                  <tr key={row.cohort_month}>
                    <td className="cohort-label">
                      {row.cohort_month}{" "}
                      {["2026-04", "2026-05", "2026-06"].includes(row.cohort_month) && (
                        <span className="badge badge-amber" style={{ marginLeft: 4 }}>Q2 Promo</span>
                      )}
                    </td>
                    <td className="cohort-size">{fmtInt(row.cohort_size)}</td>
                    {offsets.map((m) => {
                      const val = mode === "retention" ? row.retention[m] : row.cumulative_ltv[m];
                      const cnt = row.retained_counts[m];
                      const isM0 = mode === "retention" && m === "M0";
                      return (
                        <td
                          key={m}
                          style={{
                            backgroundColor: heatBg(val, mode),
                            color: isM0 ? "#FFFFFF" : val !== undefined ? "#0F172A" : "#CBD5E1",
                            fontWeight: isM0 || m === "M1" ? 600 : 400,
                          }}
                          title={
                            val !== undefined
                              ? `${row.cohort_month} · ${m}: ${mode === "retention" ? `${val.toFixed(1)}% (${fmtInt(cnt)} / ${fmtInt(row.cohort_size)})` : fmtInr(val)}`
                              : "Unmatured period"
                          }
                        >
                          {val === undefined ? "" : mode === "retention" ? `${val.toFixed(1)}%` : fmtInr(val)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {statistical_tests.map((t) => (
        <StatTestCard key={t.test_id} test={t} />
      ))}

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Q2 2026 Promo Cohorts vs Baseline Retention Curve</h2>
              <p className="panel-subtitle">Weighted M0–M4 retention comparing Apr–Jun 2026 promo surge against Oct–Feb baseline</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={285}
              data={[
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Baseline (Oct 2025 – Feb 2026)",
                  x: cmpOffsets,
                  y: avgCurve(baselineCohorts, cmpOffsets),
                  line: { color: CHART_COLORS.navy, width: 2.5 },
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Q2 2026 Promo Surge (Apr–Jun 2026)",
                  x: cmpOffsets,
                  y: avgCurve(q2Cohorts, cmpOffsets),
                  line: { color: CHART_COLORS.red, width: 2.5, dash: "dot" },
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "All Cohorts Weighted Avg",
                  x: weighted_curve.slice(0, 5).map((w) => w.label),
                  y: weighted_curve.slice(0, 5).map((w) => w.weighted_retention_pct),
                  line: { color: CHART_COLORS.steel, width: 1.8 },
                },
              ]}
              layout={{
                margin: { t: 28, r: 20, b: 38, l: 48 },
                yaxis: { title: { text: "Retention (%)", font: { size: 11 } }, ticksuffix: "%" },
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Channel Mix Shift vs Month-1 Retention</h2>
              <p className="panel-subtitle">Social Media + Affiliate acquisition share vs resulting cohort M1 retention</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={285}
              data={[
                {
                  type: "bar",
                  name: "Social + Affiliate Share %",
                  x: cohort_quality_summary.map((c) => c.cohort_month),
                  y: cohort_quality_summary.map((c) => c.promo_channel_share_pct),
                  marker: { color: CHART_COLORS.lightBlue },
                },
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "M1 Retention %",
                  x: cohort_quality_summary.map((c) => c.cohort_month),
                  y: cohort_quality_summary.map((c) => c.m1_retention_pct),
                  yaxis: "y2",
                  line: { color: CHART_COLORS.red, width: 2.4 },
                },
              ]}
              layout={{
                margin: { t: 28, r: 52, b: 42, l: 48 },
                yaxis: { title: { text: "Promo Channel Share (%)", font: { size: 11 } }, ticksuffix: "%" },
                yaxis2: { title: { text: "M1 Retention (%)", font: { size: 11 } }, overlaying: "y", side: "right", ticksuffix: "%", showgrid: false },
              }}
            />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Cohort Quality Decomposition Table</h2>
            <p className="panel-subtitle">Acquisition mix, subscription adoption, retention checkpoints, and lifetime value by cohort</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={qualityCols} rows={cohort_quality_summary} defaultSortKey="cohort_month" defaultSortDir="asc" />
        </div>
      </section>
    </>
  );
};
