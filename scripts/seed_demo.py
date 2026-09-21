#!/usr/bin/env python3
"""Seed the live dashboard with realistic demo data so visitors see a working
platform instead of empty panels.  Populates the actual SQLite databases that
dashboard API endpoints read from (ELO, debates, trending, tournaments).

Usage:
    python scripts/seed_demo.py              # Seed all data
    python scripts/seed_demo.py --clear      # Clear demo data first
    python scripts/seed_demo.py --check      # Just check if data exists
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("seed_demo")
random.seed(42)


def _default_demo_data_dir() -> Path:
    """Keep demo data rooted in the current checkout by default."""
    return _REPO_ROOT / ".nomic"


def _ensure_demo_data_dir_env() -> None:
    """Avoid linked-worktree defaults that place demo data under the shared git dir."""
    if os.environ.get("ARAGORA_DATA_DIR") or os.environ.get("ARAGORA_NOMIC_DIR"):
        return
    os.environ["ARAGORA_DATA_DIR"] = str(_default_demo_data_dir())


_ensure_demo_data_dir_env()

# -- Demo content -----------------------------------------------------------
DEBATES = [
    ("Should we adopt microservices or keep the monolith?", "architecture", True, 0.91),
    ("Is React or Vue better for enterprise dashboards?", "frontend", True, 0.84),
    ("Should AI-generated code require human review?", "engineering", True, 0.96),
    ("Build vs buy for our observability stack?", "infrastructure", False, 0.52),
    ("Should we migrate from REST to GraphQL?", "api_design", True, 0.79),
    ("Is Rust worth the learning curve for our backend?", "engineering", True, 0.73),
    ("Should we open-source our SDK?", "strategy", True, 0.88),
    ("Kubernetes vs serverless for our next deployment?", "infrastructure", True, 0.81),
    ("Should we enforce 90% code coverage?", "quality", False, 0.48),
    ("Is it time to drop Python 3.9 support?", "compatibility", True, 0.93),
]
AGENTS = [  # (name, elo, wins, losses, draws, debates)
    ("claude-opus", 1782, 47, 12, 6, 65),
    ("gpt-4o", 1721, 41, 17, 7, 65),
    ("gemini-pro", 1654, 35, 22, 8, 65),
    ("mistral-large", 1598, 30, 25, 10, 65),
    ("grok-2", 1543, 27, 28, 10, 65),
    ("deepseek-v4-pro", 1487, 23, 31, 11, 65),
    ("llama-405b", 1412, 18, 35, 12, 65),
    ("qwen-72b", 1356, 14, 39, 12, 65),
]
TRENDING = [
    ("AI agents are replacing junior developers", "hackernews", "ai", 342),
    ("New NIST post-quantum cryptography standard released", "arxiv", "security", 189),
    ("Rust memory safety approach adopted by Linux 6.14", "github", "systems", 567),
    ("LLM context windows now exceed 10M tokens", "arxiv", "ai", 231),
    ("Remote work productivity data after 5 years", "hackernews", "culture", 418),
]
RISKS = [
    ("high", "3 agents show calibration drift >15% in security domain"),
    ("medium", "Consensus confidence below SLO target for architecture debates"),
    ("low", "ELO variance increasing for deepseek-v4-pro over last 20 matches"),
]
TOURN_AGENTS = ["claude-opus", "gpt-4o", "gemini-pro", "mistral-large"]
_DEMO_LIKE = "demo_%"

PIPELINES = [
    {
        "id": "demo_pipeline_001",
        "ideas": ["Implement rate limiting for API endpoints", "Add circuit breaker pattern"],
        "goals": ["Reduce API abuse by 90%", "Improve system resilience under load"],
        "status": "complete",
        "duration": 127.3,
    },
    {
        "id": "demo_pipeline_002",
        "ideas": ["Migrate authentication to OIDC", "Add MFA support"],
        "goals": ["Enterprise SSO compliance", "SOC 2 Type II alignment"],
        "status": "complete",
        "duration": 243.8,
    },
    {
        "id": "demo_pipeline_003",
        "ideas": ["Build customer health dashboard", "Add churn prediction"],
        "goals": ["Reduce churn by 15%", "Proactive customer outreach"],
        "status": "in_progress",
        "duration": 89.1,
    },
    {
        "id": "demo_pipeline_004",
        "ideas": ["Evaluate GraphQL migration", "Schema federation design"],
        "goals": ["Unified API gateway", "Reduce frontend API calls by 40%"],
        "status": "complete",
        "duration": 312.5,
    },
]

RECEIPTS = [
    {
        "id": "demo_receipt_001",
        "gauntlet_id": "demo_gauntlet_001",
        "debate_id": "demo_debate_000",
        "verdict": "APPROVED",
        "confidence": 0.94,
        "risk_level": "LOW",
        "risk_score": 0.08,
        "summary": "Microservices adoption approved with phased rollout plan",
    },
    {
        "id": "demo_receipt_002",
        "gauntlet_id": "demo_gauntlet_002",
        "debate_id": "demo_debate_002",
        "verdict": "APPROVED",
        "confidence": 0.97,
        "risk_level": "LOW",
        "risk_score": 0.04,
        "summary": "AI-generated code review requirement unanimously endorsed",
    },
    {
        "id": "demo_receipt_003",
        "gauntlet_id": "demo_gauntlet_003",
        "debate_id": "demo_debate_003",
        "verdict": "NEEDS_REVIEW",
        "confidence": 0.52,
        "risk_level": "MEDIUM",
        "risk_score": 0.41,
        "summary": "Build vs buy decision split — need cost analysis from finance",
    },
    {
        "id": "demo_receipt_004",
        "gauntlet_id": "demo_gauntlet_004",
        "debate_id": "demo_debate_006",
        "verdict": "APPROVED",
        "confidence": 0.88,
        "risk_level": "LOW",
        "risk_score": 0.12,
        "summary": "SDK open-sourcing approved with IP review completed",
    },
    {
        "id": "demo_receipt_005",
        "gauntlet_id": "demo_gauntlet_005",
        "debate_id": "demo_debate_008",
        "verdict": "REJECTED",
        "confidence": 0.71,
        "risk_level": "HIGH",
        "risk_score": 0.67,
        "summary": "90% coverage mandate rejected — diminishing returns analysis showed 80% optimal",
    },
]


def _data_dir() -> Path:
    try:
        from aragora.persistence.db_config import get_default_data_dir

        d = get_default_data_dir()
    except ImportError:
        d = Path(".nomic")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _past(days=0, hours=0):
    return (datetime.now(timezone.utc) - timedelta(days=days, hours=hours)).isoformat()


# -- Seed ELO ---------------------------------------------------------------
def seed_elo(clear: bool) -> int:
    try:
        from aragora.ranking.elo import EloSystem, AgentRating
    except ImportError:
        logger.warning("EloSystem not importable, skipping")
        return 0
    elo = EloSystem()
    if clear:
        with elo._db.connection() as c:
            for tbl in ("ratings", "matches", "elo_history"):
                try:
                    c.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
        logger.info("  Cleared ELO data")
    count = 0
    for name, rating, wins, losses, draws, debates in AGENTS:
        if elo.get_rating(name, use_cache=False).games_played > 0 and not clear:
            continue
        ar = AgentRating(
            agent_name=name,
            elo=float(rating),
            domain_elos={
                "engineering": rating + random.randint(-80, 80),
                "architecture": rating + random.randint(-80, 80),
            },
            wins=wins,
            losses=losses,
            draws=draws,
            debates_count=debates,
            critiques_accepted=random.randint(20, 60),
            critiques_total=random.randint(60, 100),
            calibration_correct=random.randint(10, 30),
            calibration_total=random.randint(30, 50),
            calibration_brier_sum=random.uniform(3.0, 8.0),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        elo._save_rating(ar)
        elo._record_elo_history(name, float(rating), debate_id="demo_seed")
        count += 1
    # 20 match history rows so recent-matches API is populated
    names = [a[0] for a in AGENTS]
    for i in range(20):
        a1, a2 = random.sample(names, 2)
        w = random.choice([a1, a2, None])
        s = {
            a1: 1.0 if w == a1 else (0.5 if w is None else 0.0),
            a2: 1.0 if w == a2 else (0.5 if w is None else 0.0),
        }
        try:
            elo._save_match(
                f"demo_match_{i:03d}",
                w,
                [a1, a2],
                random.choice(["engineering", "architecture", "security"]),
                s,
                {a1: random.uniform(-15, 15), a2: random.uniform(-15, 15)},
            )
        except Exception:
            pass
    return count


# -- Seed debates (DebateStorage) -------------------------------------------
def seed_debates(clear: bool) -> int:
    try:
        from aragora.storage.debate_storage import DebateStorage
    except ImportError:
        logger.warning("DebateStorage not importable, skipping")
        return 0
    st = DebateStorage()
    pool = [a[0] for a in AGENTS]
    count = 0
    if clear:
        with st.connection() as c:
            c.execute("DELETE FROM debates WHERE id LIKE ?", (_DEMO_LIKE,))
        logger.info("  Cleared debate data")
    for idx, (task, domain, consensus, conf) in enumerate(DEBATES):
        did = f"demo_debate_{idx:03d}"
        with st.connection() as c:
            if c.execute("SELECT 1 FROM debates WHERE id=?", (did,)).fetchone() and not clear:
                continue
        agents = random.sample(pool, random.randint(3, 5))
        created = datetime.now(timezone.utc) - timedelta(
            days=random.randint(1, 28), hours=random.randint(0, 23)
        )
        artifact = json.dumps(
            {
                "artifact_id": did,
                "task": task,
                "agents": agents,
                "rounds": 3,
                "messages": [
                    {
                        "agent": ag,
                        "round": r,
                        "content": f"Round {r} analysis of: {task}",
                        "timestamp": (created + timedelta(seconds=r * 60)).isoformat(),
                    }
                    for r in range(1, 4)
                    for ag in agents
                ],
                "consensus_proof": {
                    "reached": consensus,
                    "confidence": conf,
                    "method": "supermajority",
                },
                "domain": domain,
                "duration_seconds": random.randint(45, 300),
                "created_at": created.isoformat(),
                "metadata": {"demo": True},
            }
        )
        slug = st.generate_slug(task)
        with st.connection() as c:
            c.execute(
                """INSERT OR REPLACE INTO debates
                         (id,slug,task,agents,artifact_json,consensus_reached,confidence,created_at)
                         VALUES (?,?,?,?,?,?,?,?)""",
                (
                    did,
                    slug,
                    task,
                    json.dumps(agents),
                    artifact,
                    consensus,
                    conf,
                    created.isoformat(),
                ),
            )
        count += 1
    return count


# -- Seed CritiqueStore debates ---------------------------------------------
def seed_critique_debates(clear: bool) -> int:
    try:
        from aragora.memory.store import CritiqueStore
    except ImportError:
        logger.warning("CritiqueStore not importable, skipping")
        return 0
    st = CritiqueStore()
    count = 0
    if clear:
        with st.connection() as c:
            c.execute("DELETE FROM debates WHERE id LIKE ?", (_DEMO_LIKE,))
        logger.info("  Cleared critique data")
    for idx, (task, _dom, consensus, conf) in enumerate(DEBATES):
        did = f"demo_debate_{idx:03d}"
        with st.connection() as c:
            if c.execute("SELECT 1 FROM debates WHERE id=?", (did,)).fetchone() and not clear:
                continue
        verdict = f"Consensus conclusion for: {task}" if consensus else None
        with st.connection() as c:
            c.execute(
                """INSERT INTO debates
                         (id,task,final_answer,consensus_reached,confidence,rounds_used,
                          duration_seconds,created_at)
                         VALUES (?,?,?,?,?,?,?,?)""",
                (
                    did,
                    task,
                    verdict,
                    int(consensus),
                    conf,
                    3,
                    random.uniform(45, 300),
                    _past(days=random.randint(1, 28)),
                ),
            )
        count += 1
    return count


# -- Seed trending topics + risk warnings -----------------------------------
def seed_trending(clear: bool) -> int:
    try:
        from aragora.pulse.store import ScheduledDebateStore
    except ImportError:
        logger.warning("ScheduledDebateStore not importable, skipping")
        return 0
    st = ScheduledDebateStore()
    count = 0
    if clear:
        with st.connection() as c:
            c.execute("DELETE FROM scheduled_debates WHERE id LIKE ?", (_DEMO_LIKE,))
        logger.info("  Cleared trending data")

    def _insert(rec_id, topic, platform, category, volume, debate_id, consensus, conf, rounds):
        with st.connection() as c:
            if (
                c.execute("SELECT 1 FROM scheduled_debates WHERE id=?", (rec_id,)).fetchone()
                and not clear
            ):
                return False
        h = ScheduledDebateStore.hash_topic(topic)
        with st.connection() as c:
            c.execute(
                """INSERT OR REPLACE INTO scheduled_debates
                         (id,topic_hash,topic_text,platform,category,volume,debate_id,
                          created_at,consensus_reached,confidence,rounds_used,scheduler_run_id)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rec_id,
                    h,
                    topic,
                    platform,
                    category,
                    volume,
                    debate_id,
                    time.time() - random.randint(0, 86400),
                    consensus,
                    conf,
                    rounds,
                    "demo_run_001",
                ),
            )
        return True

    for i, (topic, plat, cat, vol) in enumerate(TRENDING):
        linked = i < 3
        count += _insert(
            f"demo_trend_{i:03d}",
            topic,
            plat,
            cat,
            vol,
            f"demo_debate_{i:03d}" if linked else None,
            1 if linked else None,
            round(random.uniform(0.7, 0.95), 2) if linked else None,
            3 if linked else 0,
        )
    for i, (sev, desc) in enumerate(RISKS):
        count += _insert(
            f"demo_risk_{i:03d}",
            desc,
            "internal",
            f"risk_{sev}",
            random.randint(1, 100),
            None,
            None,
            None,
            0,
        )
    return count


