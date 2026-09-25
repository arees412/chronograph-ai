# Evaluation

ChronoGraph includes a deterministic correctness harness. It is not a benchmark and does not claim accuracy, throughput, latency, scale, or comparison superiority.

Run it with:

```bash
chronograph eval
```

## Scenarios

1. A fact changes over time from Acme to Orbit.
2. A retroactive fact has valid time before recorded time.
3. Same-time exclusive assertions become a conflict.
4. Two people with the same name and conflicting identifiers remain separate.
5. An alias with the same explicit identifier resolves to one entity.
6. Repeated point-in-time snapshots produce the same digest.
7. Current agent memory returns the active employer.
8. Restricted memory is excluded by the default policy.
9. Duplicate ingestion is idempotent.
10. Invalid provider output causes no partial graph mutation.

Every scenario uses local deterministic providers and assertions. A process exits nonzero when any scenario fails and reports every scenario rather than stopping at the first failure.

## Interpretation

A pass means the checked invariant held for the included fixture. It does not establish correctness for arbitrary extraction text, external models, production workloads, multilingual resolution, or a future database adapter. Broader claims require separately designed datasets, evaluation methodology, and reproducible measurements.

The unit suite adds graph traversal, explainable ranking, merge approval/rejection/reversal, memory budgets, disputed-fact policy, retention, audit privacy, SQLite persistence, concurrent idempotency, replay, FastAPI, and CLI coverage.
