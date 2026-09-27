---
title: Repo-root allowlist
description: Repo-root allowlist
---

# Repo-root allowlist

The repository root must stay curated: only the files listed below may be tracked
directly at the root of `synaptent/aragora`. Everything else belongs in a
subdirectory. The list is enforced by `scripts/ci/check_root_allowlist.py`, which
exits non-zero (naming the offender) when a tracked root file is not listed here.

This guard was introduced with the P1 repo-root hygiene cleanup (HEALTH-1 #8258),
which untracked stale clutter (marketing screenshots, a stale generated
`openapi.json` whose canonical copy lives at `docs/api/openapi.json`, an
inbox-triage dump, and two stray root test files). A follow-on legibility pass
(m7-root-clutter-relocation) relocated the remaining tracked research/audit
docs and the brand PNGs into `docs/archive/` via `git mv`. No redirect stubs
were left at the root for the archived markdown files because each had zero
referrers outside this allowlist (the root `NEXT_STEPS.md` was a redundant
legacy pointer; `docs/NEXT_STEPS.md` and `docs/status/NEXT_STEPS.md` already
serve as compatibility pointers to the canonical
`docs/status/NEXT_STEPS_CANONICAL.md`). No binary assets remain tracked at the
repo root.

The relocation audit also checked the content being moved, not only inbound
references. The three archived Markdown files contain no Markdown links, so
changing their directory depth cannot alter a relative target. A repository-wide
tracked-file scan found no product or documentation references to either PNG;
the remaining basename matches are this inventory and synthetic allowlist tests.
`scripts/validate_doc_links.py` and `scripts/check_docs_consistency.py` both pass
after the moves.

## Root clutter inventory (tracked vs gitignored)

The root is cleaned by distinguishing two categories:

**Gitignored local-only artifacts (NOT repo content -- never tracked, never `git mv`ed, never deleted):**

| Artifact | Gitignore rule | Notes |
|----------|----------------|-------|
| `FireShot*.png` / `Screenshot*.png` | `.gitignore` (~L178) | Dev/testing screenshots. Local-only; not in git history. |
| `Aragora Idea-to-Execution Strategy.docx` | `.gitignore` (~L235) | Sales/strategy collateral kept out of the code repo. Local-only. |

These files live only on a contributor's local disk. They are never tracked, so
there is nothing to `git mv`; the mission never deletes or moves a user's local
files. They are listed here only so the allowlist is a *complete* picture of
what can appear at the root.

**Tracked clutter relocated via `git mv` into `docs/archive/` (no stub -- zero referrers):**

| Former root path | New location | Stub at root? |
|------------------|--------------|---------------|
| `Idea-to-Execution-Pipeline-Research.md` | `docs/archive/2026-03-18-Idea-to-Execution-Pipeline-Research.md` | no (zero referrers; archived) |
| `SECURITY_AUDIT_INPUT_VALIDATION.md` | `docs/archive/2026-06-04-SECURITY_AUDIT_INPUT_VALIDATION.md` | no (zero referrers; archived) |
| `NEXT_STEPS.md` | `docs/archive/2026-02-11-NEXT_STEPS.md` | no (redundant; `docs/status/NEXT_STEPS_CANONICAL.md` is canonical) |

**Tracked binary assets relocated via `git mv` (no stub -- binary, unreferenced):**

| Former root path | New location |
|------------------|--------------|
| `aragora_logo.png` | `docs/archive/aragora_logo.png` |
| `favicon.png` | `docs/archive/favicon.png` |

The brand PNGs had zero product or documentation references in tracked files
(Docusaurus uses its own `img/logo.svg` / `img/favicon.ico`), so the move leaves
no dangling image links. Basename matches in `tests/ci/test_check_root_allowlist.py`
are synthetic fixture inputs, not consumers of either asset.

## How to update

When you legitimately need a new root-level file, add its exact name between the
markers below (keep the list sorted). To remove clutter instead, run
`git rm --cached <file>` and add a matching pattern to `.gitignore`. Regenerate
the candidate set with `git ls-files | grep -v /`.

## Allowed root files

<!-- ROOT_ALLOWLIST_BEGIN -->
```text
.dockerignore
.env.example
.env.production.example
.gitattributes
.gitguardian.yaml
.gitignore
.gitleaks.toml
.importlinter
.mypy-baseline
.pre-commit-config.yaml
.trivy.yaml
.trivyignore
AGENTS.md
CHANGELOG.md
CLAUDE.md
CODE_OF_CONDUCT.md
CONTRIBUTING.md
DEVELOPMENT.md
Dockerfile
INSTALL.md
LICENSE
MANIFEST.in
Makefile
README.md
ROADMAP.md
SECURITY.md
THIRD_PARTY_LICENSES.md
TROUBLESHOOTING.md
action.yml
alembic.ini
docker-compose.dev.yml
docker-compose.production.yml
docker-compose.quickstart.yml
docker-compose.simple.yml
docker-compose.sme.yml
docker-compose.yml
github-app-manifest.json
k8s
pyproject.toml
requirements.txt
run_staging.py
sitecustomize.py
trivy.yaml
uv.lock
```
<!-- ROOT_ALLOWLIST_END -->