# -- Seed tournament --------------------------------------------------------
def seed_tournament(clear: bool) -> int:
    try:
        from aragora.ranking.tournaments import TournamentManager
    except ImportError:
        logger.warning("TournamentManager not importable, skipping")
        return 0
    mgr = TournamentManager()
    if clear:
        with mgr._get_connection() as c:
            c.execute("DELETE FROM tournaments WHERE name LIKE 'Demo%'")
            c.execute("DELETE FROM matches")
        logger.info("  Cleared tournament data")
    for t in mgr.list_tournaments(limit=10):
        if t.name.startswith("Demo"):
            logger.info("  Tournament exists, skipping")
            return 0
    tourn = mgr.create_tournament("Demo Weekly Championship", TOURN_AGENTS, "round_robin")
    for m in mgr.get_matches(tournament_id=tourn.tournament_id):
        w = random.choice([m.agent1, m.agent2, None])
        s1, s2 = round(random.uniform(0.3, 1.0), 2), round(random.uniform(0.3, 1.0), 2)
        if w == m.agent1:
            s1 = max(s1, s2 + 0.1)
        elif w == m.agent2:
            s2 = max(s1 + 0.1, s2)
        mgr.record_match_result(m.match_id, w, s1, s2, update_elo=False)
    return len(mgr.get_matches(tournament_id=tourn.tournament_id))


