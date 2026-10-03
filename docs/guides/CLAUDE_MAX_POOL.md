# Claude Max Pool Guide

How to run many Anthropic **Claude Max** (Pro/Max subscription) plans as a pool that
Aragora uses for heterogeneous, **non-OpenAI** code reviews and for review throughput.

A "profile" is one Claude subscription. Profiles are named `max-01` … `max-13`. Each
profile authenticates with its **subscription** (OAuth login), not an API key, so review
traffic draws on your flat-rate Max plans instead of metered API spend.

## TL;DR

```bash
# 1. Log in each subscription once (interactive OAuth — opens a browser per profile)
scripts/claude_profiles_bootstrap.sh login

# 2. Verify (live-probes tokens; catches expired logins that "status" mislabels) and
#    write the health snapshot the review router trusts
scripts/claude_profiles_bootstrap.sh verify --json

# 3. Use the pool — a codex/OpenAI session can get a non-OpenAI review on a local diff:
git diff origin/main...HEAD | aragora review-local --diff -
```

## Why a pool

- **Heterogeneous review (anti-collusion):** a change written by an OpenAI/codex worker
  should be reviewed by a *different* model family. Claude profiles supply that
  non-OpenAI evidence.
- **Throughput:** spreading reviews across many subscriptions avoids saturating one plan
  while the rest sit idle.
- **Cost:** subscription auth means reviews run on flat-rate Max plans, not per-token API
  billing.

## How profiles work

`scripts/claude_profile.sh <profile> <args...>` runs the `claude` CLI with a
per-profile `HOME` / `CLAUDE_CONFIG_DIR` and the API key unset, so each profile keeps an
isolated login and uses subscription auth. The bootstrap helper drives it across the whole
pool.

| Command | Purpose |
|---------|---------|
| `claude_profiles_bootstrap.sh login [--force] [profile...]` | Interactive OAuth login per profile. `--force` re-logs an already-valid profile. |
| `claude_profiles_bootstrap.sh status [profile...]` | Cheap local check. **Can report `loggedIn:true` even when the token is expired.** |
| `claude_profiles_bootstrap.sh verify [--json] [profile...]` | Live-probes each profile to detect expired tokens. `--json` writes the health snapshot. |

> **Trust `verify`, not `status`.** A local `status` can say a profile is logged in while
> its token is actually expired. The review router was hardened to rely on the
> `verify`-backed snapshot for exactly this reason.

## Health snapshot

`verify --json` writes `.aragora/claude_pool_health.json`:

```json
{
  "generated_at": "2026-06-03T00:00:00Z",
  "healthy": 11,
  "total": 13,
  "profiles": [
    {"name": "max-01", "email": "you+01@example.com", "state": "ok"},
    {"name": "max-09", "email": "", "state": "not_configured"}
  ]
}
```

States: `ok`, `expired`, `logged_out`, `not_configured`, `unknown`. The review router skips
profiles whose state is unhealthy (`expired` / `logged_out` / `not_configured` /
`unauthenticated`) and only counts the snapshot when it is fresh (see TTL below).

Override the snapshot location with `ARAGORA_CLAUDE_POOL_HEALTH_FILE`.

## Routing and environment knobs

The review router (`aragora/swarm/review_routing.py`) picks a reviewer family, expands the
`claude` family across the profile pool, runs a preflight per candidate, and fails over to
the next candidate on auth/billing problems.

| Variable | Default | Effect |
|----------|---------|--------|
| `ARAGORA_REVIEW_PROVIDER_ORDER` | `claude,gemini,grok,openrouter` order logic | Comma-separated reviewer family order. The worker's own family is skipped. |
| `ARAGORA_CLAUDE_REVIEW_PROFILES` | `max-01`…`max-13` | Comma-separated profile list to use as the claude pool. |
| `ARAGORA_CLAUDE_REVIEW_PROBE` | `snapshot` | Preflight mode: `snapshot` (trust health file, fall back to `status`), `live` (probe now), or `status` (local check only). |
| `ARAGORA_CLAUDE_POOL_HEALTH_TTL` | `3600` (seconds) | How long a snapshot is trusted. `0` = always stale (forces fallback). |
| `ARAGORA_CLAUDE_POOL_HEALTH_FILE` | `.aragora/claude_pool_health.json` | Snapshot path override. |
| `ARAGORA_CLAUDE_REVIEW_ROTATE` | on | Spread reviews across subscriptions via a persisted cursor. Set `0`/`false`/`no`/`off` to always start at the first profile. |

