import json
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from incidentiq.models import (
    Base,
    Document,
    DocumentChunk,
    EvaluationCaseResult,
    EvaluationRun,
    Job,
)
from incidentiq.services.evaluation import (
    aggregate_metrics,
    compare_baseline,
    load_dataset,
    retrieval_metrics,
)
from incidentiq.services.evaluation_runner import run_evaluation_job
from tests.auth_support import authorized_client, create_test_app

DATASETS = Path(__file__).parents[1] / "datasets"


def test_versioned_validation_and_holdout_datasets_are_separate():
    validation = load_dataset(DATASETS, "incidentiq_demo", "validation")
    holdout = load_dataset(DATASETS, "incidentiq_demo", "holdout")
    assert validation["version"] == holdout["version"] == "1.0.0"
    assert validation["split"] == "validation"
    assert holdout["split"] == "holdout"
    assert {case["case_id"] for case in validation["cases"]}.isdisjoint(
        {case["case_id"] for case in holdout["cases"]}
    )


def test_dataset_loader_rejects_traversal_and_missing_datasets():
    with pytest.raises(ValueError):
        load_dataset(DATASETS, "../incidentiq_demo", "validation")
    with pytest.raises(ValueError, match="not found"):
        load_dataset(DATASETS, "missing", "validation")


def test_retrieval_metrics_and_unlabeled_cases():
    result = retrieval_metrics(["a", "b"], ["x", "b", "a"], 2)
    assert result == {
        "recall": 0.5,
        "hit_rate": 1.0,
        "mrr": 0.5,
        "ndcg": 0.38685280723454163,
    }
    assert retrieval_metrics([], ["a"], 5)["recall"] is None
    assert retrieval_metrics(["a", "b"], ["a", "a", "b"], 2)["recall"] == 1.0


def test_aggregate_metrics_and_baseline_regression_gate():
    metrics = aggregate_metrics(
        [
            {
                "recall_at_k": 0.5,
                "hit_rate_at_k": 1.0,
                "mrr": 0.5,
                "ndcg_at_k": 0.4,
                "correctness_rate": 1.0,
                "citations_total": 1,
                "citations_supported": 1,
                "schema_valid": True,
                "abstention_correct": 1.0,
                "latency_ms": 10,
                "estimated_cost_usd": 0.02,
            },
            {
                "recall_at_k": None,
                "hit_rate_at_k": None,
                "mrr": None,
                "ndcg_at_k": None,
                "correctness_rate": None,
                "citations_total": 0,
                "citations_supported": 0,
                "schema_valid": False,
                "abstention_correct": 0.0,
                "latency_ms": 20,
                "estimated_cost_usd": 0.04,
            },
        ],
        5,
    )
    assert metrics["recall_at_5"] == 0.5
    assert metrics["schema_valid_rate"] == 0.5
    assert metrics["citation_support_rate"] == 1.0
    assert metrics["p95_latency_ms"] == 20
    assert (
        compare_baseline(
            {"recall_at_5": 0.45, "p95_latency_ms": 110},
            {"recall_at_5": 0.5, "p95_latency_ms": 100},
            {"recall_at_5": 0.02, "p95_latency_ms": 20},
        )["passed"]
        is False
    )
    comparison = compare_baseline({"mrr": 0.6}, {"mrr": 0.5}, {})
    assert abs(comparison["deltas"]["mrr"] - 0.1) < 1e-9
    assert comparison["passed"] is None


