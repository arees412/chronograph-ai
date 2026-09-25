"""Provider protocols and deterministic offline implementations."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from typing import Protocol

from pydantic import TypeAdapter

from chronograph_ai.models import Confidence, EntityCandidate, Episode, FactCandidate
from chronograph_ai.utils import normalize_name, tokenize


class RetryableProviderError(RuntimeError):
    """Signals a bounded retryable provider failure."""


class EntityExtractionProvider(Protocol):
    name: str
    version: str

    def extract_entities(self, episode: Episode) -> list[EntityCandidate]: ...


class FactExtractionProvider(Protocol):
    name: str
    version: str

    def extract_facts(self, episode: Episode) -> list[FactCandidate]: ...


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    name: str

    def score(self, query: str, document: str) -> float: ...


class DeterministicEntityExtractor:
    """Extract only explicit fixture metadata and narrowly supported statements."""

    name = "deterministic"
    version = "1.0"
    _works = re.compile(
        r"^\s*(?P<subject>[A-Za-z][A-Za-z .'-]{0,100}?)\s+(?:now\s+)?works at\s+"
        r"(?P<object>[A-Za-z][A-Za-z0-9& .'-]{0,100}?)[.!]?\s*$",
        re.IGNORECASE,
    )
    _status = re.compile(
        r"^\s*(?P<subject>[A-Za-z][A-Za-z0-9 .'-]{0,100}?)\s+(?:now\s+)?(?:has\s+)?"
        r"status\s+(?:is\s+)?(?P<value>[A-Za-z0-9_-]+)[.!]?\s*$",
        re.IGNORECASE,
    )

    def extract_entities(self, episode: Episode) -> list[EntityCandidate]:
        raw = episode.metadata.get("entities")
        if raw is not None:
            return TypeAdapter(list[EntityCandidate]).validate_python(raw)
        match = self._works.match(episode.content)
        if match:
            return [
                EntityCandidate(
                    canonical_name=match.group("subject").strip(),
                    entity_type="Person",
                    confidence=Confidence.HIGH,
                    evidence_path="content:subject",
                ),
                EntityCandidate(
                    canonical_name=match.group("object").strip(),
                    entity_type="Organization",
                    confidence=Confidence.HIGH,
                    evidence_path="content:object",
                ),
            ]
        match = self._status.match(episode.content)
        if match:
            return [
                EntityCandidate(
                    canonical_name=match.group("subject").strip(),
                    entity_type=str(episode.metadata.get("subject_type", "Project")),
                    confidence=Confidence.MEDIUM,
                    evidence_path="content:subject",
                )
            ]
        return []


class DeterministicFactExtractor:
    """Parse explicit fixtures without guessing unsupported relationships."""

    name = "deterministic"
    version = "1.0"
    _works = DeterministicEntityExtractor._works
    _status = DeterministicEntityExtractor._status

    def extract_facts(self, episode: Episode) -> list[FactCandidate]:
        raw = episode.metadata.get("facts")
        if raw is not None:
            return TypeAdapter(list[FactCandidate]).validate_python(raw)
        match = self._works.match(episode.content)
        if match:
            return [
                FactCandidate(
                    subject_name=match.group("subject").strip(),
                    subject_type="Person",
                    predicate="WORKS_AT",
                    object_name=match.group("object").strip(),
                    object_type="Organization",
                    valid_from=episode.event_time,
                    confidence=Confidence.HIGH,
                    evidence_path="content",
                )
            ]
        match = self._status.match(episode.content)
        if match:
            return [
                FactCandidate(
                    subject_name=match.group("subject").strip(),
                    subject_type=str(episode.metadata.get("subject_type", "Project")),
                    predicate="HAS_STATUS",
                    literal_value=match.group("value"),
                    valid_from=episode.event_time,
                    confidence=Confidence.MEDIUM,
                    evidence_path="content",
                )
            ]
        return []


class DeterministicEmbeddingProvider:
    """Produce stable local vectors; scores are signals, not probabilities."""

    name = "deterministic-sha256"

    def __init__(self, dimensions: int = 32) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        for token in tokenize(text):
            raw = hashlib.sha256(token.encode("utf-8")).digest()
            for index in range(self.dimensions):
                values[index] += (raw[index] - 127.5) / 127.5
        return values


class NoOpEmbeddingProvider:
    name = "none"

    def embed(self, text: str) -> list[float]:
        del text
        return [0.0]


class DeterministicReranker:
    name = "deterministic-token-overlap"

    def score(self, query: str, document: str) -> float:
        query_tokens = set(tokenize(query))
        document_tokens = set(tokenize(document))
        if not query_tokens:
            return 0.0
        return len(query_tokens & document_tokens) / len(query_tokens)


class DeterministicModelProvider:
    """Provider facade used in CI and local development without external services."""

    def __init__(self) -> None:
        self.entity_extractor = DeterministicEntityExtractor()
        self.fact_extractor = DeterministicFactExtractor()
        self.embedding_provider = DeterministicEmbeddingProvider()
        self.reranker = DeterministicReranker()

    def extract_entities(self, episode: Episode) -> list[EntityCandidate]:
        return self.entity_extractor.extract_entities(episode)

    def extract_facts(self, episode: Episode) -> list[FactCandidate]:
        return self.fact_extractor.extract_facts(episode)

    def resolve_candidates(self, candidates: Sequence[EntityCandidate]) -> list[str]:
        return [normalize_name(candidate.canonical_name) for candidate in candidates]

    def summarize_entity(self, name: str, facts: Sequence[str]) -> str:
        return f"{name}: " + "; ".join(facts)

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        return [self.reranker.score(query, document) for document in documents]


def bounded_provider_call[T](operation: str, call: Callable[[], T], *, retries: int = 2) -> T:
    """Retry only explicitly temporary provider failures with a hard bound."""

    for attempt in range(retries + 1):
        try:
            return call()
        except RetryableProviderError:
            if attempt == retries:
                raise
    raise RuntimeError(f"unreachable provider retry state: {operation}")
