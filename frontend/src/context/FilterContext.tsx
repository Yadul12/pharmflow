import React, { createContext, useContext, useEffect, useState } from "react";
import { apiGet } from "../api/client";
import type { FilterState, MetaFilters } from "../types/analytics";

export const DEFAULT_FILTERS: FilterState = {
  start_date: "2025-09-01",
  end_date: "2026-10-31",
  city: "",
  city_tier: "",
  channel: "",
  device: "",
  category_id: "",
  customer_type: "",
};

interface FilterContextValue {
  filters: FilterState;
  setFilter: <K extends keyof FilterState>(key: K, value: FilterState[K]) => void;
  setFilters: React.Dispatch<React.SetStateAction<FilterState>>;
  resetFilters: () => void;
  meta: MetaFilters | null;
  activeFilterCount: number;
}

const FilterContext = createContext<FilterContextValue | null>(null);

export const FilterProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [meta, setMeta] = useState<MetaFilters | null>(null);

  useEffect(() => {
    apiGet<MetaFilters>("/api/meta/filters")
      .then((res) => setMeta(res))
      .catch(() => {
        // handled gracefully by pages
      });
  }, []);

  const setFilter = <K extends keyof FilterState>(key: K, value: FilterState[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const resetFilters = () => setFilters(DEFAULT_FILTERS);

  const activeFilterCount =
    (filters.start_date !== DEFAULT_FILTERS.start_date || filters.end_date !== DEFAULT_FILTERS.end_date ? 1 : 0) +
    (filters.city ? 1 : 0) +
    (filters.city_tier ? 1 : 0) +
    (filters.channel ? 1 : 0) +
    (filters.device ? 1 : 0) +
    (filters.category_id ? 1 : 0) +
    (filters.customer_type ? 1 : 0);

  return (
    <FilterContext.Provider value={{ filters, setFilter, setFilters, resetFilters, meta, activeFilterCount }}>
      {children}
    </FilterContext.Provider>
  );
};

export function useFilters(): FilterContextValue {
  const ctx = useContext(FilterContext);
  if (!ctx) throw new Error("useFilters must be used inside FilterProvider");
  return ctx;
}
