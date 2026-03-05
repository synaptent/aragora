# Next Roadmap Items — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement four roadmap items in priority order: GitHub Actions pre-merge gate, public demo page, EU AI Act Article 9+15 artifacts, and G2 trust-tier taint tracking.

**Architecture:** Track 1-2 are additive (new files only). Track 3 extends one existing 1,442-line file by mirroring its own patterns. Track 4 adds optional dataclass fields and propagation logic with no breaking changes.

**Tech Stack:** Python 3.11, GitHub Actions composite actions, Next.js 14 (App Router), TypeScript, pytest

**Working directory:** `/Users/armand/Development/aragora/.worktrees/codex-auto/claude-20260305-070153-6cf1bbf3`

---

## Track 1: GitHub Actions Pre-Merge Gate

### Task 1.1: Create the composite action

**Files:**
- Create: `.github/actions/aragora-code-review/action.yml`

**Step 1: Create the composite action file**

```yaml
# .github/actions/aragora-code-review/action.yml
name: Aragora Code Review
description: Multi-agent AI code review using aragora review CLI

inputs:
  anthropic-api-key:
    description: Anthropic API key (optional; omit to run in --demo mode)
    required: false
    default: ''
  rounds:
    description: Number of debate rounds
    required: false
    default: '2'
  focus:
    description: Comma-separated focus areas (security,performance,quality)
    required: false
    default: 'security,performance,quality'
  output-format:
    description: Output format (github, json, sarif)
    required: false
    default: 'github'
  post-comment:
    description: Post review as PR comment
    required: false
    default: 'true'

runs:
  using: composite
  steps:
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - name: Install aragora
      shell: bash
      run: pip install -e ".[dev]" --quiet 2>/dev/null || pip install aragora --quiet

    - name: Run aragora review
      shell: bash
      env:
        ANTHROPIC_API_KEY: ${{ inputs.anthropic-api-key }}
        GITHUB_TOKEN: ${{ github.token }}
        PR_URL: ${{ github.event.pull_request.html_url }}
      run: |
        ARGS="--output-format ${{ inputs.output-format }} --rounds ${{ inputs.rounds }} --focus ${{ inputs.focus }}"
        if [[ "${{ inputs.post-comment }}" == "true" ]]; then
          ARGS="$ARGS --post-comment"
        fi
        if [[ -z "${{ inputs.anthropic-api-key }}" ]]; then
          echo "No API key provided — running in demo mode"
          ARGS="$ARGS --demo"
        fi
        aragora review "$PR_URL" $ARGS || true
```

**Step 2: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/actions/aragora-code-review/action.yml'))" && echo "YAML OK"
```
Expected: `YAML OK`

**Step 3: Commit**

```bash
git add .github/actions/aragora-code-review/action.yml
git commit -m "feat(ci): add aragora-code-review composite action"
```

---

### Task 1.2: Create the PR-triggered workflow

**Files:**
- Create: `.github/workflows/aragora-review.yml`

**Step 1: Create the workflow**

```yaml
# .github/workflows/aragora-review.yml
name: Aragora Code Review

on:
  pull_request:
    types: [opened, synchronize, ready_for_review]

concurrency:
  group: aragora-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    if: "!github.event.pull_request.draft"
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4

      - name: Verify checkout integrity
        shell: bash
        run: |
          if [[ ! -f pyproject.toml ]]; then
            echo "::warning::pyproject.toml missing; attempting recovery"
            git sparse-checkout disable || true
            git fetch --no-tags origin "${GITHUB_SHA:-HEAD}"
            git reset --hard FETCH_HEAD
            git clean -ffd || true
          fi
          if [[ ! -f pyproject.toml ]]; then
            git archive "${GITHUB_SHA:-HEAD}" | tar -x || git archive HEAD | tar -x
          fi
          if [[ ! -f pyproject.toml ]]; then
            echo "::error::Checkout incomplete"
            exit 1
          fi

      - name: Aragora Multi-Agent Code Review
        uses: ./.github/actions/aragora-code-review
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          rounds: 2
          focus: security,performance,quality
          output-format: github
          post-comment: true
```

**Step 2: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/aragora-review.yml'))" && echo "YAML OK"
```
Expected: `YAML OK`

**Step 3: Verify aragora review CLI has --demo flag**

```bash
python -m aragora.cli.main review --help 2>/dev/null | grep -E "demo|post-comment|output-format" || aragora review --help 2>/dev/null | grep -E "demo|post-comment"
```
Expected: Lines showing `--demo`, `--post-comment`, `--output-format`

**Step 4: Commit**

```bash
git add .github/workflows/aragora-review.yml
git commit -m "feat(ci): add aragora review pre-merge gate workflow

Runs on every non-draft PR. Posts multi-agent code review comment.
Falls back to --demo mode when ANTHROPIC_API_KEY is not set so
forks and external PRs always get a review attempt.
Non-required check, cancel-in-progress enabled."
```

