import React, { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Activity,
  BarChart3,
  BookOpen,
  Database,
  FileSpreadsheet,
  Filter,
  GitBranch,
  Layers,
  Package,
  RefreshCw,
  RotateCcw,
  Users,
  X,
  XCircle,
} from "lucide-react";
import { DEFAULT_FILTERS, useFilters } from "../context/FilterContext";

const NAV_GROUPS = [
  {
    label: "Executive",
    items: [{ path: "/", label: "Executive Overview", icon: BarChart3 }],
  },
  {
    label: "Acquisition & Funnel",
    items: [{ path: "/funnel", label: "Customer Funnel", icon: Filter }],
  },
  {
    label: "Retention & Lifecycle",
    items: [
      { path: "/retention", label: "Customer Retention", icon: Activity },
      { path: "/cohorts", label: "Cohort Analytics", icon: Layers },
      { path: "/segmentation", label: "Customer Segmentation", icon: Users },
    ],
  },
  {
    label: "Commercial & Operations",
    items: [
      { path: "/subscriptions", label: "Subscription Performance", icon: RefreshCw },
      { path: "/categories", label: "Product Categories", icon: Package },
      { path: "/cancellations", label: "Cancellations & Refunds", icon: XCircle },
    ],
  },
  {
    label: "Analyst Workbench",
    items: [
      { path: "/sql-lab", label: "SQL Lab", icon: Database },
      { path: "/reports", label: "Reports & Exports", icon: FileSpreadsheet },
    ],
  },
];

const PAGE_META: Record<string, { title: string; subtitle: string; showFilters: boolean }> = {
  "/": {
    title: "Executive Overview",
    subtitle: "Commercial performance, funnel conversion, retention trajectory & automated insight engine",
    showFilters: true,
  },
  "/funnel": {
    title: "Customer & Order Funnel",
    subtitle: "7-stage interactive session conversion, stage drop-off diagnostics & order reconciliation",
    showFilters: true,
  },
  "/retention": {
    title: "Customer Retention",
    subtitle: "D1/D7/D30/D90 retention, repeat purchase velocity, inactivity & win-back reactivation",
    showFilters: true,
  },
  "/cohorts": {
    title: "Cohort Analytics",
    subtitle: "Monthly acquisition cohort retention matrix, cumulative LTV & channel-mix quality shift",
    showFilters: true,
  },
  "/segmentation": {
    title: "Customer Segmentation",
    subtitle: "RFM business segments, K-Means PCA clustering & time-aware churn risk evaluation",
    showFilters: true,
  },
  "/subscriptions": {
    title: "Subscription Performance",
    subtitle: "Recurring refill renewal rates, cadence adherence & subscriber retention comparison",
    showFilters: true,
  },
  "/categories": {
    title: "Product Category Analytics",
    subtitle: "Category repeat rates, seasonal demand shifts, top SKUs & cross-category basket affinity",
    showFilters: true,
  },
  "/cancellations": {
    title: "Cancellation & Refund Analysis",
    subtitle: "Operational cancellation drivers, refund leakage, payment friction & regional SLA breaches",
    showFilters: true,
  },
  "/sql-lab": {
    title: "PostgreSQL Analytical SQL Lab",
    subtitle: "12 curated commercial SQL studies & read-only PostgreSQL query execution with EXPLAIN plans",
    showFilters: false,
  },
  "/reports": {
    title: "Reports & Data Exports",
    subtitle: "8-worksheet formatted Excel workbooks, filtered CSV record exports & run audit history",
    showFilters: true,
  },
};

