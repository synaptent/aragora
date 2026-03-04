# GitHub Actions Integration

Integrate Aragora's AI code review and security auditing into your CI/CD pipeline with GitHub Actions.

## Quick Start

### 1. Add API Keys

Add at least one API key to your repository secrets:

```
Settings → Secrets and variables → Actions → New repository secret
```

| Secret | Provider | Required |
|--------|----------|----------|
| `ANTHROPIC_API_KEY` | Anthropic (Claude) | Recommended |
| `OPENAI_API_KEY` | OpenAI (GPT) | Optional |
| `OPENROUTER_API_KEY` | OpenRouter (fallback) | Optional |
| `GEMINI_API_KEY` | Google (Gemini) | Optional |
| `MISTRAL_API_KEY` | Mistral | Optional |

### 2. Copy Workflow Template

Download and copy to `.github/workflows/`:

```bash
# AI Code Review (runs on every PR)
curl -o .github/workflows/aragora-review.yml \
  https://raw.githubusercontent.com/an0mium/aragora/main/.github/workflows/templates/aragora-review-template.yml

# Gauntlet Security Audit (scheduled + manual)
curl -o .github/workflows/aragora-gauntlet.yml \
  https://raw.githubusercontent.com/an0mium/aragora/main/.github/workflows/templates/aragora-gauntlet-template.yml
```

### 3. Create PR

The workflow runs automatically on pull requests.

---

## Workflows

### AI Code Review

Multi-agent code review that posts findings directly to your PR.

**Features:**
- Multiple AI models debate code changes
- Identifies security vulnerabilities, performance issues, code quality
- Shows unanimous findings (high confidence) vs split opinions
- Posts formatted comment with actionable feedback

**Example Output:**

```markdown
## AI Red Team Code Review

**3 agents reviewed this PR** (anthropic-api, openai-api)

### Unanimous Issues
> All AI models agree - address these first

- SQL injection in `search_users()` - user input directly concatenated
- Missing input validation on file upload endpoint

### Split Opinions
> Agents disagree - your call on the tradeoff

| Topic | For | Against |
|-------|-----|---------|
| Add rate limiting | anthropic-api, openai-api | gemini |

---
*Agreement score: 85% | Powered by Aragora - AI Red Team*
```

**Configuration:**

```yaml
env:
  ARAGORA_AGENTS: "anthropic-api,openai-api"  # Which models to use
  ARAGORA_ROUNDS: "2"                          # Debate rounds (1-3)
  ARAGORA_FOCUS: "security,performance,quality" # Focus areas
```

### Gauntlet Security Audit

Deep security auditing using predefined playbooks.

**Playbooks:**

| Playbook | Purpose | Duration |
|----------|---------|----------|
| `security-red-team` | Attack surface analysis, prompt injection, jailbreak testing | ~30 min |
| `gdpr-compliance` | GDPR compliance audit for EU data handling | ~45 min |
| `soc2-readiness` | SOC 2 Type II readiness assessment | ~60 min |
| `api-design-review` | REST API best practices, versioning, error handling | ~20 min |
| `architecture-stress-test` | Scalability, fault tolerance, disaster recovery | ~40 min |

**Intensity Levels:**

| Level | Description | Time |
|-------|-------------|------|
| `quick` | Fast scan, critical issues only | 5-10 min |
| `standard` | Balanced coverage | 15-30 min |
| `thorough` | Comprehensive analysis | 30-60 min |
| `exhaustive` | Maximum depth | 60+ min |

**Manual Trigger:**

```bash
# Via GitHub CLI
gh workflow run aragora-gauntlet.yml \
  -f playbook=security-red-team \
  -f intensity=thorough

# Or via Actions UI
# Go to Actions → Aragora Gauntlet → Run workflow
```

---

## Advanced Configuration

### Custom Agents

Use specific models for different perspectives:

```yaml
env:
  ARAGORA_AGENTS: "anthropic-api,openai-api,mistral-api"
```

**Available Agents:**