### Throughput (rotation)

With rotation on (default), each review advances a cursor at
`.aragora/claude_pool_cursor.json` so consecutive reviews **start on different
subscriptions** (and wrap around), instead of every review hammering `max-01` first.
Snapshot-unhealthy profiles are dropped from the rotation.

## Offline non-OpenAI reviews: `review-local`

`aragora review-pr` reviews a live GitHub PR. When GitHub is degraded — or you just want a
second opinion on an uncommitted change — use the offline `review-local` command. It has
**no GitHub dependency**.

```bash
# Review the current branch's diff with a non-OpenAI reviewer (default: claude pool)
git diff origin/main...HEAD | aragora review-local --diff -

# Review a saved patch, with extra context, as JSON
aragora review-local --diff /tmp/change.patch --spec docs/specs/my-change.md --json
```

Key flags:

- `--diff <path|->` — unified diff file, or `-` for stdin.
- `--worker-model <family>` — the family that produced the change (excluded from review;
  default `codex`).
- `--review-model` / `--reviewer <family>` — preferred non-worker reviewer (default
  `claude`).
- `--spec <path>`, `--title <text>` — optional context for the prompt.
- `--json`, `--artifact-dir <dir>`.

A receipt is written to `.aragora/review-local/<timestamp>/` (`review.json` + `input.diff`).
The verdict status maps to the exit code: `passed` → 0, `changes_requested` → 2, anything
blocked → 1.

## Staying alive without re-login: VibeProxy token sync

**Why profiles kept expiring.** Anthropic OAuth **single-use-rotates** the refresh
token on every refresh — once used, the old refresh token is revoked. When the
same account is refreshed by more than one process, whoever refreshes first wins
and every other holder is left with a revoked token. In the field this pool ran
at **0/12 healthy**: 9 of 12 profiles held accounts that VibeProxy's
`cli-proxy-api` *also* refreshes on its own schedule, and two profile pairs
shared a single login. The hourly `claude_pool_verify.py` refresh side-effect
could not win a race it could not see. (Its own docstring predicted this:
"canNOT revive a revoked refresh token — duplicate accounts, same-org seats, or
the same account used concurrently.")

**The fix — consume VibeProxy's tokens instead of competing.** VibeProxy stays
alive because it is the **single owner** of each account's refresh token. So
aragora stops refreshing and instead copies VibeProxy's already-fresh access
token into the matching profile, written **without a usable refresh token**
(pure consumer). aragora can then never rotate VibeProxy's live token, and the
hourly `claude_pool_verify.py` is automatically safe — a profile with no refresh
token cannot rotate anything even when probed.

First, declare your account map in an **untracked local config** — the
email→profile mapping is PII and is deliberately not in the repo:

```bash
cp scripts/claude_profile_sync.json.example ~/.aragora/claude_profile_sync.json
chmod 600 ~/.aragora/claude_profile_sync.json
# then edit it: sync_target = {your-email: profile}, native_only = {profile: reason}
```

```bash
# Preview the plan (dry-run):
python3 scripts/sync_claude_profiles_from_vibeproxy.py

# ONE-TIME bootstrap: profiles that still hold a native (or dead) refresh token
# are protected by default, so convert them to VibeProxy-managed consumers once
# with --force. Run from the repo so --probe-after can find claude_profile.sh.
python3 scripts/sync_claude_profiles_from_vibeproxy.py --apply --force --probe-after

# Steady state (no --force): keeps the managed profiles fresh.
python3 scripts/sync_claude_profiles_from_vibeproxy.py --apply

# Make it durable: a launchd timer (deploys the script to ~/.aragora/bin, outside
# any git checkout so worktree TTL-cleanup and merges never touch it; seeds the
# config from the example if absent)
bash scripts/install_claude_profile_sync_launchd.sh
```

> **First run needs `--force`.** The daemon runs `--apply` without `--force` and
> refuses to overwrite any non-blank refresh token (it cannot tell a live native
> login from a revoked one offline). Until you bootstrap once with `--force`, the
> sync skips every native/dead profile and **exits non-zero** so the launchd log
> flags it rather than silently reporting success.

This revives every profile VibeProxy can source — one profile per VibeProxy
account. Requirements: VibeProxy running with the Claude accounts connected
(auth files at `~/.cli-proxy-api/claude-*.json`) and the local config filled in.
The sync backs up a **native** credential (`0600` `.bak`) before replacing it
and refuses to overwrite a profile holding a real refresh token without
`--force`. The timer interval must be **≤ VibeProxy's refresh lead** (it
refreshes ~10 min before the ~8h access-token expiry) so a sync always lands in
the window between the new token appearing and the old one lapsing; the default
is **5 min**. A wider interval would leave a profile on an expired, blank-refresh
token for up to `(interval − lead)` every ~8h.

