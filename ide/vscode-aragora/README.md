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

Requires Node.js `^20.19.0 || >=22.12.0`.

```bash
cd ide/vscode-aragora
npm ci
npm run compile
npm run package
```

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
- Node.js 20.19.0 or higher, or Node.js 22.12.0 or higher, when building from source
- Aragora API key (get one at https://aragora.ai)

## Support

- [Documentation](https://docs.aragora.ai)
- [GitHub Issues](https://github.com/aragora/aragora/issues)
- [Discord Community](https://discord.gg/aragora)

## License

MIT
