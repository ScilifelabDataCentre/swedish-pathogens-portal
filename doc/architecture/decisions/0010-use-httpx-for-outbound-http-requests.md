# 10. Use `httpx` for outbound HTTP requests

**Date**: 2026-08-31

## Status

Accepted

## Context

The portal fetches JSON from external APIs.
We need one HTTP client with predictable failure handling, connection reuse, and an interface that supports both current synchronous code and possible asynchronous use later.

## Decision

We will use the pinned `httpx` package and route outbound API calls through the shared client in `cms.services.api_client`.

HTTPX was preferred over `requests` because it offers a similarly familiar API while adding full type annotations, asynchronous support, and default timeouts.
Its secure defaults include HTTPS certificate verification and no automatic redirect following.
The shared client also applies a 10-second timeout, and the current callers use fixed HTTPS endpoints.

### Security validation

As of 2026-08-31, no obvious security risk was identified in `httpx==0.28.1` or its locked runtime dependencies.
Upstream has [no published security advisories](https://github.com/encode/httpx/security/advisories), and the known historical [CVE-2021-41945](https://nvd.nist.gov/vuln/detail/CVE-2021-41945) affects HTTPX versions before 0.23.0.
The exact lockfile that introduced HTTPX also passed the project's [Trivy scan](https://github.com/ScilifelabDataCentre/spp-wagtail/actions/runs/33084694915) for medium, high, and critical vulnerabilities.
This is a point-in-time assessment; Renovate vulnerability alerts and the existing Trivy scans provide ongoing monitoring.

## Consequences

- Outbound API calls have consistent timeout, error-handling, and connection-pooling behaviour.
- The same library can support asynchronous requests later without introducing another client.
- HTTPX adds a small dependency tree and remains pre-1.0, so versions stay pinned and upgrades must include changelog and security review.
- Callers must not disable TLS verification or pass untrusted user-controlled URLs.
