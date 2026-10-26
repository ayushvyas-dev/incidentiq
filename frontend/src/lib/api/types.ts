export type Incident = {
  incident_id: string;
  title: string;
  description: string;
  service: string;
  environment: string;
  severity: string;
  status: string;
  latest_run_id: string | null;
  latest_result: Analysis | null;
  created_at: string;
};

export type Evidence = { source: string; document_id: string; chunk_id: string; quote: string };
export type Analysis = {
  incident_id: string;
  status: string;
  summary: string;
  hypotheses: Array<{ rank: number; title: string; confidence: string; reasoning: string; supporting_evidence: Evidence[]; contradictory_evidence: Evidence[]; missing_evidence: string[] }>;
  diagnostic_steps: Array<{ step: number; action: string; reason: string; risk: "read_only" }>;
  citations: Array<{ document_id: string; chunk_id: string; source: string }>;
  limitations: string[];
  quality: { result: "evidence_found" | "insufficient_evidence"; abstained: boolean };
  run?: { run_id: string; provider: string | null; model: string | null; routing_policy: string | null; latency_ms: number | null; input_tokens: number | null; output_tokens: number | null; estimated_cost_usd: number | null; routing_decision: Record<string, unknown> | null };
};
export type AnalysisRun = NonNullable<Analysis["run"]> & { status: string; created_at: string; finished_at: string | null; error_code: string | null };
export type Page<T> = { items: T[]; next_cursor: string | null };
export type Document = { document_id: string; filename: string; source_type: string; service: string | null; environment: string | null; status: string; chunk_count: number; content_sha256: string; error: { code: string } | null; created_at: string; updated_at: string };
export type Job = { job_id: string; job_type: string; status: string; progress: unknown; error: { code: string } | null; created_at: string; finished_at: string | null };
export type Evaluation = { evaluation_run_id: string; experiment_name: string; dataset_id: string; dataset_version: string; split: string; status: string; config_hash: string; created_at: string };
export type Metrics = { window: string; requests: { total: number; success_rate: number; error_rate: number }; latency_ms: { p50: number | null; p95: number | null; p99: number | null }; llm: { input_tokens: number; output_tokens: number; estimated_cost_usd: number; fallback_count: number }; retrieval: { average_candidates: number; reranker_usage_rate: number } };
export type SearchResult = { document_id: string; chunk_id: string; source: string; source_type: string; excerpt: string; score: number; rank: number; service?: string | null; environment?: string | null };
