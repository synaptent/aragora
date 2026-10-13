#!/usr/bin/env python3
"""
Add request/response examples to key OpenAPI endpoints.
"""

import json
import sys
from pathlib import Path
from typing import Any

# Examples for key endpoints
ENDPOINT_EXAMPLES: dict[str, dict[str, Any]] = {
    # Debates
    "POST /api/debates": {
        "requestBody": {
            "content": {
                "application/json": {
                    "example": {
                        "question": "Should we adopt TypeScript for our backend services?",
                        "agents": ["claude-3-opus", "gpt-4", "gemini-pro"],
                        "rounds": 3,
                        "consensus_threshold": 0.7,
                        "workspace_id": "ws_abc123",
                        "protocol": "structured",
                        "context": "We currently use Python with type hints. Consider developer productivity, type safety, and ecosystem.",
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "example": {
                            "id": "dbt_xyz789",
                            "status": "active",
                            "question": "Should we adopt TypeScript for our backend services?",
                            "agents": ["claude-3-opus", "gpt-4", "gemini-pro"],
                            "current_round": 1,
                            "total_rounds": 3,
                            "created_at": "2024-01-15T10:30:00Z",
                            "consensus_reached": False,
                        }
                    }
                }
            }
        },
    },
    "GET /api/debates/{id}": {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "example": {
                            "id": "dbt_xyz789",
                            "status": "completed",
                            "question": "Should we adopt TypeScript for our backend services?",
                            "agents": ["claude-3-opus", "gpt-4", "gemini-pro"],
                            "current_round": 3,
                            "total_rounds": 3,
                            "created_at": "2024-01-15T10:30:00Z",
                            "completed_at": "2024-01-15T10:35:00Z",
                            "consensus_reached": True,
                            "verdict": "Adopt TypeScript for new services, migrate existing services gradually",
                            "confidence": 0.85,
                            "proposals": [
                                {
                                    "agent": "claude-3-opus",
                                    "content": "TypeScript offers significant benefits...",
                                    "round": 1,
                                }
                            ],
                            "votes": {
                                "claude-3-opus": "approve",
                                "gpt-4": "approve",
                                "gemini-pro": "approve",
                            },
                        }
                    }
                }
            }
        }
    },
    # Gauntlet
    "POST /api/gauntlet/runs": {
        "requestBody": {
            "content": {
                "application/json": {
                    "example": {
                        "debate_id": "dbt_xyz789",
                        "attack_types": ["adversarial", "edge_case", "contradiction"],
                        "defender_agent": "claude-3-opus",
                        "max_iterations": 5,
                        "confidence_threshold": 0.8,
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "example": {
                            "run_id": "gnt_abc123",
                            "status": "running",
                            "debate_id": "dbt_xyz789",
                            "started_at": "2024-01-15T10:40:00Z",
                            "attack_count": 0,
                            "defense_count": 0,
                        }
                    }
                }
            }
        },
    },
    # Workflows
    "POST /api/workflows": {
        "requestBody": {
            "content": {
                "application/json": {
                    "example": {
                        "name": "Code Review Workflow",
                        "template_id": "tpl_code_review",
                        "workspace_id": "ws_abc123",
                        "inputs": {
                            "repository": "https://github.com/org/repo",
                            "pull_request": 42,
                            "review_depth": "thorough",
                        },
                        "schedule": {"trigger": "on_pr_open", "filters": ["*.py", "*.ts"]},
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "example": {
                            "id": "wf_def456",
                            "name": "Code Review Workflow",
                            "status": "pending",
                            "template_id": "tpl_code_review",
                            "created_at": "2024-01-15T10:45:00Z",
                        }
                    }
                }
            }
        },
    },
    # Agents
    "GET /api/agents": {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "example": {
                            "agents": [
                                {
                                    "id": "claude-3-opus",
                                    "name": "Claude 3 Opus",
                                    "provider": "anthropic",
                                    "capabilities": ["reasoning", "coding", "analysis"],
                                    "status": "available",
                                    "elo_rating": 1850,
                                },
                                {
                                    "id": "gpt-4",
                                    "name": "GPT-4",
                                    "provider": "openai",
                                    "capabilities": ["reasoning", "coding", "creative"],
                                    "status": "available",
                                    "elo_rating": 1820,
                                },
                            ],
                            "total": 2,
                        }
                    }
                }
            }
        }
    },
    # Receipts
    "GET /api/receipts/{id}": {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "example": {
                            "receipt_id": "rcp_ghi789",
                            "debate_id": "dbt_xyz789",
                            "verdict": "Adopt TypeScript for new services",
                            "confidence": 0.85,
                            "risk_level": "LOW",
                            "risk_score": 0.15,
                            "checksum": "sha256:abc123...",
                            "created_at": "2024-01-15T10:35:00Z",
                            "participants": ["claude-3-opus", "gpt-4", "gemini-pro"],
                            "consensus_proof": {
                                "type": "supermajority",
                                "threshold": 0.7,
                                "achieved": 1.0,
                            },
                        }
                    }
                }
            }
        }
    },
    # Health
    "GET /api/health": {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "example": {
                            "status": "healthy",
                            "version": "2.2.0",
                            "uptime_seconds": 86400,
                            "timestamp": "2024-01-15T10:00:00Z",
                        }
                    }
                }
            }
        }
    },
    "GET /api/health/detailed": {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "example": {
                            "status": "healthy",
                            "version": "2.2.0",
                            "components": {
                                "database": {"status": "healthy", "latency_ms": 5},
                                "redis": {"status": "healthy", "latency_ms": 2},
                                "agents": {"status": "healthy", "available": 15},
                            },
                            "uptime_seconds": 86400,
                            "timestamp": "2024-01-15T10:00:00Z",
                        }
                    }
                }
            }
        }
    },
    # Budgets
    "POST /api/budgets": {
        "requestBody": {
            "content": {
                "application/json": {
                    "example": {
                        "name": "Q1 AI Budget",
                        "workspace_id": "ws_abc123",
                        "limit_usd": 5000.00,
                        "period": "monthly",
                        "alerts": {"thresholds": [0.5, 0.8, 0.95], "notify": ["admin@example.com"]},
                    }
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "example": {
                            "id": "bgt_jkl012",
                            "name": "Q1 AI Budget",
                            "limit_usd": 5000.00,
                            "spent_usd": 0.00,
                            "remaining_usd": 5000.00,
                            "period": "monthly",
                            "created_at": "2024-01-15T10:50:00Z",
                        }
                    }
                }
            }
        },
    },
    # Rankings
    "GET /api/rankings": {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "example": {
                            "rankings": [
                                {
                                    "agent": "claude-3-opus",
                                    "elo": 1850,
                                    "wins": 142,
                                    "losses": 58,
                                    "rank": 1,
                                },
                                {
                                    "agent": "gpt-4",
                                    "elo": 1820,
                                    "wins": 135,
                                    "losses": 65,
                                    "rank": 2,
                                },
                                {
                                    "agent": "gemini-pro",
                                    "elo": 1780,
                                    "wins": 120,
                                    "losses": 80,
                                    "rank": 3,
                                },
                            ],
                            "updated_at": "2024-01-15T10:00:00Z",
                        }
                    }
                }
            }
        }
    },
}


