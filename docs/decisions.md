# Architecture decisions

## ADR-001: independent repository and implementation

ChronoGraph is a new original project rather than a fork. Reference projects informed ecosystem and architecture research only. This keeps code, tests, documentation, prompts, branding, history, and claims attributable to this repository.

## ADR-002: episodes as the replay source

Accepted source episodes are append-only inputs. Entities and facts are deterministic projections. Corrections arrive as later evidence rather than destructive source edits, making replay and audit possible.

## ADR-003: bi-temporal facts

Facts carry valid time and system time because "when true" and "when learned" are different questions. `asserted_valid_to` preserves the earlier knowledge view when later supersession closes the resolved interval.

## ADR-004: append-only evidence and explicit provenance

Every fact requires evidence and source episode identifiers. Equivalent facts coalesce additional evidence instead of creating silent duplicates. Retention can redact or tombstone source content without pretending the evidence never existed.

## ADR-005: deterministic CI providers

Local providers cover extraction, embeddings, and reranking so all routine checks run without network access or paid credentials. External AI integrations remain optional adapter work and cannot weaken core validation.

## ADR-006: conservative entity resolution

Only exact identifiers or exact normalized canonical/alias evidence resolve automatically. Conflicting identifiers and ambiguous matches preserve separate entities. Human-governed merge proposals support approval, rejection, and reversal.

## ADR-007: no required vector database or paid LLM

The local semantic signal uses a deterministic hash embedding and the store API has no vector-database requirement. This makes the base behavior inspectable and reproducible, while leaving typed extension points.

## ADR-008: bounded traversal and retrieval

Depth, neighbors, results, episode size, metadata size, memory budgets, and provider retries have explicit bounds. The implementation favors predictable failure over unbounded work.

## ADR-009: optional graph-backend adapters

The core depends on `GraphStore`, not a graph query language. In-memory and SQLite adapters are implemented. Neo4j, FalkorDB, PostgreSQL, and other adapters are possible future work and are not advertised as supported.

## ADR-010: local SQLite snapshot adapter

SQLite stores one canonical logical snapshot transactionally after each mutation. This is simple to audit and reload but is not a graph-native index, distributed database, or high-throughput multi-writer design.
