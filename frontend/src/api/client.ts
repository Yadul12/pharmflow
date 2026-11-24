import type { FilterState } from "../types/analytics";

export function buildQueryParams(
  filters: FilterState,
  extra?: Record<string, string | number | undefined | null>
): string {
  const params = new URLSearchParams();
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
  if (filters.city) params.set("city", filters.city);
  if (filters.city_tier) params.set("city_tier", filters.city_tier);
  if (filters.channel) params.set("channel", filters.channel);
  if (filters.device) params.set("device", filters.device);
  if (filters.category_id) params.set("category_id", filters.category_id);
  if (filters.customer_type) params.set("customer_type", filters.customer_type);

  if (extra) {
    for (const [k, v] of Object.entries(extra)) {
      if (v !== undefined && v !== null && v !== "") {
        params.set(k, String(v));
      }
    }
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      if (err?.detail) detail = String(err.detail);
    } catch {
      // ignore json parse failure
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      if (err?.detail) detail = String(err.detail);
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const fmtInt = (n: number | null | undefined): string =>
  n === null || n === undefined || Number.isNaN(n) ? "—" : Math.round(n).toLocaleString("en-IN");

export const fmtDec = (n: number | null | undefined, digits = 2): string =>
  n === null || n === undefined || Number.isNaN(n)
    ? "—"
    : Number(n).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const fmtPct = (n: number | null | undefined, digits = 1): string =>
  n === null || n === undefined || Number.isNaN(n) ? "—" : `${Number(n).toFixed(digits)}%`;

export const fmtInr = (n: number | null | undefined, compact = false): string => {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const val = Number(n);
  if (compact) {
    if (Math.abs(val) >= 1e7) return `₹${(val / 1e7).toFixed(2)} Cr`;
    if (Math.abs(val) >= 1e5) return `₹${(val / 1e5).toFixed(2)} L`;
  }
  return `₹${Math.round(val).toLocaleString("en-IN")}`;
};

export const fmtBytes = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
};
