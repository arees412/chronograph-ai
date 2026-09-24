# Research references and implementation integrity

ChronoGraph is an independent implementation. Graphiti and the other sources below were used only to understand architecture, terminology, ecosystem choices, and current engineering practices. No source code, commit history, tests, prompts, README text, branding, or benchmark claims were copied.

The implementation, tests, documentation, fixtures, project history, and evaluation claims in this repository were created for ChronoGraph.

## Execution-time ecosystem review

The current Graphiti repository was inspected on 2026-09-24. The review covered its public repository activity, Apache-2.0 license, Python packaging metadata, public provider/backend descriptions, repository structure, and CI organization. At inspection time its package metadata declared Python 3.10 or newer and version 0.30.2; its public materials described Neo4j, FalkorDB, Amazon Neptune, and a deprecated Kuzu path. These facts describe the reference project, not ChronoGraph support.

- [getzep/graphiti repository](https://github.com/getzep/graphiti)
- [Graphiti project metadata](https://raw.githubusercontent.com/getzep/graphiti/main/pyproject.toml)
- [Graphiti Apache-2.0 license](https://raw.githubusercontent.com/getzep/graphiti/main/LICENSE)
- [Graphiti commit activity](https://github.com/getzep/graphiti/commits/main/)

## Architecture and standards references

- [Microsoft Azure Architecture Center: Event Sourcing pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)
- [W3C PROV-O: The PROV Ontology](https://www.w3.org/TR/prov-o/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [Pydantic documentation](https://docs.pydantic.dev/latest/)
- [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
- [Neo4j temporal values](https://neo4j.com/docs/cypher-manual/current/values-and-types/temporal/)
- [PostgreSQL range types](https://www.postgresql.org/docs/current/rangetypes.html)
- [OpenTelemetry Python documentation](https://opentelemetry.io/docs/languages/python/)

These references informed design choices such as immutable events, separate valid and system time, explicit provenance, typed trust boundaries, adapter isolation, and deterministic offline validation. ChronoGraph does not import, vendor, or inherit a reference repository.
