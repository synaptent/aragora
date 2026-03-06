# Aragora Threat Model

**Version:** 1.1.0
**Classification:** Confidential
**Date:** March 2026
**Methodology:** STRIDE
**Platform:** Aragora Decision Integrity Platform

---

## 1. Asset Inventory

### 1.1 High-Value Assets

| Asset | Classification | Storage Location | Owner |
|-------|---------------|------------------|-------|
| Decision data (debate transcripts, votes, consensus proofs) | Confidential | PostgreSQL / SQLite | Platform |
| Decision receipts (audit trails with SHA-256 hashes) | Integrity-critical | PostgreSQL + Knowledge Mound | Platform |
| AI provider API keys (Anthropic, OpenAI, Mistral, xAI, OpenRouter) | Secret | Environment variables, `aragora/security/encryption.py` (AES-256-GCM at rest) | Platform admin |
| Agent credentials (OpenClaw gateway) | Secret | `aragora/server/handlers/openclaw/store.py` (AES-256-GCM encrypted, base64 fallback risk per F02) | Per-user |
| User PII (email, name, org membership) | Personal | PostgreSQL via `aragora/storage/` | Per-user |
| JWT signing keys | Secret | Environment / KMS via `aragora/security/kms_provider.py` | Platform admin |
| OIDC client secrets | Secret | Environment variables | Platform admin |
| Encryption master key (ARAGORA_ENCRYPTION_KEY) | Secret | Environment / KMS | Platform admin |
| Session tokens and refresh tokens | Secret | In-memory / Redis via `aragora/storage/redis_ha.py` | Per-user |
| RBAC role assignments and permissions | Integrity-critical | PostgreSQL | Platform admin |
| Tenant configuration and quotas | Confidential | PostgreSQL via `aragora/tenancy/quotas.py` | Tenant admin |
| Audit logs (security events, authorization decisions) | Integrity-critical | PostgreSQL + in-memory (10K cap per F11) | Platform |
| Knowledge Mound data (41 adapters, semantic search indices) | Confidential | PostgreSQL + file storage | Per-tenant |
| Skill definitions and marketplace content | Internal | SQLite / PostgreSQL via `aragora/skills/` | Platform |

### 1.2 Supporting Assets

| Asset | Classification | Notes |
|-------|---------------|-------|
| Source code | Internal | Git-hosted, CI/CD pipelines |
| Configuration files (.env, policy YAML) | Secret | Never committed to version control |
| Docker images and deployment manifests | Internal | `deploy/` directory |
| Prometheus metrics and Grafana dashboards | Internal | Operational telemetry |
| OpenTelemetry traces | Internal | Request correlation data |

---

## 2. Trust Boundaries

