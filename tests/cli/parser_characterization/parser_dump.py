"""Write the ``aragora`` CLI parser as one JSON document, for test_parser_characterization.py.

Usage: ``python parser_dump.py <out.json>``. The test runs it in a fresh interpreter with a
pinned environment, because ``aragora.cli.parser`` and ``aragora.config`` read several
defaults from the environment once, at import. Keys follow section 6 of
``docs/architecture/P5_CLI_PARSER_SPLIT_DESIGN.md``: ``surface`` (C-1), ``tree`` (C-2),
``help`` (C-3), ``imported`` and ``built`` (C-4).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _plain(value: Any) -> Any:
    """JSON form of a default, choice, const or ``set_defaults`` value; callables by name."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, argparse.ArgumentParser):
        return f"<parser {value.prog}>"
    if callable(value):
        return f"<callable {getattr(value, '__name__', type(value).__name__)}>"
    return re.sub(r" at 0x[0-9a-fA-F]+", "", f"<{type(value).__name__} {value!r}>")


def _key(action: argparse.Action) -> str:
    return action.option_strings[0] if action.option_strings else action.dest


def _commands(action: argparse._SubParsersAction) -> list[dict[str, Any]]:
    """Subcommands in registration order; an alias joins the entry of its parser."""
    helps = {pseudo.dest: pseudo.help for pseudo in action._choices_actions}
    entries: dict[int, dict[str, Any]] = {}
    for name, sub in action.choices.items():
        if id(sub) in entries:
            entries[id(sub)]["aliases"].append(name)
            continue
        entries[id(sub)] = {
            "name": name,
            "aliases": [],
            "listed": name in helps,
            "help": helps.get(name),
            "parser": _parser(sub),
        }
    return list(entries.values())


def _action(action: argparse.Action) -> dict[str, Any]:
    # _VersionAction.version is the installed package version, not parser shape.
    record: dict[str, Any] = {
        "kind": type(action).__name__,
        "option_strings": list(action.option_strings),
        "dest": action.dest,
        "default": _plain(action.default),
        "type": None if action.type is None else getattr(action.type, "__name__", "?"),
        "nargs": action.nargs,
        "const": _plain(action.const),
        "required": action.required,
        "help": action.help,
        "metavar": _plain(action.metavar),
    }
    if isinstance(action, argparse._SubParsersAction):
        record["commands"] = _commands(action)
    else:
        record["choices"] = _plain(action.choices)
        if not action.option_strings:
            # argparse derives it from nargs for positionals, and 3.13 changed the rule for "*".
            del record["required"]
    return {key: value for key, value in record.items() if value is not None}


def _parser(parser: argparse.ArgumentParser) -> dict[str, Any]:
    record = {
        "class": type(parser).__name__,
        "prog": parser.prog,
        "usage": parser.usage,
        "description": parser.description,
        "epilog": parser.epilog,
        "formatter": getattr(parser.formatter_class, "__name__", "?"),
        "defaults": {key: _plain(value) for key, value in parser._defaults.items()},
        "groups": [
            [group.title, group.description, [_key(a) for a in group._group_actions]]
            for group in parser._action_groups
        ],
        "exclusive": [
            [group.required, [_key(a) for a in group._group_actions]]
            for group in parser._mutually_exclusive_groups
        ],
        "actions": [_action(action) for action in parser._actions],
    }
    return {key: value for key, value in record.items() if value is not None}


def _scrubber(data_dir: str) -> Callable[[Any], Any]:
    """Replace the pinned data directory, which ``backup --database`` help embeds as a path."""
    prefixes = sorted({data_dir, str(Path(data_dir).resolve())}, key=len, reverse=True)

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, str):
            for prefix in prefixes:
                value = value.replace(prefix + os.sep, "<data-dir>/").replace(prefix, "<data-dir>")
        return value

    return scrub


def _aragora_modules() -> list[str]:
    return sorted(name for name in sys.modules if name.split(".")[0] == "aragora")


def main(out: str) -> None:
    sys.argv[:1] = ["aragora"]
    import aragora.cli.parser as facade

    imported = _aragora_modules()
    surface = sorted(
        name
        for name, value in vars(facade).items()
        if not name.startswith("__") and not isinstance(value, types.ModuleType)
    )
    root = facade.build_parser()
    built = _aragora_modules()
    (top,) = [a for a in root._actions if isinstance(a, argparse._SubParsersAction)]
    tree = {"(root)": _parser(root)}
    help_text = {"(root)": root.format_help()}
    for record in tree["(root)"]["actions"]:
        for entry in record.get("commands", ()):
            tree[entry["name"]] = entry.pop("parser")
            help_text[entry["name"]] = top.choices[entry["name"]].format_help()
    scrub = _scrubber(os.environ["ARAGORA_DATA_DIR"])
    document = {
        "surface": surface,
        "imported": imported,
        "built": built,
        "tree": scrub(tree),
        "help": scrub(help_text),
    }
    Path(out).write_text(json.dumps(document, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
