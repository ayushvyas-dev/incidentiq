"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { ErrorBox, Heading, Loading, Status } from "@/components/ui";

type Detail = { evaluation_run_id: string; experiment_name: string; dataset_id: string; split: string; status: string; config: Record<string, unknown>; metrics: Record<string, unknown>; error: { code: string } | null };
type Cases = { items: Array<{ case_id: string; passed?: boolean; [key: string]: unknown }> };
export default function EvaluationDetailPage() {
  const { evaluationId } = useParams<{ evaluationId: string }>();
  const detail = useQuery({ queryKey: ["evaluation", evaluationId], queryFn: () => api<Detail>(`api/v1/evaluations/${evaluationId}`), enabled: Boolean(evaluationId), refetchInterval: q => ["queued", "processing"].includes(q.state.data?.status || "") ? 3000 : false });
  const cases = useQuery({ queryKey: ["evaluation-cases", evaluationId], queryFn: () => api<Cases>(`api/v1/evaluations/${evaluationId}/cases`), enabled: Boolean(evaluationId) });
  const metrics = detail.data?.metrics || {};
  const entries = Object.entries(metrics);
  return <>
    <Heading title={detail.data?.experiment_name || "Evaluation run"} description={detail.data ? `${detail.data.dataset_id} · ${detail.data.split}` : "Evaluation results and case outcomes."}/>
    {detail.isLoading ? <Loading/> : detail.isError ? <ErrorBox message={detail.error.message} retry={() => void detail.refetch()}/> : detail.data && <>
      <div className="mb-5 flex items-center gap-2"><Status value={detail.data.status}/>{detail.data.error && <span className="text-xs text-[var(--red)]">{detail.data.error.code}</span>}</div>
      <div className="grid gap-6 xl:grid-cols-2">
        <section><h2 className="mb-2 border-b border-[var(--line)] pb-3 text-[13px] font-semibold">Results</h2>{entries.length ? <dl className="divide-y divide-[var(--line)]">{entries.map(([key,value]) => <div key={key} className="flex items-start justify-between gap-4 py-2.5 text-xs"><dt className="capitalize text-[var(--muted)]">{key.replaceAll("_", " ")}</dt><dd className="text-right font-mono tabular-nums">{typeof value === "number" || typeof value === "string" ? value : JSON.stringify(value)}</dd></div>)}</dl> : <p className="py-3 text-xs text-[var(--muted)]">No evaluation metrics returned yet.</p>}<details className="mt-3 text-[11px] text-[var(--muted)]"><summary>Raw metrics</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap">{JSON.stringify(metrics, null, 2)}</pre></details></section>
        <details><summary className="border-b border-[var(--line)] pb-3 text-[13px] font-semibold">Run configuration</summary><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap text-[10px] leading-5 text-[var(--muted)]">{JSON.stringify(detail.data.config, null, 2)}</pre></details>
      </div>
    </>}
    <section className="mt-6"><h2 className="mb-2 border-b border-[var(--line)] pb-3 text-[13px] font-semibold">Case results</h2>{cases.isLoading ? <Loading/> : cases.isError ? <ErrorBox message={cases.error.message} retry={() => void cases.refetch()}/> : cases.data?.items.length ? <div className="divide-y divide-[var(--line)]">{cases.data.items.map(item => <details key={item.case_id} className="py-3"><summary className="flex list-none items-center justify-between gap-3 text-xs"><span className="font-mono">{item.case_id}</span>{typeof item.passed === "boolean" && <Status value={item.passed ? "passed" : "failed"}/>}</summary><pre className="mt-3 overflow-auto whitespace-pre-wrap rounded bg-[var(--soft)] p-3 text-[10px] text-[var(--muted)]">{JSON.stringify(item, null, 2)}</pre></details>)}</div> : <p className="py-3 text-xs text-[var(--muted)]">No case results returned.</p>}</section>
  </>;
}