# -- Seed pipelines --------------------------------------------------------
def seed_pipelines(clear: bool) -> int:
    try:
        from aragora.storage.pipeline_store import get_pipeline_store
    except ImportError:
        logger.warning("PipelineResultStore not importable, skipping")
        return 0
    store = get_pipeline_store()
    count = 0
    for p in PIPELINES:
        pid = p["id"]
        existing = store.get(pid)
        if existing and not clear:
            continue
        stages = ["ideas", "goals", "actions", "orchestration"]
        if p["status"] == "complete":
            stage_status = dict.fromkeys(stages, "complete")
        else:
            stage_status = {
                "ideas": "complete",
                "goals": "complete",
                "actions": "in_progress",
                "orchestration": "pending",
            }
        agents_used = random.sample([a[0] for a in AGENTS], random.randint(3, 5))
        result_dict = {
            "pipeline_id": pid,
            "status": p["status"],
            "stage_status": stage_status,
            "ideas": [
                {
                    "id": f"{pid}_idea_{i}",
                    "text": idea,
                    "source": "demo",
                    "confidence": round(random.uniform(0.7, 0.95), 2),
                }
                for i, idea in enumerate(p["ideas"])
            ],
            "goals": [
                {
                    "id": f"{pid}_goal_{i}",
                    "title": goal,
                    "priority": i + 1,
                    "confidence": round(random.uniform(0.75, 0.98), 2),
                }
                for i, goal in enumerate(p["goals"])
            ],
            "actions": [
                {
                    "id": f"{pid}_action_{i}",
                    "description": f"Implement: {goal}",
                    "agent": agents_used[i % len(agents_used)],
                    "status": "complete" if p["status"] == "complete" else "pending",
                }
                for i, goal in enumerate(p["goals"])
            ],
            "orchestration": {
                "agents": agents_used,
                "parallel_tracks": min(len(agents_used), 3),
                "completed": p["status"] == "complete",
            },
            "duration": p["duration"],
            "created_at": _past(days=random.randint(1, 14)),
            "metadata": {"demo": True},
        }
        store.save(pid, result_dict)
        count += 1
    return count


