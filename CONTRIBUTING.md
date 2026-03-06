# Contributing to Aragora

Thank you for your interest in contributing to Aragora! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.10+
- Node.js 18+ (for frontend development)
- Docker (optional, for containerized development)

### Quick Start

```bash
# Clone the repository
git clone https://github.com/aragora-ai/aragora.git
cd aragora

# Install development dependencies
make dev

# Run tests to verify setup
make test-fast

# Start the development server
make serve
```

### Using VS Code Dev Container

1. Install the "Dev Containers" extension in VS Code
2. Open the project folder
3. Click "Reopen in Container" when prompted
4. Wait for the container to build and dependencies to install

## Development Workflow

### Running Tests

```bash
# Baseline command (matches CI deterministic gate)
python -m pip install -e ".[dev,research,test]"
python scripts/run_test_baseline.py

# Run all tests
make test

# Run fast tests only (excludes slow, e2e, load tests)
make test-fast

# Run tests with coverage
make test-cov

# Run specific test file
pytest tests/debate/test_orchestrator.py -v
```

### Code Quality

```bash
# Run linter
make lint

# Format code
make format

# Type checking
make typecheck

# Run all checks
make check
```

### Connector Registry Updates

If you add or modify connectors (including email sync services), regenerate the
connector registry artifacts:

```bash
python scripts/update_connector_registry.py
```

This updates:
- `docs/connectors/CONNECTOR_REGISTRY.json`
- `docs/connectors/CONNECTOR_CATALOG.md`

If you touch docs or the catalog, also resync the docs site:

```bash
node docs-site/scripts/sync-docs.js
```

### Working Tree Hygiene

To reduce noisy diffs and keep release preparation deterministic:

- Keep runtime artifacts out of commits (`.nomic/`, `.tmp/`, `artifacts/`, `exports/` are gitignored).
- Treat nested `*/CLAUDE.md` files as generated context unless intentionally maintained.
- Before opening a PR, verify the tree only includes intentional changes:

```bash
git status -sb
```

- If you ran long local workflows/tests, clean local scratch artifacts before commit:

```bash
python scripts/cleanup_runtime_artifacts.py --apply
```

### Development Server

```bash
# Start API server
make serve

# Interactive debate REPL
make repl

# System health check
make doctor
```

## Code Style

### Python

- Follow PEP 8 with a line length of 88 characters
- Use type hints for all function signatures
- Use `ruff` for linting and formatting
- Use `mypy` for type checking

### Commit Messages

Follow conventional commits format:

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

Examples:
```
feat(marketplace): add template rating system
fix(debate): handle timeout in consensus phase
docs(api): update authentication guide
```

### Pull Request Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Make your changes
4. Run tests and checks: `make check && make test`
5. Commit with a descriptive message
6. Push to your fork: `git push origin feat/my-feature`
7. Open a Pull Request

### Branch Discipline

To keep `main` stable and reduce multi-agent merge churn:

1. Do not commit directly to `main`; use short-lived feature branches and merge via PR.
2. Keep one active coding agent per worktree; create additional worktrees for parallel efforts.
3. Before opening a PR, run:

```bash
git status -sb
git worktree list --porcelain
```

4. Keep generated/runtime artifacts out of commits (`.nomic/`, `.tmp/`, `artifacts/`).
5. Emergency direct pushes to `main` are discouraged; if unavoidable, annotate the commit message with `[allow-direct-main]` and follow up with a PR-level postmortem.

Helper commands for PR-only flow:

```bash
# Create and switch to a feature branch from origin/main
scripts/start_feature_branch.sh feat my-change
# or
make branch-start TYPE=feat SLUG=my-change

# Push current branch and open/update PR via GitHub CLI
scripts/open_pr.sh --draft
# or
make pr-open ARGS="--draft"
```

## Architecture Overview

Aragora is a **control plane for multi-agent robust decisionmaking**. Here's how the key systems fit together:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              User Request                                │
│                    (CLI, HTTP API, WebSocket, Chat)                      │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Server Layer (unified_server.py)                 │
│  • 3,000+ API operations  • WebSocket streaming  • Handler registry       │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
             ┌──────────┐   ┌──────────┐   ┌──────────┐
             │  Arena   │   │ Knowledge│   │ Control  │
             │ (Debate) │   │  Mound   │   │  Plane   │
             └────┬─────┘   └────┬─────┘   └────┬─────┘
                  │              │              │
    ┌─────────────┼─────────────┐│              │
    ▼             ▼             ▼▼              ▼
