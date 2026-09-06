#!/bin/bash
# Aragora Docker Entrypoint
# Waits for dependencies, runs database migrations, then starts the server.
#
# Usage: Set as ENTRYPOINT in Dockerfile, or call directly.
# Environment:
#   SKIP_MIGRATIONS=1  - Skip migration step (e.g., for worker containers)
#   DATABASE_URL / ARAGORA_POSTGRES_DSN - PostgreSQL connection string

set -e

if [ -n "${DATABASE_URL}" ] || [ -n "${ARAGORA_POSTGRES_DSN}" ]; then
    DATABASE_URL="${ARAGORA_POSTGRES_DSN:-${DATABASE_URL}}"
    ARAGORA_POSTGRES_DSN="$DATABASE_URL"
    export DATABASE_URL ARAGORA_POSTGRES_DSN
fi

echo "[entrypoint] Aragora server starting..."
echo "[entrypoint] ARAGORA_ENV=${ARAGORA_ENV:-not set}"

# --------------------------------------------------------------------------
# Wait for PostgreSQL (if configured)
# --------------------------------------------------------------------------
if [ -n "${DATABASE_URL}" ] || [ -n "${ARAGORA_POSTGRES_DSN}" ]; then
    # Extract host and port from the resolved PostgreSQL URL for a simple TCP check.
    # Format: postgresql://user:pass@host:port/dbname
    DB_URL="$DATABASE_URL"
    DB_HOST=$(echo "$DB_URL" | sed -n 's|.*@\([^:/]*\).*|\1|p')
    DB_PORT=$(echo "$DB_URL" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
    DB_PORT=${DB_PORT:-5432}

    if [ -n "$DB_HOST" ]; then
        echo "[entrypoint] Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."
        RETRIES=0
        MAX_RETRIES=30
        while ! python -c "import socket; s=socket.create_connection(('${DB_HOST}', ${DB_PORT}), timeout=2); s.close()" 2>/dev/null; do
            RETRIES=$((RETRIES + 1))
            if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
                echo "[entrypoint] WARNING: PostgreSQL not reachable after ${MAX_RETRIES} attempts. Continuing anyway."
                break
            fi
            echo "[entrypoint] PostgreSQL not ready (attempt ${RETRIES}/${MAX_RETRIES}), retrying in 2s..."
            sleep 2
        done
        echo "[entrypoint] PostgreSQL is reachable."
    fi
fi

# --------------------------------------------------------------------------
# Run database migrations (unless explicitly skipped)
# --------------------------------------------------------------------------
if [ "${SKIP_MIGRATIONS}" != "1" ]; then
    if [ -n "${DATABASE_URL}" ] || [ -n "${ARAGORA_POSTGRES_DSN}" ]; then
        echo "[entrypoint] Running database migrations..."
        python -m aragora.migrations upgrade 2>&1 || {
            echo "[entrypoint] WARNING: Migration failed. Server will start but may use degraded mode."
            echo "[entrypoint] Check DATABASE_URL and database connectivity."
        }
        echo "[entrypoint] Migrations complete."
    else
        echo "[entrypoint] No DATABASE_URL set, skipping migrations (using SQLite)."
    fi
else
    echo "[entrypoint] SKIP_MIGRATIONS=1, skipping migrations."
fi

# --------------------------------------------------------------------------
# Optional: Seed demo data
# --------------------------------------------------------------------------
if [ "${ARAGORA_SEED_DEMO}" = "true" ]; then
    echo "[entrypoint] Seeding demo data..."
    if [ -f "scripts/seed_demo.py" ]; then
        python scripts/seed_demo.py 2>&1 || {
            echo "[entrypoint] WARNING: Demo seeding failed (non-fatal)."
        }
    else
        echo "[entrypoint] seed_demo.py not found, skipping demo seed."
    fi
fi

# Execute the main command (default: start the server)
exec "$@"
