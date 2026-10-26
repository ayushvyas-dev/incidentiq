"""Execute a labeled evaluation set and persist resumable case results."""

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from incidentiq.api.incidents import AnalysisDraft
from incidentiq.models import EvaluationCaseResult, EvaluationRun, Job
from incidentiq.services.analysis import analysis_messages
from incidentiq.services.evaluation import (
    aggregate_metrics,
    compare_baseline,
    load_dataset,
    retrieval_metrics,
)
from incidentiq.services.retrieval import search_chunks
from incidentiq.services.routing import RoutingError


def run_evaluation_job(
    session_factory: sessionmaker,
    evaluation_run_id: UUID,
    job_id: UUID,
    *,
    dataset_dir: Path,
    embedding_provider,
    vector_store,
    chat_gateway,
    namespace: str,
    dimension: int,
) -> dict | None:
    with session_factory() as session:
        run = session.get(EvaluationRun, evaluation_run_id)
        job = session.get(Job, job_id)
        if run is None or job is None:
            return None
        if run.status == "completed":
            job.status = "completed"
            job.progress = {**(job.progress or {}), "stage": "completed"}
            job.finished_at = job.finished_at or run.finished_at or datetime.now(UTC)
            session.commit()
            return {"status": "completed"}
        config = run.config
        split = config["split"]
        dataset = load_dataset(dataset_dir, run.dataset_id, split)
        run.status = "processing"
        job.status = "processing"
        job.progress = {"stage": "evaluating", "completed_cases": 0, "total_cases": len(dataset["cases"])}
        session.commit()

        case_rows = []
        for case in dataset["cases"]:
            prior = session.scalar(select(EvaluationCaseResult).where(
                EvaluationCaseResult.evaluation_run_id == run.id,
                EvaluationCaseResult.case_id == case["case_id"],
            ))
            if prior is not None:
                case_rows.append(prior.result)
                continue

            started = perf_counter()
            failure_categories = []
            retrieved = []
            answer = None
            provider = model = None
            input_tokens = output_tokens = None
            routing_decision = None
            cost = None
            schema_valid = False
            cited_total = cited_supported = 0
            incident = case["incident"]
            query = " ".join((incident["title"], incident["description"]))
            try:
                retrieved, _ = search_chunks(
                    session,
                    query,
                    top_k=config["top_k"],
                    mode=config["retrieval_mode"],
                    filters={"service": incident["service"], "environment": incident["environment"]},
                    embedding_provider=embedding_provider,
                    vector_store=vector_store,
                    namespace=namespace,
                    dimension=dimension,
                )
            except Exception:  # noqa: BLE001 — preserve per-case retrieval failure metrics.
                failure_categories.append("retrieval_error")

            if retrieved:
                evidence = [
                    {key: row[key] for key in ("document_id", "chunk_id", "source", "source_type", "excerpt")}
                    for row in retrieved
                ]
                if not chat_gateway.providers:
                    failure_categories.append("provider_unavailable")
                else:
                    try:
                        generated = chat_gateway.generate(
                            analysis_messages(incident, evidence),
                            config["max_output_tokens"],
                            policy=config["routing_policy"],
                            input_tokens_estimate=max(1, len(query) // 4),
                            permitted_providers=(
                                set(config["permitted_providers"])
                                if config["permitted_providers"] is not None else None
                            ),
                        )
                        cost = generated.estimated_cost_usd
                        provider, model = generated.provider, generated.model
                        input_tokens, output_tokens = generated.input_tokens, generated.output_tokens
                        routing_decision = generated.decision
                    except RoutingError as error:
                        routing_decision = error.decision
                        failure_categories.append("provider_failure")
                    except Exception:  # noqa: BLE001 — preserve per-case provider failure metrics.
                        failure_categories.append("invalid_or_failed_answer")
                    if routing_decision is not None and not failure_categories:
                        try:
                            answer = AnalysisDraft.model_validate_json(generated.content)
                            schema_valid = True
                            by_chunk = {item["chunk_id"]: item for item in retrieved}
                            refs = [
                                ref for hypothesis in answer.hypotheses
                                for ref in hypothesis.supporting_evidence + hypothesis.contradictory_evidence
                            ]
                            cited_total = len(refs)
                            cited_supported = sum(
                                ref.chunk_id in by_chunk
                                and by_chunk[ref.chunk_id]["document_id"] == ref.document_id
                                and ref.quote.casefold() in by_chunk[ref.chunk_id]["excerpt"].casefold()
                                for ref in refs
                            )
                            if cited_supported != cited_total:
                                failure_categories.append("unsupported_citation")
                        except Exception:  # noqa: BLE001 — classify malformed answers as schema-invalid.
                            failure_categories.append("schema_invalid")
            else:
                schema_valid = True
                answer = None
                cost = 0.0

            retrieved_sources = [item["source"] for item in retrieved]
            relevant = case["expected_relevant_sources"]
            retrieval = retrieval_metrics(relevant, retrieved_sources, config["top_k"])
            abstained = answer is None or answer.quality_result == "insufficient_evidence"
            abstention_correct = float(abstained == case["should_abstain"])
            answer_text = ""
            if answer is not None:
                answer_text = " ".join(
                    [answer.summary]
                    + [hypothesis.title + " " + hypothesis.rationale for hypothesis in answer.hypotheses]
                ).casefold()
            expected_facts = case["expected_facts"]
            # shortcut: exact matching misses paraphrases; upgrade after an LLM judge is human-validated.
            correctness = (
                sum(fact.casefold() in answer_text for fact in expected_facts) / len(expected_facts)
                if expected_facts else None
            )
            if expected_facts and correctness < 1:
                failure_categories.append("reference_facts_missing")
            if not schema_valid:
                failure_categories.append("schema_invalid")
            if retrieval["hit_rate"] == 0:
                failure_categories.append("relevant_source_not_retrieved")
            if not abstention_correct:
                failure_categories.append("abstention_mismatch")
            elapsed_ms = round((perf_counter() - started) * 1000)
            result = {
                "passed": not failure_categories,
                "failure_categories": list(dict.fromkeys(failure_categories)),
                "expected_relevant_sources": relevant,
                "retrieved_document_ids": list(dict.fromkeys(item["document_id"] for item in retrieved)),
                "retrieved_sources": retrieved_sources,
                "recall_at_k": retrieval["recall"],
                "hit_rate_at_k": retrieval["hit_rate"],
                "mrr": retrieval["mrr"],
                "ndcg_at_k": retrieval["ndcg"],
                "correctness_rate": correctness,
                "schema_valid": schema_valid,
                "citations_total": cited_total,
                "citations_supported": cited_supported,
                "abstention_correct": abstention_correct,
                "latency_ms": elapsed_ms,
                "estimated_cost_usd": cost,
                "provider": provider,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "routing_decision": routing_decision,
                "notes": "Evaluation uses deterministic exact-match labels; inspect per-case evidence before changing thresholds.",
            }
            row = EvaluationCaseResult(
                evaluation_run_id=run.id, case_id=case["case_id"],
                passed=result["passed"], result=result,
            )
            session.add(row)
            case_rows.append(result)
            job = session.get(Job, job_id)
            job.progress = {
                "stage": "evaluating", "completed_cases": len(case_rows),
                "total_cases": len(dataset["cases"]),
            }
            session.commit()

        metrics = aggregate_metrics(case_rows, config["top_k"])
        metrics["config_hash"] = config["config_hash"]
        metrics["providers_used"] = [
            {"provider": provider, "model": model}
            for provider, model in sorted({
                (case["provider"], case["model"])
                for case in case_rows if case.get("provider") and case.get("model")
            })
        ]
        for token_field in ("input_tokens", "output_tokens"):
            totals = [case[token_field] for case in case_rows if case.get(token_field) is not None]
            metrics[f"{token_field}_total"] = sum(totals) if totals else None
        if run.baseline_run_id:
            baseline = session.get(EvaluationRun, run.baseline_run_id)
            metrics["baseline_comparison"] = compare_baseline(
                metrics, baseline.metrics or {}, config["regression_thresholds"]
            )
        run = session.get(EvaluationRun, evaluation_run_id)
        job = session.get(Job, job_id)
        run.metrics = metrics
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        job.status = "completed"
        job.progress = {"stage": "completed", "completed_cases": len(case_rows), "total_cases": len(case_rows)}
        job.finished_at = run.finished_at
        session.commit()
        return {"status": "completed", "metrics": metrics}
