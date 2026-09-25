# Contributing

Thank you for improving ChronoGraph.

## Development workflow

1. Create a focused branch from the current default branch.
2. Install `.[dev]` in Python 3.12 or newer.
3. Make a coherent change with tests and documentation where behavior changes.
4. Run every command in `docs/development.md`.
5. Open a pull request that explains the temporal, evidence, security, and compatibility effects.

Keep source inputs untrusted, preserve provenance, and reject invalid provider output before mutation. Changes to entity resolution should remain conservative. Changes to temporal semantics need current-time, historical valid-time, and known-at tests.

Do not add benchmark, production-use, compliance, scale, or backend-support claims without reproducible evidence and actual implementation. Do not commit credentials, private data, generated databases, or environment files.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