```
                    TRUST BOUNDARY 1: Internet Edge
 ┌──────────────────────────────────────────────────────────────────┐
 │  External Users / Clients                                        │
 │  - Web browsers, API clients, CLI tools                          │
 │  - Unauthenticated until JWT/API key validated                   │
 │  - Chat connectors (Telegram, WhatsApp, Slack, Discord, Teams)   │
 └──────────────┬───────────────────────────────────────────────────┘
                │ HTTPS / WSS
                ▼
                    TRUST BOUNDARY 2: API Gateway
 ┌──────────────────────────────────────────────────────────────────┐
 │  Middleware Stack                                                 │
 │  - Rate limiting (IP, user, tenant, OAuth, platform)             │
 │  - Auth middleware (JWT validation, API key check)               │
 │  - CSRF protection (double-submit cookie)                        │
 │  - Security headers (CSP, HSTS, X-Frame-Options)                │
 │  - Body size limits (100MB uploads, MAX_JSON_CONTENT_LENGTH)     │
 │  - Tenant isolation middleware (fail-closed)                     │
 │  - RBAC middleware (DEFAULT_ROUTE_PERMISSIONS)                   │
 │  Source: aragora/server/middleware/                               │
 └──────────────┬───────────────────────────────────────────────────┘
                │ Authenticated, authorized requests
                ▼
                    TRUST BOUNDARY 3: Application Core
 ┌──────────────────────────────────────────────────────────────────┐
 │  Unified Server + Handler Modules                                │
 │  - 700+ handler modules (aragora/server/handlers/)               │
 │  - Debate orchestrator (aragora/debate/orchestrator.py)          │
 │  - WebSocket stream servers (aragora/server/stream/)             │
 │  - Knowledge Mound (aragora/knowledge/mound/)                    │
 │  - Workflow engine (aragora/workflow/engine.py)                   │
 │  - OpenClaw gateway handlers (aragora/server/handlers/openclaw/) │
 │  - File validation (aragora/server/handlers/utils/)              │
 └──────────┬──────────────┬────────────────────────────────────────┘
            │              │
            ▼              ▼
  TRUST BOUNDARY 4a     TRUST BOUNDARY 4b
  Agent Execution       Storage Layer
 ┌──────────────────┐  ┌──────────────────────────────────────────┐
 │  AI Provider APIs │  │  PostgreSQL / SQLite / Redis              │
 │  - Anthropic      │  │  - Parameterized queries (verified)       │
 │  - OpenAI         │  │  - AES-256-GCM field-level encryption     │
 │  - Mistral        │  │  - Connection via env-configured strings  │
 │  - Grok / xAI     │  │  - Advisory lock migrations               │
 │  - OpenRouter     │  │  - Schema versioning                      │
 │  Source: aragora/  │  │  Source: aragora/storage/                 │
 │    agents/         │  └──────────────────────────────────────────┘
 │    api_agents/     │
 └──────────────────┘

                    TRUST BOUNDARY 5: OpenClaw Standalone
 ┌──────────────────────────────────────────────────────────────────┐
 │  Standalone Gateway (aragora/compat/openclaw/standalone.py)      │
 │  - Runs independently of main stack                              │
 │  - Optional API key auth (ARAGORA_OPENCLAW_API_KEY)              │
 │  - Own sandbox, credential store, policy engine                  │
 │  - Computer Use bridge (browser actions, SSRF risk)              │
 │  NOTE: This boundary has weaker controls than the main server    │
 └──────────────────────────────────────────────────────────────────┘
```

### Boundary Crossing Summary

| Crossing | From | To | Controls |
|----------|------|----|----------|
| B1 -> B2 | Internet | Gateway | TLS termination, WAF (Cloudflare), rate limiting |
| B2 -> B3 | Gateway | Application | JWT/API key validation, RBAC, tenant isolation, CSRF |
| B3 -> B4a | Application | AI Providers | SSRF protection, API key management, circuit breaker |
| B3 -> B4b | Application | Storage | Parameterized queries, encryption at rest, connection auth |
| B1 -> B5 | Internet | OpenClaw Standalone | API key check (if configured), body/header limits |

---

## 3. STRIDE Analysis -- Top 5 Attack Surfaces

### 3.1 Authentication and Token Management

**Attack Surface:** JWT issuance, validation, and rotation; OIDC/SAML SSO flows; API
key authentication; MFA enforcement.

**Source files:** `aragora/auth/oidc.py`, `aragora/auth/token_rotation.py`,
`aragora/auth/lockout.py`, `aragora/server/auth_checks.py`,
`aragora/server/middleware/auth.py`, `aragora/server/middleware/mfa.py`,
`aragora/server/middleware/token_revocation.py`.

| Threat | Category | Likelihood | Impact | Existing Controls | Gaps |
|--------|----------|------------|--------|-------------------|------|
| JWT signing algorithm confusion (alg=none, HS256 vs RS256) | Spoofing | Medium | Critical | PyJWT library with explicit algorithm list | Verify `algorithms` parameter is always explicit in `jwt.decode()` calls |
| Stolen JWT replayed from another IP | Spoofing | Medium | High | Token rotation on IP change (`RotationReason.IP_CHANGE`), usage tracking | Token binding is advisory, not enforced by default |
| OIDC state parameter fixation | Spoofing | Medium | High | State parameter generated with `secrets` module | Verify state is single-use and bound to session |
| OIDC redirect URI manipulation | Spoofing | Medium | High | Callback URL validated in `OIDCConfig` | Verify strict redirect URI matching (no open redirect) |
| Brute force against MFA OTP | Tampering | Medium | High | Account lockout (`aragora/auth/lockout.py`), anomaly detection | Verify OTP rate limiting and lockout thresholds |
| Token rotation race condition (concurrent requests) | Repudiation | Low | Medium | Token usage tracking with timestamps | Verify atomicity of rotation operations |
| Auth-exempt path bypasses | Elevation of Privilege | Medium | Critical | Explicit `AUTH_EXEMPT_PATHS` frozenset | Verify path normalization (e.g., `/api/health/../admin/`) |
| API key with empty scope grants full access | Elevation of Privilege | Low | High | `APIKeyScope.allows_permission()` returns True for empty permissions | By design, but should be documented and tested |
| Impersonation without proper audit | Elevation of Privilege | Low | High | `aragora/auth/impersonation.py`, audit logging | Verify impersonation events are always logged |

