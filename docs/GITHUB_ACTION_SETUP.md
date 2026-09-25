# GitHub Action Setup Guide

Add multi-agent AI code review to your pull requests in under 5 minutes.

> **This is the canonical Action setup doc**, for the root `synaptent/aragora`
> action (the one with `emit-receipt`, below). The
> [README wedge section](../README.md#the-wedge-a-governance-gate-for-ai-written-code)
> is a shorter copy-paste version of the same root action; both describe the
> identical `uses: synaptent/aragora@<sha>` step. If instead you want the
> **nested, receipt-less** composite actions bundled inside this repository
> (`.github/actions/aragora-code-review`, `.github/actions/aragora-review`),
> see [Aragora GitHub Actions Code Review](guides/github-actions-review.md) —
> read its root-vs-nested note before reusing either snippet outside this repo.

## Quick Start

### 1. Add API Keys as GitHub Secrets

Go to your repo's **Settings > Secrets and variables > Actions** and add at least one:

| Secret | Required | Provider |
|--------|----------|----------|
| `ANTHROPIC_API_KEY` | Yes (or OpenAI) | [Anthropic Console](https://console.anthropic.com/) |
| `OPENAI_API_KEY` | Yes (or Anthropic) | [OpenAI Platform](https://platform.openai.com/) |
| `OPENROUTER_API_KEY` | No | Fallback provider |

For best results, add both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` -- multi-model consensus produces higher-quality reviews.

### 2. Add the Workflow File

Create `.github/workflows/aragora-review.yml` in your repository:

```yaml
name: Aragora AI Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

concurrency:
  group: aragora-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

permissions:
  contents: read
  pull-requests: write
  issues: write

jobs:
  review:
    name: AI Code Review
    runs-on: ubuntu-latest
    if: github.event.pull_request.draft == false && github.actor != 'dependabot[bot]'

    steps:
      - name: Run Aragora Review
        id: review
        uses: synaptent/aragora@1837e4b3cf26bd5f4a8acafded3e05475dcb0c6d
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          post-comment: 'true'
          fail-on-critical: 'false'
```

### 3. Open a Pull Request

That's it. The next PR will get an AI code review comment.

## Configuration

### Action Inputs

The Inputs and Outputs tables below are kept at full parity with
[`action.yml`](https://github.com/synaptent/aragora/blob/main/action.yml) by `tests/scripts/test_github_action_setup_doc.py`
(exact-match, not just a subset -- a field added to either side without the other
fails the test).

| Input | Default | Description |
|-------|---------|-------------|
| `agents` | `anthropic-api,openai-api` | Comma-separated agent list |
| `rounds` | `2` | Number of debate rounds (1-5) |
| `focus` | `security,performance,quality` | Review focus areas |
| `anthropic-api-key` | (none) | Anthropic API key for Claude |
| `openai-api-key` | (none) | OpenAI API key for GPT |
| `openrouter-api-key` | (none) | OpenRouter API key (fallback provider) |
| `post-comment` | `true` | Post review as PR comment |
| `fail-on-critical` | `false` | Fail CI if critical issues found |
| `max-diff-size` | `50000` | Max diff size in bytes |
| `pr-number` | (empty string) | Pull request number override, for manual/self-test runs (defaults to the triggering PR's number) |
| `failure-threshold` | `0` | Fail workflow if total issues exceed this count (`0` = disabled) |
| `output-format` | `none` | Additional output format besides the PR comment (`sarif`, `json`, `none`) |
| `sarif-upload` | `false` | Upload the generated SARIF file to the GitHub Security tab (requires `output-format: 'sarif'`) |
| `emit-receipt` | `false` | Emit a verifiable [Open Decision Receipt](specs/OPEN_DECISION_RECEIPT.md) (ODR) for the review and upload it as a build artifact. See [Emitting a Verifiable Decision Receipt](#emitting-a-verifiable-decision-receipt) below. |
| `receipt-reviewers` | `claude openai` | Space-separated model families for the receipt's merge-quorum pass. You must hold a reachable provider key for every family listed. |
| `odr-signing-key` | `''` | PKCS#8 PEM Ed25519 private key that signs the emitted receipt; pass a repository secret. Without it the receipt is unsigned. See [Sign your receipts](#sign-your-receipts). |
| `use-secrets-manager` | `false` | Hydrate provider API keys from AWS Secrets Manager instead of the `*-api-key` inputs. Requires AWS credentials in the job env. |
| `aws-region` | `us-east-2` | AWS region for Secrets Manager, when `use-secrets-manager` is `true`. |

### Action Outputs

| Output | Description |
|--------|-------------|
| `review-path` | Path to generated review file |
| `review-generated` | Whether a PR comment was generated |
| `review-json-path` | Path to the generated `review.json` (structured output) |
| `review-log-path` | Path to the `review.log` file |
| `unanimous-count` | Issues all agents agree on |
| `critical-count` | Critical severity issues |
| `high-count` | High severity issues |
| `medium-count` | Medium severity issues |
| `low-count` | Low severity issues |
| `total-count` | Total severity issues (`critical+high+medium+low`) |
| `risk-areas-count` | Risk areas noted (lower confidence items) |
| `split-opinions-count` | Split opinions (agent disagreement items) |
| `agreement-score` | Agent agreement score (0-1) |
| `sarif-path` | Path to the generated SARIF output file (only set when `output-format: 'sarif'` produced one) |
| `receipt-path` | Path to the verifiable ODR decision receipt (only set if `emit-receipt: 'true'` and emission succeeded) |
| `receipt-verdict` | Receipt verdict (`PASS` / `CHANGES_REQUESTED`) |
| `receipt-digest` | SHA-256 JCS content digest of the receipt -- the value signatures would cover |
| `receipt-verified` | `'true'` only if the receipt passed schema + digest verification before this output was set |
| `receipt-signed` | `'true'` when the receipt carries an Ed25519 signature (`odr-signing-key` was set) |
| `receipt-key-id` | Key id of the receipt's signature, empty when unsigned; match it against your published public key |

### Strict Mode (Block PRs on Critical Issues)

Set `fail-on-critical: 'true'` and add the review as a required status check:

1. Set `fail-on-critical: 'true'` in the workflow
2. Go to **Settings > Branches > Branch protection rules**
3. Enable "Require status checks to pass" and add "AI Code Review"

See `examples/github-action/aragora-review-strict.yml` for a complete example.
See also `examples/github-action/basic.yml` and `examples/github-action/advanced.yml`.

## Emitting a Verifiable Decision Receipt

Since [#8669](https://github.com/synaptent/aragora/pull/8669), this action can turn a
review into a portable, independently-verifiable
**[Open Decision Receipt](specs/OPEN_DECISION_RECEIPT.md)** (ODR) and upload it as a
build artifact. Set `emit-receipt: 'true'` to opt in. This extends the workflow from
Quick Start:

```yaml
name: Aragora AI Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write
  issues: write

jobs:
  review:
    runs-on: ubuntu-latest
    if: github.event.pull_request.draft == false
    steps:
      - uses: actions/checkout@v4

      - name: Run Aragora Review
        id: review
        uses: synaptent/aragora@1837e4b3cf26bd5f4a8acafded3e05475dcb0c6d
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          post-comment: 'true'
          emit-receipt: 'true'
          receipt-reviewers: 'claude openai'   # must be families you hold keys for

      - name: Upload the decision receipt
        if: steps.review.outputs.receipt-verified == 'true'
        uses: actions/upload-artifact@v4
        with:
          name: decision-receipt
          path: ${{ steps.review.outputs.receipt-path }}

      - name: Verify the receipt offline (optional)
        if: steps.review.outputs.receipt-verified == 'true'
        run: |
          pip install "aragora-verify>=0.1.1"
          aragora-verify "${{ steps.review.outputs.receipt-path }}"
```

See `examples/github-action/receipt.yml` for this snippet as a copy-paste workflow file.

Only the **root** `synaptent/aragora` action shown above (this `action.yml`) can emit
a receipt. The composite actions nested under `.github/actions/` in this repo
(`aragora-code-review`, `aragora-review`) have no `emit-receipt` input -- pointing
`uses:` at either of those will not produce one.

### What the emit step actually does

The `Emit decision receipt` step (gated on `inputs.emit-receipt == 'true'`) runs after
the normal review and:

1. Collects a **dry-run** heterogeneous-model merge-quorum pass over the same PR
   (`scripts/collect_quorum_evidence.py`) -- this never posts a comment or applies
   anything, regardless of merge tier.
2. Bridges that outcome into a native `DecisionReceipt` and exports it as an ODR
   document (`scripts/emit_pr_receipt.py`, calling
   `aragora.gauntlet.odr_export.decision_receipt_to_odr`).
3. Signs the receipt when `odr-signing-key` is set. The key is written to a
   runner-private file for this one command, so it never reaches the quorum step's
   model CLIs, and the file is removed when the step ends.
4. Re-validates the receipt's schema conformance and recomputes its canonical digest
   (`--verify`) before treating emission as successful.
5. Appends a short receipt summary to the PR comment and writes the receipt to
   `./aragora-artifacts/decision-receipt.odr.json`, which the action's own final step
   uploads as part of the `aragora-review-<pr>` build artifact (the snippet above
   additionally re-uploads just the receipt, under its own artifact name, for
   convenience).

Outputs: `receipt-path`, `receipt-verdict`, `receipt-digest`, `receipt-verified`,
`receipt-signed`, `receipt-key-id` (see
[Action Outputs](#action-outputs) above). Receipt emission is fail-closed once
requested: if `emit-receipt: 'true'` and no verified receipt comes out, the action's
own `Check receipt emission` step fails the job rather than silently skipping it.

### Secret-dependent limits

- **Receipts are unsigned unless you pass `odr-signing-key`.** An unsigned receipt
  still verifies (exit `0`) on schema conformance, quorum consistency and a digest
  the verifier recomputes from the file it is given, so it cannot show that a copy
  is unaltered or who produced it. `aragora-verify` reports `[WARN] signature:
  receipt is unsigned`. Sign your receipts (below) for authenticity.
- **`use-secrets-manager` / `aws-region` control *provider* keys.** When
  `use-secrets-manager: 'true'`, the quorum step hydrates `ANTHROPIC_API_KEY` /
  `OPENAI_API_KEY` / etc. from AWS Secrets Manager instead of the `*-api-key`
  inputs.
- **`receipt-reviewers` defaults to `'claude openai'`**, matching the review's own
  default agent families. Both need a reachable provider key (`ANTHROPIC_API_KEY`
  and `OPENAI_API_KEY`, as inputs or via Secrets Manager) -- if your repo only holds
  keys for other providers, override `receipt-reviewers` accordingly (e.g.
  `receipt-reviewers: 'gemini mistral'`), or the quorum step collects nothing and the
  job fails at `Check receipt emission`.

### Sign your receipts

Generate an Ed25519 key pair once, keep the private half as a repository secret, and
publish the public half where verifiers can find it (for example, commit it to the
repository):

```bash
openssl genpkey -algorithm ed25519 -out odr-signing-key.pem
openssl pkey -in odr-signing-key.pem -pubout -out odr-signing-key.pub.pem
gh secret set ARAGORA_ODR_SIGNING_KEY < odr-signing-key.pem
```

Then pass it to the action's `with:` block:

```
emit-receipt: 'true'
odr-signing-key: ${{ secrets.ARAGORA_ODR_SIGNING_KEY }}
```

Anyone can now check a receipt offline against your published key. Any edit to the
receipt, including its verdict, fails the `signature` check:

```bash
pip install "aragora-verify>=0.2.0"
aragora-verify decision-receipt.odr.json --pubkey odr-signing-key.pub.pem
```

The `receipt-key-id` output and the PR comment name the key that signed the
receipt. Keep `odr-signing-key.pem` itself out of the repository.

### Verify a receipt offline right now

You do not need to run the action to see the shape of a receipt it produces -- this
repository ships a real example built by the same merge-quorum pipeline
(`aragora/swarm/quorum_receipt.py`):

```bash
pip install "aragora-verify>=0.1.1"
aragora-verify docs/specs/examples/example-merge-quorum-receipt.odr.json
```

This exits `0` (`PASS` on schema conformance, canonical digest, and quorum
consistency; `WARN` on signature, since it is unsigned per the note above) and
reports `quorum.independence.distinct_model_families: 3`. The committed fixture is
illustrative -- it is not literally a file a live run produced -- but it comes from
the identical emitter this action's `Emit decision receipt` step calls, so its shape
is what `receipt-path` will point to.

`aragora-verify`'s full exit-code contract is
`0 verified / 1 failed / 2 usage / 3 signatures-present-unchecked` -- see the
[Independent Verifier Guide](specs/INDEPENDENT_VERIFIER_GUIDE.md#exit-code-contract)
for what each of the other three codes means. This is always the standalone
`aragora-verify`, never the in-tree `aragora verify` / `aragora receipt verify`
commands, which check a different object (the native `DecisionReceipt`, not the
portable ODR).

## How It Works

1. The action fetches the PR diff using `gh pr diff`
2. Multiple AI agents independently review the code
3. Agents debate findings over multiple rounds to reduce false positives
4. A consensus report is posted as a PR comment

### Review Comment Structure

The review comment includes:

- **Unanimous Issues** -- All agents agree these need attention (highest confidence)
- **Critical & High Severity** -- Security vulnerabilities, data loss risks
- **Split Opinions** -- Agents disagree, presented as tradeoffs for your judgment
- **Risk Areas** -- Lower confidence findings for manual review
- **Agreement Score** -- How much the agents agreed overall

## Customization

### Review Only Specific Files

Use GitHub Actions path filters to only trigger reviews on certain file types:

```yaml
on:
  pull_request:
    paths:
      - '**.py'
      - '**.ts'
      - '**.js'
```

### Security-Only Reviews

Focus the review on security concerns:

```yaml
- uses: synaptent/aragora@1837e4b3cf26bd5f4a8acafded3e05475dcb0c6d
  with:
    focus: 'security'
    rounds: '3'
    fail-on-critical: 'true'
```

### Skip Large PRs

The `max-diff-size` input prevents excessive API costs on large PRs. The default of 50KB handles most PRs. For monorepo or generated code, increase it:

```yaml
- uses: synaptent/aragora@1837e4b3cf26bd5f4a8acafded3e05475dcb0c6d
  with:
    max-diff-size: '200000'
```

## Troubleshooting

### "No API keys configured"

Ensure your GitHub Secrets are named exactly `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` and are passed to the action via `anthropic-api-key` / `openai-api-key` inputs.

### Review comment is empty

Check the workflow logs. Common causes:
- Diff is empty (no file changes)
- Diff exceeds `max-diff-size` (increase the limit)
- API key is invalid or expired

### Rate limiting

If you have many PRs, consider:
- Using `concurrency` groups to limit parallel reviews
- Reducing `rounds` from 3 to 2
- Using only one agent instead of two

### Costs

Approximate costs per review (2 agents, 2 rounds, typical PR):
- Anthropic Claude: ~$0.05-0.15
- OpenAI GPT-4: ~$0.10-0.30
- With OpenRouter fallback: ~$0.02-0.10