def add_examples(spec: dict) -> tuple[dict, int]:
    """Add examples to specified endpoints.

    Returns: (updated_spec, examples_added)
    """
    added = 0

    for endpoint_key, examples in ENDPOINT_EXAMPLES.items():
        method, path = endpoint_key.split(" ", 1)
        method = method.lower()

        if path not in spec.get("paths", {}):
            continue
        if method not in spec["paths"][path]:
            continue

        endpoint = spec["paths"][path][method]

        # Add request body example
        if "requestBody" in examples:
            if "requestBody" in endpoint:
                for content_type, content_data in (
                    examples["requestBody"].get("content", {}).items()
                ):
                    if content_type in endpoint["requestBody"].get("content", {}):
                        endpoint["requestBody"]["content"][content_type]["example"] = content_data[
                            "example"
                        ]
                        added += 1

        # Add response examples
        if "responses" in examples:
            for status_code, response_data in examples["responses"].items():
                if status_code in endpoint.get("responses", {}):
                    for content_type, content_data in response_data.get("content", {}).items():
                        if "content" not in endpoint["responses"][status_code]:
                            endpoint["responses"][status_code]["content"] = {}
                        if content_type not in endpoint["responses"][status_code]["content"]:
                            endpoint["responses"][status_code]["content"][content_type] = {}
                        endpoint["responses"][status_code]["content"][content_type]["example"] = (
                            content_data["example"]
                        )
                        added += 1

    return spec, added


def main():
    """Main entry point."""
    spec_path = Path("docs/api/openapi.json")

    if not spec_path.exists():
        print(f"Error: {spec_path} not found")
        sys.exit(1)

    print(f"Reading {spec_path}...")
    with open(spec_path) as f:
        spec = json.load(f)

    print("Adding examples...")
    spec, added = add_examples(spec)

    print(f"Writing {spec_path}...")
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2)

    print("\nResults:")
    print(f"  - Examples added: {added}")


if __name__ == "__main__":
    main()
