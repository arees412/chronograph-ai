"""Versioned ontology registry and deterministic fact validation."""

from __future__ import annotations

from chronograph_ai.models import (
    Cardinality,
    Entity,
    EntityType,
    FactCandidate,
    ObjectKind,
    OntologySchema,
    RelationType,
    TemporalBehavior,
)


def default_ontology() -> OntologySchema:
    entity_names = [
        "Person",
        "Organization",
        "Product",
        "Project",
        "Location",
        "Policy",
        "Concept",
        "Account",
    ]
    entity_types = {
        name: EntityType(name=name, description=f"ChronoGraph {name} entity")
        for name in entity_names
    }
    relations = {
        "WORKS_AT": RelationType(
            name="WORKS_AT",
            subject_types={"Person"},
            object_types={"Organization"},
            cardinality=Cardinality.ONE,
            temporal_behavior=TemporalBehavior.EXCLUSIVE,
        ),
        "OWNS": RelationType(
            name="OWNS",
            subject_types={"Person", "Organization"},
            object_types={"Product", "Project", "Account"},
        ),
        "USES": RelationType(
            name="USES",
            subject_types={"Person", "Organization", "Project"},
            object_types={"Product", "Concept"},
        ),
        "MEMBER_OF": RelationType(
            name="MEMBER_OF",
            subject_types={"Person", "Organization"},
            object_types={"Organization"},
            acyclic=True,
        ),
        "LOCATED_IN": RelationType(
            name="LOCATED_IN",
            subject_types={"Person", "Organization", "Project"},
            object_types={"Location"},
        ),
        "PREFERS": RelationType(
            name="PREFERS",
            subject_types={"Person"},
            object_types={"Product", "Concept"},
        ),
        "MANAGES": RelationType(
            name="MANAGES",
            subject_types={"Person", "Organization"},
            object_types={"Project", "Person", "Account"},
            acyclic=True,
        ),
        "DEPENDS_ON": RelationType(
            name="DEPENDS_ON",
            subject_types={"Project", "Product"},
            object_types={"Project", "Product"},
            acyclic=True,
        ),
        "ASSIGNED_TO": RelationType(
            name="ASSIGNED_TO",
            subject_types={"Project", "Account"},
            object_types={"Person", "Organization"},
        ),
        "HAS_STATUS": RelationType(
            name="HAS_STATUS",
            subject_types={"Person", "Organization", "Product", "Project", "Account"},
            object_kind=ObjectKind.LITERAL,
            literal_type="str",
            cardinality=Cardinality.ONE,
            temporal_behavior=TemporalBehavior.EXCLUSIVE,
        ),
    }
    return OntologySchema(version="1.0", entity_types=entity_types, relations=relations)


class OntologyRegistry:
    """Holds immutable schema versions and validates candidate mutations."""

    def __init__(self, schema: OntologySchema | None = None) -> None:
        initial = schema or default_ontology()
        self._schemas: dict[str, OntologySchema] = {initial.version: initial}
        self._current_version = initial.version

    @property
    def current(self) -> OntologySchema:
        return self._schemas[self._current_version]

    def register(self, schema: OntologySchema, *, make_current: bool = True) -> None:
        if schema.version in self._schemas:
            raise ValueError(f"ontology version already exists: {schema.version}")
        self._schemas[schema.version] = schema
        if make_current:
            self._current_version = schema.version

    def get(self, version: str) -> OntologySchema:
        return self._schemas[version]

    def validate_entity_type(self, entity_type: str) -> None:
        if entity_type not in self.current.entity_types:
            raise ValueError(f"unknown entity type: {entity_type}")

    def validate_fact_candidate(
        self,
        candidate: FactCandidate,
        subject: Entity,
        object_entity: Entity | None,
    ) -> RelationType:
        relation = self.current.relations.get(candidate.predicate)
        if relation is None:
            raise ValueError(f"unknown relation: {candidate.predicate}")
        if subject.entity_type not in relation.subject_types:
            raise ValueError(
                f"{candidate.predicate} does not allow subject type {subject.entity_type}"
            )
        if relation.object_kind is ObjectKind.ENTITY:
            if object_entity is None:
                raise ValueError(f"{candidate.predicate} requires an entity object")
            if object_entity.entity_type not in relation.object_types:
                raise ValueError(
                    f"{candidate.predicate} does not allow object type {object_entity.entity_type}"
                )
        else:
            if object_entity is not None or candidate.literal_value is None:
                raise ValueError(f"{candidate.predicate} requires a literal object")
            if relation.literal_type == "str" and not isinstance(candidate.literal_value, str):
                raise ValueError(f"{candidate.predicate} requires a string literal")
        return relation
