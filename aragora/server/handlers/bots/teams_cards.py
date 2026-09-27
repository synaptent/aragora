"""
Microsoft Teams Adaptive Card templates for Aragora.

Provides pre-built Adaptive Card templates for Teams integration:
- Debate cards (topic, progress, agents)
- Voting interfaces (approve/reject/abstain)
- Consensus result cards
- Leaderboard/standings cards
- Progress update cards

All cards follow Microsoft Adaptive Cards Schema v1.4+.

Usage:
    from aragora.server.handlers.bots.teams_cards import (
        create_debate_card,
        create_voting_card,
        create_consensus_card,
    )

    card = create_debate_card(
        debate_id="debate-123",
        topic="Should we adopt microservices?",
        agents=["claude", "gpt-4", "gemini"],
        progress=50,
    )
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Adaptive Card schema version
SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
VERSION = "1.4"


def _base_card() -> dict[str, Any]:
    """Create base Adaptive Card structure."""
    return {
        "$schema": SCHEMA,
        "type": "AdaptiveCard",
        "version": VERSION,
        "body": [],
        "actions": [],
    }


def _header(text: str, size: str = "Large", color: str | None = None) -> dict[str, Any]:
    """Create a header text block."""
    block = {
        "type": "TextBlock",
        "text": text,
        "weight": "Bolder",
        "size": size,
        "wrap": True,
    }
    if color:
        block["color"] = color
    return block


def _text(text: str, wrap: bool = True, size: str = "Default") -> dict[str, Any]:
    """Create a text block."""
    return {
        "type": "TextBlock",
        "text": text,
        "wrap": wrap,
        "size": size,
    }


def _fact_set(facts: list[tuple[str, str]]) -> dict[str, Any]:
    """Create a fact set from key-value pairs."""
    return {
        "type": "FactSet",
        "facts": [{"title": k, "value": v} for k, v in facts],
    }


def _submit_action(title: str, data: dict[str, Any], style: str | None = None) -> dict[str, Any]:
    """Create a submit action button."""
    action = {
        "type": "Action.Submit",
        "title": title,
        "data": data,
    }
    if style:
        action["style"] = style
    return action


def _column_set(columns: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a column set."""
    return {
        "type": "ColumnSet",
        "columns": columns,
    }


def _column(items: list[dict[str, Any]], width: str = "auto") -> dict[str, Any]:
    """Create a column."""
    return {
        "type": "Column",
        "width": width,
        "items": items,
    }


def _progress_bar(value: int, label: str | None = None) -> list[dict[str, Any]]:
    """Create a visual progress bar using ColumnSets.

    Since Adaptive Cards don't have a native progress bar, we simulate one
    using colored containers.
    """
    elements: list[dict[str, Any]] = []

    if label:
        elements.append(_text(label, size="Small"))

    # Create progress visualization
    filled_width = max(1, value)
    empty_width = max(1, 100 - value)

    elements.append(
        {
            "type": "ColumnSet",
            "columns": [
                {
                    "type": "Column",
                    "width": str(filled_width),
                    "items": [
                        {
                            "type": "Container",
                            "style": "good",
                            "minHeight": "8px",
                        }
                    ],
                },
                {
                    "type": "Column",
                    "width": str(empty_width),
                    "items": [
                        {
                            "type": "Container",
                            "style": "default",
                            "minHeight": "8px",
                        }
                    ],
                },
            ],
            "spacing": "None",
        }
    )

    elements.append(_text(f"{value}%", size="Small"))

    return elements


