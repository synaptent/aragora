# Developer Quickstart: AI Code Review in 5 Minutes

Get multi-agent AI code review on your pull requests. Multiple AI models independently review your code, debate their findings, and produce a consensus report -- so you see where models agree (high confidence) and where they disagree (needs your judgment).

> **Want to try without API keys?** Run the full platform locally with Docker:
> ```bash
> docker compose -f deploy/demo/docker-compose.yml up --build
> ```
> Backend at `localhost:8080`, frontend at `localhost:3000`. See [Docker Quickstart](guides/QUICKSTART_DOCKER.md) for details.

---

## Prerequisites

- A GitHub repository
- At least one API key: [Anthropic](https://console.anthropic.com/) or [OpenAI](https://platform.openai.com/)
- For best results, add both -- multi-model consensus is the point

---

## Step 1: Add the GitHub Action (2 minutes)

### 1a. Add API keys as GitHub Secrets

Go to your repo: **Settings > Secrets and variables > Actions > New repository secret**

Add at least one:

| Secret Name | Provider |
|-------------|----------|
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/) |
| `OPENAI_API_KEY` | [OpenAI Platform](https://platform.openai.com/) |

### 1b. Create the workflow file

Create `.github/workflows/aragora-review.yml` in your repository:

```yaml
name: Aragora AI Review
on:
  pull_request:
    types: [opened, synchronize]

permissions:
  pull-requests: write
  contents: read

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: an0mium/aragora@main
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
```

Commit and push. Every new PR will now get an AI code review.

---

## Step 2: Run Your First Review (CLI)

You can also run reviews locally before pushing.

### Install

```bash
pip install aragora
```

### Review a diff

```bash
git diff main | aragora review
```

### Review a GitHub PR directly

```bash
aragora review https://github.com/owner/repo/pull/123
```

### Try without API keys

```bash
aragora review --demo
```

The `--demo` flag runs a full review cycle with sample output so you can see the format before configuring API keys.

---

## Step 3: Read the PR Comment

When the action runs, it posts a comment on your PR with these sections:

### Unanimous Issues

Findings that all AI models agree on. These have the highest confidence and almost always warrant action.

```
## Unanimous Issues (2)
1. SQL injection vulnerability in user search -- query built with string concatenation
2. Missing input validation on file upload endpoint
```

### Split Opinions

Findings where models disagree. These are presented as tradeoffs for your judgment, not as directives.

```
## Split Opinions (2)
- Add request rate limiting
  Majority: anthropic-api, openai-api | Minority: gemini-api
- Cache database queries
  Majority: anthropic-api | Minority: openai-api, gemini-api
```

### Risk Areas

Lower-confidence findings flagged for manual review.

### Agreement Score

A 0-1 score indicating how much the models agreed overall. Higher scores mean more consensus across the review. A score of 0.75+ generally indicates strong agreement on the key findings.

---

## Step 4: Customize

### Focus areas

Narrow the review to specific concerns:

```bash
aragora review --focus security,performance
```

In the GitHub Action:

```yaml
- uses: an0mium/aragora@main
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
    focus: 'security'
```

### SARIF export

Export findings as SARIF 2.1.0 for IDE integration and the GitHub Security tab:

```bash
aragora review --sarif
```

This creates `review-results.sarif` by default. Specify a custom path:

```bash
aragora review --sarif findings.sarif
```

In the GitHub Action, enable SARIF output:

```yaml
- uses: an0mium/aragora@main
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
    output-format: 'sarif'
    sarif-upload: 'true'
```

### Fail builds on critical issues

Block PRs that have critical security findings:

```yaml
- uses: an0mium/aragora@main
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
    fail-on-critical: 'true'
```

Then in your repo's **Settings > Branches > Branch protection rules**, enable "Require status checks to pass" and add the review job as a required check.

### Gauntlet mode

Run an adversarial stress-test after the standard review. The gauntlet uses attack/defend cycles to probe deeper for vulnerabilities:

```bash
aragora review --gauntlet
```

### Adjust debate depth

More rounds means more thorough review (and higher API cost):

```yaml
- uses: an0mium/aragora@main
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
    rounds: '3'
```

### Filter by file type

Only trigger reviews on relevant file changes:

```yaml
on:
  pull_request:
    paths:
      - '**.py'
      - '**.ts'
      - '**.js'
```

---

## Advanced: Self-Hosted

Run the Aragora server locally or on your own infrastructure for full API access:

```bash
aragora serve --api-port 8080 --ws-port 8765
```

This gives you the REST API (3,000+ operations), WebSocket streaming, and programmatic access to debates, receipts, and analytics.

See [API Reference](./api/API_REFERENCE.md) for endpoint-level details and [Documentation Index](INDEX.md) for architecture navigation.

---

## What Makes This Different

**Multi-model consensus, not a single opinion.** Standard AI code review tools run one model and present its output as truth. Aragora runs multiple models independently, then has them debate. You see where they agree (act on these) and where they disagree (use your judgment).

**Disagreement is a feature.** Split opinions are explicitly surfaced. When Claude flags a security issue but GPT-4 does not, that tells you something different than when both flag it. The disagreement itself is informative.

**Cryptographic decision receipts.** Every review produces a SHA-256 hashed audit trail -- which models participated, what they found, how they voted, and what the consensus was. This is not a log file; it is a verifiable receipt.

**SARIF integration.** Findings export as standard SARIF 2.1.0, which means they show up in the GitHub Security tab alongside your other code scanning tools, and in any IDE that supports SARIF.

---

## Cost Estimate

Approximate cost per review (2 agents, 2 rounds, typical PR):

| Provider | Cost per Review |
|----------|----------------|
| Anthropic Claude | ~$0.05-0.15 |
| OpenAI GPT-4 | ~$0.10-0.30 |
| OpenRouter fallback | ~$0.02-0.10 |

---

## Next Steps

- [API Reference](./api/API_REFERENCE.md) -- REST API documentation
- [Documentation Index](INDEX.md) -- architecture, memory tiers, and reference entry points
- Example workflows: `examples/github-action/` in the repository
