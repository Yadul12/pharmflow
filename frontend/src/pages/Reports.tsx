import React, { useEffect, useState } from "react";
import { Download, FileSpreadsheet, FileText } from "lucide-react";
import { apiGet, apiPost, fmtBytes, fmtInt } from "../api/client";
import { DataTable, type ColumnDef } from "../components/DataTable";
import { useFilters } from "../context/FilterContext";
import type { ReportRun } from "../types/analytics";

const WORKBOOK_SHEETS = [
  { idx: 1, name: "Executive Summary", contents: "Report metadata, date scope, headline KPIs with formulas & data-driven business insights" },
  { idx: 2, name: "Customer Funnel", contents: "7-stage funnel, drop-off audit, denominator formulas, device & channel breakdowns" },
  { idx: 3, name: "Customer Retention", contents: "D1/D7/D30/D60/D90 retention, eligible denominators, monthly new vs returning & reactivation" },
  { idx: 4, name: "Cohort Analysis", contents: "14-month triangular retention matrix (M0–M12) with conditional shading" },
  { idx: 5, name: "Product Category Performance", contents: "10-category revenue, margin, AOV, repeat rate, reorder gap, subscription & return scorecard" },
  { idx: 6, name: "Subscription Analytics", contents: "Active MRR, renewal rates, subscriber vs non-subscriber comparison & category summary" },
  { idx: 7, name: "Customer Segments", contents: "RFM business segments economics & K-Means behavioral cluster profiles" },
  { idx: 8, name: "Cancellation Analysis", contents: "Cancellation Pareto, refund breakdown & geographic delivery SLA breach table" },
];