def create_debate_card(
    debate_id: str,
    topic: str,
    agents: list[str],
    progress: int = 0,
    current_round: int = 1,
    total_rounds: int = 3,
    status: str = "in_progress",
) -> dict[str, Any]:
    """Create an Adaptive Card for displaying debate information.

    Args:
        debate_id: Unique debate identifier
        topic: The debate topic/question
        agents: List of participating agent names
        progress: Percentage complete (0-100)
        current_round: Current round number
        total_rounds: Total number of rounds
        status: Debate status (pending, in_progress, completed)

    Returns:
        Adaptive Card dictionary
    """
    card = _base_card()

    # Status indicator
    status_color = {
        "pending": "Warning",
        "in_progress": "Accent",
        "completed": "Good",
        "failed": "Attention",
    }.get(status, "Default")

    status_icon = {
        "pending": "Pending",
        "in_progress": "In Progress",
        "completed": "Completed",
        "failed": "Failed",
    }.get(status, status.title())

    # Header with status
    card["body"].append(_header(f"Debate: {topic}"))

    # Status badge
    card["body"].append(
        {
            "type": "TextBlock",
            "text": f"Status: {status_icon}",
            "color": status_color,
            "weight": "Bolder",
            "size": "Small",
        }
    )

    # Progress bar
    if status == "in_progress":
        card["body"].extend(_progress_bar(progress, f"Round {current_round}/{total_rounds}"))

    # Agent list
    card["body"].append(
        _fact_set(
            [
                ("Debate ID", debate_id[:12] + "..." if len(debate_id) > 12 else debate_id),
                ("Agents", ", ".join(agents)),
                ("Rounds", f"{current_round}/{total_rounds}"),
            ]
        )
    )

    # Actions based on status
    if status in ("in_progress", "completed"):
        card["actions"].append(
            _submit_action(
                "Vote Approve",
                {"action": "vote", "value": "approve", "debate_id": debate_id},
                style="positive",
            )
        )
        card["actions"].append(
            _submit_action(
                "Vote Reject",
                {"action": "vote", "value": "reject", "debate_id": debate_id},
                style="destructive",
            )
        )
        card["actions"].append(
            _submit_action(
                "Abstain",
                {"action": "vote", "value": "abstain", "debate_id": debate_id},
            )
        )

    if status == "in_progress":
        card["actions"].append(
            _submit_action(
                "View Details",
                {"action": "view_details", "debate_id": debate_id},
            )
        )

    return card


def create_voting_card(
    debate_id: str,
    topic: str,
    options: list[dict[str, str]] | None = None,
    deadline: str | None = None,
) -> dict[str, Any]:
    """Create an interactive voting card.

    Args:
        debate_id: Debate identifier
        topic: What users are voting on
        options: Custom voting options (default: approve/reject/abstain)
        deadline: Optional voting deadline string

    Returns:
        Adaptive Card with voting buttons
    """
    card = _base_card()

    card["body"].append(_header("Cast Your Vote", size="Medium"))
    card["body"].append(_text(topic))

    if deadline:
        card["body"].append(
            {
                "type": "TextBlock",
                "text": f"Deadline: {deadline}",
                "color": "Warning",
                "size": "Small",
                "isSubtle": True,
            }
        )

    card["body"].append(
        {
            "type": "Container",
            "separator": True,
            "spacing": "Medium",
            "items": [
                _text("Select your position:", size="Small"),
            ],
        }
    )

    # Default or custom options
    if options is None:
        effective_options: list[dict[str, Any]] = [
            {"value": "approve", "label": "Approve", "style": "positive"},
            {"value": "reject", "label": "Reject", "style": "destructive"},
            {"value": "abstain", "label": "Abstain", "style": None},
        ]
    else:
        effective_options = options

    for opt in effective_options:
        card["actions"].append(
            _submit_action(
                opt.get("label", opt["value"].title()),
                {"action": "vote", "value": opt["value"], "debate_id": debate_id},
                style=opt.get("style"),
            )
        )

    return card