**One profile per VibeProxy account (important).** VibeProxy authenticates by
**email** and holds exactly **one org per email**. Two profiles that are
*different orgs under one shared login* — e.g. a personal Max org and a team org
under the same address — cannot both be sourced from VibeProxy: syncing both
would silently collapse one subscription onto the other's org. The config's
`sync_target` is therefore a strict 1:1 email→profile map, and the same-email
sibling goes in `native_only`. Those distinct-org seats, plus any account
VibeProxy does not hold, stay on the interactive re-login path below. A profile
can be repointed at an unused VibeProxy account by editing `sync_target` — the
sync is the binding, no native login needed.

## Re-login runbook

OAuth login is **interactive** and must be done by you (it opens a browser per profile).

```bash
# See which profiles are actually usable right now
scripts/claude_profiles_bootstrap.sh verify --json

# Re-login only the profiles that are expired / not configured (example):
scripts/claude_profiles_bootstrap.sh login max-09 max-13

# Force re-login a profile that "status" claims is fine but verify says is expired:
scripts/claude_profiles_bootstrap.sh login --force max-04

# Refresh the snapshot the router trusts
scripts/claude_profiles_bootstrap.sh verify --json
```

After re-login, always re-run `verify --json` so the health snapshot reflects reality.

## Troubleshooting

- **Reviews blocked with `claude_pool_unauthenticated`** (or "No authenticated Claude Max
  profiles"): every profile is expired/unconfigured. Run `verify --json`, then `login` the
  failing profiles, then `verify --json` again.
- **`status` says logged in but reviews still fail:** the token is expired. Use
  `verify`/`verify --json`; re-login with `--force`.
- **All reviews hit one subscription:** confirm `ARAGORA_CLAUDE_REVIEW_ROTATE` is not
  disabled and that a fresh snapshot exists so unhealthy profiles are dropped.
- **Stale snapshot ignored:** snapshots older than `ARAGORA_CLAUDE_POOL_HEALTH_TTL`
  seconds fall back to `status`; re-run `verify --json`.

## Related

- `scripts/claude_profiles_bootstrap.sh`, `scripts/claude_profile.sh`
- `scripts/sync_claude_profiles_from_vibeproxy.py`, `scripts/install_claude_profile_sync_launchd.sh` (VibeProxy token sync)
- `scripts/claude_pool_verify.py` (hourly health probe)
- `docs/guides/VIBEPROXY.md` (the local transport whose fresh tokens the sync consumes)
- `aragora/swarm/review_routing.py` (routing, preflight, snapshot, rotation)
- `aragora/cli/commands/review_pr.py` (`review-pr`, `review-local`)
