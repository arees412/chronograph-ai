from __future__ import annotations

from conftest import episode, timestamp

from chronograph_ai.engine import ChronoGraphEngine
from chronograph_ai.models import FactStatus


def test_exclusive_fact_change_closes_old_valid_interval(
    employment_engine: ChronoGraphEngine,
) -> None:
    facts = employment_engine.store.list_facts()
    old, current = facts
    assert old.status is FactStatus.SUPERSEDED
    assert old.valid_to == timestamp("2026-02-01T00:00:00")
    assert old.asserted_valid_to is None
    assert old.superseded_by == current.id
    assert current.status is FactStatus.ACTIVE


def test_valid_time_returns_historical_and_current_employer(
    employment_engine: ChronoGraphEngine,
) -> None:
    alice = next(
        entity
        for entity in employment_engine.store.list_entities()
        if entity.canonical_name == "Alice"
    )
    historical = employment_engine.facts_valid_at(
        timestamp("2026-01-15T00:00:00"), entity_id=alice.id
    )
    current = employment_engine.facts_valid_at(timestamp("2026-03-01T00:00:00"), entity_id=alice.id)
    assert (
        employment_engine.store.get_entity(historical[0].object_id or "").canonical_name == "Acme"
    )  # type: ignore[union-attr]
    assert employment_engine.store.get_entity(current[0].object_id or "").canonical_name == "Orbit"  # type: ignore[union-attr]


def test_system_time_recovers_what_was_known_before_supersession(
    employment_engine: ChronoGraphEngine,
) -> None:
    facts = employment_engine.facts_valid_at(
        timestamp("2026-03-01T00:00:00"),
        known_at=timestamp("2026-01-15T00:00:00"),
        predicate="WORKS_AT",
    )
    assert len(facts) == 1
    assert employment_engine.store.get_entity(facts[0].object_id or "").canonical_name == "Acme"  # type: ignore[union-attr]


def test_retroactive_fact_separates_valid_and_recorded_time() -> None:
    graph = ChronoGraphEngine()
    result = graph.ingest(
        episode(
            "retroactive",
            "Status record",
            event_time="2026-08-01T00:00:00",
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
    assert result.facts[0].recorded_at == timestamp("2026-09-20T00:00:00")
    assert not graph.facts_valid_at(
        timestamp("2026-08-05T00:00:00"),
        known_at=timestamp("2026-09-19T00:00:00"),
    )
    assert graph.facts_valid_at(
        timestamp("2026-08-05T00:00:00"),
        known_at=timestamp("2026-09-21T00:00:00"),
    )


def test_same_time_exclusive_assertions_are_disputed() -> None:
    graph = ChronoGraphEngine()
    graph.ingest(episode("source-a", "Alice works at Acme."))
    graph.ingest(
        episode(
            "source-b",
            "Alice works at Orbit.",
            observed_at="2026-01-02T00:00:00",
        )
    )
    assert len(graph.store.list_conflicts()) == 1
    assert {fact.status for fact in graph.store.list_facts()} == {FactStatus.DISPUTED}


def test_nonexclusive_relation_preserves_overlapping_values() -> None:
    graph = ChronoGraphEngine()
    for product in ("Tea", "Coffee"):
        graph.ingest(
            episode(
                f"preference-{product.lower()}",
                "Preference record",
                metadata={
                    "entities": [
                        {
                            "canonical_name": "Alice",
                            "entity_type": "Person",
                            "evidence_path": "record.person",
                        },
                        {
                            "canonical_name": product,
                            "entity_type": "Product",
                            "evidence_path": "record.product",
                        },
                    ],
                    "facts": [
                        {
                            "subject_name": "Alice",
                            "subject_type": "Person",
                            "predicate": "PREFERS",
                            "object_name": product,
                            "object_type": "Product",
                            "evidence_path": "record.preference",
                        }
                    ],
                },
            )
        )
    assert len(graph.facts_valid_at(timestamp("2026-02-01T00:00:00"))) == 2
    assert graph.store.list_conflicts() == []


def test_interval_and_learned_after_queries(employment_engine: ChronoGraphEngine) -> None:
    assert (
        len(
            employment_engine.facts_active_between(
                timestamp("2026-01-15T00:00:00"), timestamp("2026-02-15T00:00:00")
            )
        )
        == 2
    )
    learned = employment_engine.facts_learned_after(timestamp("2026-01-15T00:00:00"))
    assert len(learned) == 1
    assert learned[0].status is FactStatus.ACTIVE


def test_supersession_chain_and_snapshot_digest_are_deterministic(
    employment_engine: ChronoGraphEngine,
) -> None:
    old = employment_engine.store.list_facts()[0]
    assert len(employment_engine.supersession_chain(old.id)) == 2
    first = employment_engine.graph_as_of(timestamp("2026-01-15T00:00:00"))
    second = employment_engine.graph_as_of(timestamp("2026-01-15T00:00:00"))
    assert first.digest == second.digest
    assert [fact.id for fact in first.facts] == [old.id]