# -- Seed decision receipts ------------------------------------------------
def seed_receipts(clear: bool) -> int:
    try:
        from aragora.storage.receipt_store import get_receipt_store
    except ImportError:
        logger.warning("ReceiptStore not importable, skipping")
        return 0
    store = get_receipt_store()
    count = 0
    import hashlib

    for r in RECEIPTS:
        existing = store.get(r["id"])
        if existing and not clear:
            continue
        agents_used = random.sample([a[0] for a in AGENTS], random.randint(3, 5))
        created = datetime.now(timezone.utc) - timedelta(days=random.randint(1, 21))
        data = {
            "receipt_id": r["id"],
            "gauntlet_id": r["gauntlet_id"],
            "debate_id": r["debate_id"],
            "verdict": r["verdict"],
            "confidence": r["confidence"],
            "risk_level": r["risk_level"],
            "risk_score": r["risk_score"],
            "summary": r["summary"],
            "agents_used": agents_used,
            "findings_count": random.randint(2, 12),
            "critical_findings": 0 if r["risk_level"] == "LOW" else random.randint(0, 2),
            "created_at": created.isoformat(),
            "expires_at": (created + timedelta(days=365)).isoformat(),
            "provenance": {
                "debate_rounds": 3,
                "consensus_method": "supermajority",
                "dissenting_agents": [] if r["confidence"] > 0.8 else [agents_used[-1]],
            },
        }
        checksum = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        data["checksum"] = checksum
        try:
            store.save(data)
            count += 1
        except Exception as exc:
            logger.debug("Receipt save failed: %s", exc)
    return count


