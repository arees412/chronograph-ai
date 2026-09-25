from __future__ import annotations

from conftest import episode, timestamp

from chronograph_ai.engine import ChronoGraphEngine
from chronograph_ai.memory import MemoryAssembler
from chronograph_ai.models import (
    FactStatus,
    MemoryPolicy,
    MemoryRequest,
    RetentionAction,
    Sensitivity,
)
from chronograph_ai.retention import RetentionManager
from chronograph_ai.retrieval import HybridRetriever


def test_hybrid_retrieval_is_explainable_and_evidence_backed(
    employment_engine: ChronoGraphEngine,
) -> None:
    results = HybridRetriever(employment_engine).search(
        "Alice employer Orbit",
        valid_time=timestamp("2026-03-01T00:00:00"),
    )
    assert len(results) == 1
    result = results[0]
    assert result.object_entity is not None
    assert result.object_entity.canonical_name == "Orbit"
    assert result.evidence
    assert result.ranking.final_score > 0
    assert any("not calibrated probabilities" in line for line in result.ranking.explanation)


def test_graph_neighbors_and_bounded_path() -> None:
    graph = ChronoGraphEngine()
    graph.ingest(
        episode(
            "chain-1",
            "Ownership record",
            metadata={
                "entities": [
                    {
                        "canonical_name": "Alice",
                        "entity_type": "Person",
                        "evidence_path": "record.owner",
                    },
                    {
                        "canonical_name": "Project One",
                        "entity_type": "Project",
                        "evidence_path": "record.project",
                    },
                    {
                        "canonical_name": "Project Two",
                        "entity_type": "Project",
                        "evidence_path": "record.dependency",
                    },
                ],
                "facts": [
                    {
                        "subject_name": "Alice",
                        "subject_type": "Person",
                        "predicate": "OWNS",
                        "object_name": "Project One",
                        "object_type": "Project",
                        "evidence_path": "record.owns",
                    },
                    {
                        "subject_name": "Project One",
                        "subject_type": "Project",
                        "predicate": "DEPENDS_ON",
                        "object_name": "Project Two",
                        "object_type": "Project",
                        "evidence_path": "record.depends_on",
                    },
                ],
            },
        )
    )
    by_name = {entity.canonical_name: entity for entity in graph.store.list_entities()}
    neighbors = graph.neighbors(
        by_name["Alice"].id,
        valid_time=timestamp("2026-02-01T00:00:00"),
    )
    assert [entity.canonical_name for entity in neighbors] == ["Project One"]
    assert graph.path(
        by_name["Alice"].id,
        by_name["Project Two"].id,
        valid_time=timestamp("2026-02-01T00:00:00"),
        max_depth=2,
    ) == [by_name["Alice"].id, by_name["Project One"].id, by_name["Project Two"].id]
    assert not graph.path(
        by_name["Alice"].id,
        by_name["Project Two"].id,
        valid_time=timestamp("2026-02-01T00:00:00"),
        max_depth=1,
    )


def test_current_memory_excludes_superseded_fact(
    employment_engine: ChronoGraphEngine,
) -> None:
    alice = next(
        entity
        for entity in employment_engine.store.list_entities()
        if entity.canonical_name == "Alice"
    )
    bundle = MemoryAssembler(employment_engine).assemble(
        MemoryRequest(
            agent_id="agent",
            subject_entity_id=alice.id,
            query="Alice employer",
            current_time=timestamp("2026-03-01T00:00:00"),
        )
    )
    assert [item.fact.status for item in bundle.items] == [FactStatus.ACTIVE]
    assert "Orbit" in bundle.items[0].text


def test_historical_memory_uses_explicit_valid_time(
    employment_engine: ChronoGraphEngine,
) -> None:
    alice = next(
        entity
        for entity in employment_engine.store.list_entities()
        if entity.canonical_name == "Alice"
    )
    bundle = MemoryAssembler(employment_engine).assemble(
        MemoryRequest(
            agent_id="agent",
            subject_entity_id=alice.id,
            query="Alice employer",
            current_time=timestamp("2026-03-01T00:00:00"),
            historical_valid_time=timestamp("2026-01-15T00:00:00"),
        )
    )
    assert len(bundle.items) == 1
    assert "Acme" in bundle.items[0].text


