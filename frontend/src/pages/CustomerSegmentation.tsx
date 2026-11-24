import React, { useEffect, useState } from "react";
import { apiGet, buildQueryParams, fmtDec, fmtInr, fmtInt, fmtPct } from "../api/client";
import { DataTable, type ColumnDef } from "../components/DataTable";
import { CHART_COLORS, PlotlyChart } from "../components/PlotlyChart";
import { useFilters } from "../context/FilterContext";

interface SegmentationData {
  business_segments: {
    business_segment: string;
    customer_count: number;
    customer_share_pct: number;
    total_revenue: number;
    revenue_share_pct: number;
    avg_ltv: number;
    avg_aov: number;
    avg_frequency: number;
    avg_recency_days: number;
    subscriber_share_pct: number;
    high_churn_risk_pct: number | null;
  }[];
  rfm_matrix: {
    r_score: number;
    f_score: number;
    customers: number;
    avg_monetary: number;
    total_revenue: number;
  }[];
  kmeans_live_profiles: {
    cluster_id: number;
    cluster_label: string;
    customer_count: number;
    share_of_buyers_pct: number;
    avg_recency_days: number;
    avg_frequency: number;
    avg_monetary: number;
    avg_aov: number;
    subscriber_share_pct: number;
    high_churn_risk_pct: number;
  }[];
  kmeans_evaluation: {
    selected_k: number;
    selected_silhouette_score: number;
    pca_explained_variance_ratio: number[];
    pca_total_explained_variance: number;
    missing_value_strategy: string;
    k_scan: { k: number; silhouette_score: number; calinski_harabasz: number; inertia: number }[];
    cluster_descriptions: Record<string, string>;
    pca_scatter_sample: {
      customer_code: string;
      pca_x: number;
      pca_y: number;
      kmeans_cluster: number;
      kmeans_label: string;
      business_segment: string;
      frequency_orders: number;
      monetary_value: number;
      recency_days: number;
    }[];
  };
  churn_model: {
    train_cutoff?: string;
    train_outcome_window?: string;
    test_cutoff?: string;
    test_outcome_window?: string;
    train_rows?: number;
    test_rows?: number;
    train_churn_rate?: number;
    test_churn_rate?: number;
    selected_model?: string;
    model_comparison?: {
      model_name: string;
      precision: number;
      recall: number;
      f1_score: number;
      roc_auc: number;
      roc_auc_ci_95: [number, number];
      pr_auc: number;
      brier_score: number;
      confusion_matrix: { tn: number; fp: number; fn: number; tp: number };
    }[];
    top_logistic_drivers?: { feature: string; log_odds_coef: number; direction: string }[];
    slice_analysis?: { slice: string; n: number; actual_churn_rate: number; roc_auc: number; precision: number; recall: number }[];
    limitations?: string[];
  };
  customer_drilldown: {
    customer_code: string;
    primary_city: string;
    city_tier: string;
    acquisition_channel: string;
    primary_device: string;
    business_segment: string;
    rfm_code: string;
    recency_days: number | null;
    frequency_orders: number;
    monetary_value: number;
    avg_order_value: number;
    is_subscriber: boolean;
    kmeans_label: string | null;
    churn_risk_score: number | null;
    churn_risk_band: string | null;
  }[];
}