const DATE_PRESETS = [
  { label: "Full 14M", start: "2025-09-01", end: "2026-10-31" },
  { label: "Last 6M", start: "2026-05-01", end: "2026-10-31" },
  { label: "Q2 Surge", start: "2026-04-01", end: "2026-06-30" },
  { label: "Monsoon", start: "2026-07-01", end: "2026-08-31" },
];

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  const { filters, setFilter, setFilters, resetFilters, meta, activeFilterCount } = useFilters();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const current = PAGE_META[location.pathname] || PAGE_META["/"];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-brand-title">
            <span className="brand-mark">PF</span>
            PHARMFLOW
          </div>
          <div className="sidebar-brand-sub">Customer &amp; Order Analytics</div>
        </div>

        <nav className="sidebar-nav" aria-label="Primary Navigation">
          {NAV_GROUPS.map((grp) => (
            <div key={grp.label}>
              <div className="nav-section-label">{grp.label}</div>
              {grp.items.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    end={item.path === "/"}
                    className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                  >
                    <Icon size={14} strokeWidth={1.8} />
                    <span>{item.label}</span>
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div>
            <strong>Synthetic Dataset</strong> · Seed 42
          </div>
          <div>Sep 2025 – Oct 2026 (14M)</div>
          <div>PostgreSQL 16 · Non-PHI Commercial Data</div>
        </div>
      </aside>

      <div className="main-content">
        <header className="topbar">
          <div className="topbar-title-wrap">
            <h1 className="topbar-title">{current.title}</h1>
            <span className="topbar-subtitle">{current.subtitle}</span>
          </div>
          <div className="topbar-actions">
            <span className="pill-muted">
              <GitBranch size={12} />
              Sep 2025 – Oct 2026 · Synthetic
            </span>
            <button className="btn btn-sm" onClick={() => setDrawerOpen(true)}>
              <BookOpen size={13} />
              Metric Definitions
            </button>
          </div>
        </header>

        {current.showFilters && (
          <section className="filter-bar" aria-label="Analytical Filters">
            <div className="filter-group">
              <span className="filter-label">Period</span>
              <input
                type="date"
                className="filter-input"
                aria-label="Start Date"
                min={meta?.dataset_start || DEFAULT_FILTERS.start_date}
                max={filters.end_date}
                value={filters.start_date}
                onChange={(e) => setFilter("start_date", e.target.value)}
              />
              <span style={{ color: "#94A3B8" }}>–</span>
              <input
                type="date"
                className="filter-input"
                aria-label="End Date"
                min={filters.start_date}
                max={meta?.dataset_end || DEFAULT_FILTERS.end_date}
                value={filters.end_date}
                onChange={(e) => setFilter("end_date", e.target.value)}
              />
            </div>

            <div className="seg-control" aria-label="Date Presets">
              {DATE_PRESETS.map((p) => {
                const active = filters.start_date === p.start && filters.end_date === p.end;
                return (
                  <button
                    key={p.label}
                    type="button"
                    className={`seg-btn ${active ? "active" : ""}`}
                    onClick={() => setFilters((prev) => ({ ...prev, start_date: p.start, end_date: p.end }))}
                  >
                    {p.label}
                  </button>
                );
              })}
            </div>

            <div className="filter-group">
              <select
                className="filter-select"
                aria-label="City Filter"
                value={filters.city}
                onChange={(e) => setFilter("city", e.target.value)}
              >
                <option value="">All Cities</option>
                {(meta?.cities || []).map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.value} ({c.tier})
                  </option>
                ))}
              </select>

              <select
                className="filter-select"
                aria-label="Channel Filter"
                value={filters.channel}
                onChange={(e) => setFilter("channel", e.target.value)}
              >
                <option value="">All Channels</option>
                {(meta?.channels || []).map((ch) => (
                  <option key={ch} value={ch}>
                    {ch}
                  </option>
                ))}
              </select>

              <select
                className="filter-select"
                aria-label="Device Filter"
                value={filters.device}
                onChange={(e) => setFilter("device", e.target.value)}
              >
                <option value="">All Devices</option>
                {(meta?.devices || []).map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>

              <select
                className="filter-select"
                aria-label="Category Filter"
                value={filters.category_id}
                onChange={(e) => setFilter("category_id", e.target.value)}
              >
                <option value="">All Categories</option>
                {(meta?.categories || []).map((cat) => (
                  <option key={cat.category_id} value={String(cat.category_id)}>
                    {cat.category_name}
                  </option>
                ))}
              </select>

              <select
                className="filter-select"
                aria-label="Customer Type Filter"
                value={filters.customer_type}
                onChange={(e) => setFilter("customer_type", e.target.value)}
              >
                <option value="">New &amp; Repeat</option>
                <option value="new">New Customers</option>
                <option value="repeat">Repeat Customers</option>
              </select>
            </div>

            {activeFilterCount > 0 && (
              <button type="button" className="btn btn-sm" onClick={resetFilters}>
                <RotateCcw size={12} />
                Reset ({activeFilterCount})
              </button>
            )}
          </section>
        )}

        <main className="page-body">{children}</main>
      </div>

      {drawerOpen && (
        <div className="drawer-backdrop" onClick={() => setDrawerOpen(false)}>
          <div className="drawer-panel" onClick={(e) => e.stopPropagation()}>
            <div className="panel-header">
              <div>
                <h3 className="panel-title">Metric Definitions &amp; Denominator Governance</h3>
                <p className="panel-subtitle">Exact formulas enforced across SQL, Python, UI, and Excel workbooks</p>
              </div>
              <button className="btn btn-sm" onClick={() => setDrawerOpen(false)}>
                <X size={13} /> Close
              </button>
            </div>
            <div className="panel-body" style={{ overflowY: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
              <div className="callout">
                <div className="callout-title">Synthetic Data Disclaimer</div>
                <div>{meta?.synthetic_disclaimer || "100% synthetic healthcare e-commerce dataset."}</div>
              </div>
              {(meta?.metric_definitions || []).map((m) => (
                <div key={m.metric} style={{ borderBottom: "1px solid #E2E8F0", paddingBottom: 9 }}>
                  <div style={{ fontWeight: 600, color: "#0F243D", marginBottom: 2 }}>{m.metric}</div>
                  <div className="mono" style={{ fontSize: 11.5, background: "#F8FAFC", padding: "4px 6px", borderRadius: 3, border: "1px solid #E2E8F0" }}>
                    {m.formula}
                  </div>
                  <div style={{ fontSize: 11.5, color: "#475569", marginTop: 4 }}>
                    <strong>Scope:</strong> {m.scope}
                  </div>
                  <div style={{ fontSize: 11.5, color: "#64748B", marginTop: 2 }}>{m.notes}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
