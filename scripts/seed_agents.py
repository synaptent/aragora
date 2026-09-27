#!/usr/bin/env python3
"""
Seed the ELO database with default agents.

This script populates the ratings table with common AI agents
so the leaderboard displays useful data from the start.

Run: python scripts/seed_agents.py
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Try to import aragora modules
try:
    from aragora.ranking.elo import EloSystem, AgentRating, DEFAULT_ELO

    RANKING_AVAILABLE = True
except ImportError:
    RANKING_AVAILABLE = False
    DEFAULT_ELO = 1500.0
    logger.warning("EloSystem not available, will create minimal database")

# Try to import database configuration for path resolution
try:
    from aragora.persistence.db_config import (
        DatabaseType,
        get_db_path,
        get_nomic_dir,
        get_db_mode,
    )

    DB_CONFIG_AVAILABLE = True
except ImportError:
    DB_CONFIG_AVAILABLE = False
    logger.warning("Database config not available, using legacy path")


# Agent metadata with rich information
# Format: (name, provider, metadata_dict)
AGENT_METADATA = [
    # Anthropic
    {
        "name": "claude-opus",
        "provider": "anthropic",
        "model_id": "claude-opus-4-5-20251101",
        "context_window": 200000,
        "specialties": ["reasoning", "analysis", "coding", "writing"],
        "strengths": ["Deep reasoning", "Nuanced analysis", "Long-form content"],
        "release_date": "2025-01",
    },
    {
        "name": "claude-sonnet",
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-20250514",
        "context_window": 200000,
        "specialties": ["coding", "analysis", "general"],
        "strengths": ["Balanced speed/quality", "Strong coding", "Tool use"],
        "release_date": "2025-05",
    },
    {
        "name": "claude-haiku",
        "provider": "anthropic",
        "model_id": "claude-haiku-4-20250514",
        "context_window": 200000,
        "specialties": ["speed", "classification", "simple-tasks"],
        "strengths": ["Fast responses", "Cost-effective", "High throughput"],
        "release_date": "2025-05",
    },
    # OpenAI
    {
        "name": "gpt-4o",
        "provider": "openai",
        "model_id": "gpt-4o-2024-11-20",
        "context_window": 128000,
        "specialties": ["multimodal", "coding", "general"],
        "strengths": ["Multimodal", "Fast", "Well-rounded"],
        "release_date": "2024-11",
    },
    {
        "name": "gpt-4-turbo",
        "provider": "openai",
        "model_id": "gpt-4-turbo-2024-04-09",
        "context_window": 128000,
        "specialties": ["coding", "analysis", "general"],
        "strengths": ["Reliable", "Good instruction following"],
        "release_date": "2024-04",
    },
    {
        "name": "o1",
        "provider": "openai",
        "model_id": "o1-2024-12-17",
        "context_window": 200000,
        "specialties": ["reasoning", "math", "science", "coding"],
        "strengths": ["Deep reasoning", "Complex problem solving", "Chain of thought"],
        "release_date": "2024-12",
    },
    {
        "name": "o1-mini",
        "provider": "openai",
        "model_id": "o1-mini-2024-09-12",
        "context_window": 128000,
        "specialties": ["reasoning", "math", "coding"],
        "strengths": ["Fast reasoning", "Cost-effective for STEM"],
        "release_date": "2024-09",
    },
    # Google
    {
        "name": "gemini-pro",
        "provider": "google",
        "model_id": "gemini-2.0-flash",
        "context_window": 1000000,
        "specialties": ["multimodal", "long-context", "general"],
        "strengths": ["Massive context", "Multimodal", "Fast"],
        "release_date": "2024-12",
    },
    {
        "name": "gemini-ultra",
        "provider": "google",
        "model_id": "gemini-3.1-pro-preview",
        "context_window": 1000000,
        "specialties": ["reasoning", "multimodal", "analysis"],
        "strengths": ["Deep reasoning", "Agentic capabilities"],
        "release_date": "2025-01",
    },
    # xAI
    {
        "name": "grok-2",
        "provider": "xai",
        "model_id": "grok-2-1212",
        "context_window": 131072,
        "specialties": ["general", "real-time", "humor"],
        "strengths": ["Real-time knowledge", "Contrarian perspectives"],
        "release_date": "2024-12",
    },
    {
        "name": "grok-beta",
        "provider": "xai",
        "model_id": "grok-beta",
        "context_window": 131072,
        "specialties": ["general", "coding"],
        "strengths": ["Experimental features", "Fast iteration"],
        "release_date": "2024-08",
    },
    # Meta
    {
        "name": "llama-3.1-405b",
        "provider": "meta",
        "model_id": "meta-llama/llama-3.1-405b-instruct",
        "context_window": 128000,
        "specialties": ["general", "coding", "multilingual"],
        "strengths": ["Open weights", "Large scale", "Customizable"],
        "release_date": "2024-07",
    },
    {
        "name": "llama-3.1-70b",
        "provider": "meta",
        "model_id": "meta-llama/llama-3.1-70b-instruct",
        "context_window": 128000,
        "specialties": ["general", "coding"],
        "strengths": ["Open weights", "Good balance", "Self-hostable"],
        "release_date": "2024-07",
    },
    # Mistral
    {
        "name": "mistral-large",
        "provider": "mistral",
        "model_id": "mistral-large-latest",
        "context_window": 128000,
        "specialties": ["multilingual", "coding", "reasoning"],
        "strengths": ["European perspective", "Strong multilingual", "Function calling"],
        "release_date": "2024-11",
    },
    {
        "name": "codestral",
        "provider": "mistral",
        "model_id": "codestral-latest",
        "context_window": 32000,
        "specialties": ["coding", "code-completion"],
        "strengths": ["Code specialized", "Fill-in-the-middle", "Fast"],
        "release_date": "2024-05",
    },
    # DeepSeek
    {
        "name": "deepseek-v4-pro",
        "provider": "deepseek",
        "model_id": "deepseek-v4-pro",
        "context_window": 1048576,
        "specialties": ["reasoning", "coding", "math"],
        "strengths": ["Frontier reasoning", "Long-context coding", "Open weights"],
        "release_date": "2026-04",
    },
    {
        "name": "deepseek-coder",
        "provider": "deepseek",
        "model_id": "deepseek-coder",
        "context_window": 128000,
        "specialties": ["coding", "code-completion"],
        "strengths": ["Code specialized", "Repository understanding"],
        "release_date": "2024-01",
    },
    # Alibaba
    {
        "name": "qwen-2.5-72b",
        "provider": "alibaba",
        "model_id": "qwen/qwen-2.5-72b-instruct",
        "context_window": 131072,
        "specialties": ["multilingual", "coding", "math"],
        "strengths": ["Chinese/English", "Strong math", "Open weights"],
        "release_date": "2024-09",
    },
    # Cohere
    {
        "name": "command-r-plus",
        "provider": "cohere",
        "model_id": "command-r-plus-08-2024",
        "context_window": 128000,
        "specialties": ["rag", "enterprise", "multilingual"],
        "strengths": ["RAG optimized", "Enterprise focus", "Tool use"],
        "release_date": "2024-08",
    },
    # Moonshot (Kimi)
    {
        "name": "kimi-k3",
        "provider": "moonshot",
        "model_id": "moonshotai/kimi-k3",
        "context_window": 1048576,
        "specialties": ["long-context", "multimodal", "reasoning"],
        "strengths": ["Long context", "Strong Chinese", "Agentic", "Vision"],
        "release_date": "2026-07",
    },
]

# Legacy format for backward compatibility
DEFAULT_AGENTS = [(a["name"], a["provider"]) for a in AGENT_METADATA]


def seed_agent_metadata(db_path: Path) -> int:
    """Seed agent metadata table with rich information."""
    import json
    import sqlite3

    conn = sqlite3.connect(db_path)

    # Create metadata table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_metadata (
            agent_name TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            model_id TEXT,
            context_window INTEGER,
            specialties TEXT,  -- JSON array
            strengths TEXT,    -- JSON array
            release_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_provider ON agent_metadata(provider)")

    seeded = 0
    now = datetime.now().isoformat()

    for agent in AGENT_METADATA:
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_metadata
                (agent_name, provider, model_id, context_window, specialties, strengths, release_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    agent["name"],
                    agent["provider"],
                    agent.get("model_id"),
                    agent.get("context_window"),
                    json.dumps(agent.get("specialties", [])),
                    json.dumps(agent.get("strengths", [])),
                    agent.get("release_date"),
                    now,
                ),
            )
            seeded += 1
        except Exception as e:
            logger.warning(f"Failed to seed metadata for {agent['name']}: {e}")

    conn.commit()
    conn.close()
    return seeded


def seed_with_elo_system(db_path: Path, agents: list[tuple[str, str]], force: bool = False) -> int:
    """Seed agents using the EloSystem class."""
    elo_system = EloSystem(str(db_path))
    seeded = 0

    for agent_name, provider in agents:
        try:
            # Check if agent already exists
            existing = elo_system.get_rating(agent_name, use_cache=False)

            # Skip if agent has actual data (debates_count > 0)
            if existing.debates_count > 0 and not force:
                logger.info(f"Skipping {agent_name}: has {existing.debates_count} debates")
                continue

            # Create and save default rating
            rating = AgentRating(
                agent_name=agent_name,
                elo=DEFAULT_ELO,
                domain_elos={},
                wins=0,
                losses=0,
                draws=0,
                debates_count=0,
                critiques_accepted=0,
                critiques_total=0,
                updated_at=datetime.now().isoformat(),
            )

            # Use internal save method (acceptable for seed scripts)
            elo_system._save_rating(rating)
            logger.info(f"Seeded: {agent_name} ({provider}) at ELO {DEFAULT_ELO}")
            seeded += 1

        except Exception as e:
            logger.warning(f"Failed to seed {agent_name}: {e}")

    return seeded


def export_metadata_json(output_path: Path) -> None:
    """Export agent metadata to JSON file."""
    import json

    output_path.write_text(json.dumps(AGENT_METADATA, indent=2))
    logger.info(f"Exported metadata to {output_path}")


def seed_minimal_database(db_path: Path, agents: list[tuple[str, str]]) -> int:
    """Seed agents directly with SQLite (fallback if EloSystem unavailable)."""
    import sqlite3

    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)

    # Create minimal schema
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ratings (
            agent_name TEXT PRIMARY KEY,
            elo REAL DEFAULT 1500.0,
            domain_elos TEXT DEFAULT '{}',
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,
            debates_count INTEGER DEFAULT 0,
            critiques_accepted INTEGER DEFAULT 0,
            critiques_total INTEGER DEFAULT 0,
            calibration_correct INTEGER DEFAULT 0,
            calibration_total INTEGER DEFAULT 0,
            calibration_brier_sum REAL DEFAULT 0.0,
            updated_at TEXT
        )
    """
    )

    seeded = 0
    now = datetime.now().isoformat()

    for agent_name, provider in agents:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO ratings (agent_name, elo, updated_at)
                VALUES (?, ?, ?)
                """,
                (agent_name, DEFAULT_ELO, now),
            )
            seeded += 1
            logger.info(f"Seeded: {agent_name} ({provider}) at ELO {DEFAULT_ELO}")
        except Exception as e:
            logger.warning(f"Failed to seed {agent_name}: {e}")

    conn.commit()
    conn.close()
    return seeded


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Seed default agents into ELO database")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to ELO database (auto-detected based on ARAGORA_DB_MODE)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite agents that already have match history",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be seeded without making changes",
    )
    parser.add_argument(
        "--with-metadata",
        action="store_true",
        default=True,
        help="Also seed agent metadata table (default: True)",
    )
    parser.add_argument(
        "--export-json",
        type=Path,
        default=None,
        help="Export agent metadata to JSON file",
    )
    parser.add_argument(
        "--list-agents",
        action="store_true",
        help="List all available agents with metadata and exit",
    )
    args = parser.parse_args()

    # List agents mode
    if args.list_agents:
        logger.info(f"Available agents ({len(AGENT_METADATA)}):\n")
        for agent in AGENT_METADATA:
            print(
                f"  {agent['name']:<20} ({agent['provider']:<10}) "
                f"ctx:{agent.get('context_window', 'N/A'):<8} "
                f"specialties: {', '.join(agent.get('specialties', []))}"
            )
        return

    # Export JSON mode
    if args.export_json:
        export_metadata_json(args.export_json)
        return

    # Determine database path
    if args.db_path:
        db_path = args.db_path
    elif DB_CONFIG_AVAILABLE:
        # Use the database configuration to get the correct path
        # This respects ARAGORA_DB_MODE (consolidated vs legacy)
        nomic_dir = get_nomic_dir()
        db_path = get_db_path(DatabaseType.ELO, nomic_dir)
        mode = get_db_mode()
        logger.info(f"Database mode: {mode.value}")
    else:
        # Fallback to legacy path
        base_dir = Path(__file__).parent.parent
        db_path = base_dir / ".nomic" / "elo.db"

    logger.info(f"Target database: {db_path}")
    logger.info(f"Agents to seed: {len(DEFAULT_AGENTS)}")

    if args.dry_run:
        logger.info("DRY RUN - no changes will be made")
        for agent in AGENT_METADATA:
            ctx = agent.get("context_window", "N/A")
            specs = ", ".join(agent.get("specialties", [])[:3])
            logger.info(f"  Would seed: {agent['name']} ({agent['provider']}) [ctx:{ctx}, {specs}]")
        return

    # Ensure .nomic directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Seed agents
    if RANKING_AVAILABLE:
        seeded = seed_with_elo_system(db_path, DEFAULT_AGENTS, force=args.force)
    else:
        seeded = seed_minimal_database(db_path, DEFAULT_AGENTS)

    logger.info(f"Seeded {seeded} agents successfully")

    # Seed metadata
    if args.with_metadata:
        metadata_count = seed_agent_metadata(db_path)
        logger.info(f"Seeded {metadata_count} agent metadata records")

    # Print summary
    if seeded > 0:
        logger.info("Leaderboard should now show seeded agents at ELO 1500")
        logger.info("Agents will diverge in ELO as they participate in debates")


if __name__ == "__main__":
    main()
