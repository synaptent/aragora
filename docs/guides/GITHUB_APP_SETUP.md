# GitHub App Setup Guide

This guide explains how to configure the Aragora GitHub App integration for automated PR reviews, issue triage, and code analysis debates.

## Overview

The Aragora GitHub App enables:
- **Auto-triggered PR reviews**: Multi-agent code review debates on new pull requests
- **Issue triage**: Automated issue categorization and prioritization
- **Push event tracking**: Code change context for improved debate quality

## Prerequisites

- A deployed Aragora instance with a public HTTPS endpoint
- GitHub account with organization admin access (for org-wide installation)
- `GITHUB_WEBHOOK_SECRET` environment variable configured

## Installation Options

### Option 1: Create Using Manifest (Recommended)

1. Navigate to GitHub Settings > Developer settings > GitHub Apps
2. Click "New GitHub App" > "Import from manifest"
3. Paste the contents of `github-app-manifest.json` from the Aragora repository
4. Update placeholder URLs:
   - Replace `your-domain.com` with your Aragora deployment domain
   - Ensure the webhook URL points to `/api/v1/webhooks/github`

### Option 2: Manual Configuration

Create a new GitHub App with these settings:

**General Settings:**
- Name: `Aragora` (or your preferred name)
- Homepage URL: Your Aragora deployment URL
- Webhook URL: `https://your-domain.com/api/v1/webhooks/github`
- Webhook Secret: Generate a secure random string

**Permissions:**

| Permission | Access Level | Purpose |
|------------|-------------|---------|
| Contents | Read | Access code for review debates |
| Issues | Read & Write | Triage and comment on issues |
| Pull requests | Read & Write | Review PRs, post review comments |
| Metadata | Read | Access repository metadata |
| Checks | Read & Write | Create check runs for debate status |
| Statuses | Read & Write | Post commit status updates |

**Events to Subscribe:**
- `pull_request` - Trigger on PR open/sync
- `pull_request_review` - Track review submissions
- `issues` - Trigger issue triage
- `issue_comment` - Process @mentions
- `push` - Track code changes

## Environment Configuration

Add these variables to your Aragora deployment:

```bash
# Required
GITHUB_WEBHOOK_SECRET=your-webhook-secret-here

# Optional (for API access)
GITHUB_APP_ID=12345
GITHUB_APP_PRIVATE_KEY="paste-complete-PEM-contents-here"

# Optional (use personal token instead of App)
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
```

Set `GITHUB_APP_PRIVATE_KEY` to the complete contents of the private key downloaded
from GitHub. Keep the value quoted when storing it in a dotenv file, and never
commit the real key.

## Webhook Flow

```
GitHub Event                    Aragora Processing
─────────────────────────────────────────────────────
PR Opened/Synchronized    →    /api/v1/webhooks/github
                               │
                               ├─► Verify HMAC signature
                               ├─► Parse event payload
                               ├─► Fetch PR diff/context
                               ├─► Trigger code review debate
                               └─► Post results as PR comment
```

## Event Handlers

### Pull Request Events

When a PR is opened or updated:

1. **Code Review Debate**: Agents analyze the diff for:
   - Code quality issues
   - Security vulnerabilities
   - Performance concerns
   - Test coverage gaps

2. **Check Run**: Creates a GitHub Check with debate status:
   - `queued` → Debate started
   - `in_progress` → Agents deliberating
   - `completed` → Consensus reached

3. **PR Comment**: Posts a summary of the debate outcome

### Issue Events

When an issue is opened:

1. **Triage Debate**: Agents categorize the issue:
   - Bug vs feature vs question
   - Priority level
   - Component/area assignment

2. **Label Application**: Automatically applies suggested labels

3. **Comment**: Posts triage summary if significant findings

### Push Events

Push events are tracked for context but don't trigger debates directly. They provide:
- Commit history for PR reviews
- Code evolution context
- Author attribution

## API Endpoints

### Webhook Receiver
```
POST /api/v1/webhooks/github
Headers:
  - X-GitHub-Event: <event-type>
  - X-GitHub-Delivery: <delivery-id>
  - X-Hub-Signature-256: sha256=<signature>
Body: JSON payload
```

### Status Check
```
GET /api/v1/webhooks/github/status
Response:
{
  "github_app": {
    "configured": true,
    "webhook_secret_set": true,
    "webhook_endpoint": "/api/v1/webhooks/github"
  }
}
```

## Troubleshooting

### Webhook Not Receiving Events

1. **Check webhook URL**: Ensure it's publicly accessible
2. **Verify SSL certificate**: GitHub requires valid HTTPS
3. **Check firewall**: Allow GitHub IP ranges
4. **Review recent deliveries**: GitHub > App Settings > Advanced > Recent Deliveries

### Signature Verification Failures

1. **Check secret match**: `GITHUB_WEBHOOK_SECRET` must match App settings
2. **No leading/trailing whitespace**: Secrets are space-sensitive
3. **Check for double-encoding**: Secret should be raw string

### Debates Not Triggering

1. **Check event subscription**: Ensure `pull_request` is enabled
2. **Verify installation**: App must be installed on the repository
3. **Check logs**: Look for webhook processing errors

## Security Considerations

1. **Webhook Secret**: Use a cryptographically secure random string (32+ chars)
2. **IP Allowlisting**: Optionally restrict to [GitHub webhook IPs](https://api.github.com/meta)
3. **Audit Logging**: All webhook events are logged for audit
4. **Rate Limiting**: Built-in protection against webhook floods

## Example: Local Development

For local development with ngrok:

```bash
# Start ngrok tunnel
ngrok http 8080

# Update GitHub App webhook URL to ngrok URL
# https://abc123.ngrok.io/api/v1/webhooks/github

# Set environment variable
export GITHUB_WEBHOOK_SECRET=your-dev-secret

# Start Aragora server
aragora serve --api-port 8080 --ws-port 8765
```

## Related Documentation

- [Debate Orchestration](../debate/ORCHESTRATION.md)
- [Connectors Overview](../integrations/CONNECTORS.md)
- [Webhooks Reference](../api/WEBHOOKS.md)
