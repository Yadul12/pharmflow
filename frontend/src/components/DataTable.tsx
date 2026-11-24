import React, { useMemo, useState } from "react";

export interface ColumnDef<T> {
  key: keyof T | string;
  header: string;
  align?: "left" | "right";
  render?: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number;
}

interface DataTableProps<T> {
  columns: ColumnDef<T>[];
  rows: T[];
  defaultSortKey?: string;
  defaultSortDir?: "asc" | "desc";
  emptyMessage?: string;
  maxHeight?: number;
}

export function DataTable<T extends object>({
  columns,
  rows,
  defaultSortKey,
  defaultSortDir = "desc",
  emptyMessage = "No matching records for active filters.",
  maxHeight,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | undefined>(defaultSortKey);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(defaultSortDir);

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => String(c.key) === sortKey);
    return [...rows].sort((a, b) => {
      const av = col?.sortValue
        ? col.sortValue(a)
        : ((a as Record<string, unknown>)[sortKey] as string | number | null | undefined);
      const bv = col?.sortValue
        ? col.sortValue(b)
        : ((b as Record<string, unknown>)[sortKey] as string | number | null | undefined);
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      return sortDir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
  }, [rows, columns, sortKey, sortDir]);

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  return (
    <div className="table-wrap" style={maxHeight ? { maxHeight, overflowY: "auto" } : undefined}>
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col) => {
              const k = String(col.key);
              const isSorted = sortKey === k;
              return (
                <th
                  key={k}
                  className={`sortable ${col.align === "right" ? "num" : ""}`}
                  onClick={() => toggleSort(k)}
                >
                  {col.header}
                  {isSorted ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} style={{ textAlign: "center", padding: "18px", color: "#64748B" }}>
                {emptyMessage}
              </td>
            </tr>
          ) : (
            sortedRows.map((row, idx) => (
              <tr key={idx}>
                {columns.map((col) => {
                  const k = String(col.key);
                  return (
                    <td key={k} className={col.align === "right" ? "num" : ""}>
                      {col.render ? col.render(row) : String((row as Record<string, unknown>)[k] ?? "—")}
                    </td>
                  );
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
