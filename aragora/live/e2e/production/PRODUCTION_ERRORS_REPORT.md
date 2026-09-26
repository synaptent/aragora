# Production E2E Test Error Report

**Generated:** January 15, 2026
**Last Updated:** January 15, 2026
**Test Suite:** Playwright Production E2E Tests
**Domains Tested:** aragora.ai, live.aragora.ai, api.aragora.ai, status.aragora.ai

---

## Executive Summary

Production E2E tests identified several issues. Most have been fixed in code - some require infrastructure deployment.

| Severity | Original | Fixed | Remaining |
| -------- | -------- | ----- | --------- |
| Critical | 2        | 2     | 0         |
| High     | 12+      | 12+   | 0 (code)  |
| Medium   | 3        | 3     | 0         |
| Low      | 1        | 0     | 1 (DNS)   |

### Fixes Applied (Code Changes)

- React hydration error on /pricing page (added mounted state check)
- Privacy page created (`/privacy` route)
- API endpoint 404s fixed (components now use `API_BASE_URL`)
- CORS headers enhanced in `unified_server.py` and `stream/servers.py`
- Accessibility issues fixed (aria-labels added to form elements)

### Requires Infrastructure Deployment

- CORS fixes need server redeployment
- WebSocket 502 requires nginx/proxy configuration
- www.aragora.ai DNS record needs to be added

---

## Critical Issues

### 1. React Hydration Errors on `/pricing` Page

**Domain:** aragora.ai
**Page:** `/pricing`
**Error Codes:** React #418, React #423

```
Error: Minified React error #418
Error: Minified React error #423
```

**Description:**

- Error #418: "There was an error while hydrating. Because the error happened outside of a Suspense boundary, the entire root will switch to client rendering."
- Error #423: "There was an error while hydrating but React was able to recover by instead client rendering from the closest Suspense boundary."

**Root Cause:** Server-rendered HTML doesn't match what React expects to render on the client. Common causes:

- Date/time rendering differences
- Browser-specific code running during SSR
- Non-deterministic content

**Fix Priority:** HIGH
**Recommendation:** Investigate the pricing page component for SSR/client mismatches. Check for:

- `Date` or time-based content without `suppressHydrationWarning`
- Browser-only APIs used during render
- Random or non-deterministic values

---

## High Priority Issues

### 2. CORS Configuration - api.aragora.ai

**Domain:** api.aragora.ai
**Affected Endpoints:** All API endpoints

```
Access to fetch at 'https://api.aragora.ai/api/...' from origin 'https://live.aragora.ai'
has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present.
```

**Affected API Routes:**

- `/api/nomic/state`
- `/api/history/cycles`
- `/api/history/summary`
- `/api/history/debates`
- `/api/history/events`
- `/api/features`
- `/api/flips/summary`
- `/api/consensus/contrarian-views`
- `/api/consensus/stats`
- `/api/learning/patterns`
- `/api/debates`

**Root Cause:** API server is not returning proper CORS headers for cross-origin requests from live.aragora.ai.

**Fix Priority:** HIGH
**Recommendation:** Update the API server CORS configuration to allow requests from:

- `https://live.aragora.ai`
- `https://aragora.ai`

### 3. WebSocket Connection Failure

**Domain:** api.aragora.ai
**Endpoint:** `wss://api.aragora.ai/ws`

```
WebSocket connection to 'wss://api.aragora.ai/ws' failed:
Error during WebSocket handshake: Unexpected response code: 502
```

**Root Cause:** WebSocket endpoint is returning 502 Bad Gateway.

**Fix Priority:** HIGH
**Recommendation:** Check:

- WebSocket server is running
- Nginx/reverse proxy configuration for WebSocket upgrade
- Load balancer timeout settings

### 4. CORS Configuration - api-dev.aragora.ai

**Domain:** api-dev.aragora.ai

```
Access to fetch at 'https://api-dev.aragora.ai/api/health' from origin 'https://live.aragora.ai'
has been blocked by CORS policy
```

**Root Cause:** Development API also lacks CORS headers.

**Fix Priority:** MEDIUM (dev environment)
**Recommendation:** Same CORS fix as production API.

---

## Medium Priority Issues

### 5. Missing `/privacy` Page (404)

**Domain:** aragora.ai
**URL:** `https://aragora.ai/privacy`

```
HTTP 404: https://aragora.ai/privacy
```

**Root Cause:** Privacy page route doesn't exist.

**Fix Priority:** MEDIUM (Compliance)
**Recommendation:** Create `/privacy` route or redirect to privacy policy document.

### 6. Missing API Endpoints (404)

**Domain:** live.aragora.ai (Next.js API routes)

| Endpoint                  | Status |
| ------------------------- | ------ |
| `/api/replays`            | 404    |
| `/api/learning/evolution` | 404    |

**Root Cause:** These API routes are referenced by the frontend but don't exist.

**Fix Priority:** MEDIUM
**Recommendation:** Either implement these endpoints or remove references from frontend.

---

## Low Priority Issues

### 7. DNS - www.aragora.ai Not Resolving

**Domain:** www.aragora.ai

```
net::ERR_NAME_NOT_RESOLVED
```

**Root Cause:** No DNS record exists for `www.aragora.ai`.

