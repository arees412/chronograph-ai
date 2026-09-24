"""ChronoGraph orchestration for ingestion, temporal mutation, and graph queries."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from datetime import datetime
from threading import RLock
from typing import Any

from pydantic import TypeAdapter

from chronograph_ai.audit import AuditLogger, make_evidence_bundle
from chronograph_ai.entity_resolution import EntityResolver
from chronograph_ai.models import (
    Entity,
    EntityCandidate,
    EntityMergeProposal,
    Episode,
    EpisodeCreate,
    EvidenceBundle,
    Fact,
    FactCandidate,
    FactEvidence,
    FactStatus,
    GraphMutation,
    GraphSnapshot,
    IngestionResult,
    ObjectKind,
    ProposalStatus,
)
from chronograph_ai.observability import InMemoryInstrumentation, Instrumentation
from chronograph_ai.ontology import OntologyRegistry
from chronograph_ai.providers import (
    DeterministicEmbeddingProvider,
    DeterministicEntityExtractor,
    DeterministicFactExtractor,
    DeterministicReranker,
    EmbeddingProvider,
    EntityExtractionProvider,
    FactExtractionProvider,
    Reranker,
    bounded_provider_call,
)
from chronograph_ai.storage import GraphStore, InMemoryGraphStore
from chronograph_ai.temporal import TemporalResolver
from chronograph_ai.utils import (
    content_hash,
    digest,
    interval_contains,
    intervals_overlap,
    normalize_name,
    stable_id,
    utc_now,
)


class ChronoGraphEngine:
    """Typed, deterministic temporal knowledge engine.

    Ingested text is always treated as data. Only configured providers and the
    ontology may propose graph mutations, and every accepted fact requires evidence.
    """

    def __init__(
        self,
        *,
        store: GraphStore | None = None,
        ontology: OntologyRegistry | None = None,
        entity_extractor: EntityExtractionProvider | None = None,
        fact_extractor: FactExtractionProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: Reranker | None = None,
        instrumentation: Instrumentation | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.store = store or InMemoryGraphStore()
        self.ontology = ontology or OntologyRegistry()
        self.entity_extractor = entity_extractor or DeterministicEntityExtractor()
        self.fact_extractor = fact_extractor or DeterministicFactExtractor()
        self.embedding_provider = embedding_provider or DeterministicEmbeddingProvider()
        self.reranker = reranker or DeterministicReranker()
        self.instrumentation = instrumentation or InMemoryInstrumentation()
        self.clock = clock
        self.audit = AuditLogger(self.store, clock)
        self.entities = EntityResolver(self.store, self.ontology)
        self.temporal = TemporalResolver(self.store)
        self._lock = RLock()

    def ingest(self, payload: EpisodeCreate) -> IngestionResult:
        """Validate providers before committing append-only evidence and projections."""

        with self._lock:
            payload_hash = content_hash(payload.content)
            duplicate = self._find_duplicate(payload, payload_hash)
            if duplicate is not None:
                return self._duplicate_result(duplicate)
            recorded_at = payload.observed_at or self.clock()
            episode_id = stable_id(
                "episode",
                payload.source_type,
                payload.source_id,
                payload.event_time.isoformat(),
                payload_hash,
                payload.idempotency_key,
            )
            episode = Episode(
                **payload.model_dump(),
                id=episode_id,
                ingested_at=recorded_at,
                content_hash=payload_hash,
            )
            entity_candidates = TypeAdapter(list[EntityCandidate]).validate_python(
                bounded_provider_call(
                    "extract_entities", lambda: self.entity_extractor.extract_entities(episode)
                )
            )
            fact_candidates = TypeAdapter(list[FactCandidate]).validate_python(
                bounded_provider_call(
                    "extract_facts", lambda: self.fact_extractor.extract_facts(episode)
                )
            )
            entity_candidates = self._complete_entity_candidates(entity_candidates, fact_candidates)
            self._prevalidate(entity_candidates, fact_candidates)

            self.store.add_episode(episode)
            self.instrumentation.increment("episodes_ingested")
            resolved: dict[tuple[str, str], Entity] = {}
            touched_entities: dict[str, Entity] = {}
            for entity_candidate in entity_candidates:
                resolution = self.entities.resolve(
                    entity_candidate, episode_id=episode.id, recorded_at=recorded_at
                )
                resolved[
                    (
                        normalize_name(entity_candidate.canonical_name),
                        entity_candidate.entity_type,
                    )
                ] = resolution.entity
                touched_entities[resolution.entity.id] = resolution.entity
                self.instrumentation.increment(
                    "entities_created"
                    if resolution.outcome.value == "new_entity"
                    else "entities_resolved"
                )

            touched_facts: dict[str, Fact] = {}
            decisions: list[str] = []
            for index, fact_candidate in enumerate(fact_candidates):
                subject = resolved[
                    (
                        normalize_name(fact_candidate.subject_name),
                        fact_candidate.subject_type,
                    )
                ]
                object_entity = None
                if (
                    fact_candidate.object_name is not None
                    and fact_candidate.object_type is not None
                ):
                    object_entity = resolved[
                        (
                            normalize_name(fact_candidate.object_name),
                            fact_candidate.object_type,
                        )
                    ]
                relation = self.ontology.validate_fact_candidate(
                    fact_candidate, subject, object_entity
                )
                evidence = FactEvidence(
                    id=stable_id("evidence", episode.id, index, fact_candidate.evidence_path),
                    episode_id=episode.id,
                    source_path=fact_candidate.evidence_path,
                    extraction_method=self.fact_extractor.name,
                    extractor_version=self.fact_extractor.version,
                    recorded_at=recorded_at,
                    content_hash=episode.content_hash,
                )
                fact = Fact(
                    id=stable_id("fact", episode.id, index, fact_candidate.model_dump(mode="json")),
                    subject_id=subject.id,
                    predicate=fact_candidate.predicate,
                    object_id=object_entity.id if object_entity else None,
                    literal_value=fact_candidate.literal_value,
                    valid_from=fact_candidate.valid_from or episode.event_time,
                    valid_to=fact_candidate.valid_to,
                    asserted_valid_to=fact_candidate.valid_to,
                    recorded_at=recorded_at,
                    confidence=fact_candidate.confidence,
                    evidence_ids=[evidence.id],
                    source_episode_ids=[episode.id],
                    created_by=self.fact_extractor.name,
                    schema_version=self.ontology.current.version,
                    sensitivity=episode.sensitivity,
                )
                existing = self._equivalent_fact(fact)
                self.store.add_evidence(evidence)
                if existing is not None:
                    updated = existing.model_copy(
                        update={
                            "evidence_ids": sorted({*existing.evidence_ids, evidence.id}),
                            "source_episode_ids": sorted(
                                {*existing.source_episode_ids, episode.id}
                            ),
                        }
                    )
                    self.store.update_fact(updated)
                    touched_facts[updated.id] = updated
                    decisions.append(f"coalesced evidence into fact {updated.id}")
                    continue
                fact, supersessions, conflicts = self.temporal.apply(fact, relation)
                self.store.add_fact(fact)
                touched_facts[fact.id] = fact
                self.instrumentation.increment("facts_created")
                if supersessions:
                    self.instrumentation.increment("facts_superseded", len(supersessions))
                    decisions.extend(decision.reason for decision in supersessions)
                if conflicts:
                    self.instrumentation.increment("conflicts_detected", len(conflicts))
                    decisions.extend(conflict.reason for conflict in conflicts)

            mutation_entity_ids = sorted(touched_entities)
            mutation_fact_ids = sorted(touched_facts)
            mutation_payload = {
                "operation": "episode_ingestion",
                "episode_id": episode.id,
                "entity_ids": mutation_entity_ids,
                "fact_ids": mutation_fact_ids,
                "recorded_at": recorded_at,
            }
            mutation = GraphMutation(
                id=stable_id("mutation", episode.id),
                operation="episode_ingestion",
                entity_ids=mutation_entity_ids,
                fact_ids=mutation_fact_ids,
                episode_id=episode.id,
                recorded_at=recorded_at,
                digest=digest(mutation_payload),
            )
            self.audit.record(
                "episode_ingestion",
                {
                    "episode_id": episode.id,
                    "source_id": episode.source_id,
                    "content_hash": episode.content_hash,
                    "entity_ids": mutation.entity_ids,
                    "fact_ids": mutation.fact_ids,
                    "temporal_decisions": decisions,
                },
                occurred_at=recorded_at,
            )
            return IngestionResult(
                episode=episode,
                entities=sorted(touched_entities.values(), key=lambda item: item.id),
                facts=sorted(touched_facts.values(), key=lambda item: item.id),
                mutation=mutation,
            )

    def _find_duplicate(self, payload: EpisodeCreate, payload_hash: str) -> Episode | None:
        if payload.idempotency_key:
            existing = self.store.find_episode_by_idempotency(payload.idempotency_key)
            if existing is not None:
                if existing.content_hash != payload_hash:
                    raise ValueError("idempotency key was previously used for different content")
                return existing
        for existing in self.store.list_episodes():
            if (
                existing.source_type == payload.source_type
                and existing.source_id == payload.source_id
                and existing.event_time == payload.event_time
                and existing.content_hash == payload_hash
            ):
                return existing
        return None

    def _duplicate_result(self, episode: Episode) -> IngestionResult:
        entities = [
            entity
            for entity in self.store.list_entities()
            if episode.id in entity.source_episode_ids
        ]
        facts = [fact for fact in self.store.list_facts() if episode.id in fact.source_episode_ids]
        mutation_entity_ids = sorted(entity.id for entity in entities)
        mutation_fact_ids = sorted(fact.id for fact in facts)
        mutation_payload = {
            "operation": "duplicate_ingestion",
            "episode_id": episode.id,
            "entity_ids": mutation_entity_ids,
            "fact_ids": mutation_fact_ids,
            "recorded_at": episode.ingested_at,
        }
        return IngestionResult(
            episode=episode,
            entities=entities,
            facts=facts,
            mutation=GraphMutation(
                id=stable_id("duplicate-mutation", episode.id),
                operation="duplicate_ingestion",
                entity_ids=mutation_entity_ids,
                fact_ids=mutation_fact_ids,
                episode_id=episode.id,
                recorded_at=episode.ingested_at,
                digest=digest(mutation_payload),
            ),
            duplicate=True,
        )

    def _complete_entity_candidates(
        self,
        candidates: list[EntityCandidate],
        facts: list[FactCandidate],
    ) -> list[EntityCandidate]:
        completed = list(candidates)
        keys = {(normalize_name(item.canonical_name), item.entity_type) for item in completed}
        for fact in facts:
            needed = [(fact.subject_name, fact.subject_type, f"{fact.evidence_path}:subject")]
            if fact.object_name is not None and fact.object_type is not None:
                needed.append((fact.object_name, fact.object_type, f"{fact.evidence_path}:object"))
            for name, entity_type, path in needed:
                key = (normalize_name(name), entity_type)
                if key not in keys:
                    completed.append(
                        EntityCandidate(
                            canonical_name=name,
                            entity_type=entity_type,
                            confidence=fact.confidence,
                            evidence_path=path,
                        )
                    )
                    keys.add(key)
        return completed

    def _prevalidate(self, entities: list[EntityCandidate], facts: list[FactCandidate]) -> None:
        available = {(normalize_name(item.canonical_name), item.entity_type) for item in entities}
        for entity in entities:
            self.ontology.validate_entity_type(entity.entity_type)
        for fact in facts:
            relation = self.ontology.current.relations.get(fact.predicate)
            if relation is None:
                raise ValueError(f"unknown relation: {fact.predicate}")
            if fact.subject_type not in relation.subject_types:
                raise ValueError(f"invalid subject type for {fact.predicate}")
            if (normalize_name(fact.subject_name), fact.subject_type) not in available:
                raise ValueError("fact subject has no evidence-backed entity candidate")
            if relation.object_kind is ObjectKind.ENTITY:
                if fact.object_name is None or fact.object_type is None:
                    raise ValueError(f"{fact.predicate} requires an entity object")
                if fact.object_type not in relation.object_types:
                    raise ValueError(f"invalid object type for {fact.predicate}")
                if (normalize_name(fact.object_name), fact.object_type) not in available:
                    raise ValueError("fact object has no evidence-backed entity candidate")
            elif fact.literal_value is None:
                raise ValueError(f"{fact.predicate} requires a literal value")

    def _equivalent_fact(self, candidate: Fact) -> Fact | None:
        for fact in self.store.list_facts():
            if (
                fact.subject_id == candidate.subject_id
                and fact.predicate == candidate.predicate
                and fact.object_id == candidate.object_id
                and fact.literal_value == candidate.literal_value
                and fact.valid_from == candidate.valid_from
                and fact.asserted_valid_to == candidate.asserted_valid_to
            ):
                return fact
        return None

    def facts_valid_at(
        self,
        valid_time: datetime,
        *,
        known_at: datetime | None = None,
        entity_id: str | None = None,
        predicate: str | None = None,
    ) -> list[Fact]:
        facts: list[Fact] = []
        for fact in self.store.list_facts():
            if entity_id and fact.subject_id != entity_id and fact.object_id != entity_id:
                continue
            if predicate and fact.predicate != predicate:
                continue
            if fact.status in {FactStatus.INVALIDATED, FactStatus.RETRACTED}:
                continue
            if known_at is not None and fact.recorded_at > known_at:
                continue
            effective_end = fact.valid_to
            if (
                known_at is not None
                and fact.superseded_at is not None
                and known_at < fact.superseded_at
            ):
                effective_end = fact.asserted_valid_to
            if interval_contains(fact.valid_from, effective_end, valid_time):
                facts.append(fact)
        return sorted(facts, key=lambda item: (item.subject_id, item.predicate, item.id))

    def facts_active_between(
        self, start: datetime, end: datetime, *, entity_id: str | None = None
    ) -> list[Fact]:
        if end < start:
            raise ValueError("end must not precede start")
        return [
            fact
            for fact in self.store.list_facts()
            if (entity_id is None or entity_id in {fact.subject_id, fact.object_id})
            and fact.status not in {FactStatus.INVALIDATED, FactStatus.RETRACTED}
            and intervals_overlap(fact.valid_from, fact.valid_to, start, end)
        ]

    def facts_learned_after(self, timestamp: datetime) -> list[Fact]:
        return [fact for fact in self.store.list_facts() if fact.recorded_at > timestamp]

    def entity_history(self, entity_id: str) -> list[Fact]:
        if self.store.get_entity(entity_id) is None:
            raise KeyError(entity_id)
        return [
            fact
            for fact in self.store.list_facts()
            if entity_id in {fact.subject_id, fact.object_id}
        ]

    def supersession_chain(self, fact_id: str) -> list[Fact]:
        first = self.store.get_fact(fact_id)
        if first is None:
            raise KeyError(fact_id)
        chain = [first]
        seen = {first.id}
        current = first
        while current.superseded_by:
            if current.superseded_by in seen:
                raise ValueError("supersession cycle detected")
            successor = self.store.get_fact(current.superseded_by)
            if successor is None:
                break
            chain.append(successor)
            seen.add(successor.id)
            current = successor
        return chain

    def graph_as_of(
        self, valid_time: datetime, *, known_at: datetime | None = None
    ) -> GraphSnapshot:
        facts = self.facts_valid_at(valid_time, known_at=known_at)
        entity_ids = {fact.subject_id for fact in facts} | {
            fact.object_id for fact in facts if fact.object_id
        }
        entities = [entity for entity in self.store.list_entities() if entity.id in entity_ids]
        evidence_ids = {evidence_id for fact in facts for evidence_id in fact.evidence_ids}
        evidence = [item for item in self.store.list_evidence() if item.id in evidence_ids]
        payload = {
            "valid_time": valid_time,
            "known_at": known_at,
            "entities": [item.model_dump(mode="json") for item in entities],
            "facts": [item.model_dump(mode="json") for item in facts],
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }
        return GraphSnapshot(
            valid_time=valid_time,
            known_at=known_at,
            entities=entities,
            facts=facts,
            evidence=evidence,
            generated_at=known_at or valid_time,
            digest=digest(payload),
        )

    def neighbors(
        self,
        entity_id: str,
        *,
        valid_time: datetime,
        known_at: datetime | None = None,
        predicates: set[str] | None = None,
        limit: int = 100,
    ) -> list[Entity]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        adjacent: set[str] = set()
        for fact in self.facts_valid_at(valid_time, known_at=known_at):
            if predicates and fact.predicate not in predicates:
                continue
            if fact.subject_id == entity_id and fact.object_id:
                adjacent.add(fact.object_id)
            elif fact.object_id == entity_id:
                adjacent.add(fact.subject_id)
        return [
            entity
            for entity_id_ in sorted(adjacent)[:limit]
            if (entity := self.store.get_entity(entity_id_)) is not None
        ]

    def path(
        self,
        start_entity_id: str,
        end_entity_id: str,
        *,
        valid_time: datetime,
        known_at: datetime | None = None,
        predicates: set[str] | None = None,
        max_depth: int = 4,
    ) -> list[str]:
        if not 1 <= max_depth <= 5:
            raise ValueError("max_depth must be between 1 and 5")
        queue: deque[list[str]] = deque([[start_entity_id]])
        seen = {start_entity_id}
        while queue:
            current_path = queue.popleft()
            if len(current_path) - 1 >= max_depth:
                continue
            for neighbor in self.neighbors(
                current_path[-1],
                valid_time=valid_time,
                known_at=known_at,
                predicates=predicates,
            ):
                if neighbor.id == end_entity_id:
                    self.instrumentation.observe("graph_traversal_depth", len(current_path))
                    return [*current_path, neighbor.id]
                if neighbor.id not in seen:
                    seen.add(neighbor.id)
                    queue.append([*current_path, neighbor.id])
        return []

    def provenance(self, fact_id: str) -> dict[str, Any]:
        fact = self.store.get_fact(fact_id)
        if fact is None:
            raise KeyError(fact_id)
        evidence = []
        for evidence_id in fact.evidence_ids:
            evidence_item = self.store.get_evidence(evidence_id)
            if evidence_item is not None:
                evidence.append(evidence_item)
        episodes = []
        for episode_id in fact.source_episode_ids:
            episode_item = self.store.get_episode(episode_id)
            if episode_item is not None:
                episodes.append(episode_item)
        return {
            "fact": fact,
            "evidence": evidence,
            "episodes": episodes,
            "supersession_chain": self.supersession_chain(fact_id),
        }

    def evidence_bundle(self, fact_id: str) -> EvidenceBundle:
        provenance = self.provenance(fact_id)
        fact = provenance["fact"]
        episodes = provenance["episodes"]
        return make_evidence_bundle(
            operation="fact_provenance",
            input_ids=[fact_id],
            source_hashes=[episode.content_hash for episode in episodes],
            entity_ids=[fact.subject_id, *([fact.object_id] if fact.object_id else [])],
            fact_ids=[item.id for item in provenance["supersession_chain"]],
            temporal_decisions=[
                f"valid=[{fact.valid_from.isoformat()}, "
                f"{fact.valid_to.isoformat() if fact.valid_to else 'open'})",
                f"recorded_at={fact.recorded_at.isoformat()}",
            ],
            policy_decisions=[],
            created_at=self.clock(),
        )

    def propose_merge(
        self,
        source_entity_id: str,
        target_entity_id: str,
        *,
        reason: str,
        evidence_episode_ids: list[str],
    ) -> EntityMergeProposal:
        now = self.clock()
        proposal = self.entities.propose_merge(
            source_entity_id,
            target_entity_id,
            reason=reason,
            evidence_episode_ids=evidence_episode_ids,
            recorded_at=now,
        )
        self.audit.record("merge_proposal", proposal.model_dump(mode="json"), occurred_at=now)
        return proposal

    def decide_merge(self, proposal_id: str, *, approve: bool, reason: str) -> EntityMergeProposal:
        now = self.clock()
        proposal = self.entities.decide_merge(
            proposal_id, approve=approve, reason=reason, recorded_at=now
        )
        self.audit.record(
            "merge_decision",
            {
                "proposal_id": proposal.id,
                "status": proposal.status,
                "reason": reason,
            },
            occurred_at=now,
        )
        return proposal

    def reverse_merge(self, proposal_id: str, *, reason: str) -> EntityMergeProposal:
        now = self.clock()
        proposal = self.entities.reverse_merge(proposal_id, reason=reason, recorded_at=now)
        self.audit.record(
            "merge_correction",
            {"proposal_id": proposal.id, "status": ProposalStatus.REVERSED, "reason": reason},
            occurred_at=now,
        )
        return proposal

    def state_digest(self, *, include_audit: bool = True) -> str:
        state = self.store.export_state()
        if not include_audit:
            state = {key: value for key, value in state.items() if key != "audit"}
        return digest(state)

    def stats(self) -> dict[str, int | str]:
        return {
            "backend": self.store.backend_name,
            "episodes": len(self.store.list_episodes()),
            "entities": len(self.store.list_entities()),
            "facts": len(self.store.list_facts()),
            "evidence": len(self.store.list_evidence()),
            "conflicts": len(self.store.list_conflicts()),
            "merge_proposals": len(self.store.list_merge_proposals()),
            "audit_events": len(self.store.list_audit()),
            "tombstones": len(self.store.list_tombstones()),
        }


def fact_text(fact: Fact, entities: Iterable[Entity]) -> str:
    by_id = {entity.id: entity for entity in entities}
    subject = by_id[fact.subject_id].canonical_name
    object_value = (
        by_id[fact.object_id].canonical_name
        if fact.object_id and fact.object_id in by_id
        else str(fact.literal_value)
    )
    return f"{subject} {fact.predicate.replace('_', ' ').lower()} {object_value}"
