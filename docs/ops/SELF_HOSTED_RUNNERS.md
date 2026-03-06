# Self-Hosted GitHub Actions Runners

Set up spare machines as GitHub Actions runners for Aragora CI/CD.

## Prerequisites

- Linux machine (Ubuntu 22.04+, Amazon Linux 2023, or Debian 12+)
- 2+ CPU cores, 4GB+ RAM, 50GB+ disk
- Internet access (outbound HTTPS to github.com)
- `sudo` access for initial setup

## Quick Setup (15 minutes)

### 1. Install system dependencies

**Ubuntu/Debian:**
```bash
sudo apt update && sudo apt install -y git python3.11 python3.11-venv python3-pip jq tar libicu-dev
```

**Amazon Linux 2023:**
```bash
sudo dnf install -y git python3.11 python3.11-pip jq tar libicu
```

**macOS:**
```bash
brew install python@3.11 jq
```

### 2. Create runner user

```bash
sudo useradd -m -s /bin/bash github-runner
sudo usermod -aG sudo github-runner  # or wheel on AL2023
sudo su - github-runner
```

### 3. Get a registration token

You need a GitHub personal access token or admin access to the repo.

```bash
# Via GitHub CLI (if installed)
gh api repos/synaptent/aragora/actions/runners/registration-token \
  --method POST --jq '.token'

# Or via curl
curl -s -X POST \
  -H "Authorization: token YOUR_GITHUB_PAT" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/synaptent/aragora/actions/runners/registration-token \
  | jq -r '.token'
```

Save the token — it expires in 1 hour.

### 4. Download and install runner

```bash
cd ~
mkdir actions-runner && cd actions-runner

# Download latest runner (check https://github.com/actions/runner/releases for current version)
RUNNER_VERSION="2.322.0"
curl -o actions-runner.tar.gz -L \
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
tar xzf actions-runner.tar.gz
rm actions-runner.tar.gz
```

### 5. Configure the runner

```bash
./config.sh \
  --url https://github.com/synaptent/aragora \
  --token YOUR_REGISTRATION_TOKEN \
  --name "$(hostname)-runner" \
  --labels aragora \
  --work _work \
  --unattended
```

The `--labels aragora` is critical — all Aragora workflows use `runs-on: aragora`.

### 6. Install as a service

```bash
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

### 7. Install Aragora (optional, speeds up CI)

Pre-installing Aragora avoids `pip install` on every workflow run:

```bash
cd ~
git clone https://github.com/synaptent/aragora.git
cd aragora
python3.11 -m venv venv
source venv/bin/activate
pip install -e .
```

## Verify

After setup, the runner should appear at:
https://github.com/synaptent/aragora/settings/actions/runners

Check it's online and has the `aragora` label.

Test with:
```bash
gh workflow run lint.yml  # triggers a lightweight workflow
```

## Multiple Runners on One Machine

Each runner needs its own directory:

```bash
for i in 1 2; do
  mkdir -p ~/runner-$i && cd ~/runner-$i
  # Download runner, configure with --name "$(hostname)-runner-$i"
done
```

## Maintenance

### Update runner
```bash
cd ~/actions-runner
sudo ./svc.sh stop
# Runner auto-updates on restart, or manually:
# Download new version, extract, reconfigure
sudo ./svc.sh start
```

### View logs
```bash
journalctl -u actions.runner.synaptent-aragora.$(hostname)-runner -f
# or
tail -f ~/actions-runner/_diag/Runner_*.log
```

### Remove runner
```bash
cd ~/actions-runner
sudo ./svc.sh stop
sudo ./svc.sh uninstall
./config.sh remove --token YOUR_REMOVAL_TOKEN
```

## Current Runner Fleet

| Runner | Type | Location | Status |
|--------|------|----------|--------|
| hetzner-cpu1 | Hetzner VPS | EU | Active |
| hetzner-cpu2 | Hetzner VPS | EU | Active |
| hetzner-cpu3 | Hetzner VPS | EU | Active |
| aragora-runner-staging | EC2 m6i.large | us-east-2 | Active |
| aragora-runner-staging-2 | EC2 m6i.large | us-east-2 | Active |
| aragora-runner-test | EC2 m6i.large | us-east-2 | Active |
| aragora-runner-new-1 | EC2 m6i.large | us-east-2 | Active |
| aragora-runner-new-2 | EC2 m6i.large | us-east-2 | Active |
| aragora-runner-dr | EC2 m6i.large | us-east-1 | Active |

## Troubleshooting

**Runner offline:**
```bash
sudo systemctl restart actions.runner.synaptent-aragora.RUNNER_NAME
```

**Python not found in CI:**
Workflows use `actions/setup-python@v5` which may fail on self-hosted runners without the tool cache. The deploy-secure and review-gate workflows have fallback logic to use system Python. For other workflows, ensure `python3.11` is on PATH.

**Disk full:**
```bash
# Clean old workflow runs
rm -rf ~/actions-runner/_work/_temp/*
# Clean pip cache
pip cache purge
# Clean git objects
cd ~/actions-runner/_work/aragora/aragora && git gc --aggressive
```
