import React, { useEffect, useState } from "react";
import { Play, Terminal } from "lucide-react";
import { apiGet, apiPost } from "../api/client";
import type { SqlCatalogItem, SqlExecuteResult } from "../types/analytics";

export const SqlLab: React.FC = () => {
  const [catalog, setCatalog] = useState<SqlCatalogItem[]>([]);
  const [activeItem, setActiveItem] = useState<SqlCatalogItem | null>(null);
  const [sqlText, setSqlText] = useState("");
  const [includeExplain, setIncludeExplain] = useState(true);
  const [result, setResult] = useState<SqlExecuteResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"results" | "explanation" | "explain">("results");

  const runQuery = async (sqlToRun: string, explainFlag: boolean) => {
    setRunning(true);
    setError(null);
    try {
      const res = await apiPost<SqlExecuteResult>("/api/sql-lab/execute", {
        sql: sqlToRun,
        limit: 200,
        include_explain: explainFlag,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Query execution failed");
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => {
    apiGet<{ queries: SqlCatalogItem[] }>("/api/sql-lab/catalog")
      .then((res) => {
        setCatalog(res.queries);
        if (res.queries.length > 0) {
          const first = res.queries[0];
          setActiveItem(first);
          setSqlText(first.sql);
          runQuery(first.sql, true);
        }
      })
      .catch((e) => setError(e.message));
  }, []);

  const selectQuery = (item: SqlCatalogItem) => {
    setActiveItem(item);
    setSqlText(item.sql);
    setActiveTab("results");
    runQuery(item.sql, includeExplain);
  };

  return (
    <div className="sql-layout">
      <aside className="panel" style={{ maxHeight: "calc(100vh - 110px)", overflowY: "auto" }}>
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Analytical SQL Library ({catalog.length})</h2>
            <p className="panel-subtitle">CTEs, window functions, LAG/LEAD, cohorts &amp; rankings</p>
          </div>
        </div>
        <div>
          {catalog.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sql-catalog-item ${activeItem?.id === item.id ? "active" : ""}`}
              onClick={() => selectQuery(item)}
            >
              <span style={{ fontSize: 10.5, fontWeight: 600, color: "#1E56A0", textTransform: "uppercase" }}>
                {item.category}
              </span>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: "#111827" }}>{item.title}</span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 2 }}>
                {item.sql_features.map((f) => (
                  <span key={f} className="badge badge-gray" style={{ fontSize: 10 }}>
                    {f}
                  </span>
                ))}
              </div>
            </button>
          ))}
        </div>
      </aside>

      <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
        {activeItem && (
          <div className="callout">
            <div className="callout-title">Business Question — {activeItem.title}</div>
            <div>{activeItem.business_question}</div>
          </div>
        )}

        <section className="panel">
          <div className="panel-header">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Terminal size={14} />
              <h2 className="panel-title">PostgreSQL 16 Read-Only Execution Workbench</h2>
              <span className="badge badge-gray">READ ONLY · 8s timeout</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <label style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11.5, color: "#475569", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={includeExplain}
                  onChange={(e) => setIncludeExplain(e.target.checked)}
                />
                EXPLAIN ANALYZE
              </label>
              <button
                type="button"
                className="btn btn-primary"
                disabled={running}
                onClick={() => runQuery(sqlText, includeExplain)}
              >
                <Play size={12} />
                {running ? "Executing…" : "Run SQL"}
              </button>
            </div>
          </div>
          <div className="panel-body">
            <textarea
              className="sql-editor"
              value={sqlText}
              onChange={(e) => setSqlText(e.target.value)}
              spellCheck={false}
              aria-label="PostgreSQL Query Editor"
            />
            {error && <div className="error-state" style={{ textAlign: "left", padding: "10px 0 0" }}>{error}</div>}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div className="seg-control">
              <button
                type="button"
                className={`seg-btn ${activeTab === "results" ? "active" : ""}`}
                onClick={() => setActiveTab("results")}
              >
                Result Table {result ? `(${result.row_count} rows)` : ""}
              </button>
              <button
                type="button"
                className={`seg-btn ${activeTab === "explanation" ? "active" : ""}`}
                onClick={() => setActiveTab("explanation")}
              >
                Explanation &amp; Business Conclusion
              </button>
              <button
                type="button"
                className={`seg-btn ${activeTab === "explain" ? "active" : ""}`}
                onClick={() => setActiveTab("explain")}
              >
                EXPLAIN ANALYZE Plan
              </button>
            </div>
            {result && (
              <span className="pill-muted mono">
                {result.execution_ms.toFixed(1)} ms · {result.row_count} rows{result.truncated ? " (capped)" : ""}
              </span>
            )}
          </div>

          {activeTab === "results" && (
            <div className="panel-body-flush">
              {running ? (
                <div className="loading-state">Running query directly on PostgreSQL…</div>
              ) : result && result.columns.length > 0 ? (
                <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        {result.columns.map((c) => (
                          <th key={c} className="mono">
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, rIdx) => (
                        <tr key={rIdx}>
                          {result.columns.map((c) => {
                            const val = row[c];
                            const isNum = typeof val === "number";
                            return (
                              <td key={c} className={isNum ? "num mono" : ""}>
                                {val === null || val === undefined
                                  ? "NULL"
                                  : isNum
                                  ? Number.isInteger(val)
                                    ? val.toLocaleString("en-IN")
                                    : val.toLocaleString("en-IN", { maximumFractionDigits: 2 })
                                  : String(val)}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="loading-state">Select a curated analysis or execute a read-only SELECT query.</div>
              )}
            </div>
          )}

          {activeTab === "explanation" && activeItem && (
            <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div>
                <h4 style={{ margin: "0 0 4px", fontSize: 12.5, color: "#0F243D" }}>SQL Query Architecture</h4>
                <p style={{ margin: 0, color: "#334155" }}>{activeItem.query_explanation}</p>
              </div>
              <div>
                <h4 style={{ margin: "0 0 4px", fontSize: 12.5, color: "#0F243D" }}>PostgreSQL Indexing &amp; Optimization Notes</h4>
                <p style={{ margin: 0, color: "#334155" }}>{activeItem.optimization_notes}</p>
              </div>
              <div className="callout">
                <div className="callout-title">Business Conclusion</div>
                <div>{activeItem.business_conclusion}</div>
              </div>
            </div>
          )}

          {activeTab === "explain" && (
            <div className="panel-body">
              {result?.explain_plan && result.explain_plan.length > 0 ? (
                <pre className="explain-box">{result.explain_plan.join("\n")}</pre>
              ) : (
                <div className="loading-state">Enable EXPLAIN ANALYZE and click Run SQL to inspect PostgreSQL index usage and execution buffers.</div>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};
