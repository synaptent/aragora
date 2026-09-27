# Simulated Stranger Run #1 — 2026-07-10

**Instrument:** QUALITY_BAR.md dimension 1–3 baseline run (W1 amended exit
criterion). **Protocol:** clean `python:3.12-slim` container (arm64), PyPI +
public GitHub README only, no local repo access, skeptical-engineer persona
incentivized to find failures, 3-strike abandonment rule, no fixes during the
run. Runner: autonomous agent (not a human; per the 2026-07-10 founder
decision real outsiders wait for the ≥8/10 bar).

## Headline results

- **Advertised quickstart** (`pip install aragora` → `aragora demo --offline
  --receipt …` → `aragora receipt verify …`): **works verbatim, ~75 seconds**
  from container start to VALID.
- **Headline portability claim** ("anyone can verify offline with the
  standalone verifier"): **fails as written** — `aragora-verify` rejects the
  quickstart's own receipt with 12 schema errors; success required 2 failures
  + help-text spelunking to discover the undocumented `receipt export
  --format odr` bridge (succeeded on strike 3 of 3, ~2 min).
- **Signing-key endpoint** `https://aragora.ai/.well-known/aragora-odr-signing-key`:
  **HTTP 404** — the `--pubkey` authenticity path is undemonstrable
  end-to-end (#8809 is the fix).

## Findings (11)

| # | Sev | Finding |
|---|-----|---------|
| 1 | MAJOR | `aragora-verify` fails (exit 1, 12 schema errors) on the exact receipt the advertised quickstart produces; no quickstart mentions the required ODR export step |
| 2 | MAJOR | README's `aragora receipt export <id> --format odr` example fails for demo receipts ("Receipt not found as file or stored ID"); file-path form works but is not what is shown |
| 3 | MAJOR | PyPI long description is 3 sentences: no quickstart, no usage, references a repo path meaningless on PyPI |
| 4 | MAJOR | Advertised signing-key endpoint 404s; every obtainable receipt is unsigned (WARN) |
| 5 | MINOR | `aragora receipt --help` omits `odr` from its format list — hiding the exact bridge needed for finding 1 |
| 6 | MINOR | Three verify surfaces give three different check lists/verdicts on the same file; one fails outright |
| 7 | MINOR | Bare `aragora`/`--help`: 241 lines, ~120 subcommands, onboarding buried, closing examples require API keys |
| 8 | MINOR | `aragora doctor` (demo's suggested next step) exits 1 for a keyless user right after the keyless demo succeeded |
| 9 | MINOR | `aragora quickstart --demo` falsely claims it opened a browser preview (headless); never suggests verifying the receipt |
| 10 | MINOR | Happy-path demo prints "aragora-debate package unavailable" fallback note, implying a broken install |
| 11 | MINOR | Mock confidence/verdict inconsistent across surfaces (74% Pass/CONSENSUS vs 85% Approved) |

Genuine positives: 17s clean install; quickstart pair verbatim-truthful and
instant; principled exit codes; honest "weakening signals" framing; the
committed example ODR verifies.

## Durable evidence and issue map

The original subagent transcript is session-local and is not treated as a
durable public artifact. The repo-visible run record is the
[External-Proof Month scoreboard update](https://github.com/synaptent/aragora/issues/9065#issuecomment-4939711390),
and the reproducible findings are tracked as follows:

- Findings 1 and 6: [#9185](https://github.com/synaptent/aragora/issues/9185)
  (`aragora-verify` rejects the quickstart receipt; verifier disagreement).
- Finding 2: [#9186](https://github.com/synaptent/aragora/issues/9186)
  (documented export-by-ID form fails for demo receipts).
- Finding 3: [#9187](https://github.com/synaptent/aragora/issues/9187)
  (PyPI page has no usable first-run path).
- Finding 4: [#9188](https://github.com/synaptent/aragora/issues/9188)
  (signing-key endpoint 404; authenticity path unavailable).
- Findings 5 and 7-11: [#9189](https://github.com/synaptent/aragora/issues/9189)
  (the seven-item minor-friction bundle).

## Dimension scores (this run)

| Dimension | Score | One-line basis |
|---|---|---|
| 1. First-hour experience | **6/10** | Golden path fast and real; the tool's own suggested next steps (doctor, standalone verifier) then report failure |
| 2. Packaging truthfulness | **5/10** | Literal quickstart truthful; headline portability claim, export-by-ID example, PyPI page, key endpoint are not |
| 3. Docs coherence | **4/10** | Three verifiers/three stories; help text contradicts itself; PyPI/GitHub gap; doctor contradicts demo |

Each linked issue carries the stable reproduction and acceptance surface for
its finding; the issue map above replaces the non-durable session-log pointer.