def test_memory_enforces_sensitivity_policy() -> None:
    graph = ChronoGraphEngine()
    result = graph.ingest(
        episode(
            "restricted",
            "Alice works at Acme.",
            sensitivity=Sensitivity.RESTRICTED,
        )
    )
    default = MemoryAssembler(graph).assemble(
        MemoryRequest(
            agent_id="agent",
            subject_entity_id=result.facts[0].subject_id,
            query="Alice employer",
            current_time=timestamp("2026-02-01T00:00:00"),
        )
    )
    allowed = MemoryAssembler(graph).assemble(
        MemoryRequest(
            agent_id="agent",
            subject_entity_id=result.facts[0].subject_id,
            query="Alice employer",
            current_time=timestamp("2026-02-01T00:00:00"),
            policy=MemoryPolicy(allowed_sensitivities={Sensitivity.RESTRICTED}),
        )
    )
    assert default.items == []
    assert len(allowed.items) == 1


def test_memory_budgets_truncate_deterministically() -> None:
    graph = ChronoGraphEngine()
    for name in ("Tea", "Coffee"):
        graph.ingest(
            episode(
                f"preference-{name}",
                "Preference record",
                metadata={
                    "entities": [
                        {
                            "canonical_name": "Alice",
                            "entity_type": "Person",
                            "evidence_path": "person",
                        },
                        {
                            "canonical_name": name,
                            "entity_type": "Product",
                            "evidence_path": "product",
                        },
                    ],
                    "facts": [
                        {
                            "subject_name": "Alice",
                            "subject_type": "Person",
                            "predicate": "PREFERS",
                            "object_name": name,
                            "object_type": "Product",
                            "evidence_path": "preference",
                        }
                    ],
                },
            )
        )
    alice = next(
        entity for entity in graph.store.list_entities() if entity.canonical_name == "Alice"
    )
    bundle = MemoryAssembler(graph).assemble(
        MemoryRequest(
            agent_id="agent",
            subject_entity_id=alice.id,
            query="Alice prefers",
            current_time=timestamp("2026-02-01T00:00:00"),
            policy=MemoryPolicy(max_items=1),
        )
    )
    assert len(bundle.items) == 1
    assert bundle.truncated


def test_disputed_memory_is_opt_in() -> None:
    graph = ChronoGraphEngine()
    graph.ingest(episode("source-a", "Alice works at Acme."))
    second = graph.ingest(
        episode("source-b", "Alice works at Orbit.", observed_at="2026-01-02T00:00:00")
    )
    base = dict(
        agent_id="agent",
        subject_entity_id=second.facts[0].subject_id,
        query="Alice employer",
        current_time=timestamp("2026-02-01T00:00:00"),
    )
    assert MemoryAssembler(graph).assemble(MemoryRequest(**base)).items == []
    opted_in = MemoryAssembler(graph).assemble(
        MemoryRequest(**base, policy=MemoryPolicy(include_disputed=True))
    )
    assert len(opted_in.items) == 2
    assert all(item.contradictions for item in opted_in.items)


def test_expired_source_is_removed_from_active_memory() -> None:
    graph = ChronoGraphEngine()
    result = graph.ingest(episode("employment", "Alice works at Acme."))
    RetentionManager(graph).apply(
        result.episode.id,
        RetentionAction.EXPIRE_FROM_ACTIVE_MEMORY,
        reason="retention window elapsed",
    )
    bundle = MemoryAssembler(graph).assemble(
        MemoryRequest(
            agent_id="agent",
            subject_entity_id=result.facts[0].subject_id,
            query="Alice employer",
            current_time=timestamp("2026-02-01T00:00:00"),
        )
    )
    assert bundle.items == []


def test_memory_audit_stores_hashes_not_raw_query(
    employment_engine: ChronoGraphEngine,
) -> None:
    MemoryAssembler(employment_engine).assemble(
        MemoryRequest(
            agent_id="private-agent",
            query="sensitive query text",
            current_time=timestamp("2026-03-01T00:00:00"),
        )
    )
    audit = employment_engine.store.list_audit()[-1]
    serialized = str(audit.details)
    assert "sensitive query text" not in serialized
    assert "private-agent" not in serialized
