# Agent-facing surface: measured diagnosis and a working capsule

Status: **proposed**, with a measured prototype. Nothing in this document has
been adopted. See the implementation-truth matrix at the end for exactly what
exists today versus what is proposed.

Measured 2026-08-31 against `synaptent/aragora` @ `2b94459bc0e3`.
Reproduce with `python3 scripts/agent_surface/measure.py all --json`.

## Why this exists

Claims about agent ergonomics in this repo have always been assertions, because
the cost an agent pays to find out what is true had never been counted. This
work counts it. Every number below was produced by running the commands, not by
reasoning about them.

## Method

Four journeys, defined as the literal commands an agent runs today
(`scripts/agent_surface/journeys.json`), executed and token-counted by
`scripts/agent_surface/measure.py`. Budgets are pass/fail, fixed in advance:

| budget | limit |
|---|---|
| cold orientation to first safe action | ≤1 call, ≤4,000 tokens |
| quiet re-check, nothing changed | ≤1 call, ≤200 tokens |
| full situation reconstructible | ≤3 calls, ≤12,000 tokens |

Token counts use `tiktoken/cl100k_base` as a documented proxy for Claude's
tokenizer (within roughly 10–15%, far inside the margins here). Every record
names the tokenizer that produced it.

## Measured baseline — the system as it exists today

| journey | calls | tokens | budget | verdict |
|---|---:|---:|---|---|
| cold orientation | 7 | 24,272 | 1 / 4,000 | **FAIL — 6.1x** |
| quiet re-check | 4 | 4,011 | 1 / 200 | **FAIL — 20.1x** |
| resumption (PR 9924) | 6 | 3,692 | 3 / 12,000 | **FAIL on calls** |
| high-risk settlement | 5 | 9,856 | 3 / 12,000 | **FAIL on calls** |

Composition of the cold-orientation cost is the important part:

| component | tokens | share |
|---|---:|---:|
| `CLAUDE.md` + `AGENT_OPERATING_CONTRACT.md` | 18,407 | 76% |
| live state (git, PRs, CI, assigned work) | 5,865 | 24% |

**Three quarters of what an agent reads to orient is static documentation
re-read every session, containing zero live state.**

The steady-state number is worse than the startup number in the way that
matters: 4,011 tokens, paid on every tick, to be told nothing changed. That is
20x its budget and it recurs forever.

## Three structural findings

### 1. The instruments exist; nothing composes them

This repo is not short of state tooling. It has ~105 CLI parsers (~40 of them
state-reporting), 80 MCP tools, and 516 scripts of which 188 emit `--json`.
Roughly 17 of those are genuine aggregators.

The problem is the opposite of scarcity. An agent must know which of ~188
machine-readable instruments answers its question, then perform the join in its
own context window, paying for every intermediate byte. The v3 glossary budget
is ≤10 terms an agent must know before acting; the real figure is in the
hundreds.

Proof that composition is the fix, from inside aragora's own tooling:
`scripts/settle_status.py` answers "where does this PR stand in settlement" in
**~60 tokens**, including anchor, tier, evidence state, verdict, and next
action. The hand-join of the same question via
`gh pr view --json mergeStateStatus,statusCheckRollup` costs **8,816 tokens**
and still requires interpretation. The composed instrument already wins by two
orders of magnitude. There are just not enough of them, and nothing composes
the composers.

### 2. Two disjoint hemispheres of truth, with two bridges

The settlement/merge family (`settle_status.py`, `merge_quorum_io.py`,
`reconcile_merge_quorum.py`) reads **only GitHub, via `gh` subprocess** — nothing
durable on disk. The fleet/queue/worktree family reads **only `.aragora*`
filesystem state**, with `gh` as optional enrichment.

Only `aragora/work/board.py` and `scripts/loop_control_status.py` cross both.
Any question spanning the seam — "is this PR blocked by a real failure or by an
offline runner?", "is this worktree safe to remove given its PR state?" — has no
composed answer and must be hand-joined.

### 3. Four competing answers to "what should I do next"

At least four instruments independently compute a next action from
partially-overlapping sources, with no arbitration between them:
`settle_status.py` (`next_action`), `loop_control_status.py` (`next_action` per
loop plus `fleet_safe_to_continue`), `settle_one_pr.py` (`next_bounded_action`
and `recursive_best_next_prompt`), and the queue conductor (`next_action`).

