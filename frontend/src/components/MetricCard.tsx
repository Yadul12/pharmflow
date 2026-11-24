import React from "react";

interface MetricCardProps {
  label: string;
  value: string;
  subtext?: string;
  delta?: number | null;
  deltaUnit?: "%" | " pp";
  invertDeltaColor?: boolean;
  formula?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  subtext,
  delta,
  deltaUnit = "%",
  invertDeltaColor = false,
  formula,
}) => {
  let deltaEl: React.ReactNode = null;
  if (delta !== null && delta !== undefined && !Number.isNaN(delta)) {
    const isGood = invertDeltaColor ? delta <= 0 : delta >= 0;
    const cls = Math.abs(delta) < 0.05 ? "delta-neutral" : isGood ? "delta-pos" : "delta-neg";
    const sign = delta > 0 ? "+" : "";
    deltaEl = (
      <span className={cls}>
        {sign}
        {delta.toFixed(1)}
        {deltaUnit}
      </span>
    );
  }

  return (
    <div className="kpi-card" title={formula || undefined}>
      <div className="kpi-label">
        <span>{label}</span>
        {formula && (
          <span
            style={{
              fontSize: 10,
              color: "#64748B",
              border: "1px solid #CBD5E1",
              borderRadius: "50%",
              width: 14,
              height: 14,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "help",
              flexShrink: 0,
            }}
            title={`Formula: ${formula}`}
          >
            i
          </span>
        )}
      </div>
      <div className="kpi-value">{value}</div>
      {(subtext || deltaEl) && (
        <div className="kpi-meta">
          <span>{subtext || ""}</span>
          {deltaEl}
        </div>
      )}
    </div>
  );
};