### 3.2 Authorization and Multi-Tenant RBAC

**Attack Surface:** Permission checks, role hierarchy resolution, tenant isolation,
resource ownership, delegation chains, emergency access.

**Source files:** `aragora/rbac/models.py`, `aragora/rbac/checker.py`,
`aragora/rbac/middleware.py`, `aragora/rbac/hierarchy.py`, `aragora/rbac/delegation.py`,
`aragora/rbac/emergency.py`, `aragora/server/middleware/tenant_isolation.py`.

| Threat | Category | Likelihood | Impact | Existing Controls | Gaps |
|--------|----------|------------|--------|-------------------|------|
| IDOR: accessing another user's debate/decision data | Information Disclosure | High | High | Ownership verification, tenant isolation middleware | Verify ownership checks on all 700+ handlers |
| Cross-tenant data access via tenant ID injection | Information Disclosure | Medium | Critical | Fail-closed tenant isolation middleware | Verify tenant context cannot be overridden in request body |
| Vertical privilege escalation via role hierarchy | Elevation of Privilege | Medium | Critical | Role priority system, hierarchy checks | Verify role inheritance cannot create circular elevation |
| Permission cache poisoning (stale decisions) | Elevation of Privilege | Low | High | `aragora/rbac/cache.py` with TTL | Verify cache invalidation on role/permission changes |
| Delegation chain escalation (delegated delegation) | Elevation of Privilege | Low | High | `aragora/rbac/delegation.py` | Verify max delegation depth, no transitive delegation to admin |
| Break-glass emergency access without audit | Repudiation | Low | High | `aragora/rbac/emergency.py` with audit | Verify all break-glass actions produce immutable audit entries |
| OpenClaw routes bypass RBAC middleware (F06) | Elevation of Privilege | Medium | Medium | Handler-level `@require_permission` decorators | Routes not in `DEFAULT_ROUTE_PERMISSIONS`; new endpoints could lack decorators |
| Wildcard permission `*` assigned to non-admin role | Elevation of Privilege | Low | Critical | Role configuration | Verify wildcard is only assignable by platform admin |
| Colon/dot format mismatch bypasses permission check | Elevation of Privilege | Low | Medium | `_permission_candidates()` generates both formats | Verify consistent handling in all check paths |

### 3.3 OpenClaw Agent Gateway

**Attack Surface:** Session management, action execution, credential storage, policy
enforcement, skill execution, computer use bridge.

**Source files:** `aragora/compat/openclaw/standalone.py`,
`aragora/server/handlers/openclaw/store.py`,
`aragora/server/handlers/openclaw/orchestrator.py`,
`aragora/server/handlers/openclaw/credentials.py`,
`aragora/compat/openclaw/computer_use_bridge.py`,
`aragora/compat/openclaw/skill_scanner.py`.

| Threat | Category | Likelihood | Impact | Existing Controls | Gaps |
|--------|----------|------------|--------|-------------------|------|
| Standalone server impersonation via X-User-ID header (F01) | Spoofing | High | Critical | Warning logged if no API key configured | No enforced auth if `ARAGORA_OPENCLAW_API_KEY` is unset |
| Credential secrets stored as base64 instead of AES-256-GCM (F02) | Information Disclosure | Medium | High | RuntimeError in production, logger.critical | Non-production environments silently downgrade |
| SSRF via NavigateAction URL (F07) | Information Disclosure | Medium | High | Sandbox environment may limit execution | No SSRF validation in `computer_use_bridge.py` |
| Session hijacking via unbounded session lifetime (F10) | Spoofing | Medium | Medium | None | No session TTL or idle timeout |
| Skill code injection bypassing malware scanner | Tampering | Low | Critical | `skill_scanner.py` pattern detection | Obfuscated patterns may evade regex-based scanning |
| Action parameter injection (shell metacharacters) | Tampering | Medium | High | Regex whitelisting, shell metachar blocking in `validation.py` | Verify all action types are covered |
| Health endpoint exception string leakage (F08) | Information Disclosure | Medium | Low | `safe_error_message()` used elsewhere | Health handler uses raw `str(e)` |
| Audit log overflow causing evidence loss (F11) | Repudiation | Low | Medium | 10K cap with persistent store for production | In-memory store silently drops entries |

