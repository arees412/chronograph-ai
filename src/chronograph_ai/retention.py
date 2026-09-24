"""Explicit retention, redaction, tombstone, and bounded purge actions."""

from __future__ import annotations

from chronograph_ai.engine import ChronoGraphEngine
from chronograph_ai.models import (
    FactStatus,
    RetentionAction,
    RetentionPolicy,
    RetentionState,
    Tombstone,
)
from chronograph_ai.utils import stable_id


class RetentionManager:
    def __init__(self, engine: ChronoGraphEngine) -> None:
        self.engine = engine

    def apply(
        self,
        episode_id: str,
        action: RetentionAction,
        *,
        reason: str,
        policy: RetentionPolicy | None = None,
    ) -> Tombstone | None:
        policy = policy or RetentionPolicy()
        episode = self.engine.store.get_episode(episode_id)
        if episode is None:
            raise KeyError(episode_id)
        now = self.engine.clock()
        if action is RetentionAction.RETAIN:
            self.engine.audit.record(
                "retention_action",
                {"episode_id": episode_id, "action": action, "reason": reason},
                occurred_at=now,
            )
            return None
        if action is RetentionAction.PURGE_WHERE_POLICY_ALLOWS and not policy.allow_purge:
            self.engine.audit.record(
                "policy_denial",
                {"episode_id": episode_id, "action": action, "reason": "purge not allowed"},
                occurred_at=now,
            )
            raise PermissionError("retention policy does not allow purge")
        state = {
            RetentionAction.EXPIRE_FROM_ACTIVE_MEMORY: RetentionState.EXPIRED,
            RetentionAction.REDACT_CONTENT: RetentionState.REDACTED,
            RetentionAction.TOMBSTONE: RetentionState.TOMBSTONED,
            RetentionAction.PURGE_WHERE_POLICY_ALLOWS: RetentionState.TOMBSTONED,
        }[action]
        content = episode.content
        metadata = episode.metadata
        if action is RetentionAction.REDACT_CONTENT:
            content = "[REDACTED]"
            metadata = {}
        elif action in {
            RetentionAction.TOMBSTONE,
            RetentionAction.PURGE_WHERE_POLICY_ALLOWS,
        }:
            content = "[TOMBSTONED]"
            metadata = {}
        self.engine.store.update_episode(
            episode.model_copy(
                update={"content": content, "metadata": metadata, "retention_state": state}
            )
        )
        tombstone = Tombstone(
            id=stable_id("tombstone", "episode", episode_id, action),
            record_type="episode",
            record_id=episode_id,
            reason=reason,
            created_at=now,
            source_hash=episode.content_hash,
        )
        if state is RetentionState.TOMBSTONED:
            self.engine.store.add_tombstone(tombstone)
            for fact in self.engine.store.list_facts():
                if episode_id not in fact.source_episode_ids:
                    continue
                active_sources = [
                    source_id
                    for source_id in fact.source_episode_ids
                    if source_id != episode_id
                    and (source := self.engine.store.get_episode(source_id)) is not None
                    and source.retention_state is RetentionState.ACTIVE
                ]
                if not active_sources:
                    self.engine.store.update_fact(
                        fact.model_copy(update={"status": FactStatus.INVALIDATED})
                    )
        if action is RetentionAction.PURGE_WHERE_POLICY_ALLOWS:
            self.engine.store.delete_episode(episode_id)
        self.engine.audit.record(
            "retention_action",
            {"episode_id": episode_id, "action": action, "reason": reason},
            occurred_at=now,
        )
        return tombstone if state is RetentionState.TOMBSTONED else None