┌───────┐   ┌─────────┐   ┌──────────┐   ┌──────────┐
│Agents │   │ Memory  │   │ Evidence │   │  RBAC    │
│(43)   │   │Continuum│   │ & Pulse  │   │ & Audit  │
└───────┘   └─────────┘   └──────────┘   └──────────┘
```

### Core Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **Arena** | `aragora/debate/orchestrator.py` | Multi-agent debate orchestration with phases, consensus, and convergence |
| **Agents** | `aragora/agents/` | 43 agent types across 10+ providers (Claude, GPT, Gemini, Mistral, etc.) |
| **Memory** | `aragora/memory/continuum/core.py` | 4-tier memory system (fast/medium/slow/glacial) |
| **Knowledge Mound** | `aragora/knowledge/mound/` | Organizational knowledge with semantic search |
| **Server** | `aragora/server/` | HTTP/WebSocket API with 700+ handlers |
| **Control Plane** | `aragora/control_plane/` | Agent registry, scheduling, policy governance |

### Key Patterns

- **Protocol-based composition**: Features like calibration, rhetorical analysis, and trickster detection are enabled via `DebateProtocol` flags
- **Circuit breaker resilience**: All external calls use `aragora/resilience.py` for fault tolerance
- **Adapter pattern**: Knowledge Mound uses 41 adapters to integrate with subsystems
- **Event-driven streaming**: WebSocket events for real-time debate updates

## Project Structure

```
aragora/
├── aragora/           # Main package
│   ├── agents/        # Agent implementations (API + CLI)
│   ├── debate/        # Debate orchestration (Arena, phases, consensus)
│   ├── memory/        # Memory systems (Continuum, 4-tier)
│   ├── knowledge/     # Knowledge Mound with 41 adapters
│   ├── server/        # HTTP/WebSocket API (3,000+ operations)
│   ├── control_plane/ # Enterprise orchestration
│   ├── connectors/    # 130+ external integrations
│   ├── cli/           # CLI commands
│   └── rbac/          # Role-based access control
├── tests/             # 50,000+ tests across 1,600+ files
├── docs/              # Documentation (212 files)
└── sdk/typescript/    # TypeScript SDK
```

## Package Naming

### Python Packages

| Package | Purpose | Install | Import |
|---------|---------|---------|--------|
| `aragora` | Full control plane (server + CLI + framework internals) | `pip install aragora` | `from aragora import Arena` |
| `aragora-sdk` | Blessed Python SDK client (remote API; sync + async + streaming) | `pip install aragora-sdk` | `from aragora_sdk import AragoraClient` |
| `aragora-client` | Legacy async-only SDK (deprecated) | `pip install aragora-client` | `from aragora_client import AragoraClient` |

```python
# Blessed Python SDK client
from aragora_sdk import AragoraClient

# Legacy SDK (deprecated)
from aragora_client import AragoraClient as AragoraAsyncClient
```

### TypeScript Packages

Two npm packages exist, but `@aragora/sdk` is the official TypeScript SDK:

| Package | Purpose | Install |
|---------|---------|---------|
| `@aragora/sdk` | Official SDK (recommended) - workflows, explainability, marketplace | `npm install @aragora/sdk` |
| `@aragora/client` | **Deprecated** legacy client - `/api/v1` compatibility | `npm install @aragora/client` |

```typescript
// For application developers
import { createClient } from '@aragora/sdk';

