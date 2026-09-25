from __future__ import annotations

import pytest
from conftest import episode

from chronograph_ai.engine import ChronoGraphEngine
from chronograph_ai.models import EntityStatus, ProposalStatus


def _two_people() -> tuple[ChronoGraphEngine, str, str, list[str]]:
    graph = ChronoGraphEngine()
    first = graph.ingest(
        episode(
            "person-1",
            "Identity record",
            metadata={
                "entities": [
                    {
                        "canonical_name": "Arees Shah",
                        "entity_type": "Person",
                        "identifiers": {"crm": "one"},
                        "evidence_path": "record.person",
                    }
                ]
            },
        )
    )
    second = graph.ingest(
        episode(
            "person-2",
            "Identity record",
            metadata={
                "entities": [
                    {
                        "canonical_name": "A. Shah",
                        "entity_type": "Person",
                        "aliases": ["Arees"],
                        "identifiers": {"support": "two"},
                        "evidence_path": "record.person",
                    }
                ]
            },
            event_time="2026-01-02T00:00:00",
        )
    )
    return graph, first.entities[0].id, second.entities[0].id, [first.episode.id, second.episode.id]


def test_approved_merge_preserves_source_and_provenance() -> None:
    graph, source_id, target_id, episodes = _two_people()
    proposal = graph.propose_merge(
        source_id,
        target_id,
        reason="operator confirmed shared identity",
        evidence_episode_ids=episodes,
    )
    assert proposal.status is ProposalStatus.PENDING
    approved = graph.decide_merge(proposal.id, approve=True, reason="reviewed evidence")
    source = graph.store.get_entity(source_id)
    target = graph.store.get_entity(target_id)
    assert approved.status is ProposalStatus.APPROVED
    assert source is not None and source.status is EntityStatus.MERGED
    assert source.merged_into == target_id
    assert target is not None and set(target.source_episode_ids) == set(episodes)
    assert "arees shah" in {alias.normalized for alias in target.aliases}


def test_rejected_merge_leaves_entities_active() -> None:
    graph, source_id, target_id, episodes = _two_people()
    proposal = graph.propose_merge(
        source_id,
        target_id,
        reason="name similarity",
        evidence_episode_ids=episodes,
    )
    rejected = graph.decide_merge(proposal.id, approve=False, reason="insufficient evidence")
    assert rejected.status is ProposalStatus.REJECTED
    assert graph.store.get_entity(source_id).status is EntityStatus.ACTIVE  # type: ignore[union-attr]
    assert graph.store.get_entity(target_id).status is EntityStatus.ACTIVE  # type: ignore[union-attr]


def test_merge_can_be_reversed_as_a_correction() -> None:
    graph, source_id, target_id, episodes = _two_people()
    proposal = graph.propose_merge(
        source_id,
        target_id,
        reason="operator confirmed",
        evidence_episode_ids=episodes,
    )
    graph.decide_merge(proposal.id, approve=True, reason="approved")
    reversed_proposal = graph.reverse_merge(proposal.id, reason="new contradictory evidence")
    source = graph.store.get_entity(source_id)
    assert reversed_proposal.status is ProposalStatus.REVERSED
    assert source is not None and source.status is EntityStatus.ACTIVE
    assert source.merged_into is None


def test_invalid_merge_transitions_are_rejected() -> None:
    graph, source_id, target_id, episodes = _two_people()
    with pytest.raises(ValueError, match="itself"):
        graph.propose_merge(source_id, source_id, reason="bad", evidence_episode_ids=episodes)
    proposal = graph.propose_merge(
        source_id, target_id, reason="review", evidence_episode_ids=episodes
    )
    graph.decide_merge(proposal.id, approve=False, reason="no")
    with pytest.raises(ValueError, match="approved"):
        graph.reverse_merge(proposal.id, reason="cannot reverse")
