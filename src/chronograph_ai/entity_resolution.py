"""Conservative deterministic entity resolution and governed merge controls."""

from __future__ import annotations

from datetime import datetime

from chronograph_ai.models import (
    Entity,
    EntityAlias,
    EntityCandidate,
    EntityMergeProposal,
    EntityResolution,
    EntityStatus,
    ProposalStatus,
    ResolutionOutcome,
)
from chronograph_ai.ontology import OntologyRegistry
from chronograph_ai.storage import GraphStore
from chronograph_ai.utils import normalize_name, stable_id


class EntityResolver:
    def __init__(self, store: GraphStore, ontology: OntologyRegistry) -> None:
        self.store = store
        self.ontology = ontology

    def resolve(
        self, candidate: EntityCandidate, *, episode_id: str, recorded_at: datetime
    ) -> EntityResolution:
        self.ontology.validate_entity_type(candidate.entity_type)
        normalized = normalize_name(candidate.canonical_name)
        active = [
            entity
            for entity in self.store.list_entities()
            if entity.status is EntityStatus.ACTIVE and entity.entity_type == candidate.entity_type
        ]
        identifier_matches = [
            entity
            for entity in active
            if candidate.identifiers
            and any(
                entity.identifiers.get(key) == value
                for key, value in candidate.identifiers.items()
                if value
            )
        ]
        lexical_matches = [
            entity
            for entity in active
            if normalized
            in {entity.normalized_name, *(alias.normalized for alias in entity.aliases)}
        ]
        matches = identifier_matches or lexical_matches
        unique = {entity.id: entity for entity in matches}
        if len(unique) == 1:
            entity = next(iter(unique.values()))
            updated = self._enrich(entity, candidate, episode_id, recorded_at)
            self.store.upsert_entity(updated)
            reason = (
                "exact identifier match" if identifier_matches else "exact canonical/alias match"
            )
            return EntityResolution(
                outcome=ResolutionOutcome.RESOLVED_EXISTING,
                entity=updated,
                candidate_ids=[updated.id],
                reason=reason,
            )
        entity = self._create(candidate, episode_id, recorded_at)
        self.store.upsert_entity(entity)
        if len(unique) > 1:
            return EntityResolution(
                outcome=ResolutionOutcome.AMBIGUOUS,
                entity=entity,
                candidate_ids=sorted(unique),
                reason="multiple exact matches; candidate preserved as a separate identity",
            )
        return EntityResolution(
            outcome=ResolutionOutcome.NEW_ENTITY,
            entity=entity,
            reason="no exact identifier or alias match",
        )

    def _create(self, candidate: EntityCandidate, episode_id: str, recorded_at: datetime) -> Entity:
        normalized = normalize_name(candidate.canonical_name)
        entity_id = stable_id(
            "entity", candidate.entity_type, normalized, candidate.identifiers, episode_id
        )
        aliases = [
            EntityAlias(
                value=alias,
                normalized=normalize_name(alias),
                source_episode_id=episode_id,
            )
            for alias in candidate.aliases
            if normalize_name(alias) != normalized
        ]
        return Entity(
            id=entity_id,
            canonical_name=candidate.canonical_name.strip(),
            normalized_name=normalized,
            entity_type=candidate.entity_type,
            aliases=aliases,
            identifiers=candidate.identifiers,
            source_episode_ids=[episode_id],
            created_at=recorded_at,
            updated_at=recorded_at,
            confidence=candidate.confidence,
        )

    def _enrich(
        self,
        entity: Entity,
        candidate: EntityCandidate,
        episode_id: str,
        recorded_at: datetime,
    ) -> Entity:
        aliases = list(entity.aliases)
        known = {alias.normalized for alias in aliases} | {entity.normalized_name}
        for alias in [candidate.canonical_name, *candidate.aliases]:
            normalized = normalize_name(alias)
            if normalized and normalized not in known:
                aliases.append(
                    EntityAlias(
                        value=alias,
                        normalized=normalized,
                        source_episode_id=episode_id,
                    )
                )
                known.add(normalized)
        return entity.model_copy(
            update={
                "aliases": aliases,
                "identifiers": {**entity.identifiers, **candidate.identifiers},
                "source_episode_ids": sorted({*entity.source_episode_ids, episode_id}),
                "updated_at": recorded_at,
            }
        )

    def propose_merge(
        self,
        source_entity_id: str,
        target_entity_id: str,
        *,
        reason: str,
        evidence_episode_ids: list[str],
        recorded_at: datetime,
    ) -> EntityMergeProposal:
        if source_entity_id == target_entity_id:
            raise ValueError("an entity cannot be merged into itself")
        source = self.store.get_entity(source_entity_id)
        target = self.store.get_entity(target_entity_id)
        if source is None or target is None:
            raise KeyError("both merge entities must exist")
        proposal = EntityMergeProposal(
            id=stable_id("merge-proposal", source_entity_id, target_entity_id, reason),
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            reason=reason,
            evidence_episode_ids=sorted(set(evidence_episode_ids)),
            created_at=recorded_at,
        )
        self.store.add_merge_proposal(proposal)
        return proposal

    def decide_merge(
        self,
        proposal_id: str,
        *,
        approve: bool,
        reason: str,
        recorded_at: datetime,
    ) -> EntityMergeProposal:
        proposal = self.store.get_merge_proposal(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.status is not ProposalStatus.PENDING:
            raise ValueError("merge proposal has already been decided")
        status = ProposalStatus.APPROVED if approve else ProposalStatus.REJECTED
        decided = proposal.model_copy(
            update={"status": status, "decided_at": recorded_at, "decision_reason": reason}
        )
        if approve:
            source = self.store.get_entity(proposal.source_entity_id)
            target = self.store.get_entity(proposal.target_entity_id)
            if source is None or target is None:
                raise KeyError("merge entities no longer exist")
            aliases = list(target.aliases)
            known = {alias.normalized for alias in aliases} | {target.normalized_name}
            for value, normalized, source_episode_id in [
                (source.canonical_name, source.normalized_name, source.source_episode_ids[0]),
                *[
                    (alias.value, alias.normalized, alias.source_episode_id)
                    for alias in source.aliases
                ],
            ]:
                if normalized not in known:
                    aliases.append(
                        EntityAlias(
                            value=value,
                            normalized=normalized,
                            source_episode_id=source_episode_id,
                        )
                    )
                    known.add(normalized)
            self.store.upsert_entity(
                target.model_copy(
                    update={
                        "aliases": aliases,
                        "source_episode_ids": sorted(
                            {*target.source_episode_ids, *source.source_episode_ids}
                        ),
                        "updated_at": recorded_at,
                    }
                )
            )
            self.store.upsert_entity(
                source.model_copy(
                    update={
                        "status": EntityStatus.MERGED,
                        "merged_into": target.id,
                        "updated_at": recorded_at,
                    }
                )
            )
        self.store.update_merge_proposal(decided)
        return decided

    def reverse_merge(
        self, proposal_id: str, *, reason: str, recorded_at: datetime
    ) -> EntityMergeProposal:
        proposal = self.store.get_merge_proposal(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.status is not ProposalStatus.APPROVED:
            raise ValueError("only an approved merge can be reversed")
        source = self.store.get_entity(proposal.source_entity_id)
        if source is None:
            raise KeyError(proposal.source_entity_id)
        self.store.upsert_entity(
            source.model_copy(
                update={
                    "status": EntityStatus.ACTIVE,
                    "merged_into": None,
                    "updated_at": recorded_at,
                }
            )
        )
        reversed_proposal = proposal.model_copy(
            update={
                "status": ProposalStatus.REVERSED,
                "decided_at": recorded_at,
                "decision_reason": reason,
            }
        )
        self.store.update_merge_proposal(reversed_proposal)
        return reversed_proposal
