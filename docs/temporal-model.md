# Temporal model

ChronoGraph records two independent clocks. Conflating them would make retroactive corrections and historical knowledge impossible to answer precisely.

## Fact fields

- `valid_from`: first instant when the fact is true in the represented world.
- `valid_to`: exclusive end of the resolved valid-time interval, or `null` when open.
- `asserted_valid_to`: the source-asserted end before later supersession decisions. It preserves the earlier knowledge view.
- `recorded_at`: system time when ChronoGraph accepted the assertion.
- `superseded_at`: system time when a later assertion superseded the fact.
- `superseded_by`: identifier of the replacing fact.

All timestamps are timezone-aware and normalized to UTC.

## Example: fact change

Episode A says Alice works at Acme. It is valid and recorded on January 1:

```text
Alice WORKS_AT Acme
valid_from   = 2026-01-01T00:00:00Z
valid_to     = null
recorded_at  = 2026-01-01T00:00:00Z
```

Episode B says Alice now works at Orbit from February 1. `WORKS_AT` is exclusive. ChronoGraph closes A at February 1, marks it superseded, and links it to B:

```text
Alice WORKS_AT Acme
valid_from        = 2026-01-01T00:00:00Z
valid_to          = 2026-02-01T00:00:00Z
asserted_valid_to = null
recorded_at       = 2026-01-01T00:00:00Z
superseded_at     = 2026-02-01T00:00:00Z

Alice WORKS_AT Orbit
valid_from        = 2026-02-01T00:00:00Z
valid_to          = null
recorded_at       = 2026-02-01T00:00:00Z
```

Intervals use `[valid_from, valid_to)`, so the old fact is not valid at the exact start of the new one.

## Query lenses

### Current-time query

At March 1, the active valid fact is Orbit. A current memory query filters superseded facts even when scanning broader history.

### Historical valid-time query

At January 15, the valid fact is Acme. This asks what was true at that represented-world time using all knowledge now stored.

### Bi-temporal known-at query

`valid_time=2026-03-01` with `known_at=2026-01-15` asks: based only on records accepted by January 15, what did the graph say was valid on March 1? The answer is Acme because the later supersession was not yet recorded. ChronoGraph uses `asserted_valid_to` when the known-at lens predates `superseded_at`.

Facts whose `recorded_at` is later than `known_at` are excluded.

## Retroactive knowledge

A record may arrive on September 20 and assert that Project Alpha was paused from August 1 through August 10:

```text
valid_from  = 2026-08-01T00:00:00Z
valid_to    = 2026-08-10T00:00:00Z
recorded_at = 2026-09-20T00:00:00Z
```

A valid-time query for August 5 returns the fact. The same query with `known_at=2026-09-19` does not, because the system had not recorded it yet.

## Supersession

For an exclusive relation, a different value with a later `valid_from` supersedes an overlapping older value. The older fact is preserved, its resolved interval is closed when necessary, and both system-time decision fields are recorded. `supersession_chain` follows these links with cycle protection.

## Disputed facts

Two incompatible exclusive facts with overlapping intervals and no later valid-time succession are both marked `disputed`. A conflict set names both fact IDs and records the reason and detection time. No automatic winner is invented. Current memory excludes disputed facts unless policy explicitly opts in; opted-in items include conflict identifiers.

## Non-exclusive relations

Relations such as `PREFERS` may have overlapping values. They are not treated as contradictions. The ontology controls this behavior per relation rather than relying on predicate-name conventions.

## Snapshot determinism

An as-of snapshot contains the matching facts, referenced entities, and evidence in stable order. Its digest is computed from canonical JSON. `generated_at` does not introduce wall-clock variation: it uses the query's known-at value or valid-time value.
