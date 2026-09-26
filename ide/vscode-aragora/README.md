# Aragora VS Code Extension

Control plane for multi-agent vetted decisionmaking - Visual Studio Code integration.

## Features

- **Run Debates**: Start AI debates directly from VS Code
- **Run Gauntlet**: Stress-test selected code through adversarial analysis
- **List Agents**: View available AI agents and their capabilities
- **View Results**: Browse recent debate results in the sidebar
- **Quick Configuration**: Easy API setup through the command palette

## Installation

### From VS Code Marketplace

Search for "Aragora" in the Extensions view (`Ctrl+Shift+X`).

### From VSIX

1. Download the `.vsix` file from releases
2. Open VS Code
3. Press `Ctrl+Shift+P` and run "Extensions: Install from VSIX..."
4. Select the downloaded file

### Build from Source

See [Setup](#setup) and [Build](#build).

## Setup

Requires Node.js `>=22.22.0`. `.npmrc` sets `engine-strict=true`, so `npm ci` refuses older
releases (`@vscode/test-electron` 3 needs Node 22 and `posthog-node` needs 22.22). CI uses Node
22.22.2.

```bash
cd ide/vscode-aragora
npm ci
npm --prefix webview-ui ci
```

## Run

```bash
npm ci
npm run compile
```

`npm run compile` builds the extension into `out/` and also compiles the integration suite.

### Debug with F5

Open `ide/vscode-aragora` itself as the VS Code workspace folder (the launch configuration uses
`${workspaceFolder}` as the extension directory), then press **F5** or pick **Run Aragora
Extension** in Run and Debug. The `preLaunchTask` in `.vscode/launch.json` runs the `npm: compile`
task from `.vscode/tasks.json` first, so F5 always starts from a fresh build, then opens an
Extension Development Host with the extension loaded. Breakpoints in `src/` resolve through the
source maps in `out/`. The webview panels load `webview-ui/dist/`, so run `npm run build:webview`
once before opening them.

## Build

```bash
npm run package
```

This writes `aragora-<version>.vsix`; `vscode:prepublish` compiles the extension and builds the
webview first. The script runs `vsce package --no-dependencies`, and `.vscodeignore` keeps only
`out/` (without tests), `webview-ui/dist/`, `resources/`, `package.json` and this README, so
`node_modules/` is never bundled. Such a VSIX does not contain the telemetry SDKs, so telemetry
stays off in it (see [Configuration](#configuration)). To write the VSIX elsewhere, run
`npx vsce package --no-dependencies --out /tmp/aragora.vsix`.

## Test

Unit tests run under Jest with a mocked `vscode` module, the coverage thresholds from
`jest.config.js`, and a JUnit report in `junit.xml`:

```bash
npx jest --ci --coverage
```

Integration tests run Mocha inside a real VS Code 1.136.1 through `@vscode/test-electron`:

```bash
npm run test:integration
```

The first run downloads VS Code 1.136.1 into `.vscode-test/` (about 300 MB); later runs reuse it.
A VS Code window opens for a few seconds, so run one suite at a time. On Linux without a display,
use `xvfb-run -a npm run test:integration`. The suite lives in `src/test/suite/` and the version
pin is `VSCODE_VERSION` in `src/test/runTest.ts`. `tsconfig.integration.json` compiles the suite
as a separate program because the Mocha and Jest global types clash, and Jest ignores it.

From the repository root, `make readiness-test-vscode` runs the unit tests and
`make readiness-heavy-vscode` runs the integration suite.

## Lint

```bash
npm run lint                     # ESLint (flat config)
npm --prefix webview-ui run lint # ESLint for the webview
npm run format:check             # Prettier for the extension and webview-ui
npx knip                         # unused files, exports and dependencies
```

From the repository root, `make readiness-lint-vscode` runs these plus the file-size ratchet, and
`make readiness-typecheck-vscode` type-checks the extension, the integration suite and the
webview. The `vscode-typecheck` pre-push hook runs `npm run compile`.

## Configuration

Open Settings (`Ctrl+,`) and search for "Aragora":

| Setting                        | Description                                                                                   | Default                  |
| ------------------------------ | --------------------------------------------------------------------------------------------- | ------------------------ |
| `aragora.apiUrl`               | Aragora API URL                                                                               | `https://api.aragora.ai` |
| `aragora.apiKey`               | Your API key                                                                                  | (empty)                  |
| `aragora.defaultAgents`        | Default agents for debates                                                                    | `claude,gpt-4`           |
| `aragora.defaultRounds`        | Default number of rounds                                                                      | `3`                      |
| `aragora.logLevel`             | Minimum level written to the Aragora output channel (`debug`, `info`, `warn`, `error`, `off`) | `info`                   |
| `aragora.telemetry.enabled`    | Send error reports and usage events                                                           | `false`                  |
| `aragora.telemetry.sentryDsn`  | Sentry DSN for error reports                                                                  | (empty)                  |
| `aragora.telemetry.posthogKey` | PostHog project key for usage events                                                          | (empty)                  |

Or use the command `Aragora: Configure API` from the command palette.

Logs go to the **Aragora** output channel. API keys, tokens, secrets, passwords and
`Authorization` values are redacted before they are written.

Telemetry is off by default. The extension creates Sentry or PostHog clients only when all of
these hold: VS Code telemetry is enabled, `aragora.telemetry.enabled` is `true`, and a Sentry DSN
or PostHog key is set. The DSN and key can also come from the `ARAGORA_SENTRY_DSN` and
`ARAGORA_POSTHOG_KEY` environment variables; `ARAGORA_POSTHOG_HOST` overrides the PostHog host.
The telemetry settings are user-level only, so a workspace cannot turn them on. The SDKs are
optional at runtime: if `@sentry/node` or `posthog-node` cannot be loaded (for example in a VSIX
packaged with `--no-dependencies`), that client stays off.

## Commands

| Command                              | Description                    |
| ------------------------------------ | ------------------------------ |
| `Aragora: Run Debate`                | Start a new multi-agent debate |
| `Aragora: Run Gauntlet on Selection` | Stress-test selected code      |
| `Aragora: List Available Agents`     | Show available AI agents       |
| `Aragora: Show Recent Results`       | Open the Aragora sidebar       |
| `Aragora: Configure API`             | Quick configuration wizard     |

## Usage

### Running a Debate

1. Press `Ctrl+Shift+P` to open command palette
2. Type "Aragora: Run Debate"
3. Enter your question or topic
4. Select agents (or use defaults)
5. Wait for the debate to complete
6. View or copy the consensus answer

### Running Gauntlet on Code

1. Select code in the editor
2. Right-click and select "Aragora: Run Gauntlet on Selection"
3. Or press `Ctrl+Shift+P` and type "Aragora: Run Gauntlet"

### Sidebar Views

The Aragora sidebar shows:

- **Recent Debates**: Browse your recent debate results
- **Agents**: View available AI agents and their status

## Requirements

- VS Code 1.85.0 or higher
- Node.js 22.22.0 or higher when building from source
- Aragora API key (get one at https://aragora.ai)

## Support

- [Documentation](https://docs.aragora.ai)
- [GitHub Issues](https://github.com/aragora/aragora/issues)
- [Discord Community](https://discord.gg/aragora)

## License

MIT
