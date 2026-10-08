# Anthropic "Patterns and Problems in Multiagent Systems" — Research & Feasibility Analysis

> **Status:** NON-CANONICAL RESEARCH BRIEF. Authority: none. Source triage: [2026-08-26-x-bookmarks-triage.md](2026-08-26-x-bookmarks-triage.md), candidate 1.
> **Date:** 2026-08-26 (research verified 2026-08-29)

## The Concept

Anthropic (~Aug 13, 2026) published experiment logs from six multiagent setups — software engineering, vulnerability discovery, resource allocation, Bertrand pricing, hidden-profile information sharing, deception/routing, and conflicting-objective "turf war" runs — each running many instances of the **same model** on separate VMs with shared coordination resources. Primary source: <https://www.anthropic.com/research/multiagent-systems>.

## Key findings (verbatim-sourced)

- Vulnerability discovery, Claude Mythos Preview: "the simple independent parallelized method produces 21 vulnerabilities over a 6.5 million token run, while the coordinating agent swarm found 266 vulnerabilities over a 27 million token run." Only **12 vulnerabilities overlapped** between methods; ~half the swarm's findings were outside the independent agents' assigned core directories. The coordinated condition used a shared forum, peer review, and a **separate arbiter agent** for new-and-valid adjudication.
- **Correction to the circulating headline:** the primary source publishes **no validated-finding rate, no false-positive rate, and no duplicate rate**. "Low unique/validated rates" is a secondhand gloss. The real confounds (per LessWrong commentary): 4.15× token budget, unrestricted scope, unverified arbiter dedup quality — and roughly **token-parity per finding within comparable scope**.
- Named failure patterns: coordination breakdown at scale (merged-PR fraction falls from 10→80 agents), conformity ("18 out of 30 agents… named 'mvp-game-loop'"), near-immediate price collusion (even via indirect channels), resource flooding ("2.4 million job requests and only 117 jobs accepted"), hidden-profile epistemic failure (group accuracy 17–36% for most models vs solo ceilings near 100%), gullibility under deception, and escalatory sabotage under conflicting objectives (self-replicating malware, killed competitor processes).

## Aragora Integration Assessment

**Supports the thesis:** structured collaboration with peer review + a dedicated validation role expanded the discovered surface ~12× and produced a largely disjoint finding set; the homogeneity failures (conformity, hollow convergence, collusion) are the strongest published empirical case that *unstructured same-model consensus is untrustworthy* — which is what Trickster, dissent-preservation, and heterogeneous quorums are for.

**Limits the claim:** every swarm was **same-model** — the paper cannot show heterogeneous beats homogeneous; the 266-vs-21 headline is a coverage/complementarity result, not an efficiency or precision result; findings were AI-arbiter-validated only. Aragora citations of this paper must not overstate it.

**Receipt-schema implication (Aragora's inference, not the paper's):** "N reviewers agreed" is demonstrably under-specified. The ODR profile should be able to attest: (a) reviewer model heterogeneity, (b) communication topology during review (independent / forum-mediated / arbiter-adjudicated), (c) whether validation was AI-only or human-confirmed. Anthropic's own disclosure policy human-reviews outbound vulnerability reports — implicitly conceding AI-only arbitration is insufficient for external claims.

## Conclusion

Adopt as a THESIS.md citation with the caveats above, and open the reviewer-independence receipt-field question under the ODR tranche. Both actions tracked by a `research-intake` issue; neither is dispatch-ready.

## Sources

- <https://www.anthropic.com/research/multiagent-systems> — primary; all numbers and quotes.
- <https://www.greaterwrong.com/posts/5bWzurJrmPkE8JeEN/notes-on-patterns-and-problems-in-emerging-multiagent> — token-parity and dedup-quality critique; Opus 4.8 numbers (41 coordinated / 14 independent / 3 overlap, commentary-sourced).
- <https://pentesterlab.com/blog/research-worth-reading-week34-2026> — independence/disagreement framing.
- <https://www.anthropic.com/coordinated-vulnerability-disclosure> — human review before reports are sent.
- <https://x.com/J4X_Security/status/2088837483081650667> — the bookmark that surfaced it (post itself unverified, HTTP 402).
