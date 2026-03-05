# SME Quick Start Guide

> **Canonical entry point:** New to Aragora? Start at **[docs/START_HERE.md](../START_HERE.md)** for a decision tree that picks the right package for you.

This guide helps Subject Matter Experts (SMEs) get started with Aragora for AI-powered decision making.

## Overview

Aragora provides a multi-agent debate platform that helps SMEs make defensible decisions. Multiple AI agents (Claude, GPT, Gemini, etc.) analyze your question from different perspectives and reach consensus.

## Getting Started

### 1. First-Time Setup

When you first log in, you'll go through a brief onboarding:

1. **Welcome**: Overview of the platform
2. **Profile Setup**: Configure your preferences
3. **First Debate**: Run a sample debate to see how it works

### 2. Running Your First Debate

#### Quick Debate (2-3 minutes)

Use the Quick Debate feature for fast decisions:

```bash
# Via API
curl -X POST https://api.aragora.ai/api/v1/debates/quick \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Should we migrate our database to PostgreSQL?",
    "context": "Currently using MySQL, 500GB data, 3 developers",
    "template": "quick_decision"
  }'
```

#### Template Options

| Template | Rounds | Best For |
|----------|--------|----------|
| `quick_decision` | 2 | Simple yes/no decisions |
| `thorough_analysis` | 4 | Complex strategic decisions |
| `risk_assessment` | 3 | Risk-sensitive choices |
| `cost_benefit` | 3 | Financial decisions |

### 3. Understanding Results

Each debate produces:

- **Consensus**: The agreed-upon recommendation
- **Confidence Score**: How certain the agents are (0-1)
- **Dissents**: Any minority opinions
- **Receipt**: Cryptographic proof of the decision

Example response:

```json
{
  "id": "debate-abc123",
  "consensus_reached": true,
  "confidence": 0.85,
  "final_position": "Recommend proceeding with PostgreSQL migration",
  "key_factors": [
    "Better JSON support for your use case",
    "Stronger community and tooling",
    "Migration effort is manageable with 3 developers"
  ],
  "dissenting_views": [
    "Consider waiting until Q2 when team capacity increases"
  ]
}
```

## Usage Dashboard

Monitor your usage at `/api/v1/dashboard/debates`:

### Metrics Available

- **Total Debates**: Number of debates run
- **Consensus Rate**: How often consensus is reached
- **Average Confidence**: Overall decision quality
- **Recent Activity**: Debates in the last 24 hours

### Dashboard Permissions

The dashboard requires authentication with `dashboard.read` permission. Your organization admin can grant this permission.

## Template Selection Guide

### When to Use Each Template

#### Quick Decision (`quick_decision`)
- Simple binary choices
- Time-sensitive decisions
- Low-risk scenarios
- Example: "Should we enable dark mode?"

#### Thorough Analysis (`thorough_analysis`)
- Complex strategic decisions
- High-stakes choices
- Multiple stakeholders
- Example: "Should we expand to the European market?"

#### Risk Assessment (`risk_assessment`)
- Security decisions
- Compliance choices
- Operational changes
- Example: "Should we adopt a zero-trust security model?"

#### Cost-Benefit Analysis (`cost_benefit`)
- Budget decisions
- Investment choices
- Resource allocation
- Example: "Should we build vs. buy this feature?"

### SME-Specific Templates

These templates are specifically designed for common SME business decisions:

| Template | Category | Agents | Rounds | Time |
|----------|----------|--------|--------|------|
| `sme_hiring_decision` | Team | 2 | 3 | 5 min |
| `sme_performance_review` | Team | 2 | 2 | 3 min |
| `sme_feature_prioritization` | Project | 3 | 3 | 5 min |
| `sme_sprint_planning` | Project | 2 | 2 | 3 min |
| `sme_tool_selection` | Vendor | 3 | 4 | 7 min |
| `sme_contract_review` | Vendor | 2 | 3 | 5 min |
| `sme_remote_work_policy` | Policy | 3 | 3 | 5 min |
| `sme_budget_allocation` | Policy | 3 | 2 | 3 min |

