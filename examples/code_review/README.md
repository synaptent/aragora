# Code Review with Aragora

Multi-model AI code review with consensus-based findings and audit-ready decision receipts.

## Quick Start

### 1. Install

```bash
pip install aragora
```

### 2. Try Demo Mode (no API keys)

```bash
# Review your uncommitted changes
git diff main | aragora review --demo

# Review a specific PR
aragora review --pr https://github.com/your-org/your-repo/pull/42 --demo
```

Demo mode uses three mock agents to show the full review workflow. The output includes unanimous findings, split opinions, and a confidence score.

### 3. Live Review (with API keys)

```bash
# Set at least one API key
export ANTHROPIC_API_KEY=your-key
export OPENAI_API_KEY=your-key  # optional, adds a second model

# Review changes
git diff main | aragora review

# Review with specific output format
git diff main | aragora review --format sarif --output findings.sarif
```

When multiple models with different training data independently flag the same issue, that convergence is meaningful. When they disagree, the disagreement tells you where human judgment is needed.

## Understanding the Output

### Verdict

| Verdict | Meaning |
|---------|---------|
| **PASS** | No critical issues, high agent agreement |
| **CONDITIONAL** | Issues found but agents mostly agree, human review recommended |
| **FAIL** | Critical issues found or low agent agreement |

### Confidence Score

The confidence score (0-100%) reflects how much the reviewing agents agreed. High confidence with PASS means strong consensus that the code is sound. Low confidence means the agents disagreed -- look at the split opinions to understand why.

### Decision Receipt

Every review produces a decision receipt with:

- **Unanimous critiques** -- issues all agents flagged (highest signal)
- **Split opinions** -- where agents disagreed (needs human judgment)
- **Risk areas** -- potential concerns that weren't unanimous
- **Provenance chain** -- SHA-256-hashed audit trail of each agent's assessment

View or export receipts:

```bash
# Save receipt as JSON
git diff main | aragora review --output receipt.json

# View a saved receipt in the browser
aragora receipt view receipt.json

# Verify receipt integrity
aragora receipt verify receipt.json

# Export to HTML
aragora receipt export receipt.json --format html --output review.html
```

## GitHub Actions Integration

Add Aragora to your CI pipeline so every PR gets multi-agent review:

```yaml
# .github/workflows/aragora-review.yml
name: Aragora Review
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Need full history for diff

      - name: Install Aragora
        run: pip install aragora

      - name: Run AI Code Review
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          git diff origin/main...HEAD | aragora review --format github
```

Or generate the workflow automatically:

```bash
aragora init --ci github
```

## Advanced Usage

### SARIF Output for IDE Integration

```bash
# Export findings in SARIF format (works with VS Code, GitHub Code Scanning)
git diff main | aragora review --format sarif --output findings.sarif
```

### Gauntlet Mode for Specs

For reviewing specifications, architecture docs, or policies (not just code):

```bash
# Adversarial stress-test a specification
aragora gauntlet spec.md --profile thorough --output report.html

# Review with GDPR compliance persona
aragora gauntlet policy.yaml --input-type policy --persona gdpr
```

### Programmatic Usage

```python
from aragora.client import AragoraClient

client = AragoraClient(base_url="http://localhost:8080")

# Submit a review
review = await client.reviews.submit(
    diff="...",
    agents=["anthropic-api", "openai-api", "gemini"],
)

# Get the decision receipt
receipt = review.receipt
print(f"Verdict: {receipt.verdict} ({receipt.confidence:.0%})")
```

## Next Steps

- [Quickstart](../../docs/quickstart.md) -- full setup guide
- [Gauntlet Guide](../../docs/debate/GAUNTLET.md) -- adversarial stress-testing
- [SDK Guide](../../docs/SDK_GUIDE.md) -- Python and TypeScript SDKs
- [API Reference](../../docs/api/API_REFERENCE.md) -- REST API documentation
