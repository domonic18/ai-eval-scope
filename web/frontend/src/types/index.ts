export interface Project {
  id: string;
  name: string;
  description: string;
  default_rule_set: string;
  default_task_set: string;
  created_at: string;
  latest_run_id: string | null;
  run_count: number;
  latest_run?: LatestRun | null;
}

export interface LatestRun {
  run_id: string;
  created_at: string;
  dr: number;
  cpr: number;
  avg_reward: number;
}

export interface RunSummary {
  run_id: string;
  project_id?: string;
  created_at?: string;
  total_samples: number;
  metrics: Metrics;
  thresholds?: Record<string, ThresholdStatus>;
  failure_breakdown?: Record<string, number>;
  sample_scores?: SampleScore[];
}

export interface Metrics {
  DR: number;
  CPR: number;
  avg_reward: number;
  condR: number;
  avg_time_ms: number;
}

export interface ThresholdStatus {
  value: number;
  target: number;
  status: "PASS" | "BELOW";
}

export interface SampleScore {
  sample_id: string;
  s_format: number;
  s_common: number;
  s_soft: number;
  s_pref: number;
  reward: number;
}

export interface RunIndexEntry {
  run_id: string;
  mode: string;
  total_samples: number;
  metrics: Metrics;
  failure_breakdown: Record<string, number>;
  created_at: string;
  project: string | null;
}

export interface TrendData {
  project_id: string;
  metrics: string[];
  data_points: TrendDataPoint[];
  thresholds: Record<string, number>;
}

export interface TrendDataPoint {
  run_id: string;
  created_at: string;
  DR: number;
  CPR: number;
  Reward: number;
}

export interface TaskDetail {
  run_id: string;
  task_id: string;
  rule_results: RuleResult[];
  scores: ScoreSummary;
  report: Record<string, unknown>;
  evidence_files: string[];
}

export interface RuleResult {
  rule_id: string;
  constraint_id: string;
  name: string;
  tier: string;
  passed: boolean;
  score: number;
  reason: string;
  details?: Record<string, unknown>;
  duration_ms: number;
  judge_provider?: string | null;
  judge_model?: string | null;
  judge_record_path?: string | null;
  module_results?: Record<string, unknown>;
}

export interface ScoreSummary {
  s_format: number;
  s_common: number;
  s_soft: number;
  s_pref: number;
  reward: number;
  dimensions?: Record<string, number>;
}

export interface DirectoryManifest {
  mode: string;
  root_dir: string;
  total_files: number;
  file_types: Record<string, number>;
  hierarchy_depth: number;
  modules: DirectoryModule[];
}

export interface DirectoryModule {
  name: string;
  path: string;
  file_count: number;
  children: Array<{ name: string; path: string; depth: number; size: number }>;
}
