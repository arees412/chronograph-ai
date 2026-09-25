"""Storage protocol, deterministic memory store, and transactional SQLite store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from chronograph_ai.models import (
    AuditEvent,
    ConflictSet,
    Entity,
    EntityMergeProposal,
    Episode,
    Fact,
    FactEvidence,
    Tombstone,
)
from chronograph_ai.utils import canonical_json


class GraphStore(Protocol):
    backend_name: str

    def add_episode(self, episode: Episode) -> None: ...
    def get_episode(self, episode_id: str) -> Episode | None: ...
    def find_episode_by_idempotency(self, key: str) -> Episode | None: ...
    def list_episodes(self) -> list[Episode]: ...
    def update_episode(self, episode: Episode) -> None: ...
    def delete_episode(self, episode_id: str) -> None: ...
    def upsert_entity(self, entity: Entity) -> None: ...
    def get_entity(self, entity_id: str) -> Entity | None: ...
    def list_entities(self) -> list[Entity]: ...
    def add_evidence(self, evidence: FactEvidence) -> None: ...
    def get_evidence(self, evidence_id: str) -> FactEvidence | None: ...
    def list_evidence(self) -> list[FactEvidence]: ...
    def add_fact(self, fact: Fact) -> None: ...
    def update_fact(self, fact: Fact) -> None: ...
    def get_fact(self, fact_id: str) -> Fact | None: ...
    def list_facts(self) -> list[Fact]: ...
    def add_merge_proposal(self, proposal: EntityMergeProposal) -> None: ...
    def update_merge_proposal(self, proposal: EntityMergeProposal) -> None: ...
    def get_merge_proposal(self, proposal_id: str) -> EntityMergeProposal | None: ...
    def list_merge_proposals(self) -> list[EntityMergeProposal]: ...
    def add_conflict(self, conflict: ConflictSet) -> None: ...
    def list_conflicts(self) -> list[ConflictSet]: ...
    def add_audit(self, event: AuditEvent) -> None: ...
    def list_audit(self) -> list[AuditEvent]: ...
    def add_tombstone(self, tombstone: Tombstone) -> None: ...
    def list_tombstones(self) -> list[Tombstone]: ...
    def export_state(self) -> dict[str, Any]: ...


class InMemoryGraphStore:
    backend_name = "memory"

    def __init__(self) -> None:
        self._lock = RLock()
        self._episodes: dict[str, Episode] = {}
        self._idempotency: dict[str, str] = {}
        self._entities: dict[str, Entity] = {}
        self._evidence: dict[str, FactEvidence] = {}
        self._facts: dict[str, Fact] = {}
        self._merge_proposals: dict[str, EntityMergeProposal] = {}
        self._conflicts: dict[str, ConflictSet] = {}
        self._audit: dict[str, AuditEvent] = {}
        self._tombstones: dict[str, Tombstone] = {}

    def add_episode(self, episode: Episode) -> None:
        with self._lock:
            if episode.id in self._episodes:
                raise ValueError(f"episode already exists: {episode.id}")
            if episode.idempotency_key and episode.idempotency_key in self._idempotency:
                raise ValueError(f"idempotency key already exists: {episode.idempotency_key}")
            self._episodes[episode.id] = episode
            if episode.idempotency_key:
                self._idempotency[episode.idempotency_key] = episode.id

    def get_episode(self, episode_id: str) -> Episode | None:
        return self._episodes.get(episode_id)

    def find_episode_by_idempotency(self, key: str) -> Episode | None:
        episode_id = self._idempotency.get(key)
        return self._episodes.get(episode_id) if episode_id else None

    def list_episodes(self) -> list[Episode]:
        return sorted(self._episodes.values(), key=lambda item: (item.ingested_at, item.id))

    def update_episode(self, episode: Episode) -> None:
        with self._lock:
            if episode.id not in self._episodes:
                raise KeyError(episode.id)
            self._episodes[episode.id] = episode

    def delete_episode(self, episode_id: str) -> None:
        with self._lock:
            episode = self._episodes.pop(episode_id)
            if episode.idempotency_key:
                self._idempotency.pop(episode.idempotency_key, None)

    def upsert_entity(self, entity: Entity) -> None:
        with self._lock:
            self._entities[entity.id] = entity

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def list_entities(self) -> list[Entity]:
        return sorted(self._entities.values(), key=lambda item: item.id)

    def add_evidence(self, evidence: FactEvidence) -> None:
        with self._lock:
            self._evidence[evidence.id] = evidence

    def get_evidence(self, evidence_id: str) -> FactEvidence | None:
        return self._evidence.get(evidence_id)

    def list_evidence(self) -> list[FactEvidence]:
        return sorted(self._evidence.values(), key=lambda item: item.id)

    def add_fact(self, fact: Fact) -> None:
        with self._lock:
            if fact.id in self._facts:
                raise ValueError(f"fact already exists: {fact.id}")
            self._facts[fact.id] = fact

    def update_fact(self, fact: Fact) -> None:
        with self._lock:
            if fact.id not in self._facts:
                raise KeyError(fact.id)
            self._facts[fact.id] = fact

    def get_fact(self, fact_id: str) -> Fact | None:
        return self._facts.get(fact_id)

    def list_facts(self) -> list[Fact]:
        return sorted(self._facts.values(), key=lambda item: (item.recorded_at, item.id))

    def add_merge_proposal(self, proposal: EntityMergeProposal) -> None:
        with self._lock:
            self._merge_proposals[proposal.id] = proposal

    def update_merge_proposal(self, proposal: EntityMergeProposal) -> None:
        with self._lock:
            if proposal.id not in self._merge_proposals:
                raise KeyError(proposal.id)
            self._merge_proposals[proposal.id] = proposal

    def get_merge_proposal(self, proposal_id: str) -> EntityMergeProposal | None:
        return self._merge_proposals.get(proposal_id)

    def list_merge_proposals(self) -> list[EntityMergeProposal]:
        return sorted(self._merge_proposals.values(), key=lambda item: item.id)

    def add_conflict(self, conflict: ConflictSet) -> None:
        with self._lock:
            self._conflicts[conflict.id] = conflict

    def list_conflicts(self) -> list[ConflictSet]:
        return sorted(self._conflicts.values(), key=lambda item: item.id)

    def add_audit(self, event: AuditEvent) -> None:
        with self._lock:
            self._audit[event.id] = event

    def list_audit(self) -> list[AuditEvent]:
        return sorted(self._audit.values(), key=lambda item: (item.occurred_at, item.id))

    def add_tombstone(self, tombstone: Tombstone) -> None:
        with self._lock:
            self._tombstones[tombstone.id] = tombstone

    def list_tombstones(self) -> list[Tombstone]:
        return sorted(self._tombstones.values(), key=lambda item: item.id)

    def export_state(self) -> dict[str, Any]:
        return {
            "episodes": [item.model_dump(mode="json") for item in self.list_episodes()],
            "entities": [item.model_dump(mode="json") for item in self.list_entities()],
            "evidence": [item.model_dump(mode="json") for item in self.list_evidence()],
            "facts": [item.model_dump(mode="json") for item in self.list_facts()],
            "merge_proposals": [
                item.model_dump(mode="json") for item in self.list_merge_proposals()
            ],
            "conflicts": [item.model_dump(mode="json") for item in self.list_conflicts()],
            "audit": [item.model_dump(mode="json") for item in self.list_audit()],
            "tombstones": [item.model_dump(mode="json") for item in self.list_tombstones()],
        }


class SQLiteGraphStore(InMemoryGraphStore):
    """Checkpoint logical state as canonical JSON in one SQLite transaction.

    This local adapter favors replayability and correctness over scale. Distributed
    writers and graph-native query planning are intentionally unsupported.
    """

    backend_name = "sqlite"

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS chronograph_state "
            "(singleton INTEGER PRIMARY KEY CHECK(singleton = 1), payload TEXT NOT NULL)"
        )
        self._load()

    def close(self) -> None:
        self._connection.close()

    def _load(self) -> None:
        row = self._connection.execute(
            "SELECT payload FROM chronograph_state WHERE singleton = 1"
        ).fetchone()
        if row is None:
            return
        state = json.loads(str(row[0]))
        self._episodes = {item["id"]: Episode.model_validate(item) for item in state["episodes"]}
        self._idempotency = {
            item.idempotency_key: item.id
            for item in self._episodes.values()
            if item.idempotency_key
        }
        self._entities = {item["id"]: Entity.model_validate(item) for item in state["entities"]}
        self._evidence = {
            item["id"]: FactEvidence.model_validate(item) for item in state["evidence"]
        }
        self._facts = {item["id"]: Fact.model_validate(item) for item in state["facts"]}
        self._merge_proposals = {
            item["id"]: EntityMergeProposal.model_validate(item)
            for item in state["merge_proposals"]
        }
        self._conflicts = {
            item["id"]: ConflictSet.model_validate(item) for item in state["conflicts"]
        }
        self._audit = {item["id"]: AuditEvent.model_validate(item) for item in state["audit"]}
        self._tombstones = {
            item["id"]: Tombstone.model_validate(item) for item in state["tombstones"]
        }

    def _persist(self) -> None:
        payload = canonical_json(self.export_state())
        with self._connection:
            self._connection.execute(
                "INSERT INTO chronograph_state(singleton, payload) VALUES(1, ?) "
                "ON CONFLICT(singleton) DO UPDATE SET payload = excluded.payload",
                (payload,),
            )

    def add_episode(self, episode: Episode) -> None:
        super().add_episode(episode)
        self._persist()

    def update_episode(self, episode: Episode) -> None:
        super().update_episode(episode)
        self._persist()

    def delete_episode(self, episode_id: str) -> None:
        super().delete_episode(episode_id)
        self._persist()

    def upsert_entity(self, entity: Entity) -> None:
        super().upsert_entity(entity)
        self._persist()

    def add_evidence(self, evidence: FactEvidence) -> None:
        super().add_evidence(evidence)
        self._persist()

    def add_fact(self, fact: Fact) -> None:
        super().add_fact(fact)
        self._persist()

    def update_fact(self, fact: Fact) -> None:
        super().update_fact(fact)
        self._persist()

    def add_merge_proposal(self, proposal: EntityMergeProposal) -> None:
        super().add_merge_proposal(proposal)
        self._persist()

    def update_merge_proposal(self, proposal: EntityMergeProposal) -> None:
        super().update_merge_proposal(proposal)
        self._persist()

    def add_conflict(self, conflict: ConflictSet) -> None:
        super().add_conflict(conflict)
        self._persist()

    def add_audit(self, event: AuditEvent) -> None:
        super().add_audit(event)
        self._persist()

    def add_tombstone(self, tombstone: Tombstone) -> None:
        super().add_tombstone(tombstone)
        self._persist()