---

## Track 2: Public Demo Page

### Task 2.1: Create the public demo page

**Files:**
- Create: `aragora/live/src/app/(standalone)/demo/page.tsx`

**Step 1: Check what the instant demo page looks like for reference**

```bash
cat aragora/live/src/app/\(app\)/demo/instant/page.tsx 2>/dev/null | head -80
```

**Step 2: Create the standalone demo page**

```tsx
// aragora/live/src/app/(standalone)/demo/page.tsx
'use client';

import { useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

interface DemoResult {
  topic: string;
  consensus_reached: boolean;
  confidence: number;
  verdict: string;
  participants: string[];
  receipt_hash?: string;
}

export default function PublicDemoPage() {
  const [topic, setTopic] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DemoResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runDemo = async () => {
    if (!topic.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/demo/adversarial`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topic.trim(), agent_count: 3, rounds: 2 }),
      });
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const data = await res.json();
      setResult(data?.data ?? data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-start px-4 py-16">
      <div className="w-full max-w-2xl space-y-8">
        <div className="text-center space-y-3">
          <h1 className="text-4xl font-bold tracking-tight">Live Debate Demo</h1>
          <p className="text-gray-400 text-lg">
            Watch 3 AI agents debate your question and reach consensus in real time.
          </p>
        </div>

        <div className="space-y-3">
          <textarea
            className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-white placeholder-gray-500 resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500"
            rows={3}
            placeholder="e.g. Should we rewrite this service in Rust?"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            disabled={loading}
          />
          <button
            onClick={runDemo}
            disabled={loading || !topic.trim()}
            className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-xl transition-colors"
          >
            {loading ? 'Agents are debating...' : 'Start Debate'}
          </button>
        </div>

        {error && (
          <div className="bg-red-900/40 border border-red-700 rounded-xl px-4 py-3 text-red-300">
            {error}
          </div>
        )}

        {result && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-400">Consensus</span>
              <span className={`font-semibold ${result.consensus_reached ? 'text-green-400' : 'text-yellow-400'}`}>
                {result.consensus_reached ? 'Reached' : 'Not reached'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-400">Confidence</span>
              <span className="font-mono">{(result.confidence * 100).toFixed(0)}%</span>
            </div>
            {result.verdict && (
              <div className="border-t border-gray-800 pt-4">
                <p className="text-sm text-gray-400 mb-1">Verdict</p>
                <p className="text-white">{result.verdict}</p>
              </div>
            )}
            <div className="flex items-center justify-between text-xs text-gray-500">
              <span>{result.participants?.length ?? 0} agents</span>
              {result.receipt_hash && (
                <span className="font-mono">#{result.receipt_hash.slice(0, 12)}</span>
              )}
            </div>
            <div className="border-t border-gray-800 pt-4 text-center">
              <a
                href="/signup"
                className="text-indigo-400 hover:text-indigo-300 text-sm font-medium"
              >
                Save debates and get full receipts — sign up free →
              </a>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
```

**Step 3: Verify TypeScript compiles (from live/ directory)**

```bash
cd aragora/live && npx tsc --noEmit 2>&1 | head -20
```
Expected: No errors (or only pre-existing errors unrelated to this file)

**Step 4: Commit**

```bash
git add aragora/live/src/app/\(standalone\)/demo/page.tsx
git commit -m "feat(frontend): add public demo page at /demo (no auth required)

Standalone page outside (app)/ layout — no session check, no redirect.
Calls /api/v1/demo/adversarial with topic + 3 agents + 2 rounds.
Shows consensus verdict, confidence, receipt hash, and sign-up CTA."
```

---

### Task 2.2: Add demo CTA to the landing page

**Files:**
- Read + Modify: `aragora/live/src/components/landing/LandingPage.tsx` (or wherever the hero CTA is)

**Step 1: Find the landing page hero/CTA**

```bash
grep -n "CTA\|hero\|button\|Try\|Get Started\|Sign up" aragora/live/src/components/landing/LandingPage.tsx 2>/dev/null | head -20
# If not there, search:
grep -rn "Get started\|Sign up\|Try" aragora/live/src/components/landing/ --include="*.tsx" -l 2>/dev/null | head -5
```

**Step 2: Add "Try a live debate" as a secondary CTA**

Find the primary CTA button (e.g. "Get Started" or "Sign Up"). After it, add:

```tsx
<a
  href="/demo"
  className="inline-flex items-center text-sm text-gray-400 hover:text-white transition-colors"
>
  Try a live debate — no account needed →
</a>
```

**Step 3: Commit**

```bash
git add aragora/live/src/components/landing/
git commit -m "feat(frontend): add live demo CTA to landing page"
```

---

## Track 3: EU AI Act Article 9 + 15 Artifacts

**Key file:** `aragora/compliance/eu_ai_act.py` (1,442 lines)
**Reference pattern:** Read `_generate_art12()` (line ~965) before writing `_generate_art9()` and `_generate_art15()`.

### Task 3.1: Write failing tests for Article 9 + 15

**Files:**
- Modify: `tests/compliance/test_eu_ai_act.py`

**Step 1: Read the existing test file to understand the fixture pattern**

```bash
head -80 tests/compliance/test_eu_ai_act.py
```

**Step 2: Add failing tests at the bottom of the test file**

```python
# Minimal receipt fixture shared by Article 9 and 15 tests
_MINIMAL_RECEIPT = {
    "receipt_id": "rcpt-test001",
    "topic": "Should we migrate to microservices?",
    "verdict": "Conditional: migrate incrementally with circuit breakers",
    "confidence": 0.82,
    "robustness_score": 0.75,
    "consensus_reached": True,
    "participants": ["claude-3", "gpt-4o", "mistral-large"],
    "risk_summary": {"critical": 0, "high": 1, "medium": 2, "low": 3},
    "dissenting_agents": ["mistral-large"],
    "artifact_hash": "abc123def456",
    "signature": "sig-xyz",
    "votes": [
        {"agent": "claude-3", "choice": "yes", "confidence": 0.9},
        {"agent": "gpt-4o", "choice": "yes", "confidence": 0.85},
        {"agent": "mistral-large", "choice": "no", "confidence": 0.6},
    ],
}


class TestArticle9Artifact:
    def test_generate_returns_article9_artifact(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator, Article9Artifact
        gen = ComplianceArtifactGenerator()
        art9 = gen._generate_art9(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art9, Article9Artifact)

    def test_article9_has_required_fields(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator
        gen = ComplianceArtifactGenerator()
        art9 = gen._generate_art9(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert art9.risk_identification_methodology
        assert isinstance(art9.identified_risks, list)
        assert isinstance(art9.risk_mitigation_measures, list)
        assert art9.overall_residual_risk_level in ("acceptable", "conditional", "unacceptable")
        assert art9.integrity_hash

    def test_bundle_includes_article9(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator
        gen = ComplianceArtifactGenerator()
        bundle = gen.generate(_MINIMAL_RECEIPT)
        assert bundle.article_9 is not None
        assert bundle.article_9.artifact_id.startswith("ART9-")

    def test_article9_serializes_to_dict(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator
        gen = ComplianceArtifactGenerator()
        art9 = gen._generate_art9(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        d = art9.to_dict()
        assert "identified_risks" in d
        assert "overall_residual_risk_level" in d
        assert "integrity_hash" in d


class TestArticle15Artifact:
    def test_generate_returns_article15_artifact(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator, Article15Artifact
        gen = ComplianceArtifactGenerator()
        art15 = gen._generate_art15(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art15, Article15Artifact)

    def test_article15_has_required_fields(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator
        gen = ComplianceArtifactGenerator()
        art15 = gen._generate_art15(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art15.accuracy_metrics, dict)
        assert 0.0 <= art15.robustness_score <= 1.0
        assert isinstance(art15.cryptographic_controls, dict)
        assert art15.integrity_hash

    def test_bundle_includes_article15(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator
        gen = ComplianceArtifactGenerator()
        bundle = gen.generate(_MINIMAL_RECEIPT)
        assert bundle.article_15 is not None
        assert bundle.article_15.artifact_id.startswith("ART15-")

    def test_article15_serializes_to_dict(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator
        gen = ComplianceArtifactGenerator()
        art15 = gen._generate_art15(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        d = art15.to_dict()
        assert "accuracy_metrics" in d
        assert "robustness_score" in d
        assert "cryptographic_controls" in d
```

**Step 3: Run tests to confirm they fail**

```bash
pytest tests/compliance/test_eu_ai_act.py::TestArticle9Artifact tests/compliance/test_eu_ai_act.py::TestArticle15Artifact -x --tb=short 2>&1 | tail -20
```
Expected: `ImportError: cannot import name 'Article9Artifact'` or `AttributeError`

**Step 4: Commit the failing tests**

```bash
git add tests/compliance/test_eu_ai_act.py
git commit -m "test(compliance): add failing tests for Article 9 and 15 artifacts"
```

---

### Task 3.2: Implement Article9Artifact dataclass and generator

**Files:**
- Read then Modify: `aragora/compliance/eu_ai_act.py`

**Step 1: Read the Article12Artifact pattern (lines ~770-800 and ~965-1046)**

```bash
sed -n '770,800p' aragora/compliance/eu_ai_act.py
sed -n '865,920p' aragora/compliance/eu_ai_act.py
```

**Step 2: Add `Article9Artifact` dataclass after the `Article14Artifact` class**

Find the line with `@dataclass` just before `class ComplianceArtifactBundle`. Insert before it:

```python
@dataclass
class Article9Artifact:
    """EU AI Act Article 9 — Risk Management System artifact."""

    artifact_id: str
    receipt_id: str
    generated_at: str

    # Risk identification
    risk_identification_methodology: str
    identified_risks: list[dict]  # [{risk_id, description, likelihood, severity, category}]

    # Reasonably foreseeable misuse
    foreseeable_misuse_scenarios: list[str]

    # Risk mitigation
    risk_mitigation_measures: list[dict]  # [{risk_id, measure, residual_risk_level}]

    # Residual risk assessment
    residual_risks: list[dict]
    overall_residual_risk_level: str  # "acceptable" | "conditional" | "unacceptable"

    # Monitoring plan
    post_market_monitoring_plan: str

    integrity_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "receipt_id": self.receipt_id,
            "generated_at": self.generated_at,
            "risk_identification_methodology": self.risk_identification_methodology,
            "identified_risks": self.identified_risks,
            "foreseeable_misuse_scenarios": self.foreseeable_misuse_scenarios,
            "risk_mitigation_measures": self.risk_mitigation_measures,
            "residual_risks": self.residual_risks,
            "overall_residual_risk_level": self.overall_residual_risk_level,
            "post_market_monitoring_plan": self.post_market_monitoring_plan,
            "integrity_hash": self.integrity_hash,
        }
```

**Step 3: Add `article_9` field to `ComplianceArtifactBundle`**

Find `class ComplianceArtifactBundle` and add after the existing `article_14` field:

```python
    article_9: "Article9Artifact | None" = None
```

Also update `to_dict()` inside the bundle to include:
```python
            "article_9": self.article_9.to_dict() if self.article_9 else None,
```

**Step 4: Add `_generate_art9()` method to `ComplianceArtifactGenerator`**

Add after `_generate_art14()`:

```python
    def _generate_art9(
        self,
        receipt: dict[str, Any],
        receipt_id: str,
        timestamp: str,
    ) -> Article9Artifact:
        """Generate Article 9 (Risk Management System) artifact."""
        artifact_id = f"ART9-{uuid.uuid4().hex[:8]}"

        risk_summary = receipt.get("risk_summary", {})
        dissenting = receipt.get("dissenting_agents", [])
        confidence = receipt.get("confidence", 0.0)
        topic = receipt.get("topic", "unspecified")

        # Build identified risks from the receipt's risk summary
        identified_risks = []
        for severity, count in risk_summary.items():
            if count > 0:
                identified_risks.append({
                    "risk_id": f"RISK-{severity.upper()}-001",
                    "description": f"{count} {severity}-severity risk(s) identified during debate",
                    "likelihood": "medium" if severity in ("high", "critical") else "low",
                    "severity": severity,
                    "category": "operational",
                })

        # Foreseeable misuse based on topic
        foreseeable_misuse = [
            "Use for irreversible decisions without human review",
            "Applying verdict to out-of-scope domains",
            "Treating low-confidence verdicts as definitive",
        ]
        if dissenting:
            foreseeable_misuse.append(
                f"Ignoring minority dissent from: {', '.join(dissenting)}"
            )

        # Mitigation measures
        mitigations = [
            {
                "risk_id": "RISK-HALLUCINATION",
                "measure": "Multi-agent adversarial debate with dissent capture",
                "residual_risk_level": "low",
            },
            {
                "risk_id": "RISK-BIAS",
                "measure": "Heterogeneous model ensemble (different providers and RLHF targets)",
                "residual_risk_level": "low",
            },
            {
                "risk_id": "RISK-SYCOPHANCY",
                "measure": "Trickster hollow-consensus detection + RhetoricalObserver",
                "residual_risk_level": "low",
            },
        ]

        # Residual risk level
        critical_count = risk_summary.get("critical", 0)
        high_count = risk_summary.get("high", 0)
        if critical_count > 0:
            residual_level = "unacceptable"
        elif high_count > 2 or confidence < 0.5:
            residual_level = "conditional"
        else:
            residual_level = "acceptable"

        residual_risks = [
            {
                "description": "Correlated model failures on shared blind spots",
                "likelihood": "low",
                "severity": "medium",
                "accepted": True,
                "rationale": "Heterogeneous ensemble reduces but does not eliminate shared failures",
            }
        ]

        integrity_input = f"{artifact_id}:{receipt_id}:{residual_level}"
        integrity_hash = hashlib.sha256(integrity_input.encode()).hexdigest()

        return Article9Artifact(
            artifact_id=artifact_id,
            receipt_id=receipt_id,
            generated_at=timestamp,
            risk_identification_methodology=(
                "Multi-agent adversarial debate with structured critique phases. "
                "Risk identification emerges from agent disagreement, dissent, and "
                "confidence calibration across heterogeneous model ensemble."
            ),
            identified_risks=identified_risks,
            foreseeable_misuse_scenarios=foreseeable_misuse,
            risk_mitigation_measures=mitigations,
            residual_risks=residual_risks,
            overall_residual_risk_level=residual_level,
            post_market_monitoring_plan=(
                "Periodic re-evaluation via SettlementTracker (automated data checks: days, "
                "human review panels: months, market resolution: years). ELO calibration "
                "tracks model performance over time. Brier scores updated after settlement."
            ),
            integrity_hash=integrity_hash,
        )
```

**Step 5: Wire `article_9` into `generate()`**

Find the `return ComplianceArtifactBundle(...)` call in `generate()` and add:
```python
            article_9=self._generate_art9(receipt, receipt_id, timestamp),
```

**Step 6: Run Article 9 tests**

```bash
pytest tests/compliance/test_eu_ai_act.py::TestArticle9Artifact -v --tb=short
```
Expected: All 4 tests PASS

**Step 7: Commit**

```bash
git add aragora/compliance/eu_ai_act.py tests/compliance/test_eu_ai_act.py
git commit -m "feat(compliance): add Article 9 (risk management) artifact to EU AI Act bundle"
```

---

### Task 3.3: Implement Article15Artifact dataclass and generator

**Files:**
- Modify: `aragora/compliance/eu_ai_act.py`

**Step 1: Add `Article15Artifact` dataclass** (alongside Article9Artifact)

```python
@dataclass
class Article15Artifact:
    """EU AI Act Article 15 — Accuracy, Robustness, Cybersecurity artifact."""

    artifact_id: str
    receipt_id: str
    generated_at: str

    # Accuracy
    accuracy_metrics: dict  # {consensus_confidence, agreement_ratio, agent_count}

    # Robustness
    robustness_score: float
    adversarial_testing: dict  # {dissent_detected, dissent_count, hollow_consensus_checked}

    # Cybersecurity
    cryptographic_controls: dict  # {signing_algorithm, hash_algorithm, integrity_hash_present}

    # Error analysis
    error_indicators: list[str]

    # Monitoring
    continuous_monitoring: str

    integrity_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "receipt_id": self.receipt_id,
            "generated_at": self.generated_at,
            "accuracy_metrics": self.accuracy_metrics,
            "robustness_score": self.robustness_score,
            "adversarial_testing": self.adversarial_testing,
            "cryptographic_controls": self.cryptographic_controls,
            "error_indicators": self.error_indicators,
            "continuous_monitoring": self.continuous_monitoring,
            "integrity_hash": self.integrity_hash,
        }
```

**Step 2: Add `article_15` field to `ComplianceArtifactBundle`**

```python
    article_15: "Article15Artifact | None" = None
```

Update `to_dict()`:
```python
            "article_15": self.article_15.to_dict() if self.article_15 else None,
```

**Step 3: Add `_generate_art15()` method**

```python
    def _generate_art15(
        self,
        receipt: dict[str, Any],
        receipt_id: str,
        timestamp: str,
    ) -> Article15Artifact:
        """Generate Article 15 (Accuracy, Robustness, Cybersecurity) artifact."""
        artifact_id = f"ART15-{uuid.uuid4().hex[:8]}"

        votes = receipt.get("votes", [])
        participants = receipt.get("participants", [])
        dissenting = receipt.get("dissenting_agents", [])
        confidence = receipt.get("confidence", 0.0)
        robustness = receipt.get("robustness_score", 0.0)
        artifact_hash = receipt.get("artifact_hash", "")
        signature = receipt.get("signature", "")
        sig_algo = receipt.get("signature_algorithm", "")

        # Accuracy metrics
        agreement_ratio = (
            (len(participants) - len(dissenting)) / len(participants)
            if participants else 1.0
        )
        accuracy_metrics = {
            "consensus_confidence": round(confidence, 4),
            "agreement_ratio": round(agreement_ratio, 4),
            "agent_count": len(participants),
            "vote_confidence_mean": (
                round(sum(v.get("confidence", 0) for v in votes) / len(votes), 4)
                if votes else 0.0
            ),
        }

        # Adversarial testing (what the debate structure provides)
        adversarial_testing = {
            "dissent_detected": len(dissenting) > 0,
            "dissent_count": len(dissenting),
            "hollow_consensus_checked": True,  # Trickster always active
            "rhetorical_device_scoring": True,  # RhetoricalObserver active
            "multi_round_critique": True,
        }

        # Cryptographic controls
        cryptographic_controls = {
            "integrity_hash_algorithm": "SHA-256",
            "integrity_hash_present": bool(artifact_hash),
            "signature_present": bool(signature),
            "signing_algorithm": sig_algo or "not-signed",
        }

        # Error indicators from debate dissent
        error_indicators = []
        if dissenting:
            error_indicators.append(
                f"Minority dissent from {len(dissenting)} agent(s): {', '.join(dissenting)}"
            )
        if confidence < 0.7:
            error_indicators.append(f"Low consensus confidence: {confidence:.0%}")
        if robustness < 0.5:
            error_indicators.append(f"Below-threshold robustness score: {robustness:.2f}")

        integrity_input = f"{artifact_id}:{receipt_id}:{robustness}"
        integrity_hash = hashlib.sha256(integrity_input.encode()).hexdigest()

        return Article15Artifact(
            artifact_id=artifact_id,
            receipt_id=receipt_id,
            generated_at=timestamp,
            accuracy_metrics=accuracy_metrics,
            robustness_score=robustness,
            adversarial_testing=adversarial_testing,
            cryptographic_controls=cryptographic_controls,
            error_indicators=error_indicators,
            continuous_monitoring=(
                "ELO-based model performance tracking updated after each debate. "
                "Brier calibration scores updated after settlement resolution. "
                "SettlementTracker monitors claim accuracy over review_horizon_days."
            ),
            integrity_hash=integrity_hash,
        )
```

**Step 4: Wire `article_15` into `generate()`**

```python
            article_15=self._generate_art15(receipt, receipt_id, timestamp),
```

**Step 5: Run all compliance tests**

```bash
pytest tests/compliance/test_eu_ai_act.py -v --tb=short 2>&1 | tail -30
```
Expected: All tests PASS (including pre-existing ones)

**Step 6: Commit**

```bash
git add aragora/compliance/eu_ai_act.py
git commit -m "feat(compliance): add Article 15 (accuracy/robustness/cybersecurity) artifact

ComplianceArtifactBundle now includes all 5 articles (9, 12, 13, 14, 15).
Article 9: risk management process, identified risks, mitigations, residual risk.
Article 15: accuracy metrics, robustness score, adversarial testing, crypto controls."
```

---

## Track 4: G2 Trust-Tier Taint Tracking

### Task 4.1: Write failing tests for taint tracking

**Files:**
- Create: `tests/debate/test_taint_tracking.py`

**Step 1: Write the failing tests**

```python
# tests/debate/test_taint_tracking.py
"""Tests for G2 trust-tier taint tracking in debate orchestrator."""

import pytest


class TestAgentProposalTaint:
    def test_default_trust_tier_is_standard(self):
        from aragora.debate.distributed_events import AgentProposal
        p = AgentProposal(
            agent_id="claude", instance_id="i1", content="test", round_number=1
        )
        assert p.trust_tier == "standard"
        assert p.taint_source is None
        assert p.taint_evidence == []

    def test_untrusted_tier_can_be_set(self):
        from aragora.debate.distributed_events import AgentProposal
        p = AgentProposal(
            agent_id="claude", instance_id="i1", content="test", round_number=1,
            trust_tier="untrusted",
            taint_source="retrieved_context",
            taint_evidence=["ev-001"],
        )
        assert p.trust_tier == "untrusted"
        assert p.taint_source == "retrieved_context"
        assert "ev-001" in p.taint_evidence

    def test_to_dict_includes_taint_fields(self):
        from aragora.debate.distributed_events import AgentProposal
        p = AgentProposal(
            agent_id="claude", instance_id="i1", content="test", round_number=1,
            trust_tier="untrusted", taint_source="config_file",
        )
        d = p.to_dict()
        assert "trust_tier" in d
        assert d["trust_tier"] == "untrusted"
        assert "taint_source" in d


class TestConsensusProofTaint:
    def test_default_trust_score_is_one(self):
        from aragora.gauntlet.receipt_models import ConsensusProof
        cp = ConsensusProof(reached=True, confidence=0.9)
        assert cp.trust_score == 1.0
        assert cp.tainted_proposals == []

    def test_tainted_proposals_can_be_recorded(self):
        from aragora.gauntlet.receipt_models import ConsensusProof
        cp = ConsensusProof(
            reached=True, confidence=0.9,
            tainted_proposals=["prop-001"],
            trust_score=0.67,
        )
        assert len(cp.tainted_proposals) == 1
        assert cp.trust_score == pytest.approx(0.67)

    def test_to_dict_includes_taint_fields(self):
        from aragora.gauntlet.receipt_models import ConsensusProof
        cp = ConsensusProof(
            reached=True, confidence=0.9,
            tainted_proposals=["prop-001"],
            trust_score=0.67,
        )
        d = cp.to_dict()
        assert "trust_score" in d
        assert "tainted_proposals" in d


class TestDecisionReceiptTaintAnalysis:
    def test_taint_analysis_defaults_to_none(self):
        from aragora.gauntlet.receipt_models import DecisionReceipt
        r = DecisionReceipt(
            receipt_id="r1", gauntlet_id="g1", timestamp="2026-01-01T00:00:00Z",
            input_summary="test", input_hash="abc",
            risk_summary={}, attacks_attempted=0, attacks_successful=0,
            probes_run=0, vulnerabilities_found=0,
            verdict="PASS", confidence=0.9, robustness_score=0.8,
        )
        assert r.taint_analysis is None

    def test_taint_analysis_can_be_set(self):
        from aragora.gauntlet.receipt_models import DecisionReceipt
        taint = {
            "taint_level": "low",
            "tainted_proposal_count": 1,
            "trust_score": 0.75,
            "sources": ["retrieved_context"],
            "recommendation": "proceed",
        }
        r = DecisionReceipt(
            receipt_id="r1", gauntlet_id="g1", timestamp="2026-01-01T00:00:00Z",
            input_summary="test", input_hash="abc",
            risk_summary={}, attacks_attempted=0, attacks_successful=0,
            probes_run=0, vulnerabilities_found=0,
            verdict="PASS", confidence=0.9, robustness_score=0.8,
            taint_analysis=taint,
        )
        assert r.taint_analysis["taint_level"] == "low"
        assert r.taint_analysis["recommendation"] == "proceed"


class TestTaintLevelComputation:
    """Tests for the taint_level computation helper."""

    def test_no_taint_when_trust_score_high(self):
        from aragora.debate.taint import compute_taint_analysis
        result = compute_taint_analysis(tainted_proposals=[], total_proposals=5)
        assert result["taint_level"] == "none"
        assert result["recommendation"] == "proceed"

    def test_low_taint_level(self):
        from aragora.debate.taint import compute_taint_analysis
        # 1 out of 5 tainted = trust_score 0.8 -> "low"
        result = compute_taint_analysis(
            tainted_proposals=["p1"], total_proposals=5,
            taint_sources=["retrieved_context"],
        )
        assert result["taint_level"] == "low"
        assert result["trust_score"] == pytest.approx(0.8)

    def test_high_taint_requires_human_approval(self):
        from aragora.debate.taint import compute_taint_analysis
        # 4 out of 5 tainted = trust_score 0.2 -> "high"
        result = compute_taint_analysis(
            tainted_proposals=["p1", "p2", "p3", "p4"], total_proposals=5,
        )
        assert result["taint_level"] == "high"
        assert result["recommendation"] == "human approval required"
```

**Step 2: Run to confirm failures**

```bash
pytest tests/debate/test_taint_tracking.py -x --tb=short 2>&1 | tail -15
```
Expected: `ImportError` or `AttributeError` on missing fields/module

**Step 3: Commit failing tests**

```bash
git add tests/debate/test_taint_tracking.py
git commit -m "test(security): add failing tests for G2 trust-tier taint tracking"
```

---

### Task 4.2: Add taint fields to AgentProposal

**Files:**
- Read then Modify: `aragora/debate/distributed_events.py`

**Step 1: Read the AgentProposal dataclass (lines ~106-130)**

```bash
sed -n '100,135p' aragora/debate/distributed_events.py
```

**Step 2: Add taint fields with defaults (after `metadata` field)**

```python
    # Trust-tier taint tracking (G2 security roadmap item)
    trust_tier: str = "standard"   # "untrusted" | "standard" | "vetted" | "system"
    taint_source: str | None = None  # e.g. "retrieved_context", "config_file"
    taint_evidence: list[str] = field(default_factory=list)  # evidence IDs
```

**Step 3: Update `to_dict()` to include new fields**

```python
            "trust_tier": self.trust_tier,
            "taint_source": self.taint_source,
            "taint_evidence": self.taint_evidence,
```

**Step 4: Run relevant tests**

```bash
pytest tests/debate/test_taint_tracking.py::TestAgentProposalTaint -v --tb=short
```
Expected: All 3 PASS

**Step 5: Commit**

```bash
git add aragora/debate/distributed_events.py
git commit -m "feat(security): add trust_tier/taint_source/taint_evidence to AgentProposal"
```

---

### Task 4.3: Add taint fields to ConsensusProof and DecisionReceipt

**Files:**
- Read then Modify: `aragora/gauntlet/receipt_models.py`

**Step 1: Read ConsensusProof (lines ~51-70) and DecisionReceipt end**

```bash
sed -n '51,75p' aragora/gauntlet/receipt_models.py
grep -n "schema_version\|taint_analysis\|settlement_metadata" aragora/gauntlet/receipt_models.py
```

**Step 2: Add to ConsensusProof (after `evidence_hash` field)**

```python
    # Taint tracking (G2)
    tainted_proposals: list[str] = field(default_factory=list)
    trust_score: float = 1.0  # 1.0 = all clean; lower = tainted proposals in consensus
```

Update `ConsensusProof.to_dict()`:
```python
            "tainted_proposals": self.tainted_proposals,
            "trust_score": self.trust_score,
```

**Step 3: Add to DecisionReceipt (after `settlement_metadata`)**

```python
    # Taint analysis (G2 — populated when tainted context influenced any proposal)
    taint_analysis: dict[str, Any] | None = None
```

**Step 4: Run taint tests**

```bash
pytest tests/debate/test_taint_tracking.py::TestConsensusProofTaint tests/debate/test_taint_tracking.py::TestDecisionReceiptTaintAnalysis -v --tb=short
```
Expected: All PASS

**Step 5: Commit**

```bash
git add aragora/gauntlet/receipt_models.py
git commit -m "feat(security): add taint fields to ConsensusProof and DecisionReceipt"
```

---

### Task 4.4: Create the taint computation helper module

**Files:**
- Create: `aragora/debate/taint.py`

**Step 1: Create the module**

```python
# aragora/debate/taint.py
"""
Trust-tier taint analysis for debate proposals.

G2 security roadmap item: taint propagates from untrusted context sources
(retrieved docs, config files) through proposals into the consensus receipt.
"""

from __future__ import annotations

from typing import Any


def compute_taint_analysis(
    tainted_proposals: list[str],
    total_proposals: int,
    taint_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Compute taint level and recommendation from proposal taint data.

    Args:
        tainted_proposals: List of proposal IDs with trust_tier != "standard"
        total_proposals: Total number of proposals in the debate
        taint_sources: Optional list of taint source strings for the report

    Returns:
        Dict with taint_level, tainted_proposal_count, trust_score, sources,
        recommendation.
    """
    taint_count = len(tainted_proposals)
    sources = taint_sources or []

    if total_proposals == 0:
        trust_score = 1.0
    else:
        trust_score = (total_proposals - taint_count) / total_proposals

    if trust_score >= 0.9:
        taint_level = "none"
        recommendation = "proceed"
    elif trust_score >= 0.7:
        taint_level = "low"
        recommendation = "proceed"
    elif trust_score >= 0.5:
        taint_level = "medium"
        recommendation = "review before acting"
    else:
        taint_level = "high"
        recommendation = "human approval required"

    return {
        "taint_level": taint_level,
        "tainted_proposal_count": taint_count,
        "trust_score": round(trust_score, 4),
        "sources": sources,
        "recommendation": recommendation,
    }


def mark_proposal_tainted(
    metadata: dict[str, Any],
) -> tuple[str, str | None]:
    """Derive trust_tier and taint_source from a proposal's metadata dict.

    Returns:
        (trust_tier, taint_source) — "untrusted" if metadata indicates
        retrieved or config-file context, "standard" otherwise.
    """
    source_type = metadata.get("source_type", "")
    if source_type in ("retrieved", "config_file", "memory_file"):
        return "untrusted", source_type
    return "standard", None
```

**Step 2: Run all taint tests**

```bash
pytest tests/debate/test_taint_tracking.py -v --tb=short
```
Expected: All tests PASS

**Step 3: Run full test suite to check for regressions**

```bash
pytest tests/debate/ tests/compliance/ -x --timeout=60 --tb=short -q 2>&1 | tail -20
```
Expected: All existing tests still pass

**Step 4: Commit**

```bash
git add aragora/debate/taint.py
git commit -m "feat(security): add taint computation helper (compute_taint_analysis)

G2 security item: trust_score >= 0.9 -> 'none', >= 0.7 -> 'low',
>= 0.5 -> 'medium', < 0.5 -> 'high' with 'human approval required'.
mark_proposal_tainted() derives trust_tier from proposal metadata."
```

---

### Task 4.5: Final push and PR

**Step 1: Push the branch**

```bash
git push origin codex/claude-20260305-070153-6cf1bbf3
```

**Step 2: Update PR #629 description or open a new PR**

If changes are on the same branch as the docs PR (#629), the existing PR picks them up.
Otherwise:

```bash
gh pr create \
  --title "feat: GH Actions gate + public demo + EU AI Act Art 9/15 + G2 taint tracking" \
  --body "Four roadmap items implemented in priority order per docs/plans/2026-03-05-next-roadmap-items-design.md" \
  --base main
```

---

## Quick Reference

| Track | Key files | Tests |
|-------|-----------|-------|
| 1: GH gate | `.github/actions/aragora-code-review/action.yml`, `.github/workflows/aragora-review.yml` | Manual verify via workflow_dispatch |
| 2: Demo page | `aragora/live/src/app/(standalone)/demo/page.tsx` | `npx tsc --noEmit` |
| 3: EU AI Act | `aragora/compliance/eu_ai_act.py` | `pytest tests/compliance/test_eu_ai_act.py` |
| 4: Taint | `aragora/debate/distributed_events.py`, `aragora/gauntlet/receipt_models.py`, `aragora/debate/taint.py` | `pytest tests/debate/test_taint_tracking.py` |
