---
title: Complete Environment Variable Reference
description: Complete Environment Variable Reference
---

# Complete Environment Variable Reference

> **Last Updated:** 2026-02-01
> **Auto-generated from codebase scan**

This document provides a comprehensive reference for ALL environment variables used across the Aragora codebase. For commonly-used variables with detailed explanations, see [ENVIRONMENT.md](../getting-started/environment).

---

## Table of Contents

1. [AI Provider Keys](#ai-provider-keys)
2. [Chat Platform Integrations](#chat-platform-integrations)
3. [Email & SMTP Configuration](#email--smtp-configuration)
4. [Microsoft / Azure Integration](#microsoft--azure-integration)
5. [Database Configuration](#database-configuration)
6. [Redis Configuration](#redis-configuration)
7. [Server Configuration](#server-configuration)
8. [Authentication & Security](#authentication--security)
9. [Debate & Context Configuration](#debate--context-configuration)
10. [Voice & Audio Configuration](#voice--audio-configuration)
11. [TTS (Text-to-Speech) Configuration](#tts-text-to-speech-configuration)
12. [Transcription Configuration](#transcription-configuration)
13. [Observability & Monitoring](#observability--monitoring)
14. [Knowledge & Vector Storage](#knowledge--vector-storage)
15. [Queue & Worker Configuration](#queue--worker-configuration)
16. [Blockchain / ERC8004 Configuration](#blockchain--erc8004-configuration)
17. [Payment Connectors](#payment-connectors)
18. [Accounting & Payroll Integrations](#accounting--payroll-integrations)
19. [Legal / DocuSign Integration](#legal--docusign-integration)
20. [DevOps Integrations](#devops-integrations)
21. [Threat Intelligence](#threat-intelligence)
22. [Sandbox & Container Pool](#sandbox--container-pool)
23. [Session & State Management](#session--state-management)
24. [Cache & Performance](#cache--performance)
25. [Moderation & Spam](#moderation--spam)
26. [Dead Letter Queue](#dead-letter-queue)
27. [Testing & CI Variables](#testing--ci-variables)
28. [Internal / Advanced](#internal--advanced)

---

## AI Provider Keys

Primary AI provider API keys. At least one is required.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | One required | Anthropic Claude API key | - |
| `OPENAI_API_KEY` | One required | OpenAI API key | - |
| `GEMINI_API_KEY` | Optional | Google Gemini API key | - |
| `GOOGLE_API_KEY` | Optional | Alias for `GEMINI_API_KEY` | - |
| `XAI_API_KEY` | Optional | Grok/XAI API key | - |
| `GROK_API_KEY` | Optional | Alias for `XAI_API_KEY` | - |
| `MISTRAL_API_KEY` | Optional | Mistral AI API key | - |
| `OPENROUTER_API_KEY` | Optional | OpenRouter multi-model access | - |
| `SUPERMEMORY_API_KEY` | Optional | Supermemory API key for external memory sync | - |
| `DEEPSEEK_API_KEY` | Optional | DeepSeek API key | - |
| `TINKER_API_KEY` | Optional | Tinker fine-tuning API key | - |

### OpenRouter Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `OPENROUTER_TIER` | Optional | OpenRouter tier for rate limits | - |
| `ARAGORA_OPENROUTER_FALLBACK_ENABLED` | Optional | OpenRouter fallback toggle; set `false` to opt out | `true` |

---

## Chat Platform Integrations

### Slack

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SLACK_BOT_TOKEN` | For Slack | Bot token (xoxb-...) for Slack API | - |
| `SLACK_SIGNING_SECRET` | For Slack | Request signing secret | - |
| `SLACK_CLIENT_ID` | For OAuth | OAuth app client ID | - |
| `SLACK_CLIENT_SECRET` | For OAuth | OAuth app client secret | - |
| `SLACK_APP_TOKEN` | Optional | App-level token for Socket Mode (xapp-...) | - |
| `SLACK_WEBHOOK_URL` | Optional | Outbound webhook URL | - |
| `SLACK_REDIRECT_URI` | Prod required | OAuth callback URL | Auto-construct in dev |
| `SLACK_SCOPES` | Optional | OAuth scopes (comma-separated) | Default scopes |

### Discord

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `DISCORD_BOT_TOKEN` | For Discord | Bot authentication token | - |
| `DISCORD_APPLICATION_ID` | For Discord | Application ID for slash commands | - |
| `DISCORD_PUBLIC_KEY` | For Discord | Public key for interaction verification | - |

### Telegram

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | For Telegram | Bot token from @BotFather | - |
| `TELEGRAM_CHAT_ID` | Optional | Default chat ID for notifications | - |

### Microsoft Teams

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `TEAMS_APP_ID` | For Teams | Azure Bot registration App ID | - |
| `TEAMS_APP_PASSWORD` | For Teams | Azure Bot registration password | - |
| `TEAMS_BOT_ID` | Optional | Teams bot identifier | - |
| `TEAMS_TENANT_ID` | Optional | Azure AD tenant ID | - |
| `TEAMS_WEBHOOK_URL` | Optional | Incoming webhook URL | - |
| `MICROSOFT_APP_ID` | Optional | Alias for Teams App ID | - |
| `MICROSOFT_APP_PASSWORD` | Optional | Alias for Teams password | - |

### Zoom

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ZOOM_CLIENT_ID` | For Zoom | OAuth client ID | - |
| `ZOOM_CLIENT_SECRET` | For Zoom | OAuth client secret | - |
| `ZOOM_BOT_JID` | For Zoom | Bot's JID for chat messages | - |
| `ZOOM_SECRET_TOKEN` | For Zoom | Webhook signature verification | - |
| `ZOOM_VERIFICATION_TOKEN` | Optional | Legacy verification token | - |

### WhatsApp

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `WHATSAPP_ACCESS_TOKEN` | For WhatsApp | Meta Graph API access token | - |
| `WHATSAPP_PHONE_NUMBER_ID` | For WhatsApp | WhatsApp phone number ID | - |
| `WHATSAPP_VERIFY_TOKEN` | For WhatsApp | Webhook verification token | - |

---

## Email & SMTP Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SMTP_HOST` | For email | SMTP server hostname | - |
| `SMTP_PORT` | Optional | SMTP server port | `587` |
| `SMTP_USER` | Optional | SMTP username | - |
| `SMTP_USERNAME` | Optional | Alias for SMTP_USER | - |
| `SMTP_PASSWORD` | Optional | SMTP password | - |
| `SMTP_USE_TLS` | Optional | Enable STARTTLS | `true` |
| `SMTP_USE_SSL` | Optional | Enable SSL/TLS | `false` |
| `SMTP_FROM_EMAIL` | Optional | From email address | `debates@aragora.ai` |
| `SMTP_FROM_NAME` | Optional | From display name | `Aragora Debates` |
| `SENDGRID_API_KEY` | Optional | SendGrid API key (alternative to SMTP) | - |
| `ALERT_EMAIL_RECIPIENTS` | Optional | Comma-separated alert recipients | - |

### Aragora SMTP (Billing/Notifications)

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SMTP_HOST` | Optional | SMTP host for billing | - |
| `ARAGORA_SMTP_PORT` | Optional | SMTP port for billing | `587` |
| `ARAGORA_SMTP_USER` | Optional | SMTP username for billing | - |
| `ARAGORA_SMTP_PASSWORD` | Optional | SMTP password for billing | - |
| `ARAGORA_SMTP_FROM` | Optional | From address for billing | `billing@aragora.ai` |

---

## Microsoft / Azure Integration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `AZURE_CLIENT_ID` | For Azure | Azure AD application client ID | - |
| `AZURE_CLIENT_SECRET` | For Azure | Azure AD client secret | - |
| `AZURE_TENANT_ID` | For Azure | Azure AD tenant ID | - |
| `MICROSOFT_CLIENT_ID` | Optional | Alias for Azure client ID | - |
| `MICROSOFT_CLIENT_SECRET` | Optional | Alias for Azure client secret | - |

### Outlook Calendar

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `OUTLOOK_TENANT_ID` | Optional | Outlook tenant ID | `common` |
| `OUTLOOK_CLIENT_ID` | Optional | Outlook OAuth client ID | - |
| `OUTLOOK_CLIENT_SECRET` | Optional | Outlook OAuth client secret | - |
| `OUTLOOK_CALENDAR_CLIENT_ID` | Optional | Calendar-specific client ID | - |
| `OUTLOOK_CALENDAR_CLIENT_SECRET` | Optional | Calendar-specific secret | - |

---

## Database Configuration

### Primary Database

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `DATABASE_URL` | Recommended | Primary database connection string | - |
| `ARAGORA_DATABASE_URL` | Optional | Alias for DATABASE_URL | - |
| `ARAGORA_POSTGRES_DSN` | Optional | Legacy Postgres DSN alias | - |
| `ARAGORA_SQL_CONNECTION` | Optional | Legacy SQL connection alias | - |
| `ARAGORA_DB_BACKEND` | Optional | Backend: `sqlite`, `postgres`, `postgresql` | Auto-detect |
| `ARAGORA_DB_MODE` | Optional | Layout: `legacy` or `consolidated` | `legacy` |
| `ARAGORA_DB_TIMEOUT` | Optional | Connection timeout (seconds) | `30` |
| `ARAGORA_DB_POOL_SIZE` | Optional | Connection pool size | `10`-`20` |
| `ARAGORA_DB_POOL_MAX_OVERFLOW` | Optional | Extra pool connections | `5`-`15` |
| `ARAGORA_DB_POOL_TIMEOUT` | Optional | Pool wait timeout (seconds) | `30` |

### SQLite Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SQLITE_PATH` | Optional | SQLite database file path | `aragora.db` |
| `ARAGORA_SQLITE_POOL_SIZE` | Optional | SQLite connection pool size | `10` |

### PostgreSQL Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_PG_HOST` | Optional | Postgres host | `localhost` |
| `ARAGORA_PG_PORT` | Optional | Postgres port | `5432` |
| `ARAGORA_PG_DATABASE` | Optional | Postgres database name | `aragora` |
| `ARAGORA_PG_USER` | Optional | Postgres username | `aragora` |
| `ARAGORA_PG_PASSWORD` | Optional | Postgres password | - |
| `ARAGORA_PG_SSL_MODE` | Optional | Postgres SSL mode | `require` |
| `ARAGORA_POSTGRESQL_POOL_SIZE` | Optional | Postgres pool size | `5` |
| `ARAGORA_POSTGRESQL_POOL_MAX_OVERFLOW` | Optional | Postgres pool overflow | `10` |

### Supabase

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SUPABASE_URL` | Optional | Supabase project URL | - |
| `SUPABASE_KEY` | Optional | Supabase service key | - |
| `SUPABASE_ANON_KEY` | Optional | Supabase anonymous key | - |
| `SUPABASE_JWT_SECRET` | Optional | Supabase JWT secret | - |
| `SUPABASE_SYNC_ENABLED` | Optional | Enable Supabase sync | `false` |
| `SUPABASE_SYNC_BATCH_SIZE` | Optional | Sync batch size | - |
| `SUPABASE_SYNC_INTERVAL_SECONDS` | Optional | Sync interval | - |
| `SUPABASE_SYNC_MAX_RETRIES` | Optional | Max sync retries | - |

### Store Backend Selection

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_INTEGRATION_STORE_BACKEND` | Optional | Integration store backend | `sqlite` |
| `ARAGORA_GMAIL_STORE_BACKEND` | Optional | Gmail token store backend | `sqlite` |
| `ARAGORA_INBOX_STORE_BACKEND` | Optional | Unified inbox store backend | `sqlite` |
| `ARAGORA_WORKFLOW_STORE_BACKEND` | Optional | Workflow store backend | `sqlite` |
| `ARAGORA_FEDERATION_STORE_BACKEND` | Optional | Federation registry backend | `sqlite` |
| `ARAGORA_EXPLAINABILITY_STORE_BACKEND` | Optional | Explainability batch store | Auto (Redis) |
| `ARAGORA_GAUNTLET_STORE_BACKEND` | Optional | Gauntlet run store backend | Auto |
| `ARAGORA_APPROVAL_STORE_BACKEND` | Optional | Approval request store backend | Auto |
| `ARAGORA_POLICY_STORE_BACKEND` | Optional | Policy store backend | Uses DB backend |
| `ARAGORA_AUDIT_STORE_BACKEND` | Optional | Audit log backend | Uses DB backend |
| `USE_SUPABASE_SLACK_STORE` | Optional | Force Supabase for Slack store | - |
| `USE_SUPABASE_TEAMS_STORE` | Optional | Force Supabase for Teams store | - |

---

## Redis Configuration

### Core Redis Settings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `REDIS_URL` | Optional | Legacy Redis URL | `redis://localhost:6379` |
| `ARAGORA_REDIS_URL` | Optional | Primary Redis URL | `redis://localhost:6379/0` |
| `ARAGORA_REDIS_MODE` | Optional | Mode: `standalone`, `sentinel`, `cluster` | Auto-detect |
| `ARAGORA_REDIS_HOST` | Optional | Redis host (standalone) | `localhost` |
| `ARAGORA_REDIS_PORT` | Optional | Redis port (standalone) | `6379` |
| `ARAGORA_REDIS_PASSWORD` | Optional | Redis password | - |
| `ARAGORA_REDIS_DB` | Optional | Redis database number | `0` |
| `ARAGORA_REDIS_USERNAME` | Optional | Redis username | - |

### Redis Connection Pool

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REDIS_MAX_CONNECTIONS` | Optional | Max connections in pool | `50` |
| `ARAGORA_REDIS_SOCKET_TIMEOUT` | Optional | Socket timeout (seconds) | `5.0` |
| `ARAGORA_REDIS_SOCKET_CONNECT_TIMEOUT` | Optional | Connect timeout (seconds) | `5.0` |
| `ARAGORA_REDIS_RETRY_ON_TIMEOUT` | Optional | Retry on timeout | `true` |
| `ARAGORA_REDIS_HEALTH_CHECK_INTERVAL` | Optional | Health check interval (seconds) | `30` |
| `ARAGORA_REDIS_DECODE_RESPONSES` | Optional | Decode responses to strings | `true` |

### Redis Sentinel

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REDIS_SENTINEL_HOSTS` | For Sentinel | Comma-separated sentinel hosts | - |
| `ARAGORA_REDIS_SENTINEL_MASTER` | Optional | Sentinel master name | `mymaster` |
| `ARAGORA_REDIS_SENTINEL_PASSWORD` | Optional | Sentinel password | - |
| `REDIS_SENTINEL_HOSTS` | Optional | Alternative sentinel hosts | - |
| `REDIS_SENTINEL_MASTER` | Optional | Alternative master name | `aragora-master` |
| `REDIS_PASSWORD` | Optional | Redis password (Sentinel setup) | - |

### Redis Cluster

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REDIS_CLUSTER_NODES` | For Cluster | Comma-separated cluster nodes | - |
| `ARAGORA_REDIS_CLUSTER_READ_FROM_REPLICAS` | Optional | Read from replicas | `true` |
| `ARAGORA_REDIS_CLUSTER_SKIP_FULL_COVERAGE` | Optional | Skip slot coverage check | `false` |
| `ARAGORA_REDIS_CLUSTER_MODE` | Optional | Cluster mode: `auto`, `cluster`, `standalone` | `auto` |
| `ARAGORA_REDIS_CLUSTER_MAX_CONNECTIONS` | Optional | Max connections per node | `32` |
| `ARAGORA_REDIS_CLUSTER_PASSWORD` | Optional | Cluster password | - |

### Redis SSL/TLS

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REDIS_SSL` | Optional | Enable SSL/TLS | `false` |
| `ARAGORA_REDIS_SSL_CERT_REQS` | Optional | SSL certificate requirements | - |
| `ARAGORA_REDIS_SSL_CA_CERTS` | Optional | Path to CA certificates | - |

### Redis Rate Limiting

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REDIS_KEY_PREFIX` | Optional | Key prefix for rate limits | `aragora:ratelimit:` |
| `ARAGORA_REDIS_TTL` | Optional | TTL for limiter keys (seconds) | `120` |
| `REDIS_RATE_LIMIT_PREFIX` | Optional | Rate limit key prefix | `aragora:ratelimit` |
| `ARAGORA_REDIS_FAILURE_THRESHOLD` | Optional | Failures before disabling | `3` |

---

## Server Configuration

### Core Server Settings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ENV` | Recommended | Environment: `development`, `production` | `development` |
| `ARAGORA_ENVIRONMENT` | Optional | Alias for ARAGORA_ENV | `development` |
| `ARAGORA_API_URL` | Optional | API base URL | `http://localhost:8080` |
| `ARAGORA_API_BASE_URL` | Optional | Internal API base URL | `http://localhost:8080` |
| `ARAGORA_HOST` | Optional | Bind host | `0.0.0.0` |
| `ARAGORA_PORT` | Optional | HTTP port | `8080` |
| `ARAGORA_BIND_HOST` | Optional | Server bind host | `0.0.0.0` |
| `ARAGORA_DEFAULT_HOST` | Optional | Fallback host for links | `localhost:8080` |
| `ARAGORA_GATEWAY_ID` | Optional | Gateway identifier | `default` |

### Authentication

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_API_TOKEN` | Optional | API authentication token; strict production/staging requires managed custody | Disabled |
| `ARAGORA_TOKEN_TTL` | Optional | Token lifetime (seconds) | `3600` |
| `ARAGORA_API_KEY` | Optional | Alternative API key | - |
| `ARAGORA_AUTH_REQUIRED` | Optional | Require authentication | - |
| `ARAGORA_AUTH_CLEANUP_INTERVAL` | Optional | Auth cleanup interval (seconds) | `300` |

### CORS Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ALLOWED_ORIGINS` | Optional | Comma-separated allowed origins | See docs |
| `ARAGORA_ALLOWED_OAUTH_HOSTS` | Optional | Allowed OAuth redirect hosts | `localhost:8080` |

### WebSocket Settings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_WS_MAX_MESSAGE_SIZE` | Optional | Max WebSocket message size | `65536` |
| `ARAGORA_WS_HEARTBEAT` | Optional | Heartbeat interval (seconds) | `30` |
| `ARAGORA_WS_CONN_RATE` | Optional | Connections per IP per minute | `30` |
| `ARAGORA_WS_MAX_PER_IP` | Optional | Max concurrent connections per IP | `10` |
| `ARAGORA_WS_MSG_RATE` | Optional | Messages per second per connection | `10` |
| `ARAGORA_WS_MSG_BURST` | Optional | Message burst size | `20` |
| `ARAGORA_TRUSTED_PROXIES` | Optional | Trusted proxy IPs | `127.0.0.1,::1,localhost` |

### Rate Limiting

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_RATE_LIMIT` | Optional | Requests per minute per token | `60` |
| `ARAGORA_IP_RATE_LIMIT` | Optional | Requests per minute per IP | `120` |
| `ARAGORA_BURST_MULTIPLIER` | Optional | Burst multiplier | `2.0` |
| `ARAGORA_RATE_LIMIT_FAIL_OPEN` | Optional | Allow requests if Redis down | `false` |
| `ARAGORA_RATE_LIMIT_CIRCUIT_BREAKER` | Optional | Enable circuit breaker | `true` |
| `ARAGORA_RATE_LIMIT_DISTRIBUTED_METRICS` | Optional | Enable distributed metrics | `true` |
| `ARAGORA_RATE_LIMIT_METRICS_INTERVAL` | Optional | Metrics interval (seconds) | `60` |

### Request Timeouts

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REQUEST_TIMEOUT` | Optional | Default request timeout (seconds) | `30` |
| `ARAGORA_SLOW_REQUEST_TIMEOUT` | Optional | Slow endpoint timeout (seconds) | `60`-`120` |
| `ARAGORA_MAX_REQUEST_TIMEOUT` | Optional | Maximum timeout (seconds) | `300`-`600` |
| `ARAGORA_TIMEOUT_WORKERS` | Optional | Timeout thread pool size | `4`-`10` |

### HTTP Client Pool

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_HTTP_POOL_SIZE` | Optional | HTTP connection pool size | `20` |
| `ARAGORA_HTTP_CONNECT_TIMEOUT` | Optional | HTTP connect timeout (seconds) | `10` |
| `ARAGORA_HTTP_TIMEOUT` | Optional | HTTP read timeout (seconds) | `60` |
| `ARAGORA_HTTP_KEEPALIVE` | Optional | Keepalive timeout (seconds) | `30` |
| `ARAGORA_HTTP_MAX_RETRIES` | Optional | Max HTTP retries | `3` |

### Connection Pool (Generic)

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_POOL_MIN_CONNECTIONS` | Optional | Min pool connections | `5` |
| `ARAGORA_POOL_MAX_CONNECTIONS` | Optional | Max pool connections | `50` |
| `ARAGORA_POOL_OVERFLOW_MAX` | Optional | Pool overflow limit | `10` |
| `ARAGORA_POOL_IDLE_TIMEOUT` | Optional | Idle connection timeout (seconds) | `300.0` |
| `ARAGORA_POOL_MAX_WAIT_TIME` | Optional | Max wait for connection (seconds) | `5.0` |
| `ARAGORA_POOL_HEALTH_CHECK_INTERVAL` | Optional | Health check interval (seconds) | `30.0` |
| `ARAGORA_POOL_HEALTH_CHECK_TIMEOUT` | Optional | Health check timeout (seconds) | `2.0` |
| `ARAGORA_POOL_MAX_RETRIES` | Optional | Max pool retries | `3` |
| `ARAGORA_POOL_RETRY_DELAY` | Optional | Pool retry delay (seconds) | `0.1` |

### Streaming

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_STREAM_BUFFER_SIZE` | Optional | Max SSE buffer size (bytes) | `10485760` |
| `ARAGORA_STREAM_CHUNK_TIMEOUT` | Optional | Timeout between chunks (seconds) | `180` |

### SSL/TLS

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SSL_ENABLED` | Optional | Enable SSL/TLS | `false` |
| `ARAGORA_SSL_CERT` | If SSL | Path to SSL certificate | - |
| `ARAGORA_SSL_KEY` | If SSL | Path to SSL private key | - |

---

## Authentication & Security

### JWT Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_JWT_SECRET` | Prod required | JWT signing secret (min 32 chars) | - |
| `ARAGORA_JWT_SECRET_PREVIOUS` | Optional | Previous secret for rotation | - |
| `ARAGORA_JWT_SECRET_ROTATED_AT` | Optional | Unix timestamp of rotation | - |
| `ARAGORA_JWT_ROTATION_GRACE_HOURS` | Optional | Grace period for previous secret | `24` |
| `ARAGORA_JWT_EXPIRY_HOURS` | Optional | Access token expiry (hours) | `24` |
| `ARAGORA_JWT_SESSION_TTL` | Optional | Session TTL (seconds) | `2592000` (30 days) |
| `ARAGORA_REFRESH_TOKEN_EXPIRY_DAYS` | Optional | Refresh token expiry (days) | `30` |
| `JWT_SECRET` | Optional | Alias for JWT secret | - |

### Token Blacklist

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_BLACKLIST_BACKEND` | Optional | Backend: `memory`, `sqlite`, `redis` | `sqlite` |

### Session Management

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_MAX_SESSIONS_PER_USER` | Optional | Max sessions per user | `10` |
| `ARAGORA_SESSION_INACTIVITY_TIMEOUT` | Optional | Inactivity timeout (seconds) | `86400` |

### Password & Security

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ALLOW_INSECURE_PASSWORDS` | Optional | Allow weak passwords (dev only) | `0` |
| `ARAGORA_ALLOW_INSECURE_JWT` | Optional | Allow insecure JWT (dev only) | - |
| `ARAGORA_ALLOW_FORMAT_ONLY_API_KEYS` | Optional | Format-only API key validation | `0` |

### Encryption

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ENCRYPTION_KEY` | Prod required | Encryption key for data at rest | - |
| `ARAGORA_ENCRYPTION_REQUIRED` | Optional | Fail if encryption unavailable | Auto in prod |
| `ARAGORA_AUDIT_SIGNING_KEY` | Optional | Key for signing audit logs | - |
| `ARAGORA_CREDENTIAL_VAULT_SALT` | Optional | Salt for credential vault | - |

### SAML Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ALLOW_UNSAFE_SAML` | Optional | Allow unsafe SAML (dev only) | - |
| `ARAGORA_ALLOW_UNSAFE_SAML_CONFIRMED` | Optional | Confirm unsafe SAML | - |

### SSO Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SSO_ENABLED` | Optional | Enable SSO | `false` |
| `ARAGORA_SSO_PROVIDER_TYPE` | If SSO | Provider: `oidc`, `saml`, `azure_ad`, `okta`, `google` | `oidc` |
| `ARAGORA_SSO_CLIENT_ID` | OIDC | OAuth client ID | - |
| `ARAGORA_SSO_CLIENT_SECRET` | OIDC | OAuth client secret | - |
| `ARAGORA_SSO_ISSUER_URL` | OIDC | OIDC issuer URL | - |
| `ARAGORA_SSO_CALLBACK_URL` | If SSO | Auth callback URL | - |
| `ARAGORA_SSO_ENTITY_ID` | If SSO | Service provider entity ID | - |
| `ARAGORA_SSO_ALLOWED_DOMAINS` | Optional | Comma-separated allowed email domains | All |
| `ARAGORA_SSO_ALLOWED_REDIRECT_HOSTS` | Optional | Allowed redirect hosts | - |
| `ARAGORA_SSO_AUTO_PROVISION` | Optional | Auto-create users | `true` |
| `ARAGORA_SSO_SESSION_DURATION` | Optional | Session duration (seconds) | `28800` |
| `ARAGORA_SSO_IDP_CERTIFICATE` | SAML | IdP X.509 certificate | - |

### CSRF Protection

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_CSRF_ENABLED` | Optional | Enable CSRF protection | Auto (prod) |
| `ARAGORA_CSRF_COOKIE_NAME` | Optional | CSRF cookie name | Default |
| `ARAGORA_CSRF_HEADER_NAME` | Optional | CSRF header name | Default |
| `ARAGORA_CSRF_COOKIE_SAMESITE` | Optional | Cookie SameSite attribute | `Strict` |
| `ARAGORA_CSRF_TOKEN_MAX_AGE` | Optional | Token max age (seconds) | Default |
| `ARAGORA_CSRF_EXEMPT_PATHS` | Optional | Comma-separated exempt paths | - |
| `ARAGORA_CSRF_SAFE_METHODS` | Optional | Safe HTTP methods | - |

### Security Headers

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SECURITY_HEADERS_ENABLED` | Optional | Enable security headers | `true` |
| `ARAGORA_X_FRAME_OPTIONS` | Optional | X-Frame-Options header | Default |
| `ARAGORA_X_XSS_PROTECTION` | Optional | X-XSS-Protection header | Default |
| `ARAGORA_REFERRER_POLICY` | Optional | Referrer-Policy header | Default |
| `ARAGORA_CONTENT_SECURITY_POLICY` | Optional | CSP header | Default |
| `ARAGORA_STRICT_TRANSPORT_SECURITY` | Optional | HSTS header | Default |

### CSP Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ENABLE_CSP` | Optional | Enable Content Security Policy | `true` |
| `ARAGORA_CSP_MODE` | Optional | CSP mode: `standard`, etc. | `standard` |
| `ARAGORA_CSP_REPORT_URI` | Optional | CSP violation report URI | `/api/csp-report` |

### XSS Protection

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_AUTO_ESCAPE_HTML` | Optional | Auto-escape HTML | `true` |
| `ARAGORA_ENFORCE_COOKIE_SECURITY` | Optional | Enforce secure cookies | `true` |
| `ARAGORA_COOKIE_SAMESITE` | Optional | Cookie SameSite | `Lax` |
| `ARAGORA_COOKIE_SECURE` | Optional | Secure cookie flag | `true` |
| `ARAGORA_COOKIE_HTTPONLY` | Optional | HttpOnly cookie flag | `true` |

---

## Debate & Context Configuration

### Debate Defaults

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DEFAULT_ROUNDS` | Optional | Default debate rounds | `9` |
| `ARAGORA_MAX_ROUNDS` | Optional | Max debate rounds | `12` |
| `ARAGORA_DEFAULT_CONSENSUS` | Optional | Consensus mode | `judge` |
| `ARAGORA_DEBATE_TIMEOUT` | Optional | Debate timeout (seconds) | `600` |
| `ARAGORA_AGENT_TIMEOUT` | Optional | Per-agent timeout (seconds) | `240` |

### Agent Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DEFAULT_AGENTS` | Optional | Default agent list | Multiple |
| `ARAGORA_STREAMING_AGENTS` | Optional | Streaming-capable agents | Multiple |
| `ARAGORA_MAX_CLI_SUBPROCESSES` | Optional | Max CLI agent subprocesses | `4` |

### Context Gathering Timeouts

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_CONTEXT_TIMEOUT` | Optional | Total context gather timeout | `150.0` |
| `ARAGORA_CLAUDE_SEARCH_TIMEOUT` | Optional | Claude search timeout | `120.0` |
| `ARAGORA_EVIDENCE_TIMEOUT` | Optional | Evidence timeout | `30.0` |
| `ARAGORA_TRENDING_TIMEOUT` | Optional | Trending topics timeout | `5.0` |
| `ARAGORA_KNOWLEDGE_MOUND_TIMEOUT` | Optional | Knowledge Mound timeout | `10.0` |
| `ARAGORA_BELIEF_CRUX_TIMEOUT` | Optional | Belief crux timeout | `5.0` |
| `ARAGORA_THREAT_INTEL_TIMEOUT` | Optional | Threat intel timeout | `10.0` |
| `ARAGORA_CODEBASE_CONTEXT_TIMEOUT` | Optional | Codebase context timeout | `60.0` |

### Context Cache Sizes

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_MAX_EVIDENCE_CACHE` | Optional | Evidence cache size | `100` |
| `ARAGORA_MAX_CONTEXT_CACHE` | Optional | Context cache size | `100` |
| `ARAGORA_MAX_CONTINUUM_CACHE` | Optional | Continuum cache size | `100` |
| `ARAGORA_MAX_TRENDING_CACHE` | Optional | Trending cache size | `50` |

### Context Features

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DISABLE_TRENDING` | Optional | Disable trending topics | - |
| `ARAGORA_CONTEXT_USE_CODEBASE` | Optional | Use codebase context | - |

### Similarity & Convergence

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SIMILARITY_BACKEND` | Optional | Similarity backend | - |
| `ARAGORA_CONVERGENCE_BACKEND` | Optional | Convergence backend | - |

### Belief Network

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_BELIEF_MAX_ITERATIONS` | Optional | Max belief iterations | `100` |
| `ARAGORA_BELIEF_CONVERGENCE_THRESHOLD` | Optional | Convergence epsilon | `0.001` |

---

## Voice & Audio Configuration

### Voice Input

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_VOICE_DEVICE_ID` | Optional | Audio input device ID | - |
| `ARAGORA_VOICE_SAMPLE_RATE` | Optional | Sample rate (Hz) | `16000` |
| `ARAGORA_VOICE_CHANNELS` | Optional | Audio channels | `1` |
| `ARAGORA_VOICE_CHUNK_SIZE` | Optional | Audio chunk size | `1024` |

### Voice Session Limits

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_VOICE_MAX_SESSION` | Optional | Max session duration (seconds) | `300` |
| `ARAGORA_VOICE_MAX_BUFFER` | Optional | Max buffer size (bytes) | `25MB` |
| `ARAGORA_VOICE_INTERVAL` | Optional | Transcribe interval (ms) | `3000` |
| `ARAGORA_VOICE_MAX_SESSIONS_IP` | Optional | Max sessions per IP | `3` |
| `ARAGORA_VOICE_RATE_BYTES` | Optional | Rate limit (bytes) | `5MB` |

### Voice TTS

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_VOICE_TTS_ENABLED` | Optional | Enable TTS for voice | `true` |
| `ARAGORA_VOICE_TTS_DEFAULT_VOICE` | Optional | Default TTS voice | `narrator` |

### Wake Word Detection

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_WAKE_PHRASES` | Optional | Wake phrases | `hey aragora,ok aragora` |
| `ARAGORA_WAKE_BACKEND` | Optional | Detection backend | `keyword` |
| `ARAGORA_WAKE_SENSITIVITY` | Optional | Detection sensitivity | `0.5` |
| `ARAGORA_WAKE_MIN_CONFIDENCE` | Optional | Minimum confidence | `0.6` |
| `ARAGORA_WAKE_COOLDOWN` | Optional | Cooldown (seconds) | `2.0` |
| `ARAGORA_WAKE_MAX_LISTEN` | Optional | Max listen time (seconds) | `30.0` |
| `ARAGORA_WAKE_SILENCE_THRESHOLD` | Optional | Silence threshold (seconds) | `1.5` |
| `ARAGORA_WAKE_DEBUG` | Optional | Enable debug logging | - |
| `PICOVOICE_ACCESS_KEY` | Optional | Picovoice API key | - |
| `PORCUPINE_MODEL_PATH` | Optional | Porcupine model path | - |
| `VOSK_MODEL_PATH` | Optional | Vosk model path | - |

---

## TTS (Text-to-Speech) Configuration

### Backend Selection

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_TTS_BACKEND` | Optional | Force specific backend | Auto |
| `ARAGORA_TTS_ORDER` | Optional | Backend priority | `elevenlabs,xtts,edge-tts,pyttsx3` |
| `TTS_BACKEND` | Optional | Alternative backend selector | - |
| `TTS_BACKEND_PRIORITY` | Optional | Alternative backend priority | - |

### ElevenLabs

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ELEVENLABS_API_KEY` | Optional | ElevenLabs API key | - |
| `ELEVENLABS_API_KEY` | Optional | Alias for API key | - |
| `ARAGORA_ELEVENLABS_MODEL_ID` | Optional | ElevenLabs model | `eleven_multilingual_v2` |
| `ELEVENLABS_MODEL` | Optional | Alias for model | - |
| `ARAGORA_ELEVENLABS_VOICE_ID` | Optional | Default voice ID | - |
| `ARAGORA_ELEVENLABS_DEFAULT_VOICE_ID` | Optional | Alternative default voice | - |
| `ELEVENLABS_VOICE_ID` | Optional | Alias for voice ID | - |
| `ARAGORA_ELEVENLABS_VOICE_MAP` | Optional | JSON speaker-to-voice mapping | - |

### XTTS (Coqui)

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_XTTS_MODEL_PATH` | Optional | XTTS model path | Default model |
| `ARAGORA_XTTS_MODEL` | Optional | XTTS model name | - |
| `XTTS_MODEL_PATH` | Optional | Alias for model path | - |
| `ARAGORA_XTTS_DEVICE` | Optional | Device: `auto`, `cuda`, `cpu` | `auto` |
| `XTTS_DEVICE` | Optional | Alias for device | `auto` |
| `ARAGORA_XTTS_LANGUAGE` | Optional | Language code | `en` |
| `XTTS_LANGUAGE` | Optional | Alias for language | `en` |
| `ARAGORA_XTTS_SPEAKER_WAV` | Optional | Default speaker WAV | - |
| `XTTS_SPEAKER_WAV` | Optional | Alias for speaker WAV | - |
| `ARAGORA_XTTS_SPEAKER_WAV_MAP` | Optional | JSON speaker-to-WAV mapping | - |

### AWS Polly

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_POLLY_REGION` | Optional | AWS region for Polly | AWS_REGION |
| `ARAGORA_POLLY_ENGINE` | Optional | Polly engine | `neural` |
| `ARAGORA_POLLY_TEXT_TYPE` | Optional | Text type | `text` |
| `ARAGORA_POLLY_VOICE_ID` | Optional | Default Polly voice | - |
| `ARAGORA_POLLY_DEFAULT_VOICE_ID` | Optional | Alternative voice ID | - |
| `ARAGORA_POLLY_LEXICONS` | Optional | Comma-separated lexicon names | - |

### TTS General

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_TTS_TIMEOUT` | Optional | TTS timeout (seconds) | `60` |
| `ARAGORA_TTS_RETRIES` | Optional | TTS retry attempts | `3` |
| `ARAGORA_TTS_CACHE_DIR` | Optional | TTS cache directory | `.cache/tts` |
| `TTS_CACHE_DIR` | Optional | Alias for cache dir | - |
| `ARAGORA_AUDIO_DIR` | Optional | Audio output directory | `.nomic/audio/` |

---

## Transcription Configuration

### Whisper Settings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_WHISPER_BACKEND` | Optional | Backend: `openai`, `faster-whisper`, `whisper-cpp`, `auto` | `auto` |
| `ARAGORA_WHISPER_BACKEND_ORDER` | Optional | Custom backend order | - |
| `ARAGORA_WHISPER_MODEL` | Optional | Model size: `tiny`, `base`, `small`, `medium`, `large` | `base` |
| `ARAGORA_WHISPER_DEVICE` | Optional | Device for local whisper | `auto` |
| `ARAGORA_WHISPER_LANGUAGE` | Optional | Language code | - |
| `ARAGORA_WHISPER_TIMESTAMPS` | Optional | Enable timestamps | `true` |
| `ARAGORA_WHISPER_WORD_TIMESTAMPS` | Optional | Enable word timestamps | `false` |
| `ARAGORA_TRANSCRIPTION_TIMEOUT` | Optional | Transcription timeout (seconds) | `300` |
| `ARAGORA_MAX_AUDIO_DURATION` | Optional | Max audio duration (seconds) | `3600` |
| `ARAGORA_MAX_AUDIO_SIZE_MB` | Optional | Max audio file size (MB) | `25` |
| `WHISPER_CPP_PATH` | Optional | Path to whisper.cpp binary | Auto-detect |
| `WHISPER_CPP_MODELS` | Optional | Whisper.cpp models directory | `~/.cache/whisper` |

### Speech-to-Text Provider

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_STT_PROVIDER` | Optional | STT provider | `openai_whisper` |

### YouTube Transcription

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_YOUTUBE_CACHE` | Optional | YouTube cache directory | System temp |

---

## Observability & Monitoring

### OpenTelemetry

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `OTEL_ENABLED` | Optional | Enable OpenTelemetry | - |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional | OTLP collector endpoint | - |
| `OTEL_SERVICE_NAME` | Optional | Service name | - |
| `OTEL_TRACES_SAMPLER` | Optional | Sampler type | `parentbased_traceidratio` |
| `OTEL_TRACES_SAMPLER_ARG` | Optional | Sampler argument | - |
| `OTEL_SAMPLE_RATE` | Optional | Sample rate | - |
| `OTEL_PROPAGATORS` | Optional | Propagator types | `tracecontext,baggage` |
| `OTEL_RESOURCE_ATTRIBUTES` | Optional | Resource attributes | - |
| `ARAGORA_OTLP_EXPORTER` | Optional | Exporter: `none`, `jaeger`, `zipkin`, `otlp_grpc`, `otlp_http`, `datadog` | `none` |
| `ARAGORA_OTLP_ENDPOINT` | Optional | OTLP endpoint | Type-specific |
| `ARAGORA_OTLP_HEADERS` | Optional | JSON headers for auth | - |
| `ARAGORA_OTLP_BATCH_SIZE` | Optional | Batch processor size | `512` |
| `ARAGORA_OTLP_EXPORT_TIMEOUT_MS` | Optional | Export timeout (ms) | `30000` |
| `ARAGORA_OTLP_INSECURE` | Optional | Allow non-TLS | `false` |
| `ARAGORA_OTEL_DEV_MODE` | Optional | Enable dev mode | - |
| `ARAGORA_SERVICE_NAME` | Optional | Service name | `aragora` |
| `ARAGORA_SERVICE_VERSION` | Optional | Service version | `1.0.0` |
| `ARAGORA_TRACE_SAMPLE_RATE` | Optional | Sample rate (0.0-1.0) | `1.0` |

### Datadog

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `DATADOG_API_KEY` | For Datadog | Datadog API key | - |

### Sentry

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SENTRY_DSN` | Optional | Sentry DSN | - |
| `SENTRY_ENVIRONMENT` | Optional | Sentry environment | `development` |
| `SENTRY_TRACES_SAMPLE_RATE` | Optional | Trace sample rate | `0.1` |
| `SENTRY_PROFILES_SAMPLE_RATE` | Optional | Profile sample rate | `0.1` |
| `SENTRY_SERVER_NAME` | Optional | Server name | - |

### Logging

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DEBUG` | Optional | Enable debug logging | `false` |
| `ARAGORA_LOG_LEVEL` | Optional | Log level | `INFO` |
| `LOG_LEVEL` | Optional | Alternative log level | `INFO` |
| `ARAGORA_LOG_FILE` | Optional | Log file path | stdout |
| `ARAGORA_LOG_FORMAT` | Optional | Format: `json`, `text`, `human` | `text`/`json` |
| `ARAGORA_LOG_TIMESTAMP` | Optional | Include timestamps | `true` |
| `ARAGORA_LOG_MAX_BYTES` | Optional | Max log file size | `10485760` |
| `ARAGORA_LOG_BACKUP_COUNT` | Optional | Rotated log files to keep | `5` |
| `ARAGORA_LOG_REDACT` | Optional | Redact sensitive data | `true` |
| `ARAGORA_LOG_STACKTRACE` | Optional | Include stack traces | `true` |
| `ARAGORA_DEV_MODE` | Optional | Enable dev mode features | `false` |
| `AUDIT_LOG_DIR` | Optional | Audit log directory | `logs/audit` |

### Metrics

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `METRICS_ENABLED` | Optional | Enable metrics | `true` |
| `METRICS_PORT` | Optional | Metrics server port | `9090` |
| `ARAGORA_METRICS_ENABLED` | Optional | Enable Aragora metrics | `true` |
| `ARAGORA_METRICS_TOKEN` | Optional | Metrics endpoint auth token | - |

### Alerting

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ALERTING_ENABLED` | Optional | Enable alerting | `true` |
| `ALERTING_CHECK_INTERVAL_SECONDS` | Optional | Check interval | Default |
| `ALERTING_COOLDOWN_SECONDS` | Optional | Alert cooldown | Default |
| `PROMETHEUS_ALERTMANAGER_URL` | Optional | Alertmanager URL | - |

### SLO Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SLO_AVAILABILITY_TARGET` | Optional | Availability SLO target | `99.9` |
| `SLO_LATENCY_P99_TARGET_MS` | Optional | P99 latency target (ms) | Default |
| `SLO_DEBATE_SUCCESS_TARGET` | Optional | Debate success rate target | Default |

### Telemetry Level

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_TELEMETRY_LEVEL` | Optional | Level: `SILENT`, `DIAGNOSTIC`, `CONTROLLED`, `SPECTACLE` | `CONTROLLED` |

---

## Knowledge & Vector Storage

### Vector Store Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `VECTOR_BACKEND` | Optional | Vector backend | `memory` |
| `VECTOR_STORE_URL` | Optional | Vector store URL | - |
| `VECTOR_STORE_API_KEY` | Optional | Vector store API key | - |
| `VECTOR_COLLECTION` | Optional | Collection name | `knowledge_mound` |
| `EMBEDDING_DIMENSIONS` | Optional | Embedding dimensions | `1536` |
| `DISTANCE_METRIC` | Optional | Distance metric | `cosine` |
| `VECTOR_NAMESPACE_ROUTING` | Optional | Enable namespace routing | `true` |

### Weaviate

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `WEAVIATE_URL` | Optional | Weaviate URL | `http://localhost:8080` |
| `WEAVIATE_API_KEY` | Optional | Weaviate API key | - |
| `WEAVIATE_COLLECTION` | Optional | Document collection name | `DocumentChunks` |
| `WEAVIATE_KNOWLEDGE_COLLECTION` | Optional | Knowledge collection name | `KnowledgeNodes` |

### Pinecone

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `PINECONE_API_KEY` | Optional | Pinecone API key | - |

### Embeddings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `EMBEDDING_MODEL` | Optional | Embedding model | `text-embedding-3-small` |
| `OPENAI_EMBEDDING_MODEL` | Optional | OpenAI embedding model | `text-embedding-3-small` |

### Knowledge System

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_KNOWLEDGE_AUTO_PROCESS` | Optional | Auto-process entries | `true` |
| `ARAGORA_QUERY_CACHE_ENABLED` | Optional | Enable query cache | `true` |
| `ARAGORA_QUERY_CACHE_MAX_SIZE` | Optional | Query cache size | `1000` |
| `ARAGORA_WORKSPACE` | Optional | Default workspace | `default` |

---

## Queue & Worker Configuration

### Queue Settings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_QUEUE_PREFIX` | Optional | Queue key prefix | `aragora:queue:` |
| `ARAGORA_QUEUE_MAX_TTL_DAYS` | Optional | Max job TTL (days) | `7` |
| `ARAGORA_QUEUE_CLAIM_IDLE_MS` | Optional | Claim idle timeout (ms) | `60000` |
| `ARAGORA_QUEUE_RETRY_MAX` | Optional | Max retries | `3` |
| `ARAGORA_QUEUE_RETRY_BASE_DELAY` | Optional | Base retry delay (seconds) | `1.0` |
| `ARAGORA_QUEUE_RETRY_MAX_DELAY` | Optional | Max retry delay (seconds) | `300.0` |
| `ARAGORA_QUEUE_WORKER_BLOCK_MS` | Optional | Worker block timeout (ms) | `5000` |
| `ARAGORA_QUEUE_POLL_INTERVAL` | Optional | Poll interval (seconds) | `1.0` |
| `ARAGORA_QUEUE_CONSUMER_GROUP` | Optional | Consumer group name | `debate-workers` |
| `ARAGORA_QUEUE_PENDING_WARNING` | Optional | Pending job warning threshold | `50` |
| `ARAGORA_QUEUE_PENDING_CRITICAL` | Optional | Pending job critical threshold | `200` |
| `ARAGORA_QUEUE_PROCESSING_WARNING` | Optional | Processing warning threshold | `20` |

### Worker Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_WORKER_ID` | Optional | Worker identifier | Auto-generated |
| `ARAGORA_WORKER_CAPABILITIES` | Optional | Worker capabilities | `deliberation,debate,gauntlet,workflow` |
| `ARAGORA_WORKER_BLOCK_MS` | Optional | Worker block timeout (ms) | `5000` |
| `ARAGORA_WORKER_IDLE_SLEEP` | Optional | Idle sleep time (seconds) | `0.25` |

### Notification Worker

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_NOTIFICATION_WORKER` | Optional | Enable notification worker | `1` |
| `ARAGORA_NOTIFICATION_CONCURRENCY` | Optional | Max concurrent notifications | `20` |

---

## Blockchain / ERC8004 Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ERC8004_RPC_URL` | Optional | Blockchain RPC URL | - |
| `ERC8004_CHAIN_ID` | Optional | Chain ID | `1` |
| `ERC8004_IDENTITY_REGISTRY` | Optional | Identity registry address | - |
| `ERC8004_REPUTATION_REGISTRY` | Optional | Reputation registry address | - |
| `ERC8004_VALIDATION_REGISTRY` | Optional | Validation registry address | - |
| `ERC8004_FALLBACK_RPC_URLS` | Optional | Comma-separated fallback RPCs | - |
| `ERC8004_BLOCK_CONFIRMATIONS` | Optional | Block confirmations | `12` |
| `ERC8004_GAS_LIMIT` | Optional | Gas limit | `500000` |
| `ERC8004_WALLET_KEY` | Optional | Wallet private key | - |
| `ERC8004_KEYSTORE_PATH` | Optional | Keystore file path | - |
| `ERC8004_KEYSTORE_PASSWORD` | Optional | Keystore password | - |

---

## Payment Connectors

### Stripe

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `STRIPE_SECRET_KEY` | For billing | Stripe API secret | - |
| `STRIPE_WEBHOOK_SECRET` | For billing | Webhook signing secret | - |
| `STRIPE_PRICE_STARTER` | For billing | Starter tier price ID | - |
| `STRIPE_PRICE_PROFESSIONAL` | For billing | Professional tier price ID | - |
| `STRIPE_PRICE_ENTERPRISE` | For billing | Enterprise tier price ID | - |

### PayPal

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `PAYPAL_CLIENT_ID` | Optional | PayPal client ID | - |
| `PAYPAL_CLIENT_SECRET` | Optional | PayPal client secret | - |
| `PAYPAL_ENVIRONMENT` | Optional | Environment: `sandbox`, `production` | `sandbox` |
| `PAYPAL_WEBHOOK_ID` | Optional | Webhook ID | - |
| `PAYPAL_WEBHOOK_SECRET` | Optional | Webhook secret | - |

### Square

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SQUARE_ACCESS_TOKEN` | Optional | Square access token | - |
| `SQUARE_ENVIRONMENT` | Optional | Environment: `sandbox`, `production` | `sandbox` |
| `SQUARE_APPLICATION_ID` | Optional | Application ID | - |
| `SQUARE_LOCATION_ID` | Optional | Location ID | - |
| `SQUARE_WEBHOOK_SIGNATURE_KEY` | Optional | Webhook signature key | - |

### Authorize.Net

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `AUTHORIZE_NET_API_LOGIN_ID` | Optional | API login ID | - |
| `AUTHORIZE_NET_TRANSACTION_KEY` | Optional | Transaction key | - |
| `AUTHORIZE_NET_ENVIRONMENT` | Optional | Environment: `sandbox`, `production` | `sandbox` |
| `AUTHORIZE_NET_SIGNATURE_KEY` | Optional | Signature key | - |

---

## Accounting & Payroll Integrations

### QuickBooks Online

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `QBO_CLIENT_ID` | Optional | QuickBooks OAuth client ID | - |
| `QBO_CLIENT_SECRET` | Optional | QuickBooks OAuth secret | - |
| `QBO_REDIRECT_URI` | Optional | OAuth callback URL | - |
| `QBO_ENVIRONMENT` | Optional | Environment: `sandbox`, `production` | `sandbox` |

### Plaid

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `PLAID_CLIENT_ID` | Optional | Plaid client ID | - |
| `PLAID_SECRET` | Optional | Plaid secret | - |
| `PLAID_ENVIRONMENT` | Optional | Environment: `sandbox`, `development`, `production` | `sandbox` |

### Gusto

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `GUSTO_CLIENT_ID` | Optional | Gusto OAuth client ID | - |
| `GUSTO_CLIENT_SECRET` | Optional | Gusto OAuth secret | - |
| `GUSTO_REDIRECT_URI` | Optional | OAuth callback URL | - |

---

## Legal / DocuSign Integration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `DOCUSIGN_INTEGRATION_KEY` | Optional | DocuSign integration key | - |
| `DOCUSIGN_USER_ID` | Optional | DocuSign user ID | - |
| `DOCUSIGN_ACCOUNT_ID` | Optional | DocuSign account ID | - |
| `DOCUSIGN_PRIVATE_KEY` | Optional | Path to private key | - |
| `DOCUSIGN_ENVIRONMENT` | Optional | Environment: `demo`, `production` | `demo` |

---

## DevOps Integrations

### PagerDuty

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `PAGERDUTY_API_KEY` | Optional | PagerDuty API key | - |
| `PAGERDUTY_EMAIL` | Optional | PagerDuty email | - |
| `PAGERDUTY_WEBHOOK_SECRET` | Optional | Webhook secret | - |

### GitHub

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `GITHUB_WEBHOOK_SECRET` | Optional | GitHub webhook secret | - |

### Jira

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `JIRA_WEBHOOK_SECRET` | Optional | Jira webhook secret | - |

---

## Threat Intelligence

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_THREAT_INTEL_ENRICHMENT_ENABLED` | Optional | Enable enrichment | `true` |
| `ARAGORA_THREAT_INTEL_MAX_INDICATORS` | Optional | Max indicators | `10` |
| `VIRUSTOTAL_API_KEY` | Optional | VirusTotal API key | - |
| `ABUSEIPDB_API_KEY` | Optional | AbuseIPDB API key | - |
| `PHISHTANK_API_KEY` | Optional | PhishTank API key | - |
| `URLHAUS_API_KEY` | Optional | URLhaus API key | - |

---

## Sandbox & Container Pool

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_CONTAINER_POOL_MIN` | Optional | Min pool size | `5` |
| `ARAGORA_CONTAINER_POOL_MAX` | Optional | Max pool size | `50` |
| `ARAGORA_CONTAINER_POOL_WARMUP` | Optional | Warmup container count | `10` |
| `ARAGORA_SANDBOX_IMAGE` | Optional | Base container image | `python:3.11-slim` |

---

## Session & State Management

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SESSION_VOICE_TTL` | Optional | Voice session TTL (seconds) | `86400` |
| `ARAGORA_SESSION_DEVICE_TTL` | Optional | Device session TTL (seconds) | `2592000` |
| `ARAGORA_SESSION_MAX_VOICE` | Optional | Max voice sessions | `1000` |
| `ARAGORA_SESSION_MAX_DEVICES` | Optional | Max device sessions | `10000` |
| `ARAGORA_SESSION_DEBATE_TTL` | Optional | Debate state TTL (seconds) | `3600` |
| `ARAGORA_SESSION_LOOP_TTL` | Optional | Active loop TTL (seconds) | `86400` |
| `ARAGORA_SESSION_AUTH_TTL` | Optional | Auth state TTL (seconds) | `3600` |
| `ARAGORA_SESSION_RATE_LIMIT_TTL` | Optional | Rate limit TTL (seconds) | `300` |
| `ARAGORA_SESSION_MAX_DEBATES` | Optional | Max debate states | `500` |
| `ARAGORA_SESSION_MAX_LOOPS` | Optional | Max active loops | `1000` |
| `ARAGORA_SESSION_MAX_AUTH` | Optional | Max auth states | `10000` |

---

## Cache & Performance

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_CACHE_MAX_ENTRIES` | Optional | Max LRU cache entries | `1000` |
| `ARAGORA_CACHE_EVICT_PERCENT` | Optional | Cache eviction percent | `10` |
| `ARAGORA_SLOW_QUERY_MS` | Optional | Slow query threshold (ms) | `500` |
| `ARAGORA_SLOW_DEBATE_THRESHOLD` | Optional | Slow debate threshold (seconds) | `30` |
| `ARAGORA_N1_DETECTION` | Optional | N+1 detection: `off`, `warn`, `error` | `off` |
| `ARAGORA_N1_THRESHOLD` | Optional | N+1 query threshold | `5` |

---

## Moderation & Spam

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SPAM_CHECK_ENABLED` | Optional | Enable spam checking | `true` |
| `ARAGORA_SPAM_BLOCK_THRESHOLD` | Optional | Block threshold (0.0-1.0) | `0.9` |
| `ARAGORA_SPAM_REVIEW_THRESHOLD` | Optional | Review threshold (0.0-1.0) | `0.7` |
| `ARAGORA_SPAM_CACHE_ENABLED` | Optional | Enable spam cache | `true` |
| `ARAGORA_SPAM_CACHE_TTL` | Optional | Cache TTL (seconds) | `300` |
| `ARAGORA_SPAM_CACHE_SIZE` | Optional | Cache size | `1000` |
| `ARAGORA_SPAM_FAIL_OPEN` | Optional | Fail open on errors | `true` |
| `ARAGORA_SPAM_LOG_ALL` | Optional | Log all checks | `false` |

---

## Dead Letter Queue

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DLQ_ENABLED` | Optional | Enable DLQ | `true` |
| `ARAGORA_DLQ_DB_PATH` | Optional | DLQ database path | `dlq.db` |
| `ARAGORA_DLQ_MAX_RETRIES` | Optional | Max DLQ retries | `5` |
| `ARAGORA_DLQ_RETENTION_HOURS` | Optional | DLQ retention (hours) | `168` (7 days) |

---

## Testing & CI Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `TESTING` | Optional | Testing mode flag | - |
| `PYTEST_CURRENT_TEST` | Optional | Current pytest test (auto-set) | - |
| `ARAGORA_TEST_REAL_AUTH` | Optional | Enable real auth in tests | - |
| `ARAGORA_INTEGRATION_TESTS` | Optional | Enable integration tests | - |
| `ARAGORA_TEST_URL` | Optional | Test server URL | `http://localhost:8080` |
| `ARAGORA_BASELINE_PARALLEL` | Optional | Baseline runner parallelism | `auto` |
| `ARAGORA_BASELINE_TIMEOUT` | Optional | Baseline runner timeout | `60` |

---

## Internal / Advanced

### Data Directories

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DATA_DIR` | Recommended | Data directory | `.nomic` |
| `ARAGORA_NOMIC_DIR` | Optional | Legacy alias | `.nomic` |
| `ARAGORA_STORAGE_DIR` | Optional | Storage artifacts | `.aragora` |
| `ARAGORA_STORE_DIR` | Optional | Store directory | - |
| `ARAGORA_BEAD_DIR` | Optional | Bead store directory | - |

### Instance Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_MULTI_INSTANCE` | Optional | Multi-instance mode | `false` |
| `ARAGORA_SINGLE_INSTANCE` | Optional | Single-instance mode | - |
| `ARAGORA_INSTANCE_ID` | Optional | Instance identifier | - |
| `ARAGORA_INSTANCE_COUNT` | Optional | Total instance count | `1` |
| `HOSTNAME` | Optional | Container hostname | - |
| `POD_NAME` | Optional | Kubernetes pod name | - |
| `ARAGORA_PRIMARY_REGION` | Optional | Primary region | `us-east-1` |
| `ARAGORA_REGION` | Optional | Current region | `us-east-1` |

### Feature Flags

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ALLOW_AUTO_EVOLVE` | Optional | Allow auto evolution | `false` |
| `ARAGORA_ALLOW_PROMPT_EVOLVE` | Optional | Allow prompt modification | `false` |
| `ARAGORA_HYBRID_IMPLEMENT` | Optional | Hybrid implementation mode | `false` |
| `ARAGORA_SKIP_GATES` | Optional | Skip safety gates (dev only) | `false` |
| `ARAGORA_SCOPE_CHECK` | Optional | Enable scope validation | `true` |

### Webhooks

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_WEBHOOKS` | Optional | JSON webhook configs | - |
| `ARAGORA_WEBHOOKS_CONFIG` | Optional | Path to webhook config | - |
| `ARAGORA_WEBHOOK_QUEUE_SIZE` | Optional | Webhook queue size | `1000` |
| `ARAGORA_WEBHOOK_ALLOW_LOCALHOST` | Optional | Allow localhost targets (dev) | `false` |
| `ARAGORA_WEBHOOK_WORKERS` | Optional | Concurrent webhook workers | `10` |
| `ARAGORA_WEBHOOK_MAX_RETRIES` | Optional | Webhook retry attempts | `3` |
| `ARAGORA_WEBHOOK_RETRY_DELAY` | Optional | Initial retry delay (seconds) | `1.0` |
| `ARAGORA_WEBHOOK_MAX_RETRY_DELAY` | Optional | Max retry delay (seconds) | `60.0` |
| `ARAGORA_WEBHOOK_TIMEOUT` | Optional | Webhook timeout (seconds) | `30.0` |
| `ARAGORA_WEBHOOK_SECRET` | Optional | Default webhook secret | - |
| `ARAGORA_NOTIFICATION_WEBHOOK` | Optional | Notification webhook URL | - |
| `ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS` | Optional | Allow unverified webhooks (dev) | `false` |

### Circuit Breaker

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_CB_FAILURE_THRESHOLD` | Optional | Failure threshold | Default |
| `ARAGORA_CB_TIMEOUT_SECONDS` | Optional | Timeout (seconds) | Default |
| `ARAGORA_CB_SUCCESS_THRESHOLD` | Optional | Success threshold | Default |
| `ARAGORA_CB_HALF_OPEN_MAX_CALLS` | Optional | Half-open max calls | Default |

### Audit & Compliance

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_AUDIT_ENABLED` | Optional | Enable audit logging | `true` |
| `ARAGORA_AUDIT_RETENTION_DAYS` | Optional | Audit log retention (days) | `90`-`365` |
| `ARAGORA_TENANT_ISOLATION` | Optional | Tenant isolation mode | `strict` |

### External Agents

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `OPENHANDS_URL` | Optional | OpenHands agent URL | `http://localhost:3000` |
| `AUTOGPT_URL` | Optional | AutoGPT agent URL | `http://localhost:8000` |

### Secrets Management

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SECRETS_DIR` | Optional | Absolute directory containing protected managed-secret files | - |
| `ARAGORA_SECRET_NAME` | Optional | AWS Secrets Manager name | `aragora/production` |
| `ARAGORA_USE_SECRETS_MANAGER` | Optional | Use AWS Secrets Manager | `false`; auto-enabled only in detected AWS-managed runtimes |
| `ARAGORA_SECRETS_STRICT` | Optional | Require critical secrets from managed custody instead of env fallback | `false` locally, auto in prod/staging |
| `AWS_REGION` | Optional | AWS region | - |
| `AWS_DEFAULT_REGION` | Optional | Default AWS region | - |
| `AWS_SECRET_NAME` | Optional | AWS secret name | - |
| `VAULT_TOKEN` | Optional | HashiCorp Vault token | - |

### RabbitMQ

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `RABBITMQ_URL` | Required for RabbitMQ | RabbitMQ connection URL | - |

### Moltbot Gateway

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `MOLTBOT_CANONICAL_GATEWAY` | Optional | Use canonical gateway | `1` |
| `MOLTBOT_GATEWAY_REGISTRY` | Optional | Enable gateway registry | `0` |

### Deprecated Endpoints

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_BLOCK_SUNSET_ENDPOINTS` | Optional | Block deprecated endpoints | `true` |
| `ARAGORA_LOG_DEPRECATED_USAGE` | Optional | Log deprecated usage | `true` |

### Token Rotation

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_TOKEN_ROTATION_POLICY` | Optional | Rotation policy | `standard` |

### Skills System

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SKILLS_ENABLED` | Optional | Enable skills system | `true` |
| `ARAGORA_SKILLS_RATE_LIMIT` | Optional | Skills rate limit (req/min) | `30` |
| `ARAGORA_SKILLS_TIMEOUT` | Optional | Default skill timeout (seconds) | `30` |
| `ARAGORA_SKILLS_MAX_TIMEOUT` | Optional | Max skill timeout (seconds) | `60` |
| `ARAGORA_MARKETPLACE_DB` | Optional | Skills marketplace DB path | `:memory:` |

### Google Search

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `GOOGLE_SEARCH_API_KEY` | Optional | Google Custom Search API key | - |
| `GOOGLE_SEARCH_CX` | Optional | Google search engine ID | - |

### Web Research

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `TAVILY_API_KEY` | Optional | Tavily search API key | - |
| `BRAVE_API_KEY` | Optional | Brave Search API key | - |
| `SERPER_API_KEY` | Optional | Serper API key | - |
| `NEWSAPI_KEY` | Optional | NewsAPI key | - |

### Social Media APIs

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `TWITTER_BEARER_TOKEN` | Optional | Twitter/X API bearer token | - |

### OAuth Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `GOOGLE_OAUTH_CLIENT_ID` | Prod | Google OAuth client ID | - |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Prod | Google OAuth client secret | - |
| `GOOGLE_OAUTH_REDIRECT_URI` | Prod | OAuth callback URL | - |
| `OAUTH_SUCCESS_URL` | Prod | Post-login redirect | - |
| `OAUTH_ERROR_URL` | Prod | Auth error page | - |
| `OAUTH_ALLOWED_REDIRECT_HOSTS` | Prod | Allowed redirect hosts | - |
| `OAUTH_STATE_TTL_SECONDS` | Optional | OAuth state TTL (seconds) | `600` |
| `OAUTH_MAX_STATES` | Optional | Max in-memory states | `10000` |
| `APPLE_PRIVATE_KEY` | Optional | Apple OAuth private key | - |

### Frontend URLs

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `NEXT_PUBLIC_API_URL` | Recommended | Frontend API URL | - |
| `NEXT_PUBLIC_WS_URL` | Recommended | Frontend WebSocket URL | - |

### Receipt Retention

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_RECEIPT_RETENTION_DAYS` | Optional | Receipt retention (days) | `2555` (~7 years) |
| `ARAGORA_RECEIPT_CLEANUP_INTERVAL_HOURS` | Optional | Cleanup interval (hours) | `24` |

### Explainability

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_EXPLAINABILITY_BATCH_TTL_SECONDS` | Optional | Batch job TTL (seconds) | `3600` |
| `ARAGORA_EXPLAINABILITY_DB` | Optional | SQLite path override | - |

### Control Plane

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_CONTROL_PLANE_POLICY_SOURCE` | Optional | Policy source | Auto |
| `ARAGORA_REQUIRE_DISTRIBUTED` | Optional | Require distributed stores | `auto` |
| `ARAGORA_REQUIRE_DISTRIBUTED_STATE` | Optional | Legacy distributed flag | - |
| `ARAGORA_STORAGE_MODE` | Optional | Storage mode override | `auto` |

### Billing

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_PAYMENT_GRACE_DAYS` | Optional | Payment grace period (days) | `10` |

### Workflow

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_WORKFLOW_DB` | Optional | Workflow database path | `workflows.db` |

### Decision Results

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DECISION_RESULTS_DB` | Optional | Decision results DB path | - |

### Training / Fine-tuning

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `TINKER_API_KEY` | Optional | Tinker API key | - |
| `TINKER_BASE_MODEL` | Optional | Tinker base model | `llama-3.3-70b` |

### Convoy/Store Paths

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_CANONICAL_STORE_PERSIST` | Optional | Persist canonical store | - |
| `ARAGORA_CONVOY_CANONICAL_STORE` | Optional | Convoy store path | - |

### SCIM Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SCIM_BEARER_TOKEN` | For SCIM | SCIM authentication token | - |
| `SCIM_TENANT_ID` | Optional | Multi-tenant SCIM tenant ID | - |
| `SCIM_BASE_URL` | Optional | SCIM base URL for headers | - |

---

## Notes

1. **Environment Priority**: Variables with `ARAGORA_` prefix generally take priority over their non-prefixed aliases.

2. **Production Requirements**: Variables marked "Prod required" must be set when `ARAGORA_ENV=production`.

3. **Sensitive Values**: Never commit API keys, secrets, or passwords to version control.

4. **Default Values**: Many defaults are environment-aware (different in development vs production).

5. **Auto-detection**: Some variables support "auto" which detects the appropriate value based on other configuration.

---

## See Also

- [ENVIRONMENT.md](../getting-started/environment) - Detailed documentation for commonly-used variables
- [BOT_INTEGRATIONS.md](../guides/bot-integrations) - Chat platform setup guides
- [SSO_SETUP.md](../enterprise/sso) - SSO configuration guides
- [BILLING.md](../enterprise/billing) - Billing system documentation
- [WATCHDOG](../operations/watchdog) - Control plane watchdog documentation
