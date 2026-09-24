"""Conflict detection and explicit fact supersession semantics."""

from __future__ import annotations

from chronograph_ai.models import (
    ConflictSet,
    Fact,
    FactStatus,
    RelationType,
    SupersessionDecision,
    TemporalBehavior,
)
from chronograph_ai.storage import GraphStore
from chronograph_ai.utils import intervals_overlap, stable_id


def _fact_value(fact: Fact) -> tuple[str, object]:
    return (
        ("entity", fact.object_id)
        if fact.object_id is not None
        else ("literal", fact.literal_value)
    )


class ConflictDetector:
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def incompatible(self, new_fact: Fact, relation: RelationType) -> list[Fact]:
        if relation.temporal_behavior is not TemporalBehavior.EXCLUSIVE:
            return []
        return [
            fact
            for fact in self.store.list_facts()
            if fact.subject_id == new_fact.subject_id
            and fact.predicate == new_fact.predicate
            and fact.status in {FactStatus.ACTIVE, FactStatus.DISPUTED}
            and _fact_value(fact) != _fact_value(new_fact)
            and intervals_overlap(
                fact.valid_from, fact.valid_to, new_fact.valid_from, new_fact.valid_to
            )
        ]


class TemporalResolver:
    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self.detector = ConflictDetector(store)

    def apply(
        self, new_fact: Fact, relation: RelationType
    ) -> tuple[Fact, list[SupersessionDecision], list[ConflictSet]]:
        supersessions: list[SupersessionDecision] = []
        conflicts: list[ConflictSet] = []
        for old in self.detector.incompatible(new_fact, relation):
            if new_fact.valid_from > old.valid_from:
                updated_old = old.model_copy(
                    update={
                        "valid_to": new_fact.valid_from
                        if old.valid_to is None or new_fact.valid_from < old.valid_to
                        else old.valid_to,
                        "status": FactStatus.SUPERSEDED,
                        "superseded_at": new_fact.recorded_at,
                        "superseded_by": new_fact.id,
                    }
                )
                self.store.update_fact(updated_old)
                supersessions.append(
                    SupersessionDecision(
                        old_fact_id=old.id,
                        new_fact_id=new_fact.id,
                        reason="later valid-time assertion replaced an exclusive relation",
                        decided_at=new_fact.recorded_at,
                        closed_old_interval=True,
                    )
                )
            else:
                disputed_old = old.model_copy(update={"status": FactStatus.DISPUTED})
                self.store.update_fact(disputed_old)
                new_fact = new_fact.model_copy(update={"status": FactStatus.DISPUTED})
                conflict = ConflictSet(
                    id=stable_id("conflict", old.id, new_fact.id),
                    subject_id=new_fact.subject_id,
                    predicate=new_fact.predicate,
                    fact_ids=sorted([old.id, new_fact.id]),
                    reason="overlapping exclusive facts lack a justified temporal succession",
                    detected_at=new_fact.recorded_at,
                    preferred_fact_id=None,
                )
                self.store.add_conflict(conflict)
                conflicts.append(conflict)
        return new_fact, supersessions, conflicts