| Agent | Model | Best For |
|-------|-------|----------|
| `anthropic-api` | claude-opus-4-5-20251101 | Security analysis, nuanced review |
| `openai-api` | gpt-5.3 | Code quality, performance |
| `mistral-api` | mistral-large-2512 | European compliance, fast |
| `gemini` | gemini-3-pro-preview | Architecture, scalability |
| `openrouter` | model parameter | Cost-effective fallback |

### Scheduled Audits

Run weekly security scans:

```yaml
on:
  schedule:
    - cron: '0 9 * * 1'  # Every Monday 9 AM UTC
```

### Branch Protection

Require AI review before merge:

```yaml
# In your branch protection rules:
# Settings → Branches → Add rule
# - Require status checks: "AI Red Team Review"
# - Recommended required checks: "Tests", "Lint", "Integration Tests"
#   (Treat long-running workflows like Benchmarks, Security Scan, Deploy as informational)
```

### Skip Conditions

Skip review for certain PRs:

```yaml
if: |
  github.actor != 'dependabot[bot]'
  && !contains(github.event.pull_request.labels.*.name, 'skip-ai-review')
```

### Large Diffs

The workflow automatically truncates diffs >50KB, prioritizing security-sensitive files:

```yaml
# Files containing these keywords are prioritized:
# auth, security, crypto, password, token, secret, config, env
```

---

## CLI Usage

Review code locally before pushing:

```bash
# Review a diff
git diff main | aragora review

# Review a PR
aragora review https://github.com/owner/repo/pull/123

# Demo mode (no API keys)
aragora review --demo

# Custom options
aragora review --diff-file changes.diff \
  --agents anthropic-api,openai-api \
  --rounds 3 \
  --focus security \
  --output-format json
```

Run Gauntlet locally:

```bash
# Security audit on a file
aragora gauntlet src/auth.py --playbook security-red-team

# GDPR compliance check
aragora gauntlet . --playbook gdpr-compliance --intensity thorough

# API design review
aragora gauntlet docs/api/openapi.yaml --playbook api-design-review
```

---

## Troubleshooting

### No API Keys Error

```
::warning::No API keys configured
```

**Solution:** Add at least one API key to repository secrets.

### Review Not Posted

Check the workflow logs for:
- API rate limiting (429 errors)
- Diff too large
- Invalid PR permissions

### Fork PRs Skipped

Forks don't have access to repository secrets. This is by design for security.

**Workaround:** For trusted forks, use `workflow_dispatch` to manually trigger:

```bash
gh workflow run aragora-review.yml -f pr_number=123
```

### Timeout Issues

For large codebases:
1. Reduce intensity: `standard` instead of `thorough`
2. Reduce rounds: `ARAGORA_ROUNDS: "1"`
3. Target specific paths instead of full repo

---

## Security Considerations

1. **API Keys**: Store in repository secrets, never in code
2. **Fork Safety**: Workflows skip fork PRs (no secret access)
3. **Permissions**: Use minimal required permissions
4. **Artifact Retention**: Review artifacts are retained 30-90 days

Note: The OpenAPI sync workflow on `main` requires `contents: write` so it can
commit generated spec updates.

---

## Example Workflow Files

### Minimal Setup

```yaml
name: AI Review
on: [pull_request]
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install aragora
      - run: |
          gh pr diff ${{ github.event.pull_request.number }} > pr.diff
          aragora review --diff-file pr.diff --output-format github | gh pr comment ${{ github.event.pull_request.number }} --body-file -
        env:
          GH_TOKEN: ${{ github.token }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Full Setup with Gauntlet

See the template files in:
- `.github/workflows/templates/aragora-review-template.yml`
- `.github/workflows/templates/aragora-gauntlet-template.yml`

---

## Related Documentation

- [API Reference](../api/API_REFERENCE.md) - Full API documentation
- [Security](../enterprise/SECURITY.md) - Security policies and practices
- [Gauntlet Playbooks](../../aragora/gauntlet/playbooks/) - Playbook definitions
- [SDK Examples](../../sdk/typescript/examples/) - JavaScript/TypeScript examples
