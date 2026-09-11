# Restoring production without AWS

`api.aragora.ai` already resolves to Cloudflare, and the edge is healthy — it is
waiting on an origin that no longer exists. So this is not a cloud migration.
It is giving Cloudflare a working origin again.

**The path is proven.** The same architecture already runs on `api-dev.aragora.ai`:
public → Cloudflare → Tunnel → a loopback origin, verified returning
`HTTP 200 {"status": "ok"}`. This directory does the same thing for production
on a Hetzner host.

The tunnel dials outbound, so the host needs **no inbound firewall rule, no
public IP, and no DNS change**.

---

## Before you start: the one question that changes everything

**Does a production database dump exist anywhere?**

Automated recovery is closed. Backups were bind-mounted onto the instance that is
gone (`./backups:/backups`), and the S3/GCS backend was never enabled —
`storage_backend` defaults to `"local"` with no production override. The only
possible survivor is a dump someone pulled by hand.

Check your machines for `*.sql.gz` or `*.dump`. If one exists, restore it in
step 5. If not, this brings production back on an **empty database**: the
service works, historical data does not come with it. That is worth deciding
deliberately, and telling users about, rather than discovering after cutover.

---

## Step 1 — Confirm Docker on the host

No runner advertises `docker-ready`, so this is genuinely unknown.

```bash
ssh <hetzner-host> 'docker --version && docker compose version'
```

If either is missing:

```bash
ssh <hetzner-host> 'curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER'
```

Then log out and back in so the group applies.

> The host answers to `ringrift-cpu1`, not an aragora name. Confirm whose machine
> it is and what else runs on it before production lands there.

## Step 2 — Get this directory onto the host

```bash
ssh <hetzner-host>
git clone https://github.com/synaptent/aragora.git ~/aragora   # or: git -C ~/aragora pull
cd ~/aragora/deploy/hetzner
```

## Step 3 — Create the secrets file

Every value is **new**. The AWS copies are unrecoverable and should be treated as
burned — rotate at each provider rather than trying to reuse anything.

```bash
cp secrets.env.template secrets.env
chmod 600 secrets.env
nano secrets.env
```

Generate four independent secrets:

```bash
openssl rand -hex 32      # POSTGRES_PASSWORD (URL-safe)
openssl rand -hex 32      # ARAGORA_API_TOKEN
openssl rand -hex 32      # ARAGORA_ENCRYPTION_KEY
openssl rand -hex 32      # ARAGORA_JWT_SECRET
```

Set `DATABASE_URL` to `postgresql://aragora:<POSTGRES_PASSWORD>@postgres:5432/aragora`,
using the same password as `POSTGRES_PASSWORD`. Compose loads this literal DSN
through `env_file`; it does not interpolate values from `secrets.env`.
Do not add a competing `ARAGORA_POSTGRES_DSN`.
`bring-up.sh` refuses to start if any of these five values is blank.
For live debates, the operator also adds freshly issued provider keys such as
`ANTHROPIC_API_KEY` or `OPENAI_API_KEY` to `secrets.env`. Provider setup, canary
bring-up and monitoring require separate operator authorization.

## Step 4 — Start the origin

```bash
./bring-up.sh
```

It builds, runs migrations as a gate, waits for health, and curls the local
endpoint. Everything binds to `127.0.0.1` — still unreachable from outside.

## Step 5 — (Only if you found a dump) restore the data

Do this **after** step 4 and **before** the tunnel goes live. Step 4 already
created the schema, so loading a plain-SQL dump on top of it collides with the
existing tables, and `psql` would keep going past those errors and leave a
partial restore that looks like success. Restore into an empty database and
let the migrate service bring the dump's schema forward:

```bash
docker compose stop app
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U aragora -d postgres \
  -c 'DROP DATABASE aragora WITH (FORCE)' -c 'CREATE DATABASE aragora'
gunzip -c /path/to/dump.sql.gz | docker compose exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U aragora -d aragora
docker compose run --rm migrate
docker compose up -d app
```

`ON_ERROR_STOP=1` makes the restore fail loudly on the first error instead of
continuing; if it stops, nothing in `secrets.env` needs to change — fix the
dump and rerun from the `DROP DATABASE` line.

## Step 6 — Point the tunnel at it

Your stored Cloudflare certificate is present but the API rejects it, so start
by re-authenticating:

```bash
cloudflared tunnel login
cloudflared tunnel create aragora-prod
```

That writes a credentials JSON. Install both files:

```bash
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/<TUNNEL-UUID>.json /etc/cloudflared/aragora-prod.json
sudo cp cloudflared-config.yml /etc/cloudflared/config.yml
```

Route the hostname and start the service:

```bash
cloudflared tunnel route dns aragora-prod api.aragora.ai
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

`route dns` updates the existing Cloudflare record in place. No registrar change.

## Step 7 — Verify from outside

Run these from your laptop, not the host — the point is to test the public path.

```bash
curl -sS https://api.aragora.ai/readyz
curl -s -o /dev/null -w '%{http_code}\n' https://api.aragora.ai/readyz
```

You want `{"status": "ready"}` and `200`. Then confirm it survives a restart:

```bash
ssh <hetzner-host> 'cd ~/aragora/deploy/hetzner && docker compose restart app'
sleep 30 && curl -sS https://api.aragora.ai/readyz
```

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `502` from Cloudflare | tunnel up, origin down | `docker compose ps`, `docker compose logs app` |
| `1033` | tunnel not connected | `systemctl status cloudflared` |
| Still times out | DNS route not applied | re-run `cloudflared tunnel route dns` |
| `bring-up.sh` refuses | blank required secret | fill it in — this guard is deliberate |
| migrate exits non-zero | schema failure | read its logs; the app is held back on purpose |

## What this deliberately does differently

The previous setup wrote backups to a bind mount on the same instance as the
database, so the copy died with the original. Here the nightly dump still runs,
but **a backup that shares a failure domain with its source is not a backup** —
copy `backups/` off this host on a schedule, or the next outage reads exactly
like this one.

A single host is also a single point of failure. Two hosts behind the same
tunnel cost little now and much less than the next outage.
