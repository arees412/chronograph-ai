"""Sanitized audit events and deterministic evidence bundles."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from chronograph_ai.models import AuditEvent, EvidenceBundle
from chronograph_ai.storage import GraphStore
from chronograph_ai.utils import digest, sanitize, stable_id


class AuditLogger:
    def __init__(self, store: GraphStore, clock: Callable[[], datetime]) -> None:
        self.store = store
        self.clock = clock

    def record(
        self,
        operation: str,
        details: dict[str, Any],
        *,
        actor: str = "system",
        occurred_at: datetime | None = None,
    ) -> AuditEvent:
        safe_details = sanitize(details)
        timestamp = occurred_at or self.clock()
        event_digest = digest(
            {"operation": operation, "actor": actor, "at": timestamp, "details": safe_details}
        )
        event = AuditEvent(
            id=stable_id("audit", operation, timestamp.isoformat(), event_digest),
            operation=operation,
            actor=actor,
            occurred_at=timestamp,
            details=safe_details,
            digest=event_digest,
        )
        self.store.add_audit(event)
        return event


def make_evidence_bundle(
    *,
    operation: str,
    input_ids: list[str],
    source_hashes: list[str],
    entity_ids: list[str],
    fact_ids: list[str],
    temporal_decisions: list[str],
    policy_decisions: list[str],
    created_at: datetime,
) -> EvidenceBundle:
    payload = {
        "operation": operation,
        "input_ids": sorted(input_ids),
        "source_hashes": sorted(source_hashes),
        "entity_ids": sorted(entity_ids),
        "fact_ids": sorted(fact_ids),
        "temporal_decisions": temporal_decisions,
        "policy_decisions": policy_decisions,
        "created_at": created_at,
    }
    return EvidenceBundle(
        operation=operation,
        input_ids=sorted(input_ids),
        source_hashes=sorted(source_hashes),
        entity_ids=sorted(entity_ids),
        fact_ids=sorted(fact_ids),
        temporal_decisions=temporal_decisions,
        policy_decisions=policy_decisions,
        created_at=created_at,
        digest=digest(payload),
    )
