"""Deterministic temporal-knowledge evaluation scenarios without benchmark claims."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from chronograph_ai.engine import ChronoGraphEngine
from chronograph_ai.memory import MemoryAssembler
from chronograph_ai.models import (
    EpisodeCreate,
    EpisodeSource,
    EvaluationCase,
    FactStatus,
    MemoryRequest,
    Sensitivity,
)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _episode(
    source_id: str,
    content: str,
    event_time: str,
    *,
    observed_at: str | None = None,
    metadata: dict[str, object] | None = None,
    sensitivity: Sensitivity = Sensitivity.PUBLIC,
    idempotency_key: str | None = None,
) -> EpisodeCreate:
    return EpisodeCreate(
        source_type=EpisodeSource.STRUCTURED_RECORD,
        source_id=source_id,
        content=content,
        event_time=_time(event_time),
        observed_at=_time(observed_at or event_time),
        metadata=metadata or {},
        sensitivity=sensitivity,
        idempotency_key=idempotency_key,
    )


def _employment_engine() -> ChronoGraphEngine:
    engine = ChronoGraphEngine()
    engine.ingest(_episode("employment-1", "Alice works at Acme.", "2026-01-01T00:00:00"))
    engine.ingest(_episode("employment-2", "Alice now works at Orbit.", "2026-02-01T00:00:00"))
    return engine


def scenario_fact_changes() -> None:
    engine = _employment_engine()
    alice = next(
        entity for entity in engine.store.list_entities() if entity.canonical_name == "Alice"
    )
    current = engine.facts_valid_at(_time("2026-03-01T00:00:00"), entity_id=alice.id)
    historical = engine.facts_valid_at(_time("2026-01-15T00:00:00"), entity_id=alice.id)
    assert len(current) == 1 and current[0].status is FactStatus.ACTIVE
    assert engine.store.get_entity(current[0].object_id or "").canonical_name == "Orbit"  # type: ignore[union-attr]
    assert len(historical) == 1
    assert engine.store.get_entity(historical[0].object_id or "").canonical_name == "Acme"  # type: ignore[union-attr]


def scenario_retroactive_fact() -> None:
    engine = ChronoGraphEngine()
    result = engine.ingest(
        _episode(
            "retroactive-1",
            "Project Alpha had status paused.",
            "2026-08-01T00:00:00",
            observed_at="2026-09-20T00:00:00",
            metadata={
                "entities": [
                    {
                        "canonical_name": "Project Alpha",
                        "entity_type": "Project",
                        "evidence_path": "record.project",
                    }
                ],
                "facts": [
                    {
                        "subject_name": "Project Alpha",
                        "subject_type": "Project",
                        "predicate": "HAS_STATUS",
                        "literal_value": "paused",
                        "valid_from": "2026-08-01T00:00:00Z",
                        "valid_to": "2026-08-10T00:00:00Z",
                        "evidence_path": "record.status",
                    }
                ],
            },
        )
    )
    fact = result.facts[0]
    assert fact.valid_from == _time("2026-08-01T00:00:00")
    assert fact.recorded_at == _time("2026-09-20T00:00:00")
    assert not engine.facts_valid_at(
        _time("2026-08-05T00:00:00"), known_at=_time("2026-09-19T00:00:00")
    )
    assert engine.facts_valid_at(
        _time("2026-08-05T00:00:00"), known_at=_time("2026-09-21T00:00:00")
    )


def scenario_contradiction() -> None:
    engine = ChronoGraphEngine()
    engine.ingest(_episode("source-a", "Alice works at Acme.", "2026-01-01T00:00:00"))
    engine.ingest(
        _episode(
            "source-b",
            "Alice works at Orbit.",
            "2026-01-01T00:00:00",
            observed_at="2026-01-02T00:00:00",
        )
    )
    assert len(engine.store.list_conflicts()) == 1
    assert all(fact.status is FactStatus.DISPUTED for fact in engine.store.list_facts())


def scenario_entity_ambiguity() -> None:
    engine = ChronoGraphEngine()
    for source, identifier in [("crm", "alex-1"), ("support", "alex-2")]:
        engine.ingest(
            _episode(
                source,
                "Explicit identity record",
                "2026-01-01T00:00:00",
                metadata={
                    "entities": [
                        {
                            "canonical_name": "Alex Smith",
                            "entity_type": "Person",
                            "identifiers": {"source_user_id": identifier},
                            "evidence_path": "record.identity",
                        }
                    ]
                },
            )
        )
    assert len(engine.store.list_entities()) == 2


def scenario_entity_alias() -> None:
    engine = ChronoGraphEngine()
    common = {
        "entity_type": "Organization",
        "identifiers": {"domain": "ibm.com"},
        "evidence_path": "record.organization",
    }
    engine.ingest(
        _episode(
            "org-1",
            "Organization identity",
            "2026-01-01T00:00:00",
            metadata={
                "entities": [
                    {
                        **common,
                        "canonical_name": "International Business Machines",
                        "aliases": ["IBM"],
                    }
                ]
            },
        )
    )
    engine.ingest(
        _episode(
            "org-2",
            "Organization alias",
            "2026-01-02T00:00:00",
            metadata={"entities": [{**common, "canonical_name": "IBM"}]},
        )
    )
    assert len(engine.store.list_entities()) == 1


def scenario_point_in_time_graph() -> None:
    engine = _employment_engine()
    first = engine.graph_as_of(_time("2026-01-15T00:00:00"))
    second = engine.graph_as_of(_time("2026-01-15T00:00:00"))
    assert first.digest == second.digest
    assert len(first.facts) == 1


def scenario_agent_memory() -> None:
    engine = _employment_engine()
    alice = next(
        entity for entity in engine.store.list_entities() if entity.canonical_name == "Alice"
    )
    bundle = MemoryAssembler(engine).assemble(
        MemoryRequest(
            agent_id="evaluation-agent",
            subject_entity_id=alice.id,
            query="Alice employer",
            current_time=_time("2026-03-01T00:00:00"),
        )
    )
    assert len(bundle.items) == 1
    assert "Orbit" in bundle.items[0].text


def scenario_sensitive_memory() -> None:
    engine = ChronoGraphEngine()
    result = engine.ingest(
        _episode(
            "restricted-1",
            "Alice works at Acme.",
            "2026-01-01T00:00:00",
            sensitivity=Sensitivity.RESTRICTED,
        )
    )
    bundle = MemoryAssembler(engine).assemble(
        MemoryRequest(
            agent_id="evaluation-agent",
            subject_entity_id=result.facts[0].subject_id,
            query="Alice employer",
            current_time=_time("2026-02-01T00:00:00"),
        )
    )
    assert bundle.items == []


def scenario_duplicate_ingestion() -> None:
    engine = ChronoGraphEngine()
    payload = _episode(
        "duplicate-1",
        "Alice works at Acme.",
        "2026-01-01T00:00:00",
        idempotency_key="duplicate-key",
    )
    first = engine.ingest(payload)
    second = engine.ingest(payload)
    assert not first.duplicate and second.duplicate
    assert len(engine.store.list_episodes()) == 1
    assert len(engine.store.list_facts()) == 1


def scenario_invalid_provider_output() -> None:
    engine = ChronoGraphEngine()
    try:
        engine.ingest(
            _episode(
                "invalid-provider",
                "Malformed fixture",
                "2026-01-01T00:00:00",
                metadata={"facts": [{"predicate": "WORKS_AT"}]},
            )
        )
    except ValueError:
        pass
    else:
        raise AssertionError("malformed provider output was accepted")
    assert engine.stats()["episodes"] == 0
    assert engine.stats()["facts"] == 0


SCENARIOS: list[tuple[str, Callable[[], None]]] = [
    ("fact changes over time", scenario_fact_changes),
    ("retroactive fact", scenario_retroactive_fact),
    ("contradiction", scenario_contradiction),
    ("entity ambiguity", scenario_entity_ambiguity),
    ("entity alias", scenario_entity_alias),
    ("point-in-time graph", scenario_point_in_time_graph),
    ("agent memory", scenario_agent_memory),
    ("sensitive memory", scenario_sensitive_memory),
    ("duplicate ingestion", scenario_duplicate_ingestion),
    ("invalid provider output", scenario_invalid_provider_output),
]


def run_evaluation() -> list[EvaluationCase]:
    results: list[EvaluationCase] = []
    for name, scenario in SCENARIOS:
        try:
            scenario()
        except Exception as exc:  # evaluation must report every scenario
            results.append(EvaluationCase(name=name, passed=False, details=str(exc)))
        else:
            results.append(
                EvaluationCase(name=name, passed=True, details="deterministic assertions passed")
            )
    return results