# -- Seed analytics records ------------------------------------------------
def seed_analytics(clear: bool) -> int:
    """Seed DebateAnalytics with 30 days of realistic decision data."""
    try:
        from aragora.analytics.debate_analytics import get_debate_analytics
    except ImportError:
        logger.warning("DebateAnalytics not importable, skipping")
        return 0

    import asyncio
    from decimal import Decimal

    db_path = str(_data_dir() / "debate_analytics.db")
    analytics = get_debate_analytics(db_path=db_path)
    count = 0

    # Extend debates with more entries for 30-day coverage
    extended_debates = DEBATES + [
        ("Should we implement feature flags for all new features?", "engineering", True, 0.87),
        ("Is pair programming worth the productivity cost?", "process", False, 0.45),
        ("Should we adopt trunk-based development?", "engineering", True, 0.82),
        ("Build an internal developer portal?", "platform", True, 0.76),
        ("Should we require ADRs for all architecture changes?", "process", True, 0.91),
        ("Migrate to ARM-based instances for cost savings?", "infrastructure", True, 0.85),
        ("Should we implement canary deployments?", "devops", True, 0.89),
        ("Is it time to adopt WebAssembly for edge compute?", "architecture", False, 0.41),
        ("Should we standardize on Protocol Buffers?", "api_design", True, 0.74),
        ("Implement chaos engineering practices?", "reliability", True, 0.78),
        ("Should we adopt OpenTelemetry for all services?", "observability", True, 0.92),
        ("Replace Jenkins with GitHub Actions?", "ci_cd", True, 0.86),
        ("Should we implement SLO-based alerting?", "observability", True, 0.83),
        ("Adopt Nix for reproducible builds?", "tooling", False, 0.38),
        ("Should we enforce semantic versioning?", "process", True, 0.94),
        ("Migrate auth to passkeys?", "security", True, 0.71),
        ("Should we implement blue-green deployments?", "devops", True, 0.80),
        ("Adopt Dagger for CI pipelines?", "ci_cd", False, 0.49),
        ("Should we use vector databases for search?", "architecture", True, 0.77),
        ("Implement progressive delivery with feature gates?", "devops", True, 0.88),
    ]

    agent_names = [a[0] for a in AGENTS]
    providers = {
        "claude-opus": ("anthropic", "claude-opus-5"),
        "gpt-4o": ("openai", "gpt-4o"),
        "gemini-pro": ("google", "gemini-2.5-pro"),
        "mistral-large": ("mistral", "mistral-large-latest"),
        "grok-2": ("xai", "grok-2"),
        "deepseek-v4-pro": ("deepseek", "deepseek-v4-pro"),
        "llama-405b": ("openrouter", "meta-llama/llama-3.1-405b"),
        "qwen-72b": ("openrouter", "qwen/qwen-72b-chat"),
    }

    async def _seed():
        nonlocal count
        for i, (topic, domain, consensus, confidence) in enumerate(extended_debates):
            debate_id = f"demo_analytics_{i:03d}"
            days_ago = random.randint(0, 29)
            rounds = random.randint(2, 5) if consensus else random.randint(3, 7)
            duration = random.uniform(30.0, 240.0)
            num_agents = random.randint(3, min(6, len(agent_names)))
            debate_agents = random.sample(agent_names, num_agents)
            total_messages = rounds * num_agents * 2
            total_votes = num_agents

            await analytics.record_debate(
                debate_id=debate_id,
                rounds=rounds,
                consensus_reached=consensus,
                duration_seconds=duration,
                agents=debate_agents,
                status="completed",
                protocol=domain,
                total_messages=total_messages,
                total_votes=total_votes,
                total_cost=Decimal(str(round(random.uniform(0.02, 0.50), 4))),
            )

            # Record per-agent activity
            for agent in debate_agents:
                provider_name, model_name = providers.get(agent, ("unknown", agent))
                await analytics.record_agent_activity(
                    agent_id=agent,
                    debate_id=debate_id,
                    response_time_ms=random.uniform(200, 3500),
                    tokens_in=random.randint(500, 4000),
                    tokens_out=random.randint(200, 2000),
                    cost=Decimal(str(round(random.uniform(0.005, 0.08), 4))),
                    error=random.random() < 0.03,
                    agent_name=agent,
                    provider=provider_name,
                    model=model_name,
                )
            count += 1

        # Record ELO updates with realistic drift
        for agent_name, base_elo, *_ in AGENTS:
            for day in range(30, 0, -3):
                drift = random.randint(-15, 20)
                await analytics.record_elo_update(
                    agent_id=agent_name,
                    elo_rating=base_elo + drift + (30 - day),
                    debate_id=f"demo_analytics_{random.randint(0, len(extended_debates) - 1):03d}",
                )

    asyncio.run(_seed())
    return count


