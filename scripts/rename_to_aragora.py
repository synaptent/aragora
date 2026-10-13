#!/usr/bin/env python3
"""
Rename aragora -> aragora

This script performs a complete rename of the project:
1. Renames the aragora/ directory to aragora/
2. Updates all imports and references in Python files
3. Updates pyproject.toml, README, and other config files
4. Cleans up egg-info

Run from the project root:
    python scripts/rename_to_aragora.py [--dry-run]
"""

import argparse
import os
import re
import shutil
from pathlib import Path


def find_files(root: Path, extensions: list[str]) -> list[Path]:
    """Find all files with given extensions."""
    files: list[Path] = []
    for ext in extensions:
        files.extend(root.rglob(f"*{ext}"))
    return [f for f in files if ".git" not in str(f) and "node_modules" not in str(f)]


def replace_in_file(filepath: Path, old: str, new: str, dry_run: bool = False) -> int:
    """Replace all occurrences of old with new in a file. Returns count."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return 0

    count = content.count(old)
    if count > 0:
        if dry_run:
            print(f"  Would replace {count}x in {filepath}")
        else:
            new_content = content.replace(old, new)
            filepath.write_text(new_content, encoding="utf-8")
            print(f"  Replaced {count}x in {filepath}")
    return count


def main():
    parser = argparse.ArgumentParser(description="Rename aragora to aragora")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    os.chdir(root)

    print(f"Project root: {root}")
    print(f"Dry run: {args.dry_run}")
    print()

    # === Step 1: Update file contents ===
    print("=" * 60)
    print("Step 1: Updating file contents")
    print("=" * 60)

    extensions = [".py", ".md", ".toml", ".yaml", ".yml", ".json", ".html", ".txt", ".rst"]
    files = find_files(root, extensions)

    total_replacements = 0

    # Order matters: replace longer strings first to avoid partial matches
    replacements = [
        ("aragora.ai", "aragora.ai"),
        ("from aragora", "from aragora"),
        ("import aragora", "import aragora"),
        ("aragora.", "aragora."),
        ('"aragora"', '"aragora"'),
        ("'aragora'", "'aragora'"),
        ("aragora/", "aragora/"),
        ("aragora:", "aragora:"),
        ("aragora-", "aragora-"),
        ("aragora_", "aragora_"),
        # Be careful with standalone word (use word boundaries)
    ]

    for filepath in files:
        for old, new in replacements:
            total_replacements += replace_in_file(filepath, old, new, args.dry_run)

    # Handle standalone "aragora" (word boundary)
    for filepath in files:
        try:
            content = filepath.read_text(encoding="utf-8")
            # Use regex for word boundaries
            new_content, count = re.subn(r"\baagora\b", "aragora", content)
            if count > 0:
                if args.dry_run:
                    print(f"  Would replace {count}x standalone 'aragora' in {filepath}")
                else:
                    filepath.write_text(new_content, encoding="utf-8")
                    print(f"  Replaced {count}x standalone 'aragora' in {filepath}")
                total_replacements += count
        except (UnicodeDecodeError, PermissionError):
            pass

    print(f"\nTotal replacements: {total_replacements}")

    # === Step 2: Rename directory ===
    print()
    print("=" * 60)
    print("Step 2: Renaming aragora/ directory to aragora/")
    print("=" * 60)

    old_dir = root / "aragora"
    new_dir = root / "aragora"

    if old_dir.exists():
        if args.dry_run:
            print(f"  Would rename {old_dir} -> {new_dir}")
        else:
            if new_dir.exists():
                print(f"  ERROR: {new_dir} already exists!")
                return 1
            shutil.move(str(old_dir), str(new_dir))
            print(f"  Renamed {old_dir} -> {new_dir}")
    else:
        print(f"  {old_dir} not found (already renamed?)")

    # === Step 3: Clean up egg-info ===
    print()
    print("=" * 60)
    print("Step 3: Cleaning up old egg-info")
    print("=" * 60)

    old_egg = root / "aragora.egg-info"
    if old_egg.exists():
        if args.dry_run:
            print(f"  Would remove {old_egg}")
        else:
            shutil.rmtree(old_egg)
            print(f"  Removed {old_egg}")

    # === Step 4: Rename project directory (optional) ===
    print()
    print("=" * 60)
    print("Step 4: Manual steps required")
    print("=" * 60)
    print(
        """
After running this script, you should:

1. Rename the project directory:
   mv /path/to/your-project /path/to/aragora

2. Update git remote (if applicable):
   git remote set-url origin git@github.com:yourusername/aragora.git

3. Reinstall the package:
   pip install -e .

4. Update any CI/CD configurations

5. Register on PyPI/npm when ready:
   - pypi: pip install build twine && python -m build && twine upload dist/*
   - npm: npm publish

6. Update DNS for aragora.ai
"""
    )

    if args.dry_run:
        print("\n*** DRY RUN COMPLETE - no changes made ***")
    else:
        print("\n*** RENAME COMPLETE ***")
        print("Run 'git diff' to review changes")

    return 0


if __name__ == "__main__":
    exit(main())