def create_consensus_card(
    debate_id: str,
    topic: str,
    consensus_type: str,
    final_answer: str,
    confidence: float,
    supporting_agents: list[str],
    dissenting_agents: list[str] | None = None,
    key_points: list[str] | None = None,
    vote_summary: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Create a consensus result card.

    Args:
        debate_id: Debate identifier
        topic: Original debate topic
        consensus_type: Type of consensus reached
        final_answer: The consensus conclusion
        confidence: Confidence score (0-1)
        supporting_agents: Agents that supported consensus
        dissenting_agents: Agents that dissented
        key_points: Key points from the debate
        vote_summary: Vote counts by type

    Returns:
        Adaptive Card showing consensus results
    """
    card = _base_card()

    # Determine color based on confidence
    confidence_color = (
        "Good" if confidence >= 0.7 else "Warning" if confidence >= 0.4 else "Attention"
    )

    # Header
    card["body"].append(_header("Consensus Reached", color="Good"))
    card["body"].append(
        {
            "type": "TextBlock",
            "text": topic,
            "isSubtle": True,
            "wrap": True,
        }
    )

    # Consensus type and confidence
    card["body"].append(
        {
            "type": "Container",
            "style": "emphasis",
            "items": [
                {
                    "type": "TextBlock",
                    "text": consensus_type.replace("_", " ").title(),
                    "weight": "Bolder",
                },
                {
                    "type": "TextBlock",
                    "text": f"Confidence: {confidence:.0%}",
                    "color": confidence_color,
                },
            ],
        }
    )

    # Final answer
    card["body"].append(
        {
            "type": "Container",
            "separator": True,
            "spacing": "Medium",
            "items": [
                _header("Decision", size="Medium"),
                _text(final_answer),
            ],
        }
    )

    # Agent breakdown
    facts = [("Supporting", ", ".join(supporting_agents))]
    if dissenting_agents:
        facts.append(("Dissenting", ", ".join(dissenting_agents)))
    card["body"].append(_fact_set(facts))

    # Key points
    if key_points:
        card["body"].append(
            {
                "type": "Container",
                "separator": True,
                "items": [
                    _header("Key Points", size="Small"),
                    *[_text(f"- {point}") for point in key_points[:5]],
                ],
            }
        )

    # Vote summary
    if vote_summary:
        vote_text = ", ".join(f"{k}: {v}" for k, v in vote_summary.items())
        card["body"].append(_text(f"Votes: {vote_text}", size="Small"))

    # Actions
    card["actions"].append(
        _submit_action(
            "View Full Report",
            {"action": "view_report", "debate_id": debate_id},
        )
    )
    card["actions"].append(
        _submit_action(
            "Share Result",
            {"action": "share", "debate_id": debate_id},
        )
    )

    return card


def create_leaderboard_card(
    standings: list[dict[str, Any]],
    period: str = "all_time",
    title: str = "Agent Leaderboard",
) -> dict[str, Any]:
    """Create a leaderboard/standings card.

    Args:
        standings: List of agent standings with name, score, wins, etc.
        period: Time period (today, week, month, all_time)
        title: Card title

    Returns:
        Adaptive Card showing leaderboard
    """
    card = _base_card()

    card["body"].append(_header(title))
    card["body"].append(_text(f"Period: {period.replace('_', ' ').title()}", size="Small"))

    # Create standings table
    for i, entry in enumerate(standings[:10], 1):
        name = entry.get("name", "Unknown")
        score = entry.get("score", entry.get("elo", 0))
        wins = entry.get("wins", 0)
        debates = entry.get("debates", entry.get("total_debates", 0))

        # Medal emoji for top 3
        medal = {1: "1st", 2: "2nd", 3: "3rd"}.get(i, f"{i}th")

        # Color for position
        color = "Good" if i <= 3 else "Default"

        card["body"].append(
            {
                "type": "ColumnSet",
                "columns": [
                    _column([_text(medal, size="Small")], width="40px"),
                    _column(
                        [
                            {
                                "type": "TextBlock",
                                "text": name,
                                "weight": "Bolder" if i <= 3 else "Default",
                                "color": color,
                            }
                        ],
                        width="stretch",
                    ),
                    _column([_text(f"{score:.0f}", size="Small")], width="60px"),
                    _column([_text(f"{wins}W/{debates}D", size="Small")], width="80px"),
                ],
                "separator": i == 1,
            }
        )

    card["actions"].append(
        _submit_action(
            "Full Rankings",
            {"action": "view_rankings", "period": period},
        )
    )

    return card


def create_debate_progress_card(
    debate_id: str,
    topic: str,
    current_round: int,
    total_rounds: int,
    current_phase: str,
    agent_messages: list[dict[str, str]] | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Create a debate progress update card.

    Args:
        debate_id: Debate identifier
        topic: Debate topic
        current_round: Current round number
        total_rounds: Total rounds
        current_phase: Current phase name
        agent_messages: Recent agent messages (name, preview)
        timestamp: Update timestamp

    Returns:
        Adaptive Card showing progress
    """
    card = _base_card()

    progress = int((current_round / total_rounds) * 100)

    card["body"].append(_header("Debate Update", size="Medium"))
    card["body"].append(
        {
            "type": "TextBlock",
            "text": topic,
            "isSubtle": True,
            "wrap": True,
            "size": "Small",
        }
    )

    # Progress indicator
    card["body"].extend(_progress_bar(progress))

    card["body"].append(
        _fact_set(
            [
                ("Round", f"{current_round}/{total_rounds}"),
                ("Phase", current_phase.replace("_", " ").title()),
            ]
        )
    )

    # Recent messages
    if agent_messages:
        card["body"].append(
            {
                "type": "Container",
                "separator": True,
                "items": [
                    _header("Recent Activity", size="Small"),
                ],
            }
        )

        for msg in agent_messages[:3]:
            agent_name = msg.get("agent", "Agent")
            preview = msg.get("preview", "...")
            if len(preview) > 80:
                preview = preview[:80] + "..."

            card["body"].append(
                {
                    "type": "TextBlock",
                    "text": f"**{agent_name}**: {preview}",
                    "wrap": True,
                    "size": "Small",
                }
            )

    if timestamp:
        card["body"].append(
            {
                "type": "TextBlock",
                "text": f"Updated: {timestamp.strftime('%H:%M:%S')}",
                "isSubtle": True,
                "size": "Small",
            }
        )

    card["actions"].append(
        _submit_action(
            "Watch Live",
            {"action": "watch", "debate_id": debate_id},
        )
    )

    return card


def create_error_card(
    title: str,
    message: str,
    error_code: str | None = None,
    retry_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an error notification card.

    Args:
        title: Error title
        message: Error description
        error_code: Optional error code
        retry_action: Optional retry action data

    Returns:
        Adaptive Card showing error
    """
    card = _base_card()

    card["body"].append(_header(title, color="Attention"))
    card["body"].append(_text(message))

    if error_code:
        card["body"].append(
            {
                "type": "TextBlock",
                "text": f"Error Code: {error_code}",
                "isSubtle": True,
                "size": "Small",
            }
        )

    if retry_action:
        card["actions"].append(
            _submit_action(
                "Retry",
                retry_action,
                style="positive",
            )
        )

    card["actions"].append(
        _submit_action(
            "Get Help",
            {"action": "help"},
        )
    )

    return card


def create_help_card(
    commands: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Create a help/commands card.

    Args:
        commands: List of command info (name, description)

    Returns:
        Adaptive Card showing available commands
    """
    card = _base_card()

    default_commands = [
        {"name": "/aragora debate", "desc": 'Start a new debate: `/aragora debate "topic"`'},
        {"name": "/aragora plan", "desc": 'Debate + implementation plan: `/aragora plan "topic"`'},
        {
            "name": "/aragora implement",
            "desc": 'Debate + plan with context snapshot: `/aragora implement "topic"`',
        },
        {"name": "/aragora status", "desc": "Check debate status"},
        {"name": "/aragora vote", "desc": "Vote on active debate"},
        {"name": "/aragora leaderboard", "desc": "View agent rankings"},
        {"name": "/aragora gauntlet", "desc": "Run gauntlet validation"},
        {"name": "/aragora help", "desc": "Show this help"},
    ]

    commands = commands or default_commands

    card["body"].append(_header("Aragora Commands"))
    card["body"].append(
        _text(
            "Multi-agent debate system for better decisions. "
            "Use these commands to interact with Aragora."
        )
    )

    card["body"].append(
        {
            "type": "Container",
            "separator": True,
            "items": [
                {
                    "type": "TextBlock",
                    "text": f"**{cmd['name']}**\n{cmd['desc']}",
                    "wrap": True,
                    "spacing": "Small",
                }
                for cmd in commands
            ],
        }
    )

    card["actions"].append(
        {
            "type": "Action.OpenUrl",
            "title": "Documentation",
            "url": "https://docs.aragora.ai",
        }
    )

    return card


__all__ = [
    "create_debate_card",
    "create_voting_card",
    "create_consensus_card",
    "create_leaderboard_card",
    "create_debate_progress_card",
    "create_error_card",
    "create_help_card",
]
