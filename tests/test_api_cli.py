from __future__ import annotations

import json

from conftest import episode
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from chronograph_ai.api import create_app
from chronograph_ai.cli import app as cli_app
from chronograph_ai.engine import ChronoGraphEngine


def test_health_and_not_found_responses() -> None:
    client = TestClient(create_app(ChronoGraphEngine()))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert client.get("/episodes/missing").status_code == 404
    assert client.get("/facts/missing").status_code == 404


def test_episode_query_history_and_provenance_api() -> None:
    graph = ChronoGraphEngine()
    client = TestClient(create_app(graph))
    response = client.post(
        "/episodes", json=episode("api", "Alice works at Acme.").model_dump(mode="json")
    )
    assert response.status_code == 201
    payload = response.json()
    episode_id = payload["episode"]["id"]
    entity_id = payload["facts"][0]["subject_id"]
    fact_id = payload["facts"][0]["id"]

    assert client.get(f"/episodes/{episode_id}").status_code == 200
    assert len(client.get(f"/entities/{entity_id}/history").json()) == 1
    provenance = client.get(f"/facts/{fact_id}/provenance")
    assert provenance.status_code == 200
    assert provenance.json()["evidence"]

    query = client.post(
        "/query",
        json={
            "text": "Alice employer",
            "valid_time": "2026-02-01T00:00:00Z",
            "entity_id": entity_id,
        },
    )
    assert query.status_code == 200
    assert query.json()[0]["fact"]["id"] == fact_id


def test_as_of_neighbors_memory_and_integrity_api() -> None:
    graph = ChronoGraphEngine()
    result = graph.ingest(episode("api", "Alice works at Acme."))
    client = TestClient(create_app(graph))
    entity_id = result.facts[0].subject_id

    snapshot = client.post(
        "/query/as-of",
        json={"valid_time": "2026-02-01T00:00:00Z"},
    )
    assert snapshot.status_code == 200
    assert len(snapshot.json()["facts"]) == 1
    neighbors = client.get(
        f"/entities/{entity_id}/neighbors",
        params={"at": "2026-02-01T00:00:00Z"},
    )
    assert neighbors.status_code == 200
    assert neighbors.json()[0]["canonical_name"] == "Acme"
    memory = client.post(
        "/memory/query",
        json={
            "agent_id": "api-agent",
            "query": "Alice employer",
            "current_time": "2026-02-01T00:00:00Z",
            "subject_entity_id": entity_id,
        },
    )
    assert memory.status_code == 200
    assert len(memory.json()["items"]) == 1
    assert client.get("/integrity").json()["ok"] is True
    assert client.get("/stats").json()["facts"] == 1


def test_api_rejects_missing_as_of_time_and_invalid_relation() -> None:
    client = TestClient(create_app(ChronoGraphEngine()))
    assert client.post("/query/as-of", json={"text": "x"}).status_code == 422
    invalid = episode(
        "invalid",
        "Invalid relation",
        metadata={
            "entities": [
                {
                    "canonical_name": "Alice",
                    "entity_type": "Person",
                    "evidence_path": "person",
                }
            ],
            "facts": [
                {
                    "subject_name": "Alice",
                    "subject_type": "Person",
                    "predicate": "NOT_ALLOWED",
                    "literal_value": "x",
                    "evidence_path": "fact",
                }
            ],
        },
    )
    response = client.post("/episodes", json=invalid.model_dump(mode="json"))
    assert response.status_code == 422


def test_cli_help_evaluation_and_demo() -> None:
    runner = CliRunner()
    help_result = runner.invoke(cli_app, ["--help"])
    assert help_result.exit_code == 0
    assert "temporal knowledge" in help_result.stdout
    evaluation = runner.invoke(cli_app, ["eval"])
    assert evaluation.exit_code == 0
    assert all(item["passed"] for item in json.loads(evaluation.stdout))
    demo = runner.invoke(cli_app, ["demo"])
    assert demo.exit_code == 0
    assert json.loads(demo.stdout)["current"]


def test_cli_ingest_stats_and_integrity(tmp_path) -> None:
    fixture = tmp_path / "episode.json"
    fixture.write_text(
        episode("cli", "Alice works at Acme.").model_dump_json(indent=2),
        encoding="utf-8",
    )
    database = tmp_path / "cli.db"
    runner = CliRunner()
    ingested = runner.invoke(
        cli_app,
        ["--db", str(database), "ingest", str(fixture)],
    )
    assert ingested.exit_code == 0
    assert json.loads(ingested.stdout)[0]["facts"]
    stats = runner.invoke(cli_app, ["--db", str(database), "stats"])
    assert stats.exit_code == 0
    assert json.loads(stats.stdout)["facts"] == 1
    integrity = runner.invoke(cli_app, ["--db", str(database), "integrity"])
    assert integrity.exit_code == 0
    assert json.loads(integrity.stdout)["ok"] is True