This is a governance hazard, not only an ergonomics one. Two of these can
disagree and nothing detects it.

### Supporting evidence: 14 documented hand-joins

A survey of `docs/` recovered 14 procedures written as manual multi-source
recipes, each with a documented failure mode when the join is done wrong. They
are fossils of a missing composed view. The most severe:

- **Rollup poison** — the newest check-run row for a name can be a *cancelled
  advisory run*, so reading latest-per-name yields a red that "is not evidence
  that the PR introduced violations" (`docs/runbooks/MERGE_STATE_UNSTABLE_SETTLEMENT.md:118`).
- **Settlement replay** — a human settlement status from an old head read as
  authority for a new one; "if a new commit is pushed, the head SHA changes and
  the settlement signal no longer applies" (`docs/governance/MERGE_GATE_RECONCILIATION.md:102`).
- **Skipped ≠ red** — "Reviewers and dashboards sometimes look at `gh run list
  --branch main` and conclude CI is broken because most runs show as `skipped`.
  This is a misread of the telemetry, not a real failure mode"
  (`docs/CI_LANES.md:109`).
- **Liveness disagreement** — `owner_liveness.assessed` and `liveness_state` are
  deliberately separate and can legitimately disagree; reading the wrong one
  "declares a live owner dead" (`scripts/identify_lane_owner.py:1-60`).
- **Cap read as total** — `--limit` caps silently understate queue size; a prior
  audit found true open issues at 1,379 behind a 500 cap.

### Two defects found by running the tools rather than reading them

- `scripts/settle_status.py` **requires `--repo` even when run inside the repo it
  is asking about**, and cannot infer it. Passing the wrong slug produces a raw
  200-token Python traceback naming no next action.
- `.aragora/pr-state-cache.json` **does not exist**, and
  `.aragora/backpressure.json` is dated **2026-06-30 — two months stale**. The
  cheap-read caches that would make orientation affordable exist as a design and
  are not maintained. Any capsule that trusted them would report stale data as
  fact.

## The prototype

`scripts/agent_surface/situation.py` composes one capsule with six fields in
fixed order: **ANCHOR, OBJECTIVE, BELIEFS, UNKNOWNS, FRONTIER, OBLIGATIONS**.

Two design rules do the real work:

**The join happens below the context boundary.** The tool may spend thousands of
tokens of GitHub JSON internally; the agent reads back only the answer. An agent
pays for what enters its context, not for what the tool does on its behalf. This
is what makes a 32-token tick possible over a 3,454-token data source.

**Authority is never upgraded.** A belief from a stale cache is reported stale,
never promoted to fact. What cannot be established becomes an entry in UNKNOWNS
with the cheapest probe that would answer it, rather than a reassuring default.
Absence of evidence is never rendered as evidence of absence. Concretely: main's
required-check state is deliberately an UNKNOWN, not a belief, because run
conclusions are not branch protection and conflating them is a documented
misread.

### Measured after

Two stages. The first composed git and GitHub only; the second added
`loop_control_status.py` (fleet, crossing the seam) and, under `--pr N`,
`settle_status.py`.

| journey | calls | tokens | verdict | vs baseline |
|---|---:|---:|---|---|
| cold orientation, git+GitHub | 1 | 552 | **PASS** | 24,272 → 552 (**44x**) |
| cold orientation, **composed** | 1 | 709 | **PASS** | 24,272 → 709 (**34x**) |
| quiet re-check, composed | 1 | 31 | **PASS** | 4,011 → 31 (**129x**) |

Composition costs 157 tokens and buys fleet state across the hemisphere seam
plus per-PR settlement — the two things findings 1 and 2 said were missing.

**The trade is wall-clock for context, deliberately.** The composed capsule takes
~13s to build, most of it inside `loop_control_status.py`. Wall time is cheap and
does not accumulate in a context window; tokens are expensive and do. `--no-fleet`
skips it for callers that need speed over completeness.

Two behaviours worth recording because they were checked rather than assumed:

- **The cursor is stable, not over-sensitive.** Two back-to-back capsules produce
  an identical cursor. An over-sensitive cursor would report "changed" on every
  tick and the cheap path would never fire — the failure mode that would quietly
  void the entire delta design.
- **The delta correctly detects real change.** An earlier measurement returned
  125 tokens on the changed path because edits were landing mid-run. That was the
  mechanism working, not noise.

## What the prototype does NOT do

Stated plainly so this document is not read as more finished than it is.

- OBJECTIVE is inferred from the branch name and last commit. It is the weakest
  field and is close to a placeholder.
- Finding 3 is **surfaced, not solved**. The capsule reports `settle_status.py`'s
  `next_action` as an attributed advisory under OBLIGATIONS rather than adopting
  it, precisely so it does not become a fifth unarbitrated answer. Arbitration
  between the four remains unbuilt.
- It composes two aggregators. The other ~15 are untouched.
- OBLIGATIONS carries a standing prohibition but does not track real in-flight
  effects awaiting verification.
- **There is no accretion at all.** No `POST /experience`, no record written, no
  retrieval key. The compounding property is entirely absent, and it is the one
  that matters most.
- The cursor is computed but never persisted, so the delta path depends on the
  caller holding it.

## Open questions

1. **Where does accretion actually land?** `aragora/gauntlet/receipt_store.py` is
   an in-process dict, not durable — receipts that should compound are lost at
   process exit. Durable receipts exist separately at `.aragora/receipts/`. Which
   is the accretion store, and what call surfaces it to the next agent? Until
   this is answered there is no accretion, only a noun.
2. **Who arbitrates the four `next_action` fields?** A capsule that adds a fifth
   without resolving the other four makes finding 3 worse.
3. **Is `--since` the right delta contract**, or should the cursor be
   server-persisted so an agent that lost it can still get a cheap tick?
4. Does the ≤10-term glossary budget survive contact with a real capsule, or does
   the capsule simply relocate the vocabulary problem?

## Implementation-truth matrix

| capability | status | evidence |
|---|---|---|
| Journey measurement harness | **implemented** | `scripts/agent_surface/measure.py`, runs, exit 0/3 |
| Baseline measurements, 4 journeys | **implemented** | table above, reproducible |
| Six-field capsule, GitHub + git | **implemented** | `situation.py`, measured PASS on both budgets |
| Cheap delta via cursor | **implemented** | 31 tokens measured; cursor stability verified |
| Capsule composes existing aggregators | **partial** | 2 of ~17: `loop_control_status.py`, `settle_status.py` |
| Cross-hemisphere composition | **implemented** | fleet beliefs from `.aragora*` state, measured |
| `--repo` inference for `settle_status.py` | **implemented** | slug taken from the anchor |
| Arbitration of the four `next_action` fields | **not started** | capsule attributes, does not adopt — finding 3 |
| Real OBLIGATIONS tracking | **partial** | standing prohibition + attributed advisory only |
| Accretion / experience write-back | **not started** | open question 1 |
| Net proper-noun reduction | **not evaluated** | prototype adds `capsule`, `cursor`, `anchor`, `frontier`; removes nothing yet |
| Adoption anywhere in the repo | **not started** | nothing imports this |

## First slice — done, and what it showed

The first slice was to compose `settle_status.py` and `loop_control_status.py`,
testing finding 1's claim (composition is the fix) against finding 2's obstacle
(the hemispheres) in one step, without inventing a new state store. It is done
and it held: 157 additional tokens bought fleet state across the seam plus
per-PR settlement, and cold orientation still passes at 709.

It also produced the clearest example of the authority rule earning its keep.
`loop_control_status.py` reports `fleet_safe_to_continue: true` while **3 of its
7 loops report `state: unknown`**. Restating that as a plain green would be a
summary claiming more certainty than its basis. The capsule instead reports the
verdict *with* the caveat and raises an UNKNOWN naming the three loops and the
probe that would identify them. A summary layer that silently dropped the caveat
would be indistinguishable from a correct one — right up until an agent
dispatched work into a fleet nobody could actually see.

## Recommended next slice

**Accretion, because it is the only thing here that compounds and it is the one
thing entirely absent.** Answer open question 1 first — is the durable receipt
store at `.aragora/receipts/` the accretion store, given
`aragora/gauntlet/receipt_store.py` is an in-process dict that loses everything
at exit? Then define one record an agent writes on finishing, and make the
capsule's next cold start surface it. Without a named record, a named store, and
a named retrieval call, "accretive" stays a word.

Explicitly *not* recommended next: composing more aggregators. Two was enough to
prove the pattern; a third adds tokens without answering a live question.
