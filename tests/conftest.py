from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from chronograph_ai.engine import ChronoGraphEngine
from chronograph_ai.models import EpisodeCreate, EpisodeSource, Sensitivity


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def episode(
    source_id: str,
    content: str,
    event_time: str = "2026-01-01T00:00:00",
    *,
    observed_at: str | None = None,
    metadata: dict[str, Any] | None = None,
    sensitivity: Sensitivity = Sensitivity.PUBLIC,
    idempotency_key: str | None = None,
    source_type: EpisodeSource = EpisodeSource.STRUCTURED_RECORD,
) -> EpisodeCreate:
    return EpisodeCreate(
        source_type=source_type,
        source_id=source_id,
        content=content,
        event_time=timestamp(event_time),
        observed_at=timestamp(observed_at or event_time),
        metadata=metadata or {},
        sensitivity=sensitivity,
        idempotency_key=idempotency_key,
    )


@pytest.fixture
def employment_engine() -> ChronoGraphEngine:
    graph = ChronoGraphEngine()
    graph.ingest(episode("employment-1", "Alice works at Acme."))
    graph.ingest(
        episode(
            "employment-2",
            "Alice now works at Orbit.",
            event_time="2026-02-01T00:00:00",
        )
    )
    return graph
