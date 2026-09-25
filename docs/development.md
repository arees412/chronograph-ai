# Development

## Environment

ChronoGraph requires Python 3.12 or newer. Create an isolated environment and install the package with development tools:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

No API key, cloud database, or telemetry service is needed for routine development.

## Validation

Run the same checks used by CI:

```bash
ruff format --check .
ruff check .
mypy src/chronograph_ai
pytest --cov=chronograph_ai --cov-report=term-missing
chronograph eval
chronograph --help
python scripts/validate_docs.py
python scripts/scan_secrets.py
python -m build
python -c "import chronograph_ai; print(chronograph_ai.__version__)"
```

`pytest` includes temporal invariants, conflict and supersession behavior, conservative resolution, merge corrections, memory policy, retention, SQLite round trips, concurrency, replay, API, and CLI coverage.

## Package structure

- `models.py`: strict domain and transport models.
- `engine.py`: ingestion orchestration, temporal query, traversal, provenance, and merge facade.
- `ontology.py`, `entity_resolution.py`, `temporal.py`: graph mutation rules.
- `retrieval.py`, `memory.py`, `retention.py`: ranked access and governance.
- `storage.py`: store protocol and current adapters.
- `providers.py`: deterministic defaults and extension protocols.
- `api.py`, `cli.py`: service surfaces.
- `integrity.py`, `replay.py`, `evaluation.py`: validation and repeatability.

## Adding providers

Implement the relevant protocol and pass the provider to `ChronoGraphEngine`. Treat episode content as untrusted. Return only typed candidate-compatible values. The engine performs a second validation step, but adapter code must still bound time, retries, payloads, credentials, and vendor data exposure.

## Adding stores

Implement every `GraphStore` operation with deterministic listing order and atomic mutation semantics. Preserve episode idempotency, evidence links, conflict sets, merge proposals, audit events, and tombstones. A new adapter should have a local integration-test path; routine CI must remain usable without external services.

## Pull requests

Use coherent commits, explain behavior and limitations, include tests for semantic changes, and do not add unsupported performance, compliance, or production-use claims. Run the entire local validation set before requesting review.
