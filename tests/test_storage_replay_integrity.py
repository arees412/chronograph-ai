from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import episode, timestamp

from chronograph_ai.engine import ChronoGraphEngine
from chronograph_ai.integrity import IntegrityChecker
from chronograph_ai.models import (
    Fact,
    FactStatus,
    RetentionAction,
    RetentionPolicy,
    RetentionState,
)
from chronograph_ai.replay import replay
from chronograph_ai.retention import RetentionManager
from chronograph_ai.storage import SQLiteGraphStore


def test_sqlite_roundtrip_preserves_canonical_state(tmp_path) -> None:
    path = tmp_path / "chronograph.db"
    first_store = SQLiteGraphStore(path)
    first = ChronoGraphEngine(store=first_store)
    first.ingest(episode("one", "Alice works at Acme."))
    expected = first.state_digest()
    first_store.close()

    second_store = SQLiteGraphStore(path)
    second = ChronoGraphEngine(store=second_store)
    assert second.state_digest() == expected
    assert second.stats()["facts"] == 1
    second_store.close()


def test_replay_is_order_independent_and_deterministic() -> None:
    first = episode("one", "Alice works at Acme.")
    second = episode("two", "Alice now works at Orbit.", event_time="2026-02-01T00:00:00")
    _, forward = replay([first, second])
    _, reverse = replay([second, first])
    assert forward == reverse


def test_concurrent_duplicate_ingestion_is_idempotent() -> None:
    graph = ChronoGraphEngine()
    payload = episode(
        "concurrent",
        "Alice works at Acme.",
        idempotency_key="concurrent-key",
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: graph.ingest(payload), range(16)))
    assert sum(not result.duplicate for result in results) == 1
    assert graph.stats()["episodes"] == 1
    assert graph.stats()["facts"] == 1


def test_integrity_report_is_clean_for_normal_graph(
    employment_engine: ChronoGraphEngine,
) -> None:
    report = IntegrityChecker(
        employment_engine.store,
        employment_engine.ontology,
        employment_engine.clock,
    ).check()
    assert report.ok
    assert report.issues == []


def test_integrity_detects_orphan_and_missing_provenance(
    employment_engine: ChronoGraphEngine,
) -> None:
    original = employment_engine.store.list_facts()[0]
    broken = original.model_copy(
        update={
            "id": "broken",
            "subject_id": "missing-entity",
            "evidence_ids": ["missing-evidence"],
            "status": FactStatus.ACTIVE,
            "superseded_by": None,
        }
    )
    employment_engine.store.add_fact(broken)
    report = IntegrityChecker(
        employment_engine.store,
        employment_engine.ontology,
        employment_engine.clock,
    ).check()
    assert not report.ok
    assert {issue.code for issue in report.issues} >= {"orphan_fact", "missing_provenance"}


def test_retention_redacts_content_but_preserves_source_hash() -> None:
    graph = ChronoGraphEngine()
    result = graph.ingest(episode("redact", "Alice works at Acme."))
    RetentionManager(graph).apply(
        result.episode.id,
        RetentionAction.REDACT_CONTENT,
        reason="data minimization",
    )
    redacted = graph.store.get_episode(result.episode.id)
    assert redacted is not None
    assert redacted.content == "[REDACTED]"
    assert redacted.metadata == {}
    assert redacted.content_hash == result.episode.content_hash
    assert redacted.retention_state is RetentionState.REDACTED


def test_tombstone_invalidates_single_source_fact() -> None:
    graph = ChronoGraphEngine()
    result = graph.ingest(episode("tombstone", "Alice works at Acme."))
    tombstone = RetentionManager(graph).apply(
        result.episode.id,
        RetentionAction.TOMBSTONE,
        reason="subject request",
    )
    assert tombstone is not None
    assert tombstone.source_hash == result.episode.content_hash
    assert graph.store.get_fact(result.facts[0].id).status is FactStatus.INVALIDATED  # type: ignore[union-attr]


def test_purge_requires_explicit_policy_and_preserves_tombstone() -> None:
    graph = ChronoGraphEngine()
    result = graph.ingest(episode("purge", "Alice works at Acme."))
    manager = RetentionManager(graph)
    with pytest.raises(PermissionError, match="does not allow"):
        manager.apply(
            result.episode.id,
            RetentionAction.PURGE_WHERE_POLICY_ALLOWS,
            reason="request",
        )
    tombstone = manager.apply(
        result.episode.id,
        RetentionAction.PURGE_WHERE_POLICY_ALLOWS,
        reason="approved request",
        policy=RetentionPolicy(allow_purge=True),
    )
    assert tombstone is not None
    assert graph.store.get_episode(result.episode.id) is None
    assert graph.store.list_tombstones()


def test_fact_model_prevents_reversed_intervals() -> None:
    graph = ChronoGraphEngine()
    result = graph.ingest(episode("fact", "Alice works at Acme."))
    payload = result.facts[0].model_dump()
    payload["valid_to"] = timestamp("2025-01-01T00:00:00")
    with pytest.raises(ValueError, match="valid_to"):
        Fact.model_validate(payload)
