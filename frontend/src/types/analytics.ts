export interface FilterState {
  start_date: string;
  end_date: string;
  city: string;
  city_tier: string;
  channel: string;
  device: string;
  category_id: string;
  customer_type: string;
}

export interface MetaFilters {
  dataset_start: string;
  dataset_end: string;
  cities: { value: string; tier: string }[];
  city_tiers: string[];
  channels: string[];
  devices: string[];
  categories: { category_id: number; category_name: string; category_group: string }[];
  segments: string[];
  metric_definitions: {
    metric: string;
    formula: string;
    scope: string;
    notes: string;
  }[];
  synthetic_disclaimer: string;
}

export interface BusinessInsight {
  id: string;
  severity: "high" | "medium" | "info";
  domain: string;
  title: string;
  what_happened: string;
  where_it_happened: string;
  magnitude: string;
  comparison_baseline: string;
  possible_explanation: string;
  recommended_action: string;
  evidence_type: string;
}

export interface StatProportionTest {
  test_id: string;
  title: string;
  method: string;
  group_a: { label: string; successes: number; n: number; rate_pct: number };
  group_b: { label: string; successes: number; n: number; rate_pct: number };
  difference_pp: number;
  ci_95_pp: [number, number];
  z_statistic: number;
  p_value: number;
  statistically_significant_95: boolean;
  evidence_type: string;
  causal_caveat: string;
}

export interface SqlCatalogItem {
  id: string;
  category: string;
  title: string;
  business_question: string;
  sql_features: string[];
  sql: string;
  query_explanation: string;
  optimization_notes: string;
  business_conclusion: string;
}

export interface SqlExecuteResult {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  execution_ms: number;
  explain_plan: string[];
}

export interface ReportRun {
  run_id: number;
  report_type: string;
  filename: string;
  start_date: string | null;
  end_date: string | null;
  filters: Record<string, unknown>;
  row_count: number;
  file_size_bytes: number;
  status: string;
  generated_at: string;
}
