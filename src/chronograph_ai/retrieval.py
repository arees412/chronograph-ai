"""Deterministic hybrid graph retrieval with explainable component scores."""

from __future__ import annotations

from datetime import datetime

from chronograph_ai.engine import ChronoGraphEngine, fact_text
from chronograph_ai.models import RankingEvidence, SearchResult
from chronograph_ai.utils import cosine_similarity, tokenize

DEFAULT_SOURCE_PRIORITY = {
    "manual_fact": 1.0,
    "structured_record": 0.9,
    "system_event": 0.8,
    "document_fragment": 0.7,
    "conversation": 0.6,
    "event": 0.6,
}


class HybridRetriever:
    """Ranks valid facts using documented deterministic weighted signals."""

    def __init__(
        self,
        engine: ChronoGraphEngine,
        *,
        source_priority: dict[str, float] | None = None,
    ) -> None:
        self.engine = engine
        self.source_priority = source_priority or DEFAULT_SOURCE_PRIORITY

    def search(
        self,
        query: str,
        *,
        valid_time: datetime,
        known_at: datetime | None = None,
        anchor_entity_id: str | None = None,
        predicate: str | None = None,
        max_depth: int = 2,
        max_results: int = 20,
    ) -> list[SearchResult]:
        if not 1 <= max_results <= 100:
            raise ValueError("max_results must be between 1 and 100")
        if not 0 <= max_depth <= 5:
            raise ValueError("max_depth must be between 0 and 5")
        query_tokens = set(tokenize(query))
        query_vector = self.engine.embedding_provider.embed(query)
        entities = self.engine.store.list_entities()
        by_id = {entity.id: entity for entity in entities}
        results: list[SearchResult] = []
        for fact in self.engine.facts_valid_at(valid_time, known_at=known_at, predicate=predicate):
            subject = by_id.get(fact.subject_id)
            if subject is None:
                continue
            object_entity = by_id.get(fact.object_id) if fact.object_id else None
            document = fact_text(fact, entities)
            document_tokens = set(tokenize(document))
            lexical = (
                len(query_tokens & document_tokens) / len(query_tokens) if query_tokens else 0.0
            )
            names = [subject.canonical_name, *(alias.value for alias in subject.aliases)]
            if object_entity:
                names.extend(
                    [
                        object_entity.canonical_name,
                        *(alias.value for alias in object_entity.aliases),
                    ]
                )
            entity_score = max(
                (
                    len(query_tokens & set(tokenize(name))) / len(query_tokens)
                    if query_tokens
                    else 0.0
                )
                for name in names
            )
            graph_score = self._graph_score(
                anchor_entity_id,
                [fact.subject_id, *([fact.object_id] if fact.object_id else [])],
                valid_time=valid_time,
                known_at=known_at,
                max_depth=max_depth,
            )
            temporal_score = 1.0
            source_score = self._source_score(fact.source_episode_ids)
            semantic_raw = cosine_similarity(
                query_vector, self.engine.embedding_provider.embed(document)
            )
            semantic_score = max(0.0, semantic_raw)
            final_score = (
                0.35 * lexical
                + 0.20 * entity_score
                + 0.15 * graph_score
                + 0.15 * temporal_score
                + 0.10 * source_score
                + 0.05 * semantic_score
            )
            explanation = [
                "weights: lexical=.35 entity=.20 graph=.15 temporal=.15 source=.10 semantic=.05",
                f"matched query tokens: {sorted(query_tokens & document_tokens)}",
                f"source priority signal: {source_score:.3f}",
                "component scores are ranking signals, not calibrated probabilities",
            ]
            evidence = [
                item
                for evidence_id in fact.evidence_ids
                if (item := self.engine.store.get_evidence(evidence_id)) is not None
            ]
            results.append(
                SearchResult(
                    fact=fact,
                    subject=subject,
                    object_entity=object_entity,
                    ranking=RankingEvidence(
                        lexical_score=lexical,
                        entity_score=entity_score,
                        graph_score=graph_score,
                        temporal_score=temporal_score,
                        source_score=source_score,
                        semantic_score=semantic_score,
                        final_score=final_score,
                        explanation=explanation,
                    ),
                    evidence=evidence,
                )
            )
        self.engine.instrumentation.increment("queries")
        return sorted(
            results,
            key=lambda item: (-item.ranking.final_score, item.fact.id),
        )[:max_results]

    def _source_score(self, episode_ids: list[str]) -> float:
        scores = []
        for episode_id in episode_ids:
            episode = self.engine.store.get_episode(episode_id)
            if episode:
                scores.append(self.source_priority.get(episode.source_type.value, 0.5))
        return max(scores, default=0.0)

    def _graph_score(
        self,
        anchor: str | None,
        endpoints: list[str],
        *,
        valid_time: datetime,
        known_at: datetime | None,
        max_depth: int,
    ) -> float:
        if anchor is None:
            return 0.0
        if anchor in endpoints:
            return 1.0
        if max_depth == 0:
            return 0.0
        distances: list[int] = []
        for endpoint in endpoints:
            path = self.engine.path(
                anchor,
                endpoint,
                valid_time=valid_time,
                known_at=known_at,
                max_depth=max_depth,
            )
            if path:
                distances.append(len(path) - 1)
        return 1.0 / (1.0 + min(distances)) if distances else 0.0
