"""
Database store health check utilities.

Provides individual check functions for each database store:
- Debate storage, ELO system, insight store, flip detector
- User store, consensus memory, agent metadata
- Integration store, Gmail token store, sync store, decision result store

Each function returns a dict with 'healthy' and 'status' keys,
plus additional metadata as appropriate.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from collections.abc import Callable

logger = logging.getLogger(__name__)


@runtime_checkable
class _HealthHandlerProtocol(Protocol):
    """Protocol for handlers used by database health checks."""

    ctx: dict[str, Any]

    def get_storage(self) -> Any: ...
    def get_elo_system(self) -> Any: ...
    def get_nomic_dir(self) -> Path | None: ...


def handle_store_check_errors(
    store_name: str,
    check_fn: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Unified error handler wrapper for store health checks.

    Wraps a store check function with standardized error handling:
    - Database errors (sqlite3.Error, OSError, IOError)
    - Data access errors (KeyError, TypeError, AttributeError)
    - Generic exceptions

    Args:
        store_name: Name of the store being checked (for logging)
        check_fn: Function that performs the actual check

    Returns:
        Tuple of (result_dict, is_healthy)
    """
    try:
        result = check_fn()
        return result, result.get("healthy", True)
    except (sqlite3.Error, OSError) as e:
        logger.warning("%s database error: %s: %s", store_name, type(e).__name__, e)
        return {
            "healthy": False,
            "error": "Health check failed",
            "error_type": "database",
        }, False
    except (KeyError, TypeError, AttributeError) as e:
        logger.debug("%s data access error: %s: %s", store_name, type(e).__name__, e)
        return {
            "healthy": False,
            "error": "Health check failed",
            "error_type": "data_access",
        }, False
    except ImportError:
        return {
            "healthy": True,
            "status": "module_not_available",
        }, True
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
        logger.warning("%s unexpected error: %s", store_name, e)
        return {
            "healthy": False,
            "error": "Health check failed",
        }, False