### 3.4 Data Input and Injection

**Attack Surface:** HTTP request bodies, query parameters, file uploads, WebSocket
messages, debate prompts, webhook URLs.

**Source files:** `aragora/server/request_utils.py`,
`aragora/server/handlers/utils/file_validation.py`,
`aragora/security/ssrf_protection.py`, `aragora/server/middleware/xss_protection.py`,
`aragora/server/middleware/validation.py`.

| Threat | Category | Likelihood | Impact | Existing Controls | Gaps |
|--------|----------|------------|--------|-------------------|------|
| SQL injection via non-parameterized query | Tampering | Low | Critical | Parameterized queries standard throughout codebase | Verify 100% coverage across 700+ handlers |
| Stored XSS in debate transcripts or decision data | Tampering | Medium | Medium | XSS protection middleware | Verify output encoding on all data rendered in responses |
| Path traversal in file upload filenames | Tampering | Medium | High | Path traversal prevention in `file_validation.py`, null byte detection | Verify double-encoding bypass (e.g., `..%2f..%2f`) |
| SSRF via webhook URL registration | Information Disclosure | Medium | High | `ssrf_protection.py`: private IP blocking, DNS rebinding checks, cloud metadata blocking | Verify all outbound URL fetch points use `validate_url()` |
| SSRF via DNS rebinding (TTL-based) | Information Disclosure | Low | High | Optional `resolve_dns=True` mode | DNS resolution not enabled by default (`resolve_dns=False`) |
| Prompt injection via debate input affecting agent behavior | Tampering | High | Medium | Agent sandbox, debate protocol structure | LLM-level mitigation; no input sanitization for prompt content |
| Context memory/config poisoning (Brainworm-class: malicious `CLAUDE.md`, `MEMORY.md`, retrieved notes) | Tampering | High | High | Multi-agent critique and dissent tracking; Nomic Loop worktree isolation | No signed context manifests; no provenance/authority tiering for ingested files; malicious instructions appear as peer context (G1, G2) |
| Prompt supply-chain poisoning via upstream docs or knowledge retrieval | Tampering | Medium | High | Code review, branch protection, Knowledge Mound provenance tracking | No cryptographic signing of knowledge sources; no mandatory allowlist for model-ingested files (G1) |
| Context authority collapse (tool output or retrieved text treated as trusted operator instructions) | Elevation of Privilege | Medium | High | Multi-agent critique loop; dissent capture | No deterministic trust boundary enforcement inside model context window; taint does not propagate to receipt (G2) |
| JSON body exceeding size limits | Denial of Service | Medium | Medium | `MAX_JSON_CONTENT_LENGTH` enforcement | Verify enforcement on all parsing paths |
| Multipart boundary attack (oversized boundaries) | Denial of Service | Low | Medium | `MAX_MULTIPART_PARTS = 10` | Verify boundary size is also limited |
| WebSocket message injection (malformed events) | Tampering | Medium | Medium | Message dispatch in WebSocket handler | Verify message schema validation on all 190+ event types |

### 3.5 Cryptographic Operations

**Attack Surface:** Encryption at rest, key management, token signing, TLS
configuration, random number generation.

**Source files:** `aragora/security/encryption.py`, `aragora/security/key_rotation.py`,
`aragora/security/kms_provider.py`, `aragora/auth/oidc.py` (PyJWT).

