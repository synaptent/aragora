# Simile Trained Confidence Model — Research & Feasibility Analysis

> **Status:** NON-CANONICAL RESEARCH BRIEF. Authority: none. Source triage: [2026-08-26-x-bookmarks-triage.md](2026-08-26-x-bookmarks-triage.md), candidate 2. Feeds ODR-5 ([#8229](https://github.com/synaptent/aragora/issues/8229)).
> **Date:** 2026-08-26 (research verified 2026-08-29)

## The Concept

Simile ("Building confidence in Simile," Wesel, Chen & Liang, Aug 25 2026, <https://www.simile.com/blog/confidence>) trains a **separate model whose only job is to predict the error of the primary model's output**, using ground-truth error labels (Total Variation Distance between predicted and observed human-behavior distributions). Predicted error is served with every answer, bucketed into High / Moderately-High / Medium / Low confidence — "High" ⇒ 95% likely decision-grade, "Low" ⇒ 38%.

## What Simile measured (verified)

Five architectures on ~8,600 held-out questions, 5-fold CV with strict topic-grouped splits:

| Method | AUROC | Pearson r |
|---|---|---|
| Output-distribution features (entropy, max, top-2 gap) + regression | 0.566 | 0.122 |
| General-purpose embedding of the question + regression | 0.686 | 0.446 |
| Hidden-state probe (same forward pass, zero extra cost) | 0.730 | 0.538 |
| Continued fine-tuning with scalar error head | **0.736** | **0.565** |
| Same fine-tune on stock Qwen3.5-27B (ablation) | 0.720 | 0.538 |

Sobering baseline: output-distribution features alone are barely above chance — the hidden state knows far more than the output distribution shows. This differs from post-hoc calibration (per-model monotone remapping; cannot distinguish two same-score questions), verbalized confidence (never asked), and ensembles (k extra passes; measures agreement, misses systematic bias).

## Landscape

Trained verifier/confidence models predicting a primary model's trustworthiness are established: outcome verifiers (Cobbe 2021), process reward models (Lightman 2023), P(IK) heads (Kadavath 2022, the direct ancestor of the probe result), CometKiwi reference-free MT quality estimation (the closest *production* precedent — routes translations to human review on predicted quality), selective QA calibrators (Kamath 2020).

## Aragora Integration Assessment

Aragora's analog: predict P(this DecisionReceipt's conclusion holds — settles cleanly, never overturned). Constraints that shape the design:

- **No hidden-state access** to closed API debaters — Simile's two best methods are unavailable. Realistic ceiling is the embedding+features tier (expect AUROC ~0.65–0.70), possibly plus probes on local models only.
- **Features available today:** per-agent ELO + Brier history, dissent structure/severity, convergence signals, truth-scorer ratios, consensus mode, vote margins, Trickster flags.
- **Labels are the bottleneck:** settled/overturned outcomes number in the hundreds, arrive late, and are noisy (process failures conflated with decision quality). Do not train before ~500–1,000 labeled outcomes with ≥50–100 negatives; densify via per-claim verification outcomes.
- **Leakage warning:** debates cluster by codebase area — CV must group by topic/repo or AUROC will be inflated.

**Staged plan:** (1) now — log a frozen feature vector into every receipt at decision time and ship isotonic/Platt-calibrated composite confidence (honest "calibrated confidence" without a learned model); (2) at label volume — ridge/GBM over features + task embedding, reported through the ODR-5 calibration report API with reliability deciles; (3) bucket the output Simile-style with measured decision-grade rates rather than raw probabilities.

## Conclusion

Adopt the pattern via ODR-5; the immediately actionable slice is stage 1 (receipt feature logging), filed as a `research-intake` issue. No new track.

## Sources

- <https://www.simile.com/blog/confidence> — primary; all Simile numbers.
- <https://arxiv.org/abs/2110.14168>, <https://arxiv.org/abs/2305.20050>, <https://arxiv.org/abs/2207.05221>, <https://arxiv.org/abs/2209.06243>, <https://arxiv.org/abs/2006.09462> — comparables.
- <https://x.com/simile_ai/status/2092299277154291843> — the bookmark that surfaced it.
