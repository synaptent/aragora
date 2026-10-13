#!/usr/bin/env python3
"""Fix f-string logging calls to use %-formatting.

Converts:
    logger.warning(f"Failed to do {thing}: {e}")
To:
    logger.warning("Failed to do %s: %s", thing, e)

This is a security improvement (prevents exception detail leakage to log
aggregators via lazy formatting) and a performance improvement (avoids
string interpolation when log level is suppressed).

Only handles simple cases with {var} or {expr} interpolations.
Skips complex format specs like {var:.2f} or {var!r}.
"""

import ast
import re
import sys
from pathlib import Path


def fix_fstring_logging_in_file(filepath: Path, dry_run: bool = False) -> int:
    """Fix f-string logging calls in a single file. Returns count of fixes."""
    source = filepath.read_text()
    lines = source.splitlines(keepends=True)
    fixes = 0

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0

    # Collect all logging calls with f-strings
    replacements = []  # (line_start, line_end, old_text, new_text)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Check if it's a logger.X() call
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("debug", "info", "warning", "error", "critical", "exception"):
            continue
        # Check if the receiver looks like a logger
        func_src = ast.get_source_segment(source, node.func.value)
        if func_src and not (
            func_src == "logger" or func_src.endswith("logger") or func_src == "log"
        ):
            continue

        if not node.args:
            continue

        first_arg = node.args[0]
        if not isinstance(first_arg, ast.JoinedStr):
            continue

        # It's an f-string! Extract the parts.
        fmt_parts = []
        extra_args = []
        skip = False

        for value in first_arg.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                # Literal string part - escape any existing % signs
                fmt_parts.append(value.value.replace("%", "%%"))
            elif isinstance(value, ast.FormattedValue):
                # Check for format specs or conversions we can't handle simply
                if value.format_spec is not None:
                    skip = True
                    break
                # Get the expression source
                expr_src = ast.get_source_segment(source, value.value)
                if expr_src is None:
                    skip = True
                    break
                # Handle conversion (!r, !s, !a)
                if value.conversion == ord("r"):
                    fmt_parts.append("%r")
                elif value.conversion == ord("a"):
                    fmt_parts.append("%r")  # close enough
                else:
                    fmt_parts.append("%s")
                extra_args.append(expr_src)
            else:
                skip = True
                break

        if skip or not extra_args:
            continue

        # Build the new format string
        new_fmt = "".join(fmt_parts)
        # Escape quotes in the format string to match the original quoting
        # Get the original line to determine quote style
        orig_line = ast.get_source_segment(source, first_arg)
        if orig_line is None:
            continue

        # Build the replacement: "fmt_string", arg1, arg2, ...
        # Determine quote style from original f-string
        # We'll use double quotes by default
        if '"' in new_fmt and "'" not in new_fmt:
            quote = "'"
        else:
            quote = '"'
            new_fmt = new_fmt.replace('"', '\\"') if '"' in new_fmt else new_fmt

        new_first_arg = f"{quote}{new_fmt}{quote}"
        args_str = ", ".join(extra_args)
        new_call_args = f"{new_first_arg}, {args_str}"

        # Now we need to replace just the f-string argument portion
        # Store the replacement info
        replacements.append((first_arg, new_call_args, orig_line))
        fixes += 1

    if not replacements or dry_run:
        return fixes

    # Apply replacements in reverse order to preserve line numbers
    # Sort by position (line, col) in reverse
    replacements.sort(key=lambda r: (r[0].lineno, r[0].col_offset), reverse=True)

    for fstring_node, new_args, orig_text in replacements:
        # Replace the f-string in the source
        # We need to find the exact f-string text and replace it
        source = (
            source[: _offset(source, fstring_node)]
            + new_args
            + source[_end_offset(source, fstring_node) :]
        )

    filepath.write_text(source)
    return fixes


def _offset(source: str, node: ast.expr) -> int:
    """Get byte offset of AST node in source."""
    lines = source.split("\n")
    offset = sum(len(line) + 1 for line in lines[: node.lineno - 1])
    return offset + node.col_offset


def _end_offset(source: str, node: ast.expr) -> int:
    """Get end byte offset of AST node in source."""
    if node.end_lineno is None or node.end_col_offset is None:
        raise ValueError(f"AST node at line {node.lineno} has no end position")
    lines = source.split("\n")
    offset = sum(len(line) + 1 for line in lines[: node.end_lineno - 1])
    return offset + node.end_col_offset


def main():
    dry_run = "--dry-run" in sys.argv
    target = (
        sys.argv[1]
        if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
        else "aragora/server/handlers"
    )
    target_path = Path(target)

    if target_path.is_file():
        files = [target_path]
    else:
        files = sorted(target_path.rglob("*.py"))

    total_fixes = 0
    for f in files:
        count = fix_fstring_logging_in_file(f, dry_run=dry_run)
        if count > 0:
            total_fixes += count
            action = "Would fix" if dry_run else "Fixed"
            print(f"  {action} {count} f-string logging calls in {f}")

    print(
        f"\nTotal: {total_fixes} f-string logging calls {'would be fixed' if dry_run else 'fixed'}"
    )


if __name__ == "__main__":
    main()
