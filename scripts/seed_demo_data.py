#!/usr/bin/env python3
"""Seed a PostgreSQL database with demo data for the one-click docker demo.

Creates demo organizations, users, debates, and templates so the platform
looks populated on first launch. Idempotent -- safe to run multiple times.

Usage:
    python scripts/seed_demo_data.py                    # Seed all data
    python scripts/seed_demo_data.py --check            # Check existing data
    python scripts/seed_demo_data.py --clear            # Clear demo data first
    python scripts/seed_demo_data.py --database-url … # Override DATABASE_URL

Environment:
    DATABASE_URL  PostgreSQL connection string (default: see below)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import TypedDict

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("seed_demo_data")

DEFAULT_DATABASE_URL = "postgresql://aragora:aragora_sme@localhost:5432/aragora"

# Deterministic randomness for reproducible demo data
random.seed(42)

# ---------------------------------------------------------------------------
# Demo content
# ---------------------------------------------------------------------------

DEMO_ORGS = [
    {
        "id": "demo_org_free",
        "name": "Acme Startups",
        "slug": "acme-startups",
        "tier": "free",
    },
    {
        "id": "demo_org_pro",
        "name": "TechCorp Pro",
        "slug": "techcorp-pro",
        "tier": "pro",
    },
]

DEMO_USERS = [
    {
        "id": "demo_user_admin",
        "email": "admin@demo.aragora.ai",
        "name": "Demo Admin",
        "org_id": "demo_org_pro",
        "role": "admin",
    },
    {
        "id": "demo_user_member",
        "email": "member@demo.aragora.ai",
        "name": "Demo Member",
        "org_id": "demo_org_pro",
        "role": "member",
    },
    {
        "id": "demo_user_free",
        "email": "free@demo.aragora.ai",
        "name": "Free User",
        "org_id": "demo_org_free",
        "role": "admin",
    },
]

# password: demo123  (bcrypt-style placeholder -- the app hashes on login)
DEMO_PASSWORD_HASH = hashlib.sha256(b"demo123").hexdigest()
DEMO_PASSWORD_SALT = "demo_salt_not_for_production"


class DemoDebate(TypedDict):
    question: str
    decision: str | None
    confidence: float
    agents: list[str]
    outcome: str


DEMO_DEBATES: list[DemoDebate] = [
    {
        "question": "Should we adopt microservices or keep the monolith?",
        "decision": "Adopt microservices with a phased migration starting from the billing module.",
        "confidence": 0.91,
        "agents": ["claude-opus", "gpt-4o", "gemini-pro", "mistral-large"],
        "outcome": "consensus",
    },
    {
        "question": "Is React or Vue better for our enterprise dashboard?",
        "decision": "React is preferred due to team expertise and ecosystem maturity.",
        "confidence": 0.84,
        "agents": ["claude-opus", "gpt-4o", "deepseek-v4-pro"],
        "outcome": "consensus",
    },
    {
        "question": "Should AI-generated code require human review?",
        "decision": "Yes -- all AI-generated code must pass human review before merge.",
        "confidence": 0.96,
        "agents": ["claude-opus", "gpt-4o", "gemini-pro", "grok-2", "mistral-large"],
        "outcome": "consensus",
    },
    {
        "question": "Build vs buy for our observability stack?",
        "decision": None,
        "confidence": 0.52,
        "agents": ["claude-opus", "gpt-4o", "gemini-pro"],
        "outcome": "split",
    },
    {
        "question": "Should we migrate from REST to GraphQL?",
        "decision": "Adopt GraphQL for new endpoints; keep REST for existing stable APIs.",
        "confidence": 0.79,
        "agents": ["gpt-4o", "gemini-pro", "deepseek-v4-pro", "llama-405b"],
        "outcome": "consensus",
    },
]

DEMO_TEMPLATES = [
    {
        "name": "Architecture Decision Record",
        "description": "Evaluate architectural choices with adversarial vetting from multiple AI agents.",
        "category": "engineering",
        "pattern": "adversarial",
    },
    {
        "name": "Go/No-Go Launch Review",
        "description": "Pre-launch checklist debate to surface risks before a product release.",
        "category": "product",
        "pattern": "structured",
    },
    {
        "name": "Vendor Evaluation",
        "description": "Compare vendors across cost, features, and risk dimensions.",
        "category": "procurement",
        "pattern": "comparative",
    },
    {
        "name": "Security Threat Model",
        "description": "Adversarial review of system security posture and attack surfaces.",
        "category": "security",
        "pattern": "adversarial",
    },
    {
        "name": "Hiring Decision",
        "description": "Structured evaluation of candidates against role requirements.",
        "category": "people",
        "pattern": "structured",
    },
]


def _uid() -> str:
    return str(uuid.uuid4())


def _past(days: int = 0, hours: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days, hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def get_connection(database_url: str):
    """Return a psycopg2 connection."""
    try:
        import psycopg2
    except ImportError:
        logger.error("psycopg2 not installed. Install with: pip install psycopg2-binary")
        sys.exit(1)

    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = False
        return conn
    except Exception:
        logger.error("Failed to connect to database at %s", database_url)
        raise


def _row_exists(cur, table: str, id_value: str) -> bool:
    """Check if a row with the given id exists in the given table (aragora schema)."""
    cur.execute(f"SELECT 1 FROM aragora.{table} WHERE id = %s", (id_value,))
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------


def seed_organizations(cur) -> int:
    count = 0
    for org in DEMO_ORGS:
        if _row_exists(cur, "organizations", org["id"]):
            continue
        cur.execute(
            """INSERT INTO aragora.organizations (id, name, slug, tier, settings, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, NOW(), NOW())""",
            (org["id"], org["name"], org["slug"], org["tier"], json.dumps({"demo": True})),
        )
        count += 1
    return count


def seed_users(cur) -> int:
    count = 0
    for user in DEMO_USERS:
        if _row_exists(cur, "users", user["id"]):
            continue
        cur.execute(
            """INSERT INTO aragora.users
               (id, email, password_hash, password_salt, name, org_id, role,
                is_active, email_verified, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, TRUE, NOW(), NOW())""",
            (
                user["id"],
                user["email"],
                DEMO_PASSWORD_HASH,
                DEMO_PASSWORD_SALT,
                user["name"],
                user["org_id"],
                user["role"],
            ),
        )
        count += 1
    return count


def seed_debates(cur) -> int:
    count = 0
    for idx, d in enumerate(DEMO_DEBATES):
        debate_id = f"demo_debate_{idx:03d}"
        if _row_exists(cur, "decision_results", debate_id):
            continue
        days_ago = random.randint(1, 21)
        votes = {}
        for agent in d["agents"]:
            votes[agent] = round(random.uniform(0.5, 1.0), 2)
        cur.execute(
            """INSERT INTO aragora.decision_results
               (id, debate_id, question, decision, confidence, reasoning,
                participants, votes, metadata, org_id, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                debate_id,
                debate_id,
                d["question"],
                d["decision"],
                d["confidence"],
                json.dumps(
                    {
                        "outcome": d["outcome"],
                        "rounds": 3,
                        "duration_seconds": random.randint(45, 300),
                    }
                ),
                json.dumps(d["agents"]),
                json.dumps(votes),
                json.dumps({"demo": True, "outcome": d["outcome"]}),
                "demo_org_pro",
                _past(days=days_ago),
            ),
        )
        count += 1
    return count