def test_evaluation_api_queues_run_and_worker_persists_case_metrics(tmp_path, monkeypatch):
    test_dataset_dir = tmp_path / "datasets"
    val_dir = test_dataset_dir / "test_demo" / "validation"
    val_dir.mkdir(parents=True)
    (val_dir / "v1.json").write_text(
        json.dumps(
            {
                "dataset_id": "test_demo",
                "version": "1.0.0",
                "split": "validation",
                "cases": [
                    {
                        "case_id": "connection_pool_saturation",
                        "incident": {
                            "title": "Checkout database acquisition timeouts",
                            "description": "Acquisition timeouts increased after a release.",
                            "service": "checkout",
                            "environment": "production",
                            "severity": "SEV-2",
                        },
                        "expected_relevant_sources": ["connection-pool.md"],
                        "expected_facts": ["inspect connection pool saturation"],
                        "should_abstain": False,
                    },
                    {
                        "case_id": "unknown_dependency_failure",
                        "incident": {
                            "title": "Unknown dependency failure",
                            "description": "Request failed without diagnostic signal.",
                            "service": "checkout",
                            "environment": "production",
                            "severity": "unknown",
                        },
                        "expected_relevant_sources": [],
                        "expected_facts": [],
                        "should_abstain": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EVALUATION_DATASET_DIR", str(test_dataset_dir))

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    class Queue:
        def __init__(self):
            self.calls = []

        async def enqueue_job(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    class Gateway:
        providers: ClassVar[dict[str, SimpleNamespace]] = {
            "groq": SimpleNamespace(provider="groq", model="test-free-model")
        }

        def __init__(self):
            self.evidence = None
            self.calls = 0

        def generate(self, messages, max_output_tokens, **kwargs):
            self.calls += 1
            request = json.loads(messages[1]["content"])
            self.evidence = request["evidence"][0]
            content = {
                "summary": "Inspect connection pool saturation.",
                "quality_result": "evidence_found",
                "hypotheses": [
                    {
                        "title": "Connection pool saturation",
                        "confidence": "medium",
                        "rationale": "Inspect connection pool saturation using the runbook.",
                        "supporting_evidence": [
                            {
                                "document_id": self.evidence["document_id"],
                                "chunk_id": self.evidence["chunk_id"],
                                "quote": "inspect connection pool saturation",
                            }
                        ],
                        "contradictory_evidence": [],
                        "missing_evidence": [],
                    }
                ],
                "diagnostic_steps": [],
            }
            return SimpleNamespace(
                content=json.dumps(content),
                estimated_cost_usd=0.001,
                provider="groq",
                model="test-free-model",
                input_tokens=32,
                output_tokens=20,
                decision={"selected_provider": "groq", "fallback_used": False},
            )

    queue = Queue()
    gateway = Gateway()
    client = authorized_client(
        create_test_app(factory, chat_gateway=gateway, job_queue=queue)
    )
    with factory() as session:
        doc = Document(
            filename="connection-pool.md",
            source_type="runbook",
            service="checkout",
            environment="production",
            content_sha256="d" * 64,
            status="completed",
        )
        doc.chunks.append(
            DocumentChunk(
                id=uuid4(),
                chunk_index=0,
                content="When acquisition timeouts rise, inspect connection pool saturation and connection leaks.",
                chunk_metadata={},
            )
        )
        session.add(doc)
        session.commit()

    response = client.post(
        "/api/v1/evaluations",
        json={
            "dataset_id": "test_demo",
            "split": "validation",
            "experiment_name": "baseline",
            "config": {"retrieval_mode": "keyword"},
        },
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued" and len(queue.calls) == 1
    assert queue.calls[0][0][0] == "process_evaluation_job"
    result = run_evaluation_job(
        factory,
        UUID(body["evaluation_run_id"]),
        UUID(body["job_id"]),
        dataset_dir=test_dataset_dir,
        embedding_provider=None,
        vector_store=None,
        chat_gateway=gateway,
        namespace="test",
        dimension=0,
    )
    assert result["status"] == "completed"
    assert result["metrics"]["recall_at_5"] == 1.0
    assert result["metrics"]["schema_valid_rate"] == 1.0
    assert result["metrics"]["abstention_accuracy"] == 1.0
    rerun = run_evaluation_job(
        factory,
        UUID(body["evaluation_run_id"]),
        UUID(body["job_id"]),
        dataset_dir=DATASETS,
        embedding_provider=None,
        vector_store=None,
        chat_gateway=gateway,
        namespace="test",
        dimension=0,
    )
    assert rerun["status"] == "completed" and gateway.calls == 1
    assert (
        client.get(f"/api/v1/evaluations/{body['evaluation_run_id']}").json()["status"]
        == "completed"
    )
    cases = client.get(f"/api/v1/evaluations/{body['evaluation_run_id']}/cases").json()[
        "items"
    ]
    assert len(cases) == 2 and all(item["passed"] for item in cases)
    assert client.get(f"/api/v1/jobs/{body['job_id']}").json()["status"] == "completed"
    with factory() as session:
        assert session.query(EvaluationRun).one().status == "completed"
        assert session.query(Job).one().status == "completed"
        assert session.query(EvaluationCaseResult).count() == 2
    client.close()
    engine.dispose()


def test_evaluation_api_rejects_unavailable_dataset_and_unconfigured_queue():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    client = authorized_client(create_test_app(factory))
    body = {"dataset_id": "missing", "split": "validation", "experiment_name": "x"}
    assert client.post("/api/v1/evaluations", json=body).status_code == 422
    body["dataset_id"] = "incidentiq_demo"
    assert client.post("/api/v1/evaluations", json=body).status_code == 503
    client.close()
    engine.dispose()
