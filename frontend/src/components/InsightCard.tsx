import React from "react";
import type { BusinessInsight, StatProportionTest } from "../types/analytics";
import { fmtInt } from "../api/client";

export const InsightCard: React.FC<{ insight: BusinessInsight }> = ({ insight }) => {
  const sevCls = insight.severity === "high" ? "sev-high" : insight.severity === "medium" ? "sev-medium" : "";
  const badgeCls =
    insight.severity === "high" ? "badge-red" : insight.severity === "medium" ? "badge-amber" : "badge-blue";

  return (
    <div className={`insight-card ${sevCls}`}>
      <div className="insight-header">
        <div>
          <span className={`badge ${badgeCls}`} style={{ marginBottom: 4 }}>
            {insight.domain}
          </span>
          <h4 className="insight-title">{insight.title}</h4>
        </div>
      </div>
      <dl className="insight-dl">
        <dt>What Happened</dt>
        <dd>{insight.what_happened}</dd>
        <dt>Where</dt>
        <dd>{insight.where_it_happened}</dd>
        <dt>Magnitude</dt>
        <dd style={{ fontWeight: 600 }}>{insight.magnitude}</dd>
        <dt>Baseline</dt>
        <dd>{insight.comparison_baseline}</dd>
        <dt>Explanation</dt>
        <dd>{insight.possible_explanation}</dd>
        <dt>Action</dt>
        <dd style={{ color: "#0F243D", fontWeight: 500 }}>{insight.recommended_action}</dd>
        <dt>Evidence</dt>
        <dd>
          <span className="badge badge-gray">{insight.evidence_type}</span>
        </dd>
      </dl>
    </div>
  );
};

export const StatTestCard: React.FC<{ test: StatProportionTest }> = ({ test }) => {
  return (
    <div className="callout callout-amber">
      <div className="callout-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 6 }}>
        <span>Statistical Validation — {test.title}</span>
        <span className="badge badge-blue">
          {test.method} · z = {test.z_statistic} · p = {test.p_value}
        </span>
      </div>
      <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: "6px 18px", color: "#111827" }}>
        <span>
          <strong>{test.group_a.label}:</strong> {test.group_a.rate_pct.toFixed(2)}% ({fmtInt(test.group_a.successes)} / {fmtInt(test.group_a.n)})
        </span>
        <span>
          <strong>{test.group_b.label}:</strong> {test.group_b.rate_pct.toFixed(2)}% ({fmtInt(test.group_b.successes)} / {fmtInt(test.group_b.n)})
        </span>
        <span>
          <strong>Difference:</strong> {test.difference_pp > 0 ? "+" : ""}
          {test.difference_pp.toFixed(2)} pp (95% CI: [{test.ci_95_pp[0].toFixed(2)}, {test.ci_95_pp[1].toFixed(2)}] pp)
        </span>
      </div>
      <div style={{ marginTop: 5, fontSize: 11.5, color: "#475569" }}>
        <strong>Correlation vs Causation:</strong> {test.causal_caveat}
      </div>
    </div>
  );
};