#### Hiring Decision (`sme_hiring_decision`)

Evaluate candidates with structured multi-agent debate:

```bash
curl -X POST /api/v1/debates \
  -d '{
    "template": "sme_hiring_decision",
    "topic": "Should we hire Jane Doe for Senior Developer?",
    "context": {
      "position": "Senior Developer",
      "candidate": "Jane Doe",
      "interview_notes": "Strong Python skills, 5 years experience, good culture fit"
    }
  }'
```

#### Feature Prioritization (`sme_feature_prioritization`)

Prioritize features based on impact, effort, and strategic alignment:

```bash
curl -X POST /api/v1/debates \
  -d '{
    "template": "sme_feature_prioritization",
    "topic": "Prioritize Q1 features",
    "context": {
      "features": ["Dark mode", "API v2", "Mobile app", "Export to PDF"],
      "constraints": ["2 developers", "Must ship by March"],
      "timeline": "Q1 2025"
    }
  }'
```

#### Tool Selection (`sme_tool_selection`)

Compare tools with comprehensive multi-agent analysis:

```bash
curl -X POST /api/v1/debates \
  -d '{
    "template": "sme_tool_selection",
    "topic": "Select project management tool",
    "context": {
      "category": "Project Management",
      "candidates": ["Jira", "Linear", "Asana"],
      "requirements": ["GitHub integration", "Agile support"],
      "budget": "$50/user/month"
    }
  }'
```

## Best Practices

### Writing Good Topics

**Good Topics:**
- "Should we migrate from AWS to GCP given our cost constraints?"
- "What's the best approach to handle customer data retention?"
- "Should we adopt GraphQL for our public API?"

**Poor Topics:**
- "What should we do?" (too vague)
- "Is AWS good?" (not specific enough)
- "Tell me everything about databases" (not a decision)

### Providing Context

Include relevant context:

```json
{
  "topic": "Should we implement rate limiting?",
  "context": {
    "current_traffic": "10,000 requests/minute",
    "incident_history": "3 DDoS attempts in last month",
    "team_size": "2 backend engineers",
    "timeline": "Need decision by Friday"
  }
}
```

## API Reference

### Create Quick Debate

```
POST /api/v1/debates/quick
```

**Request:**
```json
{
  "topic": "string (required)",
  "context": "string or object (optional)",
  "template": "quick_decision | thorough_analysis | risk_assessment | cost_benefit"
}
```

**Response:**
```json
{
  "debate_id": "string",
  "status": "pending | running | completed | failed",
  "estimated_duration_seconds": 120
}
```

### Get Debate Status

```
GET /api/v1/debates/{debate_id}
```

### Get Receipt

```
GET /api/v1/debates/{debate_id}/receipt
```

### Export Receipt

```
GET /api/v1/debates/{debate_id}/receipt/export?format=json|html|markdown|sarif
```

## Troubleshooting

### Common Issues

**"Authentication required"**
- Ensure your API token is valid
- Check token expiration
- Verify token permissions

**"Permission denied: dashboard.read"**
- Contact your org admin to grant dashboard access
- Required for viewing usage statistics

**"Debate timeout"**
- Complex topics may take longer
- Try simplifying the question
- Use `thorough_analysis` template for complex decisions

### Getting Help

- Documentation: [docs/START_HERE.md](../START_HERE.md)
- API Reference: [docs/api/API_REFERENCE.md](../api/API_REFERENCE.md)
- Issues: [github.com/an0mium/aragora/issues](https://github.com/an0mium/aragora/issues)

## Next Steps

1. Run your first debate using the Quick Debate feature
2. Review the results and receipt
3. Explore different templates for various decision types
4. Check the usage dashboard to monitor your activity
5. Integrate with your workflow using the API

---

*Last updated: March 2026*
