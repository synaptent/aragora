# Aragora GitHub Actions Code Review

Add multi-agent AI code review to any repository using GitHub Actions.

## Quick Start

Copy this workflow into `.github/workflows/aragora-review.yml`:

```yaml
name: Aragora Code Review

on:
  pull_request:
    types: [opened, synchronize]

concurrency:
  group: aragora-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    if: "!github.event.pull_request.draft"
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4

      - name: Aragora Multi-Agent Code Review
        uses: ./.github/actions/aragora-code-review
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          rounds: 2
          focus: security,performance,quality
          post-comment: true
```

Add your `ANTHROPIC_API_KEY` as a repository secret under Settings > Secrets and variables > Actions.

## Configuration

### Code Review Action (`.github/actions/aragora-code-review`)

| Input | Default | Description |
|-------|---------|-------------|
| `anthropic-api-key` | | Anthropic API key (Claude) |
| `openai-api-key` | | OpenAI API key (GPT) |
| `openrouter-api-key` | | OpenRouter API key (fallback/additional models) |
| `agents` | auto-detected | Comma-separated agent list; auto-detected from provided API keys if omitted |
| `rounds` | `2` | Number of debate rounds (1-5) |
| `focus` | `security,performance,quality` | Comma-separated focus areas: `security`, `performance`, `quality`, `correctness` |
| `output-format` | `github` | Output format: `github`, `json`, or `html` |
| `post-comment` | `true` | Post review results as a PR comment |
| `fail-on-critical` | `true` | Fail the workflow if critical issues are found |
| `fail-on-high` | `false` | Fail the workflow if high-severity issues are found |
| `sarif-upload` | `false` | Upload SARIF results to the GitHub Security tab |
| `max-diff-size` | `50000` | Maximum diff size in bytes (larger diffs are truncated) |

### Design Review Action (`.github/actions/aragora-review`)

| Input | Default | Description |
|-------|---------|-------------|
| `api-key` | | Aragora API key |
| `file` | | Path to the file to review (e.g., `docs/design.md`) |
| `spec` | | Inline specification text (alternative to `file`) |
| `personas` | `security,performance` | Comma-separated compliance personas (e.g., `sox,security,pci_dss`) |
| `rounds` | `3` | Number of debate rounds (1-10) |
| `fail-on-dissent` | `false` | Fail the action if there are dissenting opinions |
| `fail-on-no-consensus` | `false` | Fail the action if consensus is not reached |
| `comment-on-pr` | `true` | Post review results as a PR comment |
| `base-url` | `https://api.aragora.ai` | Custom API base URL |

## How It Works

1. **Diff extraction** -- The action fetches the PR diff using `gh pr diff` (falls back to `git diff`). Diffs larger than `max-diff-size` are truncated.
2. **Multi-agent debate** -- Multiple LLM agents independently review the diff, then debate their findings over the configured number of rounds. Agents are selected automatically from whichever API keys you provide.
3. **Consensus scoring** -- Findings that all agents agree on are surfaced as "unanimous issues." Split opinions are reported separately. An overall agreement score (0.0-1.0) summarizes how aligned the agents were.
4. **PR comment** -- Results are posted as a PR comment (updated in-place on subsequent pushes). Critical and high-severity issues are highlighted at the top.
5. **Optional SARIF upload** -- Enable `sarif-upload` to push results into the GitHub Security tab alongside CodeQL and other scanners.

## Outputs

The code review action exposes these outputs for downstream steps:

| Output | Description |
|--------|-------------|
| `review-path` | Path to the JSON review output file |
| `critical-count` | Number of critical issues found |
| `high-count` | Number of high-severity issues |
| `medium-count` | Number of medium-severity issues |
| `low-count` | Number of low-severity issues |
| `total-count` | Total number of issues |
| `agreement-score` | Agent agreement score (0.0-1.0) |
| `sarif-path` | Path to SARIF output (if generated) |

Use these in subsequent workflow steps, for example to gate deployment:

```yaml
- name: Block deploy on critical issues
  if: steps.review.outputs.critical-count != '0'
  run: exit 1
```