export const Reports: React.FC = () => {
  const { filters, meta } = useFilters();
  const [runs, setRuns] = useState<ReportRun[]>([]);
  const [segmentFilter, setSegmentFilter] = useState("");
  const [busyType, setBusyType] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = () => {
    apiGet<{ runs: ReportRun[] }>("/api/reports/runs?limit=40")
      .then((res) => setRuns(res.runs))
      .catch(() => {
        // ignore
      });
  };

  useEffect(() => {
    loadRuns();
  }, []);

  const payloadFromFilters = (entity?: "orders" | "customers") => ({
    start_date: filters.start_date,
    end_date: filters.end_date,
    city: filters.city || null,
    city_tier: filters.city_tier || null,
    channel: filters.channel || null,
    device: filters.device || null,
    category_id: filters.category_id ? Number(filters.category_id) : null,
    customer_type: filters.customer_type || null,
    segment: segmentFilter || null,
    entity: entity || "orders",
  });

  const triggerExcel = async () => {
    setBusyType("excel");
    setError(null);
    setStatusMsg(null);
    try {
      const res = await apiPost<{ run: ReportRun; download_url: string }>("/api/reports/excel", payloadFromFilters());
      setStatusMsg(`Generated 8-worksheet workbook: ${res.run.filename} (${fmtBytes(res.run.file_size_bytes)})`);
      loadRuns();
      window.location.assign(res.download_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Excel generation failed");
    } finally {
      setBusyType(null);
    }
  };

  const triggerCsv = async (entity: "orders" | "customers") => {
    setBusyType(entity);
    setError(null);
    setStatusMsg(null);
    try {
      const res = await apiPost<{ run: ReportRun; download_url: string }>("/api/reports/csv", payloadFromFilters(entity));
      setStatusMsg(`Exported ${fmtInt(res.run.row_count)} ${entity} records: ${res.run.filename}`);
      loadRuns();
      window.location.assign(res.download_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "CSV export failed");
    } finally {
      setBusyType(null);
    }
  };

  const runCols: ColumnDef<ReportRun>[] = [
    { key: "run_id", header: "Run #", align: "right", render: (r) => <span className="mono">#{r.run_id}</span> },
    {
      key: "report_type",
      header: "Format",
      render: (r) => (
        <span className={`badge ${r.report_type === "excel_workbook" ? "badge-green" : "badge-blue"}`}>
          {r.report_type === "excel_workbook" ? "Excel (8 Tabs)" : r.report_type === "customers_csv" ? "Customers CSV" : "Orders CSV"}
        </span>
      ),
    },
    { key: "filename", header: "Filename", render: (r) => <span className="mono" style={{ fontSize: 11.5 }}>{r.filename}</span> },
    {
      key: "start_date",
      header: "Period",
      render: (r) => `${r.start_date || "—"} → ${r.end_date || "—"}`,
    },
    { key: "row_count", header: "Rows", align: "right", render: (r) => fmtInt(r.row_count) },
    { key: "file_size_bytes", header: "Size", align: "right", render: (r) => fmtBytes(r.file_size_bytes) },
    {
      key: "generated_at",
      header: "Generated (UTC)",
      render: (r) => new Date(r.generated_at).toISOString().replace("T", " ").slice(0, 19),
    },
    {
      key: "download",
      header: "Action",
      align: "right",
      render: (r) => (
        <a className="btn btn-sm" href={`/api/reports/download/${r.run_id}`} style={{ textDecoration: "none" }}>
          <Download size={12} /> Download
        </a>
      ),
    },
  ];

  return (
    <>
      <div className="callout">
        <div className="callout-title">Active Report Scope (Driven by Top Filter Bar)</div>
        <div>
          Period: <strong>{filters.start_date}</strong> to <strong>{filters.end_date}</strong> · City:{" "}
          <strong>{filters.city || "All"}</strong> · Channel: <strong>{filters.channel || "All"}</strong> · Device:{" "}
          <strong>{filters.device || "All"}</strong> · Customer Type: <strong>{filters.customer_type || "New & Repeat"}</strong>.
          Every workbook embeds exact timestamps, active filter metadata, metric denominators, and the synthetic data notice.
        </div>
      </div>

      {statusMsg && (
        <div className="callout" style={{ borderLeftColor: "#166534", background: "#F0FDF4", color: "#166534" }}>
          {statusMsg}
        </div>
      )}
      {error && <div className="error-state">{error}</div>}

      <div className="grid-2">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Executive Multi-Sheet Excel Report (.xlsx)</h2>
              <p className="panel-subtitle">Styled openpyxl workbook with 8 analytical worksheets</p>
            </div>
          </div>
          <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <button
              type="button"
              className="btn btn-primary"
              style={{ justifyContent: "center", height: 34 }}
              disabled={busyType !== null}
              onClick={triggerExcel}
            >
              <FileSpreadsheet size={15} />
              {busyType === "excel" ? "Building 8-Worksheet Excel Workbook…" : "Generate & Download Excel Report"}
            </button>
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Worksheet Name</th>
                  <th>Included Tables</th>
                </tr>
              </thead>
              <tbody>
                {WORKBOOK_SHEETS.map((s) => (
                  <tr key={s.idx}>
                    <td className="num">{s.idx}</td>
                    <td><strong>{s.name}</strong></td>
                    <td style={{ color: "#475569", fontSize: 11.5 }}>{s.contents}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Filtered Record-Level CSV Exports</h2>
              <p className="panel-subtitle">Extract granular synthetic customer or order records for downstream modeling</p>
            </div>
          </div>
          <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="callout">
              <div className="callout-title">Export Scope &amp; Governance</div>
              <div>
                Exports apply your currently selected date window, city, acquisition channel, device type, and category filters.
                Up to 15,000 non-identifying synthetic records are streamed per export and archived in PostgreSQL `report_runs`.
              </div>
            </div>
            <div className="filter-group">
              <span className="filter-label">RFM Segment (Customers CSV)</span>
              <select
                className="filter-select"
                value={segmentFilter}
                onChange={(e) => setSegmentFilter(e.target.value)}
              >
                <option value="">All Segments</option>
                {(meta?.segments || []).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                className="btn"
                disabled={busyType !== null}
                onClick={() => triggerCsv("orders")}
              >
                <FileText size={13} />
                {busyType === "orders" ? "Exporting Orders…" : "Export Filtered Orders CSV"}
              </button>
              <button
                type="button"
                className="btn"
                disabled={busyType !== null}
                onClick={() => triggerCsv("customers")}
              >
                <FileText size={13} />
                {busyType === "customers" ? "Exporting Customers…" : "Export Filtered Customers CSV"}
              </button>
            </div>
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Reporting Run Audit History ({runs.length})</h2>
            <p className="panel-subtitle">Persisted in PostgreSQL `report_runs` · Re-download any previous Excel or CSV run</p>
          </div>
        </div>
        <div className="panel-body-flush">
          <DataTable
            columns={runCols}
            rows={runs}
            defaultSortKey="run_id"
            emptyMessage="No reports generated yet. Use the controls above to build an Excel workbook or CSV export."
          />
        </div>
      </section>
    </>
  );
};
