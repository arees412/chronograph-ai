"""Governed long-term memory assembly over temporal graph retrieval."""

from __future__ import annotations

from chronograph_ai.engine import ChronoGraphEngine, fact_text
from chronograph_ai.models import (
    FactStatus,
    MemoryBundle,
    MemoryItem,
    MemoryRequest,
    RetentionState,
)
from chronograph_ai.retrieval import HybridRetriever
from chronograph_ai.utils import digest


class MemoryAssembler:
    def __init__(self, engine: ChronoGraphEngine) -> None:
        self.engine = engine
        self.retriever = HybridRetriever(engine)

    def assemble(self, request: MemoryRequest) -> MemoryBundle:
        valid_time = request.historical_valid_time or request.current_time
        historical = request.historical_valid_time is not None or request.policy.include_historical
        candidates = self.retriever.search(
            request.query,
            valid_time=valid_time,
            anchor_entity_id=request.subject_entity_id,
            max_depth=request.policy.max_graph_depth,
            max_results=100,
        )
        items: list[MemoryItem] = []
        entity_ids: set[str] = set()
        character_count = 0
        truncated = False
        entities = self.engine.store.list_entities()
        for result in candidates:
            fact = result.fact
            if fact.sensitivity not in request.policy.allowed_sensitivities:
                continue
            if fact.status is FactStatus.DISPUTED and not request.policy.include_disputed:
                continue
            if not historical and fact.status is FactStatus.SUPERSEDED:
                continue
            if request.policy.allowed_entity_types is not None:
                involved = [
                    result.subject,
                    *([result.object_entity] if result.object_entity else []),
                ]
                if any(
                    entity.entity_type not in request.policy.allowed_entity_types
                    for entity in involved
                ):
                    continue
            if request.policy.max_age_days is not None:
                age = request.current_time - fact.valid_from
                if age.days > request.policy.max_age_days:
                    continue
            source_episodes = [
                episode
                for episode_id in fact.source_episode_ids
                if (episode := self.engine.store.get_episode(episode_id)) is not None
            ]
            if any(
                episode.retention_state in {RetentionState.EXPIRED, RetentionState.TOMBSTONED}
                for episode in source_episodes
            ):
                continue
            if request.policy.allowed_source_types is not None and not any(
                episode.source_type in request.policy.allowed_source_types
                for episode in source_episodes
            ):
                continue
            text = fact_text(fact, entities)
            involved_ids = {fact.subject_id, *([fact.object_id] if fact.object_id else [])}
            if len(entity_ids | involved_ids) > request.policy.max_entities:
                truncated = True
                continue
            if len(items) >= request.policy.max_items:
                truncated = True
                break
            if character_count + len(text) > request.policy.max_characters:
                truncated = True
                continue
            contradictions = [
                conflict.id
                for conflict in self.engine.store.list_conflicts()
                if fact.id in conflict.fact_ids
            ]
            items.append(
                MemoryItem(
                    fact=fact,
                    text=text,
                    source_episode_ids=fact.source_episode_ids,
                    evidence_ids=fact.evidence_ids,
                    ranking=result.ranking,
                    contradictions=contradictions,
                )
            )
            entity_ids.update(involved_ids)
            character_count += len(text)
        payload = {
            "agent_id": request.agent_id,
            "valid_time": valid_time,
            "fact_ids": [item.fact.id for item in items],
            "characters": character_count,
        }
        bundle = MemoryBundle(
            request=request,
            items=items,
            entity_ids=sorted(entity_ids),
            character_count=character_count,
            truncated=truncated,
            generated_at=request.current_time,
            digest=digest(payload),
        )
        self.engine.instrumentation.increment("memory_items_returned", len(items))
        self.engine.audit.record(
            "memory_assembly",
            {
                "agent_id_hash": digest(request.agent_id),
                "query_hash": digest(request.query),
                "fact_ids": [item.fact.id for item in items],
                "policy": request.policy.model_dump(mode="json"),
            },
            occurred_at=request.current_time,
        )
        return bundle
