# Security policy

## Supported versions

ChronoGraph has not published a release. Security fixes currently target the latest commit on the active development branch.

## Reporting a vulnerability

Do not include credentials, personal data, or exploitable details in a public issue. Use GitHub private vulnerability reporting for this repository when available. If that channel is unavailable, contact the repository owner through the GitHub profile and request a private reporting channel.

Include the affected commit, impact, minimal reproduction, and any proposed mitigation. Receipt and remediation timelines are not guaranteed for this pre-release project.

## Scope

Useful reports include validation bypasses, cross-record authorization risks, sensitive-memory disclosure, provenance leakage, query amplification, secret exposure, unsafe provider handling, and storage-integrity failures.

The default API auth provider is intentionally local-development-only. Lack of production authentication, multitenancy, distributed storage, or regulatory certification is documented functionality, not a hidden security property.
