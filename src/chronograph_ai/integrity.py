"""Graph integrity checks for provenance, time, supersession, and ontology rules."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime

from chronograph_ai.models import (
    Fact,
    FactStatus,
    IntegrityIssue,
    IntegrityReport,
    TemporalBehavior,
)
from chronograph_ai.ontology import OntologyRegistry
from chronograph_ai.storage import GraphStore
from chronograph_ai.utils import intervals_overlap


class IntegrityChecker:
    def __init__(
        self,
        store: GraphStore,
        ontology: OntologyRegistry,
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.ontology = ontology
        self.clock = clock

    def check(self) -> IntegrityReport:
        issues: list[IntegrityIssue] = []
        entities = {entity.id: entity for entity in self.store.list_entities()}
        evidence = {item.id: item for item in self.store.list_evidence()}
        facts = self.store.list_facts()
        fact_ids = {fact.id for fact in facts}
        tombstoned_records = {item.record_id for item in self.store.list_tombstones()}
        for fact in facts:
            missing_entities = [
                entity_id
                for entity_id in [fact.subject_id, fact.object_id]
                if entity_id and entity_id not in entities
            ]
            if missing_entities:
                issues.append(
                    IntegrityIssue(
                        code="orphan_fact",
                        record_ids=[fact.id, *missing_entities],
                        message="fact references missing entities",
                    )
                )
            if fact.valid_to is not None and fact.valid_to < fact.valid_from:
                issues.append(
                    IntegrityIssue(
                        code="invalid_temporal_interval",
                        record_ids=[fact.id],
                        message="fact valid_to precedes valid_from",
                    )
                )
            missing_evidence = [item for item in fact.evidence_ids if item not in evidence]
            if missing_evidence:
                issues.append(
                    IntegrityIssue(
                        code="missing_provenance",
                        record_ids=[fact.id, *missing_evidence],
                        message="fact references missing evidence",
                    )
                )
            if fact.superseded_by and fact.superseded_by not in fact_ids:
                issues.append(
                    IntegrityIssue(
                        code="dangling_supersession",
                        record_ids=[fact.id, fact.superseded_by],
                        message="supersession target is missing",
                    )
                )
        for item in evidence.values():
            if (
                self.store.get_episode(item.episode_id) is None
                and item.episode_id not in tombstoned_records
            ):
                issues.append(
                    IntegrityIssue(
                        code="orphan_evidence",
                        record_ids=[item.id, item.episode_id],
                        message="evidence episode is missing without a tombstone",
                    )
                )
        active = [fact for fact in facts if fact.status is FactStatus.ACTIVE]
        for index, left in enumerate(active):
            relation = self.ontology.current.relations.get(left.predicate)
            if relation is None or relation.temporal_behavior is not TemporalBehavior.EXCLUSIVE:
                continue
            for right in active[index + 1 :]:
                if (
                    left.subject_id == right.subject_id
                    and left.predicate == right.predicate
                    and (left.object_id, left.literal_value)
                    != (right.object_id, right.literal_value)
                    and intervals_overlap(
                        left.valid_from, left.valid_to, right.valid_from, right.valid_to
                    )
                ):
                    issues.append(
                        IntegrityIssue(
                            code="duplicate_active_exclusive_facts",
                            record_ids=[left.id, right.id],
                            message="exclusive relation has overlapping active values",
                        )
                    )
        issues.extend(self._forbidden_cycles(active))
        return IntegrityReport(ok=not issues, issues=issues, checked_at=self.clock())

    def _forbidden_cycles(self, facts: list[Fact]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        for name, relation in self.ontology.current.relations.items():
            if not relation.acyclic:
                continue
            adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
            for fact in facts:
                if fact.predicate == name and fact.object_id:
                    adjacency[fact.subject_id].append((fact.object_id, fact.id))
            issues.extend(self._cycles_for_relation(name, adjacency))
        return issues

    @staticmethod
    def _cycles_for_relation(
        name: str, adjacency: dict[str, list[tuple[str, str]]]
    ) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str, path_fact_ids: list[str]) -> None:
            if node in visiting:
                issues.append(
                    IntegrityIssue(
                        code="forbidden_cycle",
                        record_ids=path_fact_ids,
                        message=f"ontology forbids cycles for {name}",
                    )
                )
                return
            if node in visited:
                return
            visiting.add(node)
            for neighbor, fact_id in adjacency.get(node, []):
                visit(neighbor, [*path_fact_ids, fact_id])
            visiting.remove(node)
            visited.add(node)

        for start in sorted(adjacency):
            visit(start, [])
        return issues