export const CustomerSegmentation: React.FC = () => {
  const { filters } = useFilters();
  const [selectedSegment, setSelectedSegment] = useState("");
  const [churnBand, setChurnBand] = useState("");
  const [data, setData] = useState<SegmentationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<SegmentationData>(
      `/api/segmentation${buildQueryParams(filters, {
        selected_segment: selectedSegment || undefined,
        churn_band: churnBand || undefined,
        limit: 60,
      })}`
    )
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
  }, [filters, selectedSegment, churnBand]);

  if (loading && !data) return <div className="loading-state">Loading RFM segments, K-Means clusters &amp; churn model metrics…</div>;
  if (error) return <div className="error-state">Failed to load Customer Segmentation: {error}</div>;
  if (!data) return null;

  const { business_segments, rfm_matrix, kmeans_live_profiles, kmeans_evaluation, churn_model, customer_drilldown } = data;

  const segCols: ColumnDef<SegmentationData["business_segments"][number]>[] = [
    { key: "business_segment", header: "RFM Business Segment", render: (r) => <strong>{r.business_segment}</strong> },
    { key: "customer_count", header: "Customers", align: "right", render: (r) => fmtInt(r.customer_count) },
    { key: "customer_share_pct", header: "Cust Share", align: "right", render: (r) => fmtPct(r.customer_share_pct) },
    { key: "total_revenue", header: "Net Revenue", align: "right", render: (r) => fmtInr(r.total_revenue) },
    { key: "revenue_share_pct", header: "Rev Share", align: "right", render: (r) => <strong>{fmtPct(r.revenue_share_pct)}</strong> },
    { key: "avg_aov", header: "Avg AOV", align: "right", render: (r) => fmtInr(r.avg_aov) },
    { key: "avg_frequency", header: "Avg Orders", align: "right", render: (r) => fmtDec(r.avg_frequency) },
    { key: "avg_recency_days", header: "Avg Recency", align: "right", render: (r) => (r.avg_recency_days ? `${r.avg_recency_days.toFixed(0)}d` : "—") },
    { key: "subscriber_share_pct", header: "Sub %", align: "right", render: (r) => fmtPct(r.subscriber_share_pct) },
    {
      key: "high_churn_risk_pct",
      header: "High Churn %",
      align: "right",
      render: (r) => (r.high_churn_risk_pct !== null ? fmtPct(r.high_churn_risk_pct) : "—"),
    },
  ];

  // Build 5x5 RFM Heatmap matrix (R=1..5 on Y, F=1..5 on X)
  const rScores = [1, 2, 3, 4, 5];
  const fScores = [1, 2, 3, 4, 5];
  const zVals = rScores.map((r) =>
    fScores.map((f) => {
      const match = rfm_matrix.find((m) => m.r_score === r && m.f_score === f);
      return match ? match.customers : 0;
    })
  );
  const textVals = rScores.map((r) =>
    fScores.map((f) => {
      const match = rfm_matrix.find((m) => m.r_score === r && m.f_score === f);
      if (!match) return "0";
      const kStr = match.avg_monetary >= 1000 ? `₹${(match.avg_monetary / 1000).toFixed(1)}k` : fmtInr(match.avg_monetary);
      return `${fmtInt(match.customers)}\n${kStr}`;
    })
  );

  // Group PCA scatter by K-Means cluster
  const clusterNames = Array.from(new Set(kmeans_evaluation.pca_scatter_sample.map((p) => p.kmeans_label)));
  const clusterPalette = [CHART_COLORS.navy, CHART_COLORS.blue, CHART_COLORS.teal, CHART_COLORS.amber, CHART_COLORS.red, CHART_COLORS.slate];

  const kmCols: ColumnDef<SegmentationData["kmeans_live_profiles"][number]>[] = [
    { key: "cluster_label", header: "K-Means Behavioral Cluster", render: (r) => <strong>{r.cluster_label}</strong> },
    { key: "customer_count", header: "Buyers", align: "right", render: (r) => fmtInt(r.customer_count) },
    { key: "share_of_buyers_pct", header: "Buyer %", align: "right", render: (r) => fmtPct(r.share_of_buyers_pct) },
    { key: "avg_recency_days", header: "Recency", align: "right", render: (r) => `${r.avg_recency_days.toFixed(0)}d` },
    { key: "avg_frequency", header: "Orders", align: "right", render: (r) => fmtDec(r.avg_frequency) },
    { key: "avg_monetary", header: "Avg LTV", align: "right", render: (r) => fmtInr(r.avg_monetary) },
    { key: "subscriber_share_pct", header: "Sub %", align: "right", render: (r) => fmtPct(r.subscriber_share_pct) },
    { key: "high_churn_risk_pct", header: "High Risk %", align: "right", render: (r) => fmtPct(r.high_churn_risk_pct) },
  ];

  const custCols: ColumnDef<SegmentationData["customer_drilldown"][number]>[] = [
    { key: "customer_code", header: "Customer ID", render: (r) => <span className="mono">{r.customer_code}</span> },
    { key: "primary_city", header: "City" },
    { key: "acquisition_channel", header: "Channel" },
    { key: "business_segment", header: "RFM Segment", render: (r) => <span className="badge badge-blue">{r.business_segment}</span> },
    { key: "rfm_code", header: "RFM", render: (r) => <span className="mono">{r.rfm_code}</span> },
    { key: "frequency_orders", header: "Orders", align: "right", render: (r) => fmtInt(r.frequency_orders) },
    { key: "monetary_value", header: "LTV", align: "right", render: (r) => fmtInr(r.monetary_value) },
    { key: "recency_days", header: "Recency", align: "right", render: (r) => (r.recency_days !== null ? `${r.recency_days}d` : "—") },
    { key: "kmeans_label", header: "K-Means Cluster", render: (r) => r.kmeans_label || "Non-Buyer" },
    {
      key: "churn_risk_band",
      header: "Churn Risk",
      align: "right",
      render: (r) =>
        r.churn_risk_band ? (
          <span className={`badge ${r.churn_risk_band === "High" ? "badge-red" : r.churn_risk_band === "Medium" ? "badge-amber" : "badge-green"}`}>
            {r.churn_risk_band} ({((r.churn_risk_score || 0) * 100).toFixed(0)}%)
          </span>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <>
      <div className="grid-2-1">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">RFM Business Segments — Customer Share vs Revenue Share</h2>
              <p className="panel-subtitle">Mutually exclusive commercial segmentation across all 30,000 synthetic accounts (as of 2026-10-31)</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={295}
              data={[
                {
                  type: "bar",
                  name: "Customer Share %",
                  x: business_segments.map((s) => s.business_segment),
                  y: business_segments.map((s) => s.customer_share_pct),
                  marker: { color: CHART_COLORS.lightBlue },
                },
                {
                  type: "bar",
                  name: "Revenue Share %",
                  x: business_segments.map((s) => s.business_segment),
                  y: business_segments.map((s) => s.revenue_share_pct),
                  marker: { color: CHART_COLORS.navy },
                },
              ]}
              layout={{
                barmode: "group",
                margin: { t: 28, r: 16, b: 58, l: 48 },
                yaxis: { title: { text: "Share (%)", font: { size: 11 } }, ticksuffix: "%" },
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">RFM Score Grid (Recency × Frequency)</h2>
              <p className="panel-subtitle">Buyer count &amp; average LTV per (R, F) score cell (5 = best)</p>
            </div>
          </div>
          <div className="panel-body">
            <PlotlyChart
              height={295}
              data={[
                {
                  type: "heatmap",
                  x: fScores.map((f) => `F=${f}`),
                  y: rScores.map((r) => `R=${r}`),
                  z: zVals,
                  text: textVals as unknown as string[],
                  texttemplate: "%{text}",
                  textfont: { size: 10 },
                  colorscale: [
                    [0, "#F8FAFC"],
                    [0.5, "#93B5DB"],
                    [1, "#0F243D"],
                  ],
                  showscale: false,
                } as Plotly.Data,
              ]}
              layout={{
                margin: { t: 10, r: 12, b: 36, l: 42 },
                xaxis: { title: { text: "Frequency Score", font: { size: 11 } } },
                yaxis: { title: { text: "Recency Score", font: { size: 11 } } },
              }}
            />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">RFM Business Segment Economics</h2>
            <p className="panel-subtitle">Full commercial breakdown by Recency, Frequency, Monetary value, AOV &amp; churn exposure</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={segCols} rows={business_segments} defaultSortKey="total_revenue" />
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">K-Means Behavioral Clustering (Supplementary Unsupervised Analysis)</h2>
            <p className="panel-subtitle">
              Standardized log-RFM + subscription + chronic-share features · Optimal k = {kmeans_evaluation.selected_k} (Silhouette ={" "}
              {kmeans_evaluation.selected_silhouette_score}) · 2D PCA variance explained ={" "}
              {((kmeans_evaluation.pca_total_explained_variance || 0) * 100).toFixed(1)}%
            </p>
          </div>
        </div>
        <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="grid-2-1">
            <PlotlyChart
              height={310}
              data={clusterNames.map((name, idx) => {
                const pts = kmeans_evaluation.pca_scatter_sample.filter((p) => p.kmeans_label === name);
                return {
                  type: "scattergl",
                  mode: "markers",
                  name,
                  x: pts.map((p) => p.pca_x),
                  y: pts.map((p) => p.pca_y),
                  text: pts.map((p) => `${p.customer_code} (${p.business_segment}) · ${p.frequency_orders} orders · ${fmtInr(p.monetary_value)}`),
                  marker: { color: clusterPalette[idx % clusterPalette.length], size: 5.5, opacity: 0.72 },
                  hovertemplate: "%{text}<extra></extra>",
                } as Plotly.Data;
              })}
              layout={{
                margin: { t: 30, r: 16, b: 42, l: 48 },
                xaxis: { title: { text: `PC1 (${((kmeans_evaluation.pca_explained_variance_ratio?.[0] || 0) * 100).toFixed(1)}% var)`, font: { size: 11 } } },
                yaxis: { title: { text: `PC2 (${((kmeans_evaluation.pca_explained_variance_ratio?.[1] || 0) * 100).toFixed(1)}% var)`, font: { size: 11 } } },
              }}
            />

            <PlotlyChart
              height={310}
              data={[
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Silhouette Score",
                  x: (kmeans_evaluation.k_scan || []).map((k) => `k=${k.k}`),
                  y: (kmeans_evaluation.k_scan || []).map((k) => k.silhouette_score),
                  line: { color: CHART_COLORS.blue, width: 2.4 },
                  marker: { size: 8, color: CHART_COLORS.navy },
                },
              ]}
              layout={{
                margin: { t: 26, r: 20, b: 42, l: 54 },
                xaxis: { title: { text: "Cluster Count (k)", font: { size: 11 } } },
                yaxis: { title: { text: "Silhouette Score (higher = tighter)", font: { size: 11 } } },
              }}
            />
          </div>

          {kmeans_evaluation.missing_value_strategy && (
            <div className="callout">
              <strong>Feature Engineering &amp; Missing-Value Note:</strong> {kmeans_evaluation.missing_value_strategy}
            </div>
          )}
        </div>
        <div className="panel-body-flush">
          <DataTable columns={kmCols} rows={kmeans_live_profiles} defaultSortKey="avg_monetary" />
        </div>
      </section>

      {churn_model && churn_model.model_comparison && (
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Time-Aware 90-Day Churn Risk Model Evaluation (Zero Target Leakage)</h2>
              <p className="panel-subtitle">
                Train Cutoff: {churn_model.train_cutoff} (Outcome: {churn_model.train_outcome_window}) · Out-of-Time Test Cutoff:{" "}
                {churn_model.test_cutoff} (Outcome: {churn_model.test_outcome_window}) · Selected: <strong>{churn_model.selected_model}</strong>
              </p>
            </div>
            <span className="badge badge-blue">
              Train n={fmtInt(churn_model.train_rows)} · Test n={fmtInt(churn_model.test_rows)}
            </span>
          </div>
          <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th className="num">Precision</th>
                    <th className="num">Recall</th>
                    <th className="num">F1 Score</th>
                    <th className="num">ROC-AUC (95% CI)</th>
                    <th className="num">PR-AUC</th>
                    <th className="num">Brier Score</th>
                    <th className="num">Confusion (TN / FP / FN / TP)</th>
                  </tr>
                </thead>
                <tbody>
                  {churn_model.model_comparison.map((m) => (
                    <tr key={m.model_name}>
                      <td>
                        <strong>{m.model_name}</strong>
                        {m.model_name === churn_model.selected_model && (
                          <span className="badge badge-green" style={{ marginLeft: 6 }}>Selected</span>
                        )}
                      </td>
                      <td className="num">{m.precision.toFixed(3)}</td>
                      <td className="num">{m.recall.toFixed(3)}</td>
                      <td className="num">{m.f1_score.toFixed(3)}</td>
                      <td className="num">
                        <strong>{m.roc_auc.toFixed(3)}</strong>{" "}
                        <span style={{ color: "#64748B", fontSize: 11 }}>
                          [{m.roc_auc_ci_95[0].toFixed(3)}, {m.roc_auc_ci_95[1].toFixed(3)}]
                        </span>
                      </td>
                      <td className="num">{m.pr_auc.toFixed(3)}</td>
                      <td className="num">{m.brier_score.toFixed(3)}</td>
                      <td className="num mono">
                        {m.confusion_matrix.tn} / {m.confusion_matrix.fp} / {m.confusion_matrix.fn} / {m.confusion_matrix.tp}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="grid-2">
              <div>
                <h4 style={{ margin: "0 0 6px", fontSize: 12, color: "#0F243D" }}>Top Standardized Predictors (Logistic Regression)</h4>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Feature</th>
                      <th className="num">Log-Odds Coef</th>
                      <th>Effect</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(churn_model.top_logistic_drivers || []).slice(0, 7).map((d) => (
                      <tr key={d.feature}>
                        <td className="mono">{d.feature}</td>
                        <td className="num">{d.log_odds_coef > 0 ? `+${d.log_odds_coef.toFixed(3)}` : d.log_odds_coef.toFixed(3)}</td>
                        <td>
                          <span className={`badge ${d.log_odds_coef > 0 ? "badge-red" : "badge-green"}`}>{d.direction}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div>
                <h4 style={{ margin: "0 0 6px", fontSize: 12, color: "#0F243D" }}>Out-of-Time Slice Error Analysis</h4>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Subpopulation</th>
                      <th className="num">N</th>
                      <th className="num">Actual Churn</th>
                      <th className="num">ROC-AUC</th>
                      <th className="num">Precision</th>
                      <th className="num">Recall</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(churn_model.slice_analysis || []).map((s) => (
                      <tr key={s.slice}>
                        <td>{s.slice}</td>
                        <td className="num">{fmtInt(s.n)}</td>
                        <td className="num">{fmtPct(s.actual_churn_rate * 100)}</td>
                        <td className="num">{s.roc_auc.toFixed(3)}</td>
                        <td className="num">{s.precision.toFixed(3)}</td>
                        <td className="num">{s.recall.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="callout callout-amber">
              <div className="callout-title">Model Limitations &amp; Responsible Use</div>
              <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>
                {(churn_model.limitations || []).map((lim, i) => (
                  <li key={i} style={{ marginBottom: 3 }}>{lim}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      )}

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Customer Segment Drill-Down (Top 60 Matching Accounts)</h2>
            <p className="panel-subtitle">Synthetic non-identifying customer records filterable by RFM segment and churn risk band</p>
          </div>
          <div className="filter-group">
            <select className="filter-select" value={selectedSegment} onChange={(e) => setSelectedSegment(e.target.value)}>
              <option value="">All Segments</option>
              {business_segments.map((s) => (
                <option key={s.business_segment} value={s.business_segment}>
                  {s.business_segment}
                </option>
              ))}
            </select>
            <select className="filter-select" value={churnBand} onChange={(e) => setChurnBand(e.target.value)}>
              <option value="">All Churn Bands</option>
              <option value="High">High Churn Risk</option>
              <option value="Medium">Medium Churn Risk</option>
              <option value="Low">Low Churn Risk</option>
            </select>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable columns={custCols} rows={customer_drilldown} defaultSortKey="monetary_value" maxHeight={340} />
        </div>
      </section>
    </>
  );
};
