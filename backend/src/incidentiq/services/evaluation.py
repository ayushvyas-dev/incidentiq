"""Versioned evaluation dataset loading and deterministic metric calculations."""

import json
import re
from math import log2
from pathlib import Path

_DATASET_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}\Z")
_VERSION = re.compile(r"\d+\.\d+\.\d+\Z")


def load_dataset(dataset_dir: Path, dataset_id: str, split: str) -> dict:
    if not _DATASET_ID.fullmatch(dataset_id) or split not in {"validation", "holdout"}:
        raise ValueError("Unknown evaluation dataset or split")
    path = dataset_dir / dataset_id / split / "v1.json"
    try:
        if path.stat().st_size > 2_000_000:
            raise ValueError("Evaluation dataset exceeds the 2 MB limit")
        dataset = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("Evaluation dataset was not found") from None
    except OSError:
        raise ValueError("Evaluation dataset could not be read") from None
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("Evaluation dataset is not valid UTF-8 JSON") from None
    if not isinstance(dataset, dict) or (
        dataset.get("dataset_id") != dataset_id
        or dataset.get("split") != split
        or not isinstance(dataset.get("version"), str)
        or not _VERSION.fullmatch(dataset["version"])
        or not isinstance(dataset.get("cases"), list)
        or not dataset["cases"]
        or len(dataset["cases"]) > 200
    ):
        raise ValueError("Evaluation dataset metadata or cases are invalid")
    seen = set()
    for case in dataset["cases"]:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("case_id"), str)
            or not case["case_id"].strip()
            or len(case["case_id"]) > 128
            or case["case_id"] in seen
            or not isinstance(case.get("incident"), dict)
            or not {"title", "description", "service", "environment", "severity"}.issubset(case["incident"])
            or any(
                not isinstance(case["incident"].get(field), str)
                or not case["incident"][field].strip()
                or len(case["incident"][field]) > maximum
                for field, maximum in (
                    ("title", 255), ("description", 10000), ("service", 128),
                    ("environment", 64), ("severity", 16),
                )
            )
            or case["incident"]["severity"] not in {"SEV-1", "SEV-2", "SEV-3", "SEV-4", "unknown"}
            or not isinstance(case.get("expected_relevant_sources"), list)
            or len(case["expected_relevant_sources"]) > 20
            or not all(isinstance(item, str) for item in case["expected_relevant_sources"])
            or any(not item.strip() or len(item) > 255 for item in case["expected_relevant_sources"])
            or not isinstance(case.get("expected_facts"), list)
            or len(case["expected_facts"]) > 20
            or not all(isinstance(item, str) for item in case["expected_facts"])
            or any(not item.strip() or len(item) > 500 for item in case["expected_facts"])
            or not isinstance(case.get("should_abstain"), bool)
        ):
            raise ValueError("Evaluation dataset case is invalid")
        seen.add(case["case_id"])
    return dataset


def retrieval_metrics(relevant: list[str], retrieved: list[str], k: int) -> dict[str, float | None]:
    if k < 1:
        raise ValueError("k must be positive")
    relevant_set = set(relevant)
    if not relevant_set:
        return {"recall": None, "hit_rate": None, "mrr": None, "ndcg": None}
    ranked = list(dict.fromkeys(retrieved))[:k]
    matches = [item for item in ranked if item in relevant_set]
    reciprocal_rank = next((1 / (index + 1) for index, item in enumerate(ranked) if item in relevant_set), 0.0)
    dcg = sum(1 / log2(index + 2) for index, item in enumerate(ranked) if item in relevant_set)
    ideal = sum(1 / log2(index + 2) for index in range(min(len(relevant_set), k)))
    return {
        "recall": len(set(matches)) / len(relevant_set),
        "hit_rate": float(bool(matches)),
        "mrr": reciprocal_rank,
        "ndcg": dcg / ideal,
    }


def aggregate_metrics(cases: list[dict], k: int) -> dict:
    def mean(key: str):
        values = [case[key] for case in cases if case.get(key) is not None]
        return sum(values) / len(values) if values else None

    latencies = sorted(case["latency_ms"] for case in cases if case.get("latency_ms") is not None)
    costs = [case["estimated_cost_usd"] for case in cases if case.get("estimated_cost_usd") is not None]
    cited = sum(case.get("citations_total", 0) for case in cases)
    supported = sum(case.get("citations_supported", 0) for case in cases)
    schema_cases = [case for case in cases if case.get("schema_valid") is not None]
    return {
        f"recall_at_{k}": mean("recall_at_k"),
        f"hit_rate_at_{k}": mean("hit_rate_at_k"),
        "mrr": mean("mrr"),
        f"ndcg_at_{k}": mean("ndcg_at_k"),
        "answer_correctness_rate": mean("correctness_rate"),
        "citation_support_rate": supported / cited if cited else None,
        "schema_valid_rate": (
            sum(case["schema_valid"] for case in schema_cases) / len(schema_cases)
            if schema_cases else None
        ),
        "abstention_accuracy": mean("abstention_correct"),
        "p95_latency_ms": latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)] if latencies else None,
        "estimated_cost_per_case_usd": sum(costs) / len(costs) if costs else None,
        "cost_estimate_coverage": len(costs) / len(cases) if cases else 0.0,
    }


def compare_baseline(candidate: dict, baseline: dict, max_regression: dict[str, float]) -> dict:
    comparable = {
        "recall_at_", "hit_rate_at_", "mrr", "ndcg_at_", "answer_correctness_rate",
        "citation_support_rate", "schema_valid_rate", "abstention_accuracy",
        "p95_latency_ms", "estimated_cost_per_case_usd",
    }
    lower_is_better = {"p95_latency_ms", "estimated_cost_per_case_usd"}
    metrics = {
        key for key in candidate
        if key in comparable or any(key.startswith(prefix) for prefix in comparable if prefix.endswith("_"))
    }
    deltas = {
        metric: candidate[metric] - baseline[metric]
        for metric in metrics
        if isinstance(candidate.get(metric), (int, float))
        and isinstance(baseline.get(metric), (int, float))
    }
    failures = []
    for metric, allowed in max_regression.items():
        delta = deltas.get(metric)
        if delta is None:
            deltas[metric] = None
            continue
        regression = delta > allowed if metric in lower_is_better else delta < -allowed
        if regression:
            failures.append(metric)
    unavailable = [metric for metric in max_regression if deltas.get(metric) is None]
    passed = None if not max_regression or (unavailable and not failures) else not failures
    return {
        "deltas": deltas, "passed": passed, "failed_metrics": failures,
        "unavailable_metrics": unavailable,
    }
