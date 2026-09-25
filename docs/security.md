# Security model

ChronoGraph treats source content, source metadata, provider output, query text, and imported fixtures as untrusted.

## Threat model and controls

| Threat | Implemented control | Remaining boundary |
| --- | --- | --- |
| Prompt injection in source text | Text is passed as data to typed providers; the deterministic extractor follows a narrow grammar; output is revalidated | An external model adapter must isolate instructions and credentials |
| Malicious metadata or provider output | Strict Pydantic models, undeclared-field rejection, ontology prevalidation, timezone and interval checks | Custom providers still need transport and resource controls |
| Oversized episodes and metadata | 100,000-character content limit and 32,000-character serialized metadata limit | HTTP infrastructure should add body and request-rate limits |
| Graph-query abuse | Results capped at 100, traversal depth capped at 5, neighbors capped at 1,000 | Deployment must add timeouts, rate limits, and workload isolation |
| Traversal explosion | Breadth-first traversal has a visited set and depth limit | The in-memory scan is not designed for large production graphs |
| Graph-store injection | Core code uses typed store operations and parameterized SQLite statements; no Cypher or SQL is accepted from users | Future database adapters must parameterize their native queries |
| Secret leakage | Common secret patterns are redacted from audit details; memory audit stores query and agent hashes | Redaction is heuristic and is not complete PII detection |
| Provider data exfiltration | Routine providers are local and deterministic | External provider adapters must document data transfer and retention |
| Unauthorized memory access | Auth is an injectable protocol | The default local provider allows all requests; production auth is not included |
| Sensitive provenance leakage | Memory sensitivity allowlists and retention states are enforced | Direct provenance endpoints require deployment authorization |
| Denial of service | Input, retry, result, memory, and graph-depth bounds | No built-in distributed rate limiter or admission controller |

## API authentication boundary

The included `AllowAllAuthProvider` is for local development and tests. A deployment must inject an `AuthProvider` that authenticates callers and authorizes access to episodes, entities, facts, provenance, memory, and administration. ChronoGraph does not include an identity platform.

## Tenancy

The current implementation is single-tenant. Records do not contain a tenant or workspace key, and the graph must not be shared between mutually untrusted tenants. Tenant-scoped storage, query enforcement, audit, and traversal are intentionally not claimed.

## Sensitive data and privacy

Sensitivity labels are explicit, not inferred. Memory defaults to public and internal facts. Retention actions can expire an episode from active memory, redact content, preserve a tombstone, or purge the episode only when policy explicitly permits it. Purge invalidates facts with no remaining active source.

Audit sanitization covers common secret-like keys and bearer/token patterns. It does not guarantee detection of every secret or personal identifier. Avoid sending raw secrets or unnecessary personal data into episodes.

## Evidence and audit

Facts preserve evidence paths, extraction method/version, source hashes, and episode identifiers. Evidence bundles expose temporal and policy decisions. These records improve traceability but may reveal metadata; authorize them as carefully as source data. Audit events are integrity hashes over sanitized details, not an immutable external ledger.

## Operational guidance

- Put authentication, TLS, request-size limits, rate limits, and access logging at the deployment boundary.
- Keep provider credentials outside episodes and committed files.
- Review custom ontologies and adapters as privileged code.
- Run the integrity checker after imports, migrations, or retention operations.
- Back up SQLite before operational use; it is not a distributed database.

ChronoGraph does not claim GDPR, HIPAA, SOC 2, PCI, or other regulatory compliance.
