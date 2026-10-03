---
title: Type Checking Guide
description: Type Checking Guide
---

# Type Checking Guide

This document describes Aragora's approach to gradual type safety using mypy.

## Overview

Aragora uses mypy for static type checking with a **gradual adoption strategy**:

1. **Lenient defaults** - New code is checked but not required to have full type annotations
2. **Strict per-module overrides** - Core modules are held to stricter standards
3. **Legacy module exemptions** - Some older modules are explicitly exempted

## Quick Start

```bash
# Run type checking
make typecheck

# Or directly with mypy
mypy aragora/ --ignore-missing-imports

# Check a specific module
mypy aragora/debate/orchestrator.py --ignore-missing-imports

# Run with verbose output to see which modules are strict
mypy aragora/ --ignore-missing-imports --verbose
```

## Configuration

Type checking is configured in `pyproject.toml` under `[tool.mypy]`:

### Global Settings

```toml
[tool.mypy]
python_version = "3.11"
mypy_path = "typings"              # Custom type stubs directory
warn_return_any = false            # Don't warn about returning Any
warn_unused_configs = true         # Warn about unused mypy configs
warn_redundant_casts = true        # Warn about unnecessary casts
warn_unused_ignores = false        # Don't warn about unused # type: ignore
ignore_missing_imports = true      # Don't require stubs for all packages
check_untyped_defs = false         # Don't check bodies of untyped functions
disallow_untyped_defs = false      # Allow functions without type annotations
strict_optional = false            # Don't require explicit Optional
```

### Excluded Paths

```toml
exclude = [
    "tests/",
    "build/",
    "dist/",
    ".venv/",
    "node_modules/",
]
```

## Strictness Levels

### Level 1: Lenient (Default)

The default for most modules. Functions without type annotations are allowed and their bodies are not checked.

### Level 2: Moderate

For modules in transition. Untyped function bodies are checked but type annotations are not required:

```toml
[[tool.mypy.overrides]]
module = ["aragora.debate.orchestrator", "aragora.memory.consensus"]
disallow_untyped_defs = false
check_untyped_defs = true
```

### Level 3: Strict

For core modules. Full type annotations are required:

```toml
[[tool.mypy.overrides]]
module = [
    "aragora.core",
    "aragora.config.*",
    "aragora.types.*",
    "aragora.exceptions",
    # ... 400+ modules at strict level
]
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
```

## Current Status

As of January 2026, the following module categories are at **strict** level:

| Category | Modules | Status |
|----------|---------|--------|
| Core types | `aragora.core`, `aragora.types.*`, `aragora.exceptions` | Strict |
| Config | `aragora.config.*` | Strict |
| Storage | `aragora.storage.*` | Strict |
| Debate phases | `aragora.debate.phases.*` | Strict |
| Handlers | `aragora.server.handlers.*` | Strict |
| RBAC | `aragora.rbac.*` | Strict |
| Auth | `aragora.auth.*` | Strict |
| Control Plane | `aragora.control_plane.*` | Strict |
| RLM | `aragora.rlm.*` | Strict |
| Workflow | `aragora.workflow.*` | Strict |
| Connectors | `aragora.connectors.enterprise.*` | Strict |
| Plugins | `aragora.plugins.*` | Strict |

### Modules at Moderate Level

```toml
module = [
    "aragora.debate.orchestrator",
    "aragora.agents.api_agents.*",
    "aragora.memory.consensus",
    "aragora.bots.*",
]
```

### Legacy Exemptions

```toml
# Scripts are excluded
module = ["scripts.*"]
ignore_errors = true

# CLI agents use subprocess (hard to type)
module = ["aragora.agents.cli_agents"]
disallow_untyped_defs = false
check_untyped_defs = false
```

## Custom Type Stubs

Type stubs for third-party libraries without inline types are in `typings/`:

```
typings/
  sentence_transformers/__init__.pyi  # ML embedding library
  stripe/__init__.pyi                  # Payment processing
  supabase/__init__.pyi               # Database client
```

### Adding New Stubs

1. Create directory: `typings/<package_name>/`
2. Add `__init__.pyi` with type declarations
3. Stubs are automatically discovered via `mypy_path = "typings"`

Example stub structure:

```python
# typings/mypackage/__init__.pyi
from typing import Any, Optional

class Client:
    def __init__(self, api_key: str) -> None: ...
    def fetch(self, url: str) -> dict[str, Any]: ...
```

## Promoting Modules to Strict

To promote a module to strict type checking:

1. **Add annotations** to all public functions
2. **Run mypy** on the module to find issues:
   ```bash
   mypy aragora/path/to/module.py --strict --ignore-missing-imports
   ```
3. **Fix errors** iteratively
4. **Add to strict overrides** in `pyproject.toml`:
   ```toml
   [[tool.mypy.overrides]]
   module = ["aragora.path.to.module"]
   disallow_untyped_defs = true
   disallow_incomplete_defs = true
   check_untyped_defs = true
   ```

## Common Type Patterns

### Optional vs Union

```python
# Prefer Optional for nullable types
def get_user(id: str) -> Optional[User]: ...

# Use Union for multiple concrete types
def parse_input(data: Union[str, bytes]) -> dict: ...
```

### Generic Collections

```python
# Use built-in generics (Python 3.9+)
def process(items: list[str]) -> dict[str, int]: ...

# For complex types, use TypeVar
T = TypeVar("T")
def first(items: Sequence[T]) -> T | None: ...
```

### Async Functions

```python
async def fetch_data(url: str) -> dict[str, Any]: ...
# Return type is automatically Coroutine[Any, Any, dict[str, Any]]
```

### Callable Types

```python
from collections.abc import Callable

def with_retry(
    func: Callable[[str], Awaitable[T]],
    retries: int = 3,
) -> Callable[[str], Awaitable[T]]: ...
```

### Protocol Types

```python
from typing import Protocol

class Agent(Protocol):
    name: str
    async def generate(self, prompt: str) -> str: ...
```

## IDE Integration

### VS Code

Install the Pylance extension (built-in mypy-compatible checker):

```json
// .vscode/settings.json
{
    "python.analysis.typeCheckingMode": "basic",
    "python.analysis.diagnosticMode": "openFilesOnly"
}
```

### PyCharm

PyCharm has built-in type checking. Enable via:
- Settings > Editor > Inspections > Python > Type checker

## CI Integration

Type checking runs as part of the `make check` target:

```bash
make check  # Runs: lint, typecheck
```

CI fails on type errors in strict modules but allows warnings in lenient modules.

## Troubleshooting

### "Module has no attribute X"

Often means mypy can't find the import. Solutions:

1. Check if the package has stubs: `pip install types-<package>`
2. Add to `ignore_missing_imports` modules in pyproject.toml
3. Create a custom stub in `typings/`

### "Incompatible types"

Check that your annotation matches the actual usage:

```python
# Wrong: str is not Optional[str]
def get_name() -> str:
    return None  # Error!

# Correct
def get_name() -> Optional[str]:
    return None
```

### "Cannot find module"

Ensure the module is importable:

```bash
python -c "import aragora.path.to.module"
```

### Ignoring Specific Errors

Use inline comments sparingly:

```python
result = some_untyped_function()  # type: ignore[no-untyped-call]
```

For whole files, add to pyproject.toml overrides instead.

## Further Reading

- [mypy documentation](https://mypy.readthedocs.io/)
- [Python typing documentation](https://docs.python.org/3/library/typing.html)
- [PEP 484 - Type Hints](https://peps.python.org/pep-0484/)
- [PEP 585 - Type Hinting Generics](https://peps.python.org/pep-0585/)
