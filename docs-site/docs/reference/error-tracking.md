---
title: Error Tracking Setup
description: Error Tracking Setup
---

# Error Tracking Setup

This guide covers setting up error tracking for Aragora using Sentry.

## Overview

Aragora uses Sentry for:
- Real-time error tracking
- Performance monitoring
- Release tracking
- User feedback collection

## Backend Setup

### Installation

```bash
pip install sentry-sdk[aiohttp]
```

### Configuration

Add to your environment:

```bash
export SENTRY_DSN=https://xxx@sentry.io/xxx
export SENTRY_ENVIRONMENT=production  # or staging, development
export SENTRY_TRACES_SAMPLE_RATE=0.1
export SENTRY_PROFILES_SAMPLE_RATE=0.1
export SENTRY_SERVER_NAME=aragora-api
```

### Integration

The error tracking is already integrated in `aragora/server/error_monitoring.py`:

```python
from aragora.server.error_monitoring import init_monitoring

def init_sentry():
    """Initialize Sentry error tracking."""
    init_monitoring()
```

## Frontend Setup

### Installation

```bash
npm install @sentry/nextjs
```

### Configuration

Create `sentry.client.config.js`:

```javascript
import * as Sentry from '@sentry/nextjs';

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NODE_ENV,
  tracesSampleRate: 0.1,
  replaysSessionSampleRate: 0.1,
  replaysOnErrorSampleRate: 1.0,
});
```

Create `sentry.server.config.js`:

```javascript
import * as Sentry from '@sentry/nextjs';

Sentry.init({
  dsn: process.env.SENTRY_DSN,
  tracesSampleRate: 0.1,
});
```

Update `next.config.js`:

```javascript
const { withSentryConfig } = require('@sentry/nextjs');

module.exports = withSentryConfig(
  nextConfig,
  {
    silent: true,
    org: 'your-org',
    project: 'aragora-frontend',
  },
);
```

## Sensitive Data Filtering

The backend filters sensitive data before sending to Sentry (see `_before_send` in `aragora/server/error_monitoring.py`):

```python
def filter_sensitive_data(event, hint):
    """Filter sensitive data from Sentry events."""
    # Remove API keys from headers
    if 'request' in event:
        headers = event['request'].get('headers', {})
        for key in ['Authorization', 'X-API-Key', 'Cookie']:
            if key in headers:
                headers[key] = '[REDACTED]'

    # Remove sensitive environment variables
    if 'contexts' in event:
        env = event['contexts'].get('runtime', {}).get('environ', {})
        for key in list(env.keys()):
            if any(s in key.lower() for s in ['key', 'secret', 'password', 'token']):
                env[key] = '[REDACTED]'

    return event
```

## Custom Error Contexts

Add context to errors for better debugging:

```python
# Backend
with sentry_sdk.push_scope() as scope:
    scope.set_tag("debate_id", debate_id)
    scope.set_context("debate", {
        "task": task,
        "round": current_round,
        "agents": [a.name for a in agents],
    })
    sentry_sdk.capture_exception(error)
```

```javascript
// Frontend
Sentry.setContext('debate', {
  debateId: debate.id,
  status: debate.status,
});
Sentry.captureException(error);
```

## Alerting Rules

Configure these alerts in Sentry:

| Alert | Condition | Action |
|-------|-----------|--------|
| High Error Rate | >10 errors/min | Slack + Email |
| New Issue | First occurrence | Slack |
| API Timeout | p99 latency >5s | Slack |
| Critical Error | severity=critical | PagerDuty |

## Release Tracking

Tag releases for better error correlation:

```bash
# Create release
sentry-cli releases new $VERSION

# Associate commits
sentry-cli releases set-commits $VERSION --auto

# Finalize
sentry-cli releases finalize $VERSION

# Deploy
sentry-cli releases deploys $VERSION new -e production
```

## Performance Monitoring

Key transactions to monitor:

| Transaction | Target p95 | Alert Threshold |
|-------------|------------|-----------------|
| `/api/debates` POST | 2s | 5s |
| `/api/debates/\{id\}` GET | 100ms | 500ms |
| `/api/agents` GET | 50ms | 200ms |
| WebSocket connect | 100ms | 500ms |

## Dashboard Setup

Create a Sentry dashboard with:

1. **Error Overview**
   - Error count by issue
   - Error trends over time
   - Top affected endpoints

2. **Performance**
   - Transaction duration (p50, p95, p99)
   - Throughput by endpoint
   - Apdex score

3. **User Impact**
   - Unique users affected
   - Sessions with errors
   - User feedback

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SENTRY_DSN` | Sentry project DSN |
| `SENTRY_ENVIRONMENT` | Environment name |
| `SENTRY_RELEASE` | Release version/commit |
| `SENTRY_ORG` | Sentry organization |
| `SENTRY_PROJECT` | Sentry project name |
| `SENTRY_AUTH_TOKEN` | CI/CD auth token |

## Troubleshooting

### Events not appearing

1. Check DSN is correct
2. Verify network connectivity to Sentry
3. Check sample rates aren't too low
4. Review before_send filter

### High event volume

1. Increase sample rates filtering
2. Add fingerprinting for similar errors
3. Use rate limiting
4. Filter noisy errors in before_send

### Source maps not working

1. Upload source maps during build
2. Verify release names match
3. Check source map URLs