// Legacy client (deprecated)
import { AragoraClient } from '@aragora/client';
```

See [aragora-js/README.md](aragora-js/README.md) and [sdk/typescript/README.md](sdk/typescript/README.md) for detailed feature comparison.

### Version Synchronization

All packages maintain version parity. The following must stay in sync:

| File | Version Location |
|------|------------------|
| `pyproject.toml` | `project.version` |
| `aragora/__version__.py` | `__version__` |
| `sdk/typescript/package.json` | `version` |
| `aragora-js/package.json` | `version` |
| `aragora/live/package.json` | `version` |

CI automatically validates version parity on every build. To check locally:

```bash
# Verify all versions match
python -c "
import json, tomllib
py = tomllib.load(open('pyproject.toml', 'rb'))['project']['version']
sdk = json.load(open('sdk/typescript/package.json'))['version']
client = json.load(open('aragora-js/package.json'))['version']
print(f'Python: {py}, SDK: {sdk}, Client: {client}')
assert py == sdk == client, 'Version mismatch!'
"
```

> **Note**: The TypeScript packages (`@aragora/sdk` and `@aragora/client`) will be consolidated in v3.0.0. See [docs/SDK_CONSOLIDATION.md](docs/SDK_CONSOLIDATION.md) for the roadmap.

## Adding New Features

### Adding a New Agent

1. Create agent file in `aragora/agents/api_agents/`
2. Implement the `Agent` protocol
3. Register in `aragora/agents/__init__.py`
4. Add tests in `tests/agents/`

### Adding a CLI Command

1. Create command file in `aragora/cli/`
2. Register in `aragora/cli/main.py`
3. Add tests in `tests/cli/`

### Adding a Server Handler

1. Create handler in `aragora/server/handlers/`
2. Register routes in server startup
3. Add tests in `tests/server/handlers/`

## Testing Guidelines

### Test Organization

Tests mirror the source structure:
- `tests/debate/` → `aragora/debate/`
- `tests/server/handlers/` → `aragora/server/handlers/`

### Running Specific Tests

```bash
# Run tests for a specific module
pytest tests/debate/test_orchestrator.py -v

# Run tests matching a pattern
pytest tests/ -k "consensus" -v

# Run tests with markers
pytest tests/ -m "not slow and not e2e" -v

# Run with coverage for specific module
pytest tests/debate/ --cov=aragora/debate --cov-report=term-missing
```

### Test Markers

| Marker | Purpose | Example |
|--------|---------|---------|
| `@pytest.mark.slow` | Tests taking >10s | Integration tests |
| `@pytest.mark.e2e` | End-to-end tests | Full server tests |
| `@pytest.mark.load` | Load/stress tests | Performance tests |
| `@pytest.mark.serial` | Must run sequentially | Singleton tests |

### Writing Good Tests

```python
# Use descriptive names
async def test_arena_reaches_consensus_with_majority_vote():
    ...

# Use fixtures for common setup
@pytest.fixture
def mock_agent():
    return AsyncMock(spec=Agent)

# Test edge cases
async def test_arena_handles_agent_timeout_gracefully():
    ...
```

## Debugging Tips

### Common Issues

**Import Errors**
```bash
# Check if module exists
python -c "import aragora.debate.orchestrator"

# Check for circular imports
python -c "import aragora" 2>&1 | grep -i "circular"
```

**Test Failures**
```bash
# Run with verbose output
pytest tests/path/to/test.py -v --tb=long

# Run single test with debugging
pytest tests/path/to/test.py::test_name -v -s --capture=no

# Check for async issues
pytest tests/path/to/test.py --asyncio-mode=auto -v
```

**Server Issues**
```bash
# Check server health
curl http://localhost:8080/api/health | jq

# View server logs
ARAGORA_LOG_LEVEL=DEBUG aragora serve --api-port 8080 --ws-port 8765

# Check WebSocket connection
websocat ws://localhost:8765/ws
```

**Memory/Database Issues**
```bash
# Check database integrity
python -c "
from aragora.memory.continuum import ContinuumMemory
cm = ContinuumMemory()
print(cm.get_stats())
"

# Clear test database
rm -f ~/.aragora/test_*.db
```

### Debugging Debates

```python
# Enable verbose debate logging
from aragora import Arena, Environment, DebateProtocol

protocol = DebateProtocol(
    rounds=3,
    enable_debug_logging=True,  # Verbose output
)

# Run with tracing
arena = Arena(env, agents, protocol, enable_tracing=True)
result = await arena.run()
print(result.trace)  # Full execution trace
```

### Performance Profiling

```bash
# Profile a specific test
python -m cProfile -o profile.out -m pytest tests/debate/test_orchestrator.py::test_arena_run -v
python -c "import pstats; p = pstats.Stats('profile.out'); p.sort_stats('cumulative').print_stats(20)"

# Memory profiling
pip install memory_profiler
python -m memory_profiler your_script.py
```

## Getting Help

- Check existing issues for similar problems
- Open a new issue with a clear description
- Join our community discussions
- Read the relevant `docs/*.md` files for your area

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