| Threat | Category | Likelihood | Impact | Existing Controls | Gaps |
|--------|----------|------------|--------|-------------------|------|
| Encryption library unavailable in production (F02 variant) | Information Disclosure | Low | Critical | RuntimeError if `ARAGORA_ENV=production` and `cryptography` missing | Verify startup check catches all code paths |
| Weak key derivation (insufficient PBKDF2 iterations) | Information Disclosure | Low | High | PBKDF2HMAC in `encryption.py` | Verify iteration count meets current OWASP recommendations (600,000+ for SHA-256) |
| Key rotation leaving old data encrypted with expired keys | Information Disclosure | Low | Medium | Re-encryption support in `key_rotation.py` | Verify re-encryption is mandatory after rotation |
| HMAC timing attack on CSRF token validation | Spoofing | Low | Medium | HMAC-signed tokens in `csrf.py` | Verify `hmac.compare_digest()` used (not `==`) |
| Predictable random values in tokens | Spoofing | Low | High | `secrets` module used in `oidc.py`, `csrf.py` | Verify `secrets` (not `random`) used in all security-sensitive contexts |
| TLS downgrade to HTTP | Information Disclosure | Low | High | HSTS header with `SecurityHeadersMiddleware` | Verify HSTS max-age and includeSubDomains in production |

### 3.6 Model and Consensus Integrity (AI-Specific)

**Attack Surface:** Model endpoint trust, consensus arbitration logic, receipt-signing pipeline,
and auto-execution handoff. Covers both Brainworm-class (context injection) and OBLITERATUS-class
(weight surgery) attack vectors, as well as collusion and correlated failure scenarios.

**Source files:** `aragora/debate/orchestrator.py`, `aragora/debate/consensus.py`,
`aragora/debate/execution_bridge.py`, `aragora/gauntlet/signing.py`,
`aragora/server/handlers/gauntlet/receipts.py`, `aragora/agents/`, `aragora/config/settings.py`.

| Threat | Category | Likelihood | Impact | Existing Controls | Gaps |
|--------|----------|------------|--------|-------------------|------|
| OBLITERATUS-class refusal ablation (open-weight model weight surgery in participant set) | Tampering | Medium | High | Execution gate enforces provider + model-family diversity; lobotomized model must outvote intact heterogeneous peers without triggering dissent detection | Detection relies on behavioral divergence in debate; no runtime attestation challenge at registration (G3) |
| Endpoint substitution (modified model served behind expected alias) | Spoofing | Medium | High | Named agent registry, API key scoping | No behavior-signature challenge at registration; open-weight endpoints especially at risk (G3) |
| Collusion/Sybil in ensemble (multiple compromised models outvote intact minority) | Elevation of Privilege | Medium | High | Consensus proof + dissent recording; execution gate correlated-risk checks; provider diversity floors | Detection is heuristic; coordinated multi-provider compromise not addressed (G4) |
| Correlated failure across all models (shared blind spot) | Information Disclosure | Medium | High | Adversarial critique loop; heterogeneous training lineages | Consensus can be wrong; no mandatory external verification gate for high-impact decisions (G4) |
| Compromised arbitration or execution bridge logic | Elevation of Privilege | Low | Critical | Code review, tests, RBAC; execution gate requires verified signed receipts | Gate bypass is a critical regression risk; continuous verification tests required |
| Receipt-signing key compromise or misuse | Repudiation | Low | Critical | Multiple signing algorithms (HMAC-SHA256, RSA-SHA256, Ed25519); verification endpoints | Key custody and rotation policy not enforced as execution prerequisite |

**Planned mitigations (roadmap items):**
- **G1**: Signed context manifests — cryptographic provenance for trusted context sources ingested by Nomic Loop and debate orchestrator
- **G2**: Trust-tier taint propagation — tainted context annotations propagate through debate rounds and appear in receipt schema
- **G3**: Runtime model attestation — behavioral probe challenge at registration + periodic re-attestation during sessions
- **G4**: External verification gate — opt-in policy flag requiring non-Aragora verifier signature for high-impact decisions

---

## 4. Data Flow Diagrams

### 4.1 Authentication Flow

