#!/usr/bin/env python3
"""Replace actions/setup-python@v5 with .github/actions/setup-python-safe.

Handles varied `with:` blocks (python-version, cache, cache-dependency-path).
Preserves all other step attributes and indentation.
"""

import re
import sys
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# Files that already have their own fallback mechanism
SKIP_FILES = {
    "deploy-secure.yml",  # already has inline fallback
    "aragora-review-gate.yml",  # already has inline fallback
    "sdk-parity.yml",  # has its own "Ensure python toolchain" step
}


def process_file(path: Path, dry_run: bool = False) -> bool:
    """Replace setup-python@v5 with composite action. Returns True if modified."""
    content = path.read_text()

    if "actions/setup-python@v" not in content:
        return False
    if "Fallback to system Python" in content:
        return False

    lines = content.split("\n")
    new_lines = []
    i = 0
    modified = False

    while i < len(lines):
        line = lines[i]

        if "actions/setup-python@v" not in line:
            new_lines.append(line)
            i += 1
            continue

        # Detect indentation.  Two forms:
        #   "        uses: actions/setup-python@v5"   (bare uses:, indent = leading spaces)
        #   "      - uses: actions/setup-python@v5"   (list item, indent = spaces before -)
        m_bare = re.match(r"^(\s+)uses:\s+actions/setup-python@v\d+", line)
        m_list = re.match(r"^(\s+)-\s+uses:\s+actions/setup-python@v\d+", line)

        if m_list:
            # `- uses:` form — indent is at the `- ` level
            indent = m_list.group(1) + "  "  # content indent (after `- `)
        elif m_bare:
            indent = m_bare.group(1)
        else:
            new_lines.append(line)
            i += 1
            continue

        if True:  # matched
            # Check if there's an `id:` right before on same step
            # (some files have `id:` on previous line)
            has_existing_id = False
            if new_lines and re.match(r"^\s+id:\s+", new_lines[-1]):
                has_existing_id = True

            # Check for continue-on-error on next line
            has_continue = False
            peek = i + 1
            if peek < len(lines) and "continue-on-error:" in lines[peek]:
                has_continue = True

            # Collect `with:` block
            python_version = "3.11"
            cache_val = ""
            cache_dep_path = ""

            # Skip past `uses:` line and optional `continue-on-error:`
            j = i + 1
            if j < len(lines) and "continue-on-error:" in lines[j]:
                j += 1

            # Check for `with:` block
            if j < len(lines) and re.match(rf"^{re.escape(indent)}\s*with:", lines[j]):
                j += 1  # skip `with:` line
                # Read with: contents
                while j < len(lines):
                    wline = lines[j]
                    wstripped = wline.strip()
                    if not wstripped or (
                        not wline.startswith(indent + "  ") and wstripped.startswith("-")
                    ):
                        break
                    # Check indentation — must be deeper than `with:`
                    if len(wline) - len(wline.lstrip()) <= len(indent):
                        break

                    if "python-version:" in wline:
                        m = re.search(r'python-version:\s*["\']?([^"\'#\s]+)', wline)
                        if m:
                            python_version = m.group(1)
                    elif "cache:" in wline and "cache-dependency-path" not in wline:
                        m = re.search(r"cache:\s*['\"]?(\S+)['\"]?", wline)
                        if m:
                            cache_val = m.group(1).strip("'\"")
                    elif "cache-dependency-path:" in wline:
                        m = re.search(r"cache-dependency-path:\s*(.+)", wline)
                        if m:
                            cache_dep_path = m.group(1).strip().strip("'\"")
                    j += 1

            # Remove the existing id line if present
            if has_existing_id:
                new_lines.pop()

            # Build replacement — preserve `- name:` / `- uses:` list form
            if m_list:
                # Remove the `- name: Set up Python ...` line added earlier if present
                if new_lines and re.match(r"^\s+- name:\s+Set up Python", new_lines[-1]):
                    new_lines.pop()
                step_prefix = m_list.group(1) + "- "
                new_lines.append(f"{step_prefix}name: Set up Python")
                new_lines.append(f"{indent}uses: ./.github/actions/setup-python-safe")
            else:
                # Remove the `- name: Set up Python ...` line that was on a previous line
                if new_lines and re.match(r"^\s+- name:\s+Set up Python", new_lines[-1]):
                    name_line = new_lines.pop()
                    # Re-add with original prefix
                    name_prefix = re.match(r"^(\s+-\s+)", name_line)
                    if name_prefix:
                        new_lines.append(f"{name_prefix.group(1)}name: Set up Python")
                new_lines.append(f"{indent}uses: ./.github/actions/setup-python-safe")

            # Build with: block
            with_lines = [f"{indent}with:"]
            with_lines.append(f'{indent}  python-version: "{python_version}"')
            if cache_val:
                with_lines.append(f"{indent}  cache: '{cache_val}'")
            if cache_dep_path:
                with_lines.append(f"{indent}  cache-dependency-path: {cache_dep_path}")

            new_lines.extend(with_lines)

            i = j
            modified = True
        else:
            new_lines.append(line)
            i += 1

    if modified and not dry_run:
        path.write_text("\n".join(new_lines))

    return modified


def main():
    dry_run = "--dry-run" in sys.argv

    target_files = []
    for yml in sorted(WORKFLOWS_DIR.glob("*.yml")):
        if yml.name in SKIP_FILES:
            continue
        content = yml.read_text()
        if "actions/setup-python@v" in content and "runs-on: aragora" in content:
            if "Fallback to system Python" not in content:
                target_files.append(yml)

    # Also check templates
    templates_dir = WORKFLOWS_DIR / "templates"
    if templates_dir.exists():
        for yml in sorted(templates_dir.glob("*.yml")):
            if yml.name in SKIP_FILES:
                continue
            content = yml.read_text()
            if "actions/setup-python@v" in content:
                if "Fallback to system Python" not in content:
                    target_files.append(yml)

    print(f"{'[DRY RUN] ' if dry_run else ''}Found {len(target_files)} files to process")

    modified = 0
    errors = 0
    for f in target_files:
        rel = f.relative_to(WORKFLOWS_DIR.parent.parent.parent)
        try:
            if process_file(f, dry_run=dry_run):
                print(f"  {'Would modify' if dry_run else 'Modified'}: {rel}")
                modified += 1
            else:
                print(f"  Skipped: {rel}")
        except Exception as e:
            print(f"  ERROR: {rel}: {e}")
            errors += 1

    print(
        f"\nDone: {modified}/{len(target_files)} files {'would be ' if dry_run else ''}modified, {errors} errors"
    )


if __name__ == "__main__":
    main()