# -- Check ------------------------------------------------------------------
def _safe_count(fn):
    try:
        return fn()
    except Exception:
        return 0


def check_data() -> dict[str, int]:
    def _agents():
        from aragora.ranking.elo import EloSystem

        return len(EloSystem().list_agents())

    def _debates():
        from aragora.storage.debate_storage import DebateStorage

        with DebateStorage().connection() as c:
            return c.execute(
                "SELECT COUNT(*) FROM debates WHERE id LIKE ?", (_DEMO_LIKE,)
            ).fetchone()[0]

    def _trending():
        from aragora.pulse.store import ScheduledDebateStore

        with ScheduledDebateStore().connection() as c:
            return c.execute(
                "SELECT COUNT(*) FROM scheduled_debates WHERE id LIKE ?", (_DEMO_LIKE,)
            ).fetchone()[0]

    def _tourn():
        from aragora.ranking.tournaments import TournamentManager

        return len(
            [t for t in TournamentManager().list_tournaments(50) if t.name.startswith("Demo")]
        )

    def _pipelines():
        from aragora.storage.pipeline_store import get_pipeline_store

        store = get_pipeline_store()
        return len(store.list_pipelines(limit=50))

    def _receipts():
        from aragora.storage.receipt_store import get_receipt_store

        return get_receipt_store().count()

    return {
        "agents": _safe_count(_agents),
        "debates": _safe_count(_debates),
        "trending": _safe_count(_trending),
        "tournaments": _safe_count(_tourn),
        "pipelines": _safe_count(_pipelines),
        "receipts": _safe_count(_receipts),
    }


# -- Main -------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Seed Aragora dashboard with demo data")
    ap.add_argument("--clear", action="store_true", help="Clear demo data first")
    ap.add_argument("--check", action="store_true", help="Just check if data exists")
    args = ap.parse_args()
    dd = _data_dir()
    logger.info(f"Data directory: {dd}")
    if args.check:
        c = check_data()
        print("\nExisting demo data:")
        for k, v in c.items():
            print(f"  {k:15s}: {v}")
        print(f"  {'total':15s}: {sum(c.values())}")
        return 0 if sum(c.values()) > 0 else 1
    steps = [
        ("agents", seed_elo),
        ("debates", seed_debates),
        ("critique_debates", seed_critique_debates),
        ("trending_and_risks", seed_trending),
        ("tournament_matches", seed_tournament),
        ("pipelines", seed_pipelines),
        ("receipts", seed_receipts),
        ("analytics", seed_analytics),
    ]
    r = {}
    for name, fn in steps:
        logger.info(f"Seeding {name}...")
        r[name] = fn(args.clear)
    print(f"\n{'=' * 50}\nDEMO DATA SEEDED\n{'=' * 50}")
    for k, v in r.items():
        print(f"  {k:25s}: {v} created" if v else f"  {k:25s}: skipped (exists)")
    print(f"{'=' * 50}\n  Data directory: {dd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