def check_debate_storage(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check debate storage backend health.

    Args:
        handler: Health handler instance with get_storage() method

    Returns:
        Dict with healthy status, storage type, and connection status
    """
    storage = handler.get_storage()
    if storage is not None:
        # Verify connectivity by listing recent debates
        _count = len(storage.list_recent(limit=1))
        return {
            "healthy": True,
            "status": "connected",
            "type": type(storage).__name__,
        }
    else:
        return {
            "healthy": True,
            "status": "not_initialized",
            "hint": "Will auto-create on first debate",
        }


def check_elo_system(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check ELO ranking system health.

    Args:
        handler: Health handler instance with get_elo_system() method

    Returns:
        Dict with healthy status, agent count, and connection status
    """
    elo = handler.get_elo_system()
    if elo is not None:
        leaderboard = elo.get_leaderboard(limit=5)
        return {
            "healthy": True,
            "status": "connected",
            "agent_count": len(leaderboard),
        }
    else:
        return {
            "healthy": True,
            "status": "not_initialized",
            "hint": "Run: python scripts/seed_agents.py",
        }


def check_insight_store(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check insight store health.

    Args:
        handler: Health handler instance with ctx dict

    Returns:
        Dict with healthy status and store type
    """
    insight_store = handler.ctx.get("insight_store")
    if insight_store is not None:
        return {
            "healthy": True,
            "status": "connected",
            "type": type(insight_store).__name__,
        }
    else:
        return {
            "healthy": True,
            "status": "not_initialized",
            "hint": "Will auto-create on first insight",
        }


def check_flip_detector(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check flip detector health.

    Args:
        handler: Health handler instance with ctx dict

    Returns:
        Dict with healthy status and detector type
    """
    flip_detector = handler.ctx.get("flip_detector")
    if flip_detector is not None:
        return {
            "healthy": True,
            "status": "connected",
            "type": type(flip_detector).__name__,
        }
    else:
        return {
            "healthy": True,
            "status": "not_initialized",
        }


def check_user_store(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check user/organization store health.

    Args:
        handler: Health handler instance with ctx dict

    Returns:
        Dict with healthy status and store type
    """
    user_store = handler.ctx.get("user_store")
    if user_store is not None:
        return {
            "healthy": True,
            "status": "connected",
            "type": type(user_store).__name__,
        }
    else:
        return {
            "healthy": True,
            "status": "not_initialized",
        }


def check_consensus_memory(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check consensus memory database health.

    Args:
        handler: Health handler instance with get_nomic_dir() method

    Returns:
        Dict with healthy status and database path
    """
    from aragora.memory.consensus import ConsensusMemory  # noqa: F401

    nomic_dir = handler.get_nomic_dir()
    if nomic_dir is not None:
        consensus_path = nomic_dir / "consensus_memory.db"
        if consensus_path.exists():
            return {
                "healthy": True,
                "status": "exists",
                "path": str(consensus_path),
            }
        else:
            return {
                "healthy": True,
                "status": "not_initialized",
                "hint": "Run: python scripts/seed_consensus.py",
            }
    else:
        return {
            "healthy": True,
            "status": "nomic_dir_not_set",
        }


def check_agent_metadata(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check agent metadata table health.

    Args:
        handler: Health handler instance with get_nomic_dir() method

    Returns:
        Dict with healthy status and agent count
    """
    nomic_dir = handler.get_nomic_dir()
    if nomic_dir is not None:
        elo_path = nomic_dir / "elo.db"
        if elo_path.exists():
            conn = sqlite3.connect(elo_path)
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_metadata'"
                )
                has_metadata = cursor.fetchone() is not None
                if has_metadata:
                    cursor = conn.execute("SELECT COUNT(*) FROM agent_metadata")
                    count = cursor.fetchone()[0]
                    return {
                        "healthy": True,
                        "status": "connected",
                        "agent_count": count,
                    }
                else:
                    return {
                        "healthy": True,
                        "status": "table_not_exists",
                        "hint": "Run: python scripts/seed_agents.py --with-metadata",
                    }
            finally:
                conn.close()
        else:
            return {
                "healthy": True,
                "status": "database_not_exists",
            }
    else:
        return {
            "healthy": True,
            "status": "nomic_dir_not_set",
        }


def check_integration_store(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check third-party integration store health.

    Args:
        handler: Health handler instance with ctx dict

    Returns:
        Dict with healthy status and store type
    """
    from aragora.storage.integration_store import IntegrationStoreBackend  # noqa: F401

    integration_store = handler.ctx.get("integration_store")
    if integration_store is not None:
        return {
            "healthy": True,
            "status": "connected",
            "type": type(integration_store).__name__,
        }
    else:
        return {
            "healthy": True,
            "status": "not_initialized",
            "hint": "Will auto-create on first integration",
        }


def check_gmail_token_store(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check Gmail OAuth token store health.

    Args:
        handler: Health handler instance with ctx dict

    Returns:
        Dict with healthy status and store type
    """
    from aragora.storage.gmail_token_store import GmailTokenStoreBackend  # noqa: F401

    gmail_token_store = handler.ctx.get("gmail_token_store")
    if gmail_token_store is not None:
        return {
            "healthy": True,
            "status": "connected",
            "type": type(gmail_token_store).__name__,
        }
    else:
        return {
            "healthy": True,
            "status": "not_initialized",
            "hint": "Configure Gmail OAuth to enable",
        }


def check_sync_store(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check enterprise sync store health.

    Args:
        handler: Health handler instance with ctx dict

    Returns:
        Dict with healthy status and store type
    """
    from aragora.storage.sync_store import SyncStore  # noqa: F401

    sync_store = handler.ctx.get("sync_store")
    if sync_store is not None:
        return {
            "healthy": True,
            "status": "connected",
            "type": type(sync_store).__name__,
        }
    else:
        return {
            "healthy": True,
            "status": "not_initialized",
            "hint": "Enable enterprise sync to initialize",
        }


def check_decision_result_store(handler: _HealthHandlerProtocol) -> dict[str, Any]:
    """Check decision result persistence store health.

    Args:
        handler: Health handler instance with ctx dict

    Returns:
        Dict with healthy status and store type
    """
    from aragora.storage.decision_result_store import DecisionResultStore  # noqa: F401

    decision_store = handler.ctx.get("decision_result_store")
    if decision_store is not None:
        return {
            "healthy": True,
            "status": "connected",
            "type": type(decision_store).__name__,
        }
    else:
        return {
            "healthy": True,
            "status": "not_initialized",
            "hint": "Will auto-create on first decision",
        }