```
Client                  Gateway Middleware            Auth Service              Storage
  │                          │                           │                       │
  ├─── POST /auth/login ────►│                           │                       │
  │    (credentials)         ├── Rate limit check ──────►│                       │
  │                          ├── CSRF validation ───────►│                       │
  │                          │                           ├── Verify creds ──────►│
  │                          │                           │◄── User record ───────┤
  │                          │                           ├── Check lockout ─────►│
  │                          │                           ├── Check MFA ─────────►│
  │                          │                           ├── Issue JWT ──────────┤
  │                          │                           │   (sub, roles, exp,   │
  │                          │                           │    org_id, jti)       │
  │◄── JWT + refresh token ──┤◄── Token pair ────────────┤                       │
  │                          │                           │                       │
  ├─── GET /api/debates ────►│                           │                       │
  │    (Authorization: Bearer)│                          │                       │
  │                          ├── Extract JWT ───────────►│                       │
  │                          ├── Validate signature ────►│                       │
  │                          ├── Check revocation ──────►│                       │
  │                          ├── Check token rotation ──►│                       │
  │                          ├── Resolve permissions ───►│                       │
  │                          ├── Tenant isolation ──────►│                       │
  │◄── Response ─────────────┤                           │                       │
```

### 4.2 Agent Execution Flow

```
Client                  Aragora Server           Agent Proxy            AI Provider
  │                          │                       │                      │
  ├─── POST /debates ───────►│                       │                      │
  │    (topic, config)       ├── Auth + RBAC ───────►│                      │
  │                          ├── Build prompt ──────►│                      │
  │                          │                       ├── API call ─────────►│
  │                          │                       │   (with provider key) │
  │                          │                       │◄── LLM response ─────┤
  │                          │                       ├── Circuit breaker ──►│
  │                          │◄── Agent response ────┤                      │
  │                          ├── Store decision ────►│                      │
  │◄── Decision receipt ─────┤                       │                      │
```

---

## 5. Risk Summary Matrix

| Attack Surface | Highest Threat Severity | Residual Risk | Priority |
|----------------|------------------------|---------------|----------|
| Authentication / Tokens | Critical | Medium (controls strong, but JWT algorithm confusion and auth-exempt path bypass need verification) | P0 |
| Authorization / RBAC | Critical | Medium (comprehensive RBAC, but 700+ handlers need IDOR verification) | P0 |
| OpenClaw Gateway | Critical | High (standalone server has no enforced auth by default) | P0 |
| Data Input / Injection | Critical | Medium (parameterized queries standard, but SSRF, prompt injection, and context poisoning gaps exist) | P1 |
| Model & Consensus Integrity | Critical | Medium-High (debate helps, but collusion/correlated failure, context poisoning, and execution gating remain; no G1-G4 implemented) | P0 |
| Cryptographic Operations | Critical | Low (AES-256-GCM with key rotation, but encryption fallback risk in non-prod) | P1 |

---

## 6. Recommended Testing Priorities

Based on this threat model, the penetration test should prioritize in this order:

1. **OpenClaw standalone server authentication bypass** (F01) -- highest-risk finding still open
2. **IDOR and cross-tenant data access** across all major API categories
3. **JWT validation thoroughness** -- algorithm confusion, expiration bypass, path normalization
4. **RBAC boundary testing** -- role escalation, delegation chains, wildcard permissions
5. **SSRF vectors** -- webhook URLs, NavigateAction, any user-supplied URL fields
6. **File upload validation bypasses** -- path traversal, MIME spoofing, polyglot files
7. **WebSocket authentication and authorization** -- upgrade auth, subscription scope
8. **Prompt injection** via debate inputs (LLM-specific attack vector)
9. **Cryptographic validation** -- key strength, timing attacks, fallback behavior
10. **Rate limit bypass** -- distributed attacks, header manipulation, auth-exempt paths
11. **Context memory/config poisoning drills** (Brainworm-class) -- malicious `CLAUDE.md`/memory file instructions, indirect retrieval injection via Knowledge Mound
12. **Model endpoint integrity tests** (OBLITERATUS-class) -- open-weight refusal ablation simulation, endpoint substitution, provider diversity enforcement verification
13. **Consensus collusion simulations** -- compromised-model quorum and correlated-failure scenarios against arbitration logic and dissent detection
14. **Execution-gate regression verification** -- ensure high-impact actions continue to require verified signed receipts plus diversity/taint policy checks

---

*This document is confidential and should be updated after each penetration test cycle.*
