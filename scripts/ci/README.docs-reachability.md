# Docs reachability checker

`scripts/ci/check_docs_reachability.py` reports which curated documentation pages a
reader can reach by following relative Markdown links from the repository's entry
pages, and which pages are orphans (unreachable).

It uses only the Python standard library, reads the git index and the working tree,
never modifies files and never uses the network. It is a standalone tool: no CI
workflow or hook runs it, so its exit code does not gate anything by itself.

## Running it

From the repository root:

```bash
# Summary line, one "orphan:" line per curated orphan, informational whole-tree count
python3 scripts/ci/check_docs_reachability.py --scope curated

# Machine-readable report (schema v1) on stdout
python3 scripts/ci/check_docs_reachability.py --scope curated --json

# Options and exit codes
python3 scripts/ci/check_docs_reachability.py --help
```

| Option | Meaning |
|---|---|
| `--scope curated` | Candidate set to report. `curated` is the only scope and the default. Any other value is a usage error (exit 2). |
| `--json` | Print the JSON report described below instead of the text summary. |
| `--root PATH` | Repository to inspect. Must be the git worktree top-level (`git rev-parse --show-toplevel`); a subdirectory is a tool error (exit 2), not an empty report. Defaults to the checkout that contains the script. |

## Seeds and traversal

The search starts from exactly two seeds: `README.md` and `docs/README.md`. It is a
breadth-first search over git-tracked Markdown (`*.md` in the index; untracked files
are ignored). From each page it follows:

- inline links such as `[text](guides/setup.md)`, including titled links such as
  `[text](../reference/api.md "API")` and angle-bracket targets such as `[text](<my page.md>)`;
- reference definitions such as `[label]: ./guides/setup.md`;
- paths relative to the linking page (`./`, `../`) and repository-root paths with a
  leading `/`. Fragments (`#section`) and queries are dropped and `%20`-style escapes
  are decoded;
- directory links: `reference/` or `reference` resolves to `reference/README.md`.

It ignores links inside fenced code blocks (backtick and tilde fences, including a fence
opened on a list-item line such as `` - ``` ``, ending with that item) and inline code
spans, images, external URLs (`https:`, `mailto:` and other schemes, `//host`), pure
in-page anchors (`#section`), footnote definitions, links that leave the repository and
targets that are not tracked Markdown files. Cycles are handled.

Traversal may pass through tracked pages that are not curated candidates, for example
`CONTRIBUTING.md` or `docs/deployment/*.md`; a curated page linked only from such a
page still counts as reachable. Pages under `docs/archive/` are never traversed, so a
page linked only from the archive is an orphan.

## Curated candidates

The curated scope gates these tracked Markdown files:

- `docs/*.md` (the docs root, including `docs/README.md`);
- everything under `docs/getting-started/`, `docs/guides/`, `docs/reference/`,
  `docs/architecture/`, `docs/operations/`, `docs/governance/` and `docs/strategy/`,
  at any depth.

`docs/archive/` and every other `docs/` subdirectory are outside the curated set.

## JSON report (schema v1)

| Field | Meaning |
|---|---|
| `schema_version` | Always `1`. |
| `scope` | Always `"curated"`. |
| `seeds` | `["README.md", "docs/README.md"]`. |
| `candidate_count` | Number of curated candidates; equals `reachable_count + orphan_count`. |
| `reachable_count`, `reachable` | Curated candidates reached from the seeds, as a sorted list of repo-relative paths. |
| `orphan_count`, `orphans` | Curated candidates not reached, as a sorted list of repo-relative paths. |
| `whole_tree_orphan_count` | Informational: tracked `docs/**/*.md` pages outside `docs/archive/` (curated or not) that were not reached. |

`reachable` and `orphans` never overlap and together list every curated candidate.
Running the checker twice on the same tree prints identical output.

`whole_tree_orphan_count` is reported for information only. It has no threshold and
does not affect the exit code.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | No curated orphans. |
| `1` | At least one curated orphan (listed in the output). |
| `2` | Usage error (for example an unknown `--scope`) or tool error (for example the root is not a git repository or not its top-level, or a tracked path is not valid UTF-8). |

## Current repository state

The checker reports the tree as it is. The repository can currently contain curated
orphans, in which case the checker lists them and exits 1. Linking or relocating those
pages is separate documentation work; the checker itself never edits indexes or pages.
