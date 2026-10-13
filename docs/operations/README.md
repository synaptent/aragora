# Operations

Runbooks for running, self-hosting and supporting Aragora in production, plus
notes on operating the repository's own agents and CI runners. Every page in
this directory is listed below once. For first deployments, start with the
[deployment guide](../DEPLOYMENT.md) and
[production deployment](../deployment/PRODUCTION_DEPLOYMENT.md); incident and
recovery procedures are in [runbooks/](../runbooks/README.md). The full
documentation map is in [docs/README.md](../README.md).

## Running Aragora

| Page | What it covers |
|------|----------------|
| [OPERATIONS](./OPERATIONS.md) | Operations runbook: running, monitoring and troubleshooting Aragora in production |
| [PRODUCTION_RUNBOOK](./PRODUCTION_RUNBOOK.md) | Health monitoring, scaling, backup and recovery, key rotation and step-by-step procedures |
| [SELF_HOSTING](./SELF_HOSTING.md) | Run Aragora on your own infrastructure |
| [REVERSE_PROXY](./REVERSE_PROXY.md) | Put a reverse proxy in front of the HTTP API and WebSocket ports |

## Repository Operations

| Page | What it covers |
|------|----------------|
| [SELF_HOSTED_RUNNER_DOCKER](./SELF_HOSTED_RUNNER_DOCKER.md) | Docker provisioning for the `aragora`-labeled self-hosted GitHub Actions runners |
| [agent_bridge_first_real_run](./agent_bridge_first_real_run.md) | First real-run scenario for the agent bridge write API (status: scenario design) |
| [round-discipline](./round-discipline.md) | The round pattern for autonomous Claude rounds, recorded from April 2026 operation |
