"""Deterministic replay of append-only episode fixtures."""

from __future__ import annotations

from collections.abc import Iterable

from chronograph_ai.engine import ChronoGraphEngine
from chronograph_ai.models import Episode, EpisodeCreate


def replay(
    episodes: Iterable[EpisodeCreate | Episode],
    *,
    engine: ChronoGraphEngine | None = None,
) -> tuple[ChronoGraphEngine, str]:
    target = engine or ChronoGraphEngine()
    normalized: list[EpisodeCreate] = []
    for item in episodes:
        payload = EpisodeCreate.model_validate(
            {
                "source_type": item.source_type,
                "source_id": item.source_id,
                "content": item.content,
                "event_time": item.event_time,
                "observed_at": item.observed_at or item.event_time,
                "metadata": item.metadata,
                "sensitivity": item.sensitivity,
                "idempotency_key": item.idempotency_key,
            }
        )
        normalized.append(payload)
    normalized.sort(
        key=lambda item: (item.observed_at or item.event_time, item.event_time, item.source_id)
    )
    for payload in normalized:
        target.ingest(payload)
    return target, target.state_digest(include_audit=False)
