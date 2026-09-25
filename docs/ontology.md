# Ontology

The ontology is the mutation contract for the graph. Extraction providers may propose candidates, but only the registry can authorize their types and shapes.

## Entity types

The default schema defines `Person`, `Organization`, `Product`, `Project`, `Location`, `Policy`, `Concept`, and `Account`. Every entity candidate must name a declared type. Unknown types are rejected before an episode is committed.

## Relation types

Each relation declares:

- allowed subject entity types;
- either allowed object entity types or a literal type;
- cardinality as `one` or `many`;
- temporal behavior as `exclusive` or `non_exclusive`;
- whether directed cycles are forbidden.

The default relations are `WORKS_AT`, `OWNS`, `USES`, `MEMBER_OF`, `LOCATED_IN`, `PREFERS`, `MANAGES`, `DEPENDS_ON`, `ASSIGNED_TO`, and `HAS_STATUS`.

`WORKS_AT` and `HAS_STATUS` are exclusive. A different overlapping value can therefore trigger supersession or a dispute. Other default relations allow multiple overlapping values. `MEMBER_OF`, `MANAGES`, and `DEPENDS_ON` are acyclic and are checked by the integrity scanner.

## Validation sequence

Before storage, ChronoGraph validates every candidate's subject type, predicate, object kind, object type or literal type, and presence of evidence-backed entity candidates. Strict model parsing rejects undeclared fields and malformed intervals. This prevalidation happens before the episode is added, so invalid provider output has no partial graph effect.

## Custom schemas

Construct an `OntologySchema` with a new version and register it through `OntologyRegistry.register`. Versions are append-only within a registry: registering the same version twice is rejected. `make_current=False` can retain a version without switching new ingestion to it. Every accepted fact records the active schema version.

Schema migration of existing facts is not automatic. A deployment that changes semantics should ingest an explicit correction or replay into a separately reviewed projection.
