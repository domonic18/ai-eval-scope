/**
 * 摄取事件 TS 类型（与 ingest.event.v1.json 一致；供 service/repository 使用）。
 */

/**
 * 运行级指标：场景化后为动态键值（键 = MetricDefinition.id）。
 * courseware 遗留键（DR / CPR / avg_reward / avg_soft / avg_pref / condR / avg_time_ms）
 * 在评估器迁移期仍会发送，repository 经 metric() 回填一等列；新场景用任意 metric_id 作键。
 */
export type RunMetrics = Record<string, number>

export interface DimensionInput {
  dimension_id: string
  name: string
  weight: number
  score: number
  status: string
}

export interface RunEventData {
  external_run_id: string
  mode: string
  status?: string
  created_at?: string
  finished_at?: string | null
  metrics: RunMetrics
  total_samples?: number
  // Phase 3 场景化（对齐 09 §9.5.3）：场景包标识与运行快照
  scenario_id?: string
  package_id?: string
  package_version?: string
  run_config_snapshot_id?: string
  /** Phase 5：inline 运行配置快照内容（含 snapshot_hash）；后端据此建 RunConfigSnapshot 行 */
  run_config_snapshot?: Record<string, unknown>
  rule_set_version?: string
  sut_version?: string
  failure_breakdown?: Record<string, unknown> | null
  summary_report?: Record<string, unknown> | null
  thresholds?: Record<string, unknown> | null
  langfuse_trace_id?: string | null
  langfuse_host?: string | null
}

export interface SampleEventData {
  external_run_id: string
  external_sample_id: string
  content_hash?: string | null
  status?: string
  // Phase 3 场景化样本指标：metrics JSONB 为权威；下列列为遗留（迁移期保留）
  metrics?: Record<string, number>
  s_format?: number
  s_common?: number
  s_soft?: number
  s_pref?: number
  reward?: number
  total_duration_ms?: number
  llm_calls?: number
  token_usage?: number
  dimensions?: DimensionInput[]
}

export interface ConstraintEventData {
  external_run_id: string
  external_sample_id: string
  constraint_id: string
  rule_id?: string
  name: string
  tier: string
  status: string
  passed: boolean
  score: number
  raw_score?: number
  reason: string
  details?: Record<string, unknown>
  duration_ms: number
  judge_provider?: string
  judge_model?: string
  judge_record_object_key?: string
  module_results?: Record<string, unknown>
}

export interface ArtifactEventData {
  external_run_id: string
  external_sample_id?: string
  kind: string
  object_key: string
  content_type: string
  size_bytes: number
  md5?: string
  original_name?: string
  linked_constraint_id?: string
}

export type EventData = RunEventData | SampleEventData | ConstraintEventData | ArtifactEventData

export interface RunEvent {
  event_id: string
  type: "run"
  data: RunEventData
}
export interface SampleEvent {
  event_id: string
  type: "sample"
  data: SampleEventData
}
export interface ConstraintEvent {
  event_id: string
  type: "constraint"
  data: ConstraintEventData
}
export interface ArtifactEvent {
  event_id: string
  type: "artifact"
  data: ArtifactEventData
}

/** 按 type 判别的事件联合：switch(ev.type) 可收窄 ev.data 到对应类型。 */
export type IngestEvent = RunEvent | SampleEvent | ConstraintEvent | ArtifactEvent

export interface IngestBatch {
  schema_version: string
  batch_id?: string
  project_id?: string
  events: IngestEvent[]
}
