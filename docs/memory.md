# Governed agent memory

ChronoGraph memory is a bounded view over evidence-backed graph facts. It is not a transcript dump and does not create new facts.

## Assembly flow

1. Select the current time or an explicit historical valid time.
2. Run hybrid retrieval over facts valid at that time.
3. Apply sensitivity, dispute, entity-type, age, source, retention, item, character, entity, and graph-depth policies.
4. Render accepted facts into compact text while retaining fact, source episode, evidence, ranking, and contradiction identifiers.
5. Record a sanitized audit event containing hashes of the agent ID and query, never their raw values.

## Policy controls

`MemoryPolicy` supports:

- allowed sensitivities, defaulting to `public` and `internal`;
- optional entity-type and source-type allowlists;
- maximum fact age;
- disputed-fact opt-in;
- historical-memory intent;
- maximum items, characters, entities, and graph depth.

When a budget would be exceeded, the bundle reports `truncated=true`. Ranking order and stable fact IDs make the truncation deterministic for the same graph and request.

## Temporal freshness

A current request uses `current_time` as valid time and excludes superseded facts. A historical request supplies `historical_valid_time`; facts valid at that instant can be returned even when they are now superseded. The request retains both times so downstream agents can distinguish current from historical context.

## Conflicts

Disputed facts are excluded by default. If `include_disputed=true`, returned items name their conflict-set identifiers. ChronoGraph does not silently choose a winner.

## Sensitivity and retention

Fact sensitivity inherits from its source episode. A fact outside the policy allowlist is excluded. Episodes expired or tombstoned by retention policy are excluded from active memory. Redacted episodes retain their hash and can still support graph integrity, but raw content is no longer available.

These controls are application-level filters, not a replacement for transport security, database access control, tenant isolation, or deployment authorization.
