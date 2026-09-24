"""Typed domain models for ChronoGraph's temporal knowledge graph."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model that rejects undeclared data at every trust boundary."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class EpisodeSource(StrEnum):
    CONVERSATION = "conversation"
    EVENT = "event"
    DOCUMENT_FRAGMENT = "document_fragment"
    STRUCTURED_RECORD = "structured_record"
    SYSTEM_EVENT = "system_event"
    MANUAL_FACT = "manual_fact"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PII = "pii"
    RESTRICTED = "restricted"


class Confidence(StrEnum):
    VERIFIED = "verified"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNVERIFIED = "unverified"


class FactStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    DISPUTED = "disputed"
    RETRACTED = "retracted"


class EntityStatus(StrEnum):
    ACTIVE = "active"
    MERGED = "merged"
    TOMBSTONED = "tombstoned"


class ResolutionOutcome(StrEnum):
    NEW_ENTITY = "new_entity"
    RESOLVED_EXISTING = "resolved_existing"
    AMBIGUOUS = "ambiguous"
    MERGE_PROPOSED = "merge_proposed"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVERSED = "reversed"


class Cardinality(StrEnum):
    ONE = "one"
    MANY = "many"


class TemporalBehavior(StrEnum):
    EXCLUSIVE = "exclusive"
    NON_EXCLUSIVE = "non_exclusive"


class ObjectKind(StrEnum):
    ENTITY = "entity"
    LITERAL = "literal"


class RetentionAction(StrEnum):
    RETAIN = "retain"
    EXPIRE_FROM_ACTIVE_MEMORY = "expire_from_active_memory"
    REDACT_CONTENT = "redact_content"
    TOMBSTONE = "tombstone"
    PURGE_WHERE_POLICY_ALLOWS = "purge_where_policy_allows"


class RetentionState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REDACTED = "redacted"
    TOMBSTONED = "tombstoned"


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(UTC) if value is not None else None


class TemporalInterval(StrictModel):
    valid_from: datetime
    valid_to: datetime | None = None

    @field_validator("valid_from", "valid_to")
    @classmethod
    def timezone_aware(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must be greater than or equal to valid_from")
        return self


class EpisodeCreate(StrictModel):
    source_type: EpisodeSource
    source_id: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=100_000)
    event_time: datetime
    observed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sensitivity: Sensitivity = Sensitivity.PUBLIC
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("event_time", "observed_at")
    @classmethod
    def timezone_aware(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @field_validator("metadata")
    @classmethod
    def bounded_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        import json

        if len(json.dumps(value, default=str, sort_keys=True)) > 32_000:
            raise ValueError("metadata exceeds 32,000 serialized characters")
        return value


class Episode(EpisodeCreate):
    id: str
    ingested_at: datetime
    content_hash: str
    retention_state: RetentionState = RetentionState.ACTIVE

    @field_validator("ingested_at")
    @classmethod
    def ingested_timezone_aware(cls, value: datetime) -> datetime:
        checked = _aware(value)
        assert checked is not None
        return checked


class EntityType(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    description: str = ""


class EntityAlias(StrictModel):
    value: str
    normalized: str
    source_episode_id: str


class EntityCandidate(StrictModel):
    canonical_name: str = Field(min_length=1, max_length=256)
    entity_type: str
    aliases: list[str] = Field(default_factory=list, max_length=32)
    identifiers: dict[str, str] = Field(default_factory=dict)
    confidence: Confidence = Confidence.MEDIUM
    evidence_path: str


class Entity(StrictModel):
    id: str
    canonical_name: str
    normalized_name: str
    entity_type: str
    aliases: list[EntityAlias] = Field(default_factory=list)
    identifiers: dict[str, str] = Field(default_factory=dict)
    source_episode_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    confidence: Confidence
    status: EntityStatus = EntityStatus.ACTIVE
    merged_into: str | None = None


class EntityResolution(StrictModel):
    outcome: ResolutionOutcome
    entity: Entity
    candidate_ids: list[str] = Field(default_factory=list)
    reason: str
    merge_proposal_id: str | None = None


class EntityMergeProposal(StrictModel):
    id: str
    source_entity_id: str
    target_entity_id: str
    reason: str
    evidence_episode_ids: list[str]
    created_at: datetime
    decided_at: datetime | None = None
    status: ProposalStatus = ProposalStatus.PENDING
    decision_reason: str | None = None


class RelationType(StrictModel):
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    subject_types: set[str]
    object_types: set[str] = Field(default_factory=set)
    object_kind: ObjectKind = ObjectKind.ENTITY
    literal_type: str | None = None
    cardinality: Cardinality = Cardinality.MANY
    temporal_behavior: TemporalBehavior = TemporalBehavior.NON_EXCLUSIVE
    acyclic: bool = False


class OntologySchema(StrictModel):
    version: str
    entity_types: dict[str, EntityType]
    relations: dict[str, RelationType]


class FactCandidate(StrictModel):
    subject_name: str
    subject_type: str
    predicate: str
    object_name: str | None = None
    object_type: str | None = None
    literal_value: str | int | float | bool | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: Confidence = Confidence.MEDIUM
    evidence_path: str

    @field_validator("valid_from", "valid_to")
    @classmethod
    def timezone_aware(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def exactly_one_object(self) -> Self:
        if (self.object_name is None) == (self.literal_value is None):
            raise ValueError("exactly one of object_name or literal_value is required")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError("valid_to must be greater than or equal to valid_from")
        return self


class FactEvidence(StrictModel):
    id: str
    episode_id: str
    source_path: str
    extraction_method: str
    extractor_version: str
    recorded_at: datetime
    content_hash: str


class Fact(StrictModel):
    id: str
    subject_id: str
    predicate: str
    object_id: str | None = None
    literal_value: str | int | float | bool | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    asserted_valid_to: datetime | None = None
    recorded_at: datetime
    superseded_at: datetime | None = None
    superseded_by: str | None = None
    confidence: Confidence
    status: FactStatus = FactStatus.ACTIVE
    evidence_ids: list[str] = Field(min_length=1)
    source_episode_ids: list[str] = Field(min_length=1)
    created_by: str
    schema_version: str
    sensitivity: Sensitivity = Sensitivity.PUBLIC

    @field_validator("valid_from", "valid_to", "asserted_valid_to", "recorded_at", "superseded_at")
    @classmethod
    def timezone_aware(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def valid_shape(self) -> Self:
        if (self.object_id is None) == (self.literal_value is None):
            raise ValueError("exactly one of object_id or literal_value is required")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must be greater than or equal to valid_from")
        if self.asserted_valid_to is not None and self.asserted_valid_to < self.valid_from:
            raise ValueError("asserted_valid_to must be greater than or equal to valid_from")
        return self


class FactRevision(StrictModel):
    id: str
    fact_id: str
    previous_status: FactStatus
    new_status: FactStatus
    reason: str
    recorded_at: datetime


class GraphMutation(StrictModel):
    id: str
    operation: str
    entity_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    episode_id: str
    recorded_at: datetime
    digest: str


class IngestionResult(StrictModel):
    episode: Episode
    entities: list[Entity]
    facts: list[Fact]
    mutation: GraphMutation
    duplicate: bool = False


class ConflictSet(StrictModel):
    id: str
    subject_id: str
    predicate: str
    fact_ids: list[str] = Field(min_length=2)
    reason: str
    detected_at: datetime
    preferred_fact_id: str | None = None


class SupersessionDecision(StrictModel):
    old_fact_id: str
    new_fact_id: str
    reason: str
    decided_at: datetime
    closed_old_interval: bool


class GraphSnapshot(StrictModel):
    valid_time: datetime
    known_at: datetime | None = None
    entities: list[Entity]
    facts: list[Fact]
    evidence: list[FactEvidence]
    generated_at: datetime
    digest: str


class GraphQuery(StrictModel):
    text: str = Field(default="", max_length=1_000)
    valid_time: datetime | None = None
    known_at: datetime | None = None
    entity_id: str | None = None
    predicate: str | None = None
    max_results: int = Field(default=20, ge=1, le=100)
    max_depth: int = Field(default=2, ge=0, le=5)


class RankingEvidence(StrictModel):
    lexical_score: float
    entity_score: float
    graph_score: float
    temporal_score: float
    source_score: float
    semantic_score: float
    final_score: float
    explanation: list[str]


class SearchResult(StrictModel):
    fact: Fact
    subject: Entity
    object_entity: Entity | None = None
    ranking: RankingEvidence
    evidence: list[FactEvidence]


class MemoryPolicy(StrictModel):
    allowed_sensitivities: set[Sensitivity] = Field(
        default_factory=lambda: {Sensitivity.PUBLIC, Sensitivity.INTERNAL}
    )
    allowed_entity_types: set[str] | None = None
    max_age_days: int | None = Field(default=None, ge=1)
    include_disputed: bool = False
    include_historical: bool = False
    allowed_source_types: set[EpisodeSource] | None = None
    max_items: int = Field(default=10, ge=1, le=100)
    max_characters: int = Field(default=8_000, ge=100, le=100_000)
    max_entities: int = Field(default=20, ge=1, le=100)
    max_graph_depth: int = Field(default=2, ge=0, le=5)


class MemoryRequest(StrictModel):
    agent_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=1_000)
    current_time: datetime
    subject_entity_id: str | None = None
    historical_valid_time: datetime | None = None
    policy: MemoryPolicy = Field(default_factory=MemoryPolicy)


class MemoryItem(StrictModel):
    fact: Fact
    text: str
    source_episode_ids: list[str]
    evidence_ids: list[str]
    ranking: RankingEvidence
    contradictions: list[str] = Field(default_factory=list)


class MemoryBundle(StrictModel):
    request: MemoryRequest
    items: list[MemoryItem]
    entity_ids: list[str]
    character_count: int
    truncated: bool
    generated_at: datetime
    digest: str


class RetentionPolicy(StrictModel):
    allow_purge: bool = False
    preserve_audit_metadata: bool = True


class Tombstone(StrictModel):
    id: str
    record_type: str
    record_id: str
    reason: str
    created_at: datetime
    source_hash: str


class AuditEvent(StrictModel):
    id: str
    operation: str
    actor: str
    occurred_at: datetime
    details: dict[str, Any]
    digest: str


class EvidenceBundle(StrictModel):
    operation: str
    input_ids: list[str]
    source_hashes: list[str]
    entity_ids: list[str]
    fact_ids: list[str]
    temporal_decisions: list[str]
    policy_decisions: list[str]
    created_at: datetime
    digest: str


class EvaluationCase(StrictModel):
    name: str
    passed: bool
    details: str


class IntegrityIssue(StrictModel):
    code: str
    record_ids: list[str]
    message: str


class IntegrityReport(StrictModel):
    ok: bool
    issues: list[IntegrityIssue]
    checked_at: datetime


class HealthResponse(StrictModel):
    status: str
    version: str
    backend: str