def seed_templates(cur) -> int:
    count = 0
    for tmpl in DEMO_TEMPLATES:
        tmpl_id = f"demo_tmpl_{tmpl['name'].lower().replace(' ', '_')[:30]}"
        if _row_exists(cur, "marketplace_templates", tmpl_id):
            continue
        cur.execute(
            """INSERT INTO aragora.marketplace_templates
               (id, name, description, author_id, author_name, category, pattern,
                tags, workflow_definition, is_featured, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())""",
            (
                tmpl_id,
                tmpl["name"],
                tmpl["description"],
                "demo_user_admin",
                "Demo Admin",
                tmpl["category"],
                tmpl["pattern"],
                json.dumps([tmpl["category"], tmpl["pattern"], "demo"]),
                json.dumps({"demo": True}),
            ),
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


def clear_demo_data(cur) -> dict[str, int]:
    """Remove all demo-prefixed rows. Returns counts per table."""
    counts = {}
    tables = [
        ("marketplace_templates", "id LIKE 'demo_tmpl_%'"),
        ("decision_results", "id LIKE 'demo_debate_%'"),
        ("users", "id LIKE 'demo_user_%'"),
        ("organizations", "id LIKE 'demo_org_%'"),
    ]
    for table, condition in tables:
        cur.execute(f"DELETE FROM aragora.{table} WHERE {condition}")
        counts[table] = cur.rowcount
    return counts


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------


def check_data(cur) -> dict[str, int]:
    queries = {
        "organizations": "SELECT COUNT(*) FROM aragora.organizations WHERE id LIKE 'demo_org_%'",
        "users": "SELECT COUNT(*) FROM aragora.users WHERE id LIKE 'demo_user_%'",
        "debates": "SELECT COUNT(*) FROM aragora.decision_results WHERE id LIKE 'demo_debate_%'",
        "templates": "SELECT COUNT(*) FROM aragora.marketplace_templates WHERE id LIKE 'demo_tmpl_%'",
    }
    result = {}
    for label, sql in queries.items():
        try:
            cur.execute(sql)
            result[label] = cur.fetchone()[0]
        except Exception:
            result[label] = 0
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed Aragora demo data into PostgreSQL")
    ap.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection string",
    )
    ap.add_argument("--check", action="store_true", help="Check existing demo data")
    ap.add_argument("--clear", action="store_true", help="Clear demo data before seeding")
    args = ap.parse_args()

    conn = get_connection(args.database_url)
    cur = conn.cursor()

    try:
        if args.check:
            counts = check_data(cur)
            print("\nExisting demo data:")
            for k, v in counts.items():
                print(f"  {k:20s}: {v}")
            total = sum(counts.values())
            print(f"  {'total':20s}: {total}")
            return 0 if total > 0 else 1

        if args.clear:
            logger.info("Clearing demo data...")
            removed = clear_demo_data(cur)
            conn.commit()
            for table, n in removed.items():
                logger.info("  Removed %d rows from %s", n, table)

        # Seed in dependency order
        steps = [
            ("organizations", seed_organizations),
            ("users", seed_users),
            ("debates", seed_debates),
            ("templates", seed_templates),
        ]

        results = {}
        for name, fn in steps:
            logger.info("Seeding %s...", name)
            results[name] = fn(cur)

        conn.commit()

        print(f"\n{'=' * 50}")
        print("DEMO DATA SEEDED")
        print(f"{'=' * 50}")
        for k, v in results.items():
            if v:
                print(f"  {k:20s}: {v} created")
            else:
                print(f"  {k:20s}: skipped (exists)")
        print(f"{'=' * 50}")
        print()
        print("Demo credentials:")
        print("  Email:    admin@demo.aragora.ai")
        print("  Password: demo123")
        print()
        return 0

    except Exception:
        conn.rollback()
        logger.exception("Seeding failed")
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