**Fix Priority:** LOW (but affects SEO)
**Recommendation:** Add CNAME record: `www.aragora.ai` -> `aragora.ai`

---

## Accessibility Issues (WCAG 2.1 AA)

### live.aragora.ai Dashboard

| Issue                    | Severity | Count |
| ------------------------ | -------- | ----- |
| `aria-required-children` | Critical | 1     |
| `aria-valid-attr-value`  | Critical | 1     |
| `color-contrast`         | Serious  | 1     |
| `label`                  | Critical | 6     |
| `select-name`            | Critical | 6     |

**Details:**

- 6 form elements without labels
- 6 select elements without accessible names
- 1 color contrast issue
- ARIA role/attribute issues

**Fix Priority:** MEDIUM (Accessibility compliance)
**Recommendation:** Add proper labels to form elements and fix ARIA attributes.

---

## Infrastructure Issues Summary

| Issue                 | Domain             | Status                      | Priority |
| --------------------- | ------------------ | --------------------------- | -------- |
| CORS not configured   | api.aragora.ai     | FIXED (code) - needs deploy | HIGH     |
| WebSocket 502         | api.aragora.ai     | Open (nginx config)         | HIGH     |
| React hydration       | aragora.ai/pricing | FIXED                       | HIGH     |
| Missing /privacy page | aragora.ai         | FIXED                       | MEDIUM   |
| Missing API routes    | live.aragora.ai    | FIXED                       | MEDIUM   |
| www DNS missing       | www.aragora.ai     | Open (DNS)                  | LOW      |
| A11y violations       | live.aragora.ai    | FIXED                       | MEDIUM   |

---

## Infrastructure Actions Required

### 1. DNS Configuration for www.aragora.ai

**Priority:** LOW (SEO best practice)
**Owner:** Infrastructure/DevOps team

Add the following DNS record in your DNS provider (Cloudflare or similar):

| Type  | Name | Target     |
| ----- | ---- | ---------- |
| CNAME | www  | aragora.ai |

Or alternatively (A record if CNAME doesn't work):

| Type | Name | Target                  |
| ---- | ---- | ----------------------- |
| A    | www  | (same IP as aragora.ai) |

**Why:** Without this record, visitors who type `www.aragora.ai` get a DNS resolution error. This hurts SEO and user experience.

### 2. WebSocket Proxy Configuration

**Priority:** HIGH
**Owner:** Infrastructure/DevOps team

The WebSocket endpoint at `wss://api.aragora.ai/ws` returns 502 Bad Gateway. Check:

1. **Nginx configuration** needs WebSocket upgrade headers:

```nginx
location /ws {
    proxy_pass http://backend:8765;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400;
}
```

2. **Load balancer** (if using AWS ALB/ELB):
   - Enable WebSocket sticky sessions
   - Increase idle timeout to 3600 seconds

3. **Verify WebSocket server** is running on port 8765

### 3. Deploy CORS Fixes

**Priority:** HIGH
**Owner:** Backend deployment

The following files have been updated with enhanced CORS headers:

- `aragora/server/unified_server.py`
- `aragora/server/stream/servers.py`

Changes include:

- Dynamic origin validation against allowed origins
- Credentials support (`Access-Control-Allow-Credentials: true`)
- Extended methods (`DELETE, PUT, PATCH`)
- Cache max-age (3600 seconds)

Deploy these changes to apply the CORS fixes

---

## Recommended Fix Order

1. **CORS Configuration** - Blocking all API calls from dashboard
2. **WebSocket Fix** - Required for real-time features
3. **React Hydration** - User-facing error on pricing page
4. **Privacy Page** - Compliance requirement
5. **API Endpoints** - Clean up 404s
6. **Accessibility** - WCAG compliance
7. **www DNS** - SEO best practice

---

## Test Configuration Notes

- Custom HTTP headers removed (caused CORS issues with external resources)
- External CORS errors filtered (Cloudflare, Google Fonts)
- Rate limiting: 500ms between actions
- Single worker to avoid overwhelming production
- Screenshots captured on failure

---

## How to Run Tests

```bash
cd aragora/live

# Run all production tests
npx playwright test --config=playwright.production.config.ts

# Run specific test suite
npx playwright test e2e/production/smoke.prod.spec.ts --config=playwright.production.config.ts

# Run with UI mode
npx playwright test --config=playwright.production.config.ts --ui

# View HTML report
npx playwright show-report playwright-report-production
```

---

## Files Created

| File                                        | Purpose                             |
| ------------------------------------------- | ----------------------------------- |
| `playwright.production.config.ts`           | Production test configuration       |
| `e2e/production/fixtures.ts`                | Test fixtures with error collection |
| `e2e/production/smoke.prod.spec.ts`         | Smoke tests for all domains         |
| `e2e/production/landing.prod.spec.ts`       | Landing page tests                  |
| `e2e/production/dashboard.prod.spec.ts`     | Dashboard tests                     |
| `e2e/production/api-health.prod.spec.ts`    | API health tests                    |
| `e2e/production/accessibility.prod.spec.ts` | WCAG accessibility tests            |
| `e2e/production/links.prod.spec.ts`         | Broken link checker                 |
