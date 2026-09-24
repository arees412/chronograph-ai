from __future__ import annotations

from datetime import datetime

import pytest
from conftest import episode, timestamp
from pydantic import ValidationError

from chronograph_ai.models import (
    EpisodeCreate,
    EpisodeSource,
    FactCandidate,
    OntologySchema,
    TemporalInterval,
)
from chronograph_ai.ontology import OntologyRegistry, default_ontology
from chronograph_ai.providers import RetryableProviderError, bounded_provider_call
from chronograph_ai.utils import content_hash, normalize_name, sanitize


@pytest.mark.parametrize("source_type", list(EpisodeSource))
def test_all_episode_source_types_are_typed(source_type: EpisodeSource) -> None:
    payload = episode("source", "content", source_type=source_type)
    assert payload.source_type is source_type


def test_episode_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        EpisodeCreate(
            source_type=EpisodeSource.EVENT,
            source_id="naive",
            content="content",
            event_time=datetime(2026, 1, 1),
        )


def test_episode_bounds_content_and_metadata() -> None:
    with pytest.raises(ValidationError):
        episode("too-large", "x" * 100_001)
    with pytest.raises(ValidationError, match="metadata exceeds"):
        episode("metadata", "content", metadata={"value": "x" * 33_000})


def test_temporal_interval_requires_order() -> None:
    with pytest.raises(ValidationError, match="valid_to"):
        TemporalInterval(
            valid_from=timestamp("2026-02-01T00:00:00"),
            valid_to=timestamp("2026-01-01T00:00:00"),
        )


def test_fact_candidate_requires_exactly_one_object() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        FactCandidate(
            subject_name="Alice",
            subject_type="Person",
            predicate="WORKS_AT",
            evidence_path="content",
        )


def test_default_ontology_declares_exclusive_employment() -> None:
    relation = default_ontology().relations["WORKS_AT"]
    assert relation.cardinality.value == "one"
    assert relation.temporal_behavior.value == "exclusive"


def test_ontology_versions_are_append_only() -> None:
    registry = OntologyRegistry()
    with pytest.raises(ValueError, match="already exists"):
        registry.register(default_ontology())
    custom = OntologySchema(
        version="2.0",
        entity_types=registry.current.entity_types,
        relations=registry.current.relations,
    )
    registry.register(custom)
    assert registry.current.version == "2.0"


def test_normalization_and_content_hash_are_deterministic() -> None:
    assert (
        normalize_name("  International-Business  Machines ") == "international business machines"
    )
    assert content_hash("same") == content_hash("same")
    assert content_hash("same") != content_hash("different")


def test_audit_sanitizer_redacts_common_secrets() -> None:
    safe = sanitize({"api_key": "sk-123456789012345678901", "message": "Bearer abc.def.ghi"})
    assert safe == {"api_key": "[REDACTED]", "message": "[REDACTED]"}


def test_retryable_provider_failure_is_bounded() -> None:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RetryableProviderError("temporary")
        return "ok"

    assert bounded_provider_call("test", operation, retries=2) == "ok"
    assert attempts == 3
