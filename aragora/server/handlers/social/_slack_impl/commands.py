"""
Slack slash command implementations.

Handles all /aragora slash commands: help, status, debate, plan, implement, gauntlet, ask,
search, leaderboard, recent, agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs

from aragora.config import DEFAULT_ROUNDS
from aragora.utils.public_urls import public_receipt_url

if TYPE_CHECKING:
    from aragora.agents.base import AgentType

try:
    from aragora.server.storage import get_debates_db
except ImportError:  # pragma: no cover - optional dependency for tests
    get_debates_db = None  # type: ignore[assignment]

from .config import (
    ARAGORA_API_BASE_URL,
    SLACK_BOT_TOKEN,
    HandlerResult,
    auto_error_response,
    _get_audit_logger,
    _get_user_rate_limiter,
    _get_workspace_rate_limiter,
    create_tracked_task,
)
from .config import rate_limit
from .blocks import BlocksMixin

logger = logging.getLogger(__name__)


class CommandsMixin(BlocksMixin):
    """Mixin providing slash command handling for the Slack handler."""

    @auto_error_response("handle slack slash command")
    @rate_limit(requests_per_minute=30, limiter_name="slack_commands")
    def _handle_slash_command(self, handler: Any) -> HandlerResult:
        """Handle Slack slash commands.

        Expected format: /aragora <command> [args]

        Commands:
        - /aragora debate "topic" - Start a debate on a topic
        - /aragora plan "topic" - Debate with an implementation plan
        - /aragora implement "topic" - Debate with plan + context snapshot
        - /aragora status - Get system status
        - /aragora help - Show available commands
        """
        start_time = time.time()
        command = ""
        subcommand = ""
        user_id = ""
        channel_id = ""
        team_id: str | None = None

        try:
            # Parse form-encoded body (already read and stored in handle())
            body = getattr(handler, "_slack_body", "")
            params = parse_qs(body)
            workspace = getattr(handler, "_slack_workspace", None)
            team_id = getattr(handler, "_slack_team_id", None)

            command = params.get("command", [""])[0]
            text = params.get("text", [""])[0].strip()
            user_id = params.get("user_id", [""])[0]
            channel_id = params.get("channel_id", [""])[0]
            response_url = params.get("response_url", [""])[0]

            logger.info("Slack command from %s: %s %s", user_id, command, text)

            # Per-workspace rate limiting (team_id as key)
            workspace_limiter = _get_workspace_rate_limiter()
            if workspace_limiter and team_id:
                workspace_key = f"slack_workspace:{team_id}"
                ws_rate_result = workspace_limiter.allow(workspace_key, "slack_workspace_command")
                if not ws_rate_result.allowed:
                    logger.warning(
                        "Slack workspace rate limited: %s (retry_after=%ss)",
                        workspace_key,
                        ws_rate_result.retry_after,
                    )
                    # Audit log workspace rate limit event
                    audit = _get_audit_logger()
                    if audit:
                        audit.log_rate_limit(
                            workspace_id=team_id,
                            user_id=user_id,
                            command=command,
                            limit_type="workspace",
                        )
                    return self._slack_response(
                        f"This workspace is sending commands too quickly. "
                        f"Please wait {int(ws_rate_result.retry_after)} seconds.",
                        response_type="ephemeral",
                    )

            # Per-user rate limiting (workspace_id:user_id as key)
            user_limiter = _get_user_rate_limiter()
            if user_limiter and user_id:
                # Create unique key for this Slack user
                user_key = f"slack:{team_id or 'unknown'}:{user_id}"
                rate_result = user_limiter.allow(user_key, "slack_command")
                if not rate_result.allowed:
                    logger.warning(
                        "Slack user rate limited: %s (retry_after=%ss)",
                        user_key,
                        rate_result.retry_after,
                    )
                    # Audit log rate limit event
                    audit = _get_audit_logger()
                    if audit:
                        audit.log_rate_limit(
                            workspace_id=team_id or "",
                            user_id=user_id,
                            command=command,
                            limit_type="user",
                        )
                    return self._slack_response(
                        f"You're sending commands too quickly. Please wait {int(rate_result.retry_after)} seconds.",
                        response_type="ephemeral",
                    )

            # Parse the subcommand
            if not text:
                result = self._command_help()
                subcommand = "help"
            else:
                parts = text.split(maxsplit=1)
                subcommand = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""

                if subcommand == "help":
                    result = self._command_help()
                elif subcommand == "status":
                    result = self._command_status()
                elif subcommand == "debate":
                    result = self._command_debate(
                        args, user_id, channel_id, response_url, workspace, team_id
                    )
                elif subcommand == "plan":
                    decision_integrity = {
                        "include_receipt": True,
                        "include_plan": True,
                        "include_context": False,
                        "plan_strategy": "single_task",
                        "notify_origin": True,
                        "requested_by": f"slack:{user_id}",
                    }
                    result = self._command_debate(
                        args,
                        user_id,
                        channel_id,
                        response_url,
                        workspace,
                        team_id,
                        decision_integrity=decision_integrity,
                        mode_label="plan",
                    )
                elif subcommand == "implement":
                    decision_integrity = {
                        "include_receipt": True,
                        "include_plan": True,
                        "include_context": True,
                        "plan_strategy": "single_task",
                        "notify_origin": True,
                        "execution_mode": "execute",
                        "execution_engine": "hybrid",
                        "requested_by": f"slack:{user_id}",
                    }
                    result = self._command_debate(
                        args,
                        user_id,
                        channel_id,
                        response_url,
                        workspace,
                        team_id,
                        decision_integrity=decision_integrity,
                        mode_label="implementation plan",
                        command_label="implement",
                    )
                elif subcommand == "gauntlet":
                    result = self._command_gauntlet(
                        args, user_id, channel_id, response_url, workspace, team_id
                    )
                elif subcommand == "approve":
                    result = self._command_approve(args, user_id, channel_id)
                elif subcommand == "reject":
                    result = self._command_reject(args, user_id, channel_id)
                elif subcommand == "stop":
                    result = self._command_stop(
                        args, user_id, channel_id, response_url, workspace, team_id
                    )
                elif subcommand == "agents":
                    result = self._command_agents()
                elif subcommand == "ask":
                    result = self._command_ask(
                        args, user_id, channel_id, response_url, workspace, team_id
                    )
                elif subcommand == "search":
                    result = self._command_search(args)
                elif subcommand == "leaderboard":
                    result = self._command_leaderboard()
                elif subcommand == "recent":
                    result = self._command_recent()
                else:
                    result = self._slack_response(
                        f"Unknown command: `{subcommand}`. Use `/aragora help` for available commands.",
                        response_type="ephemeral",
                    )

            # Audit log successful command
            audit = _get_audit_logger()
            if audit:
                response_time_ms = (time.time() - start_time) * 1000
                audit.log_command(
                    workspace_id=team_id or "",
                    user_id=user_id,
                    command=f"{command} {subcommand}".strip(),
                    args=args if "args" in dir() else "",
                    result="success",
                    channel_id=channel_id,
                    response_time_ms=response_time_ms,
                )

            return result

        except (ValueError, KeyError, TypeError, RuntimeError, OSError, ConnectionError) as e:
            logger.error("Slash command error: %s", e, exc_info=True)

            # Audit log error
            audit = _get_audit_logger()
            if audit:
                response_time_ms = (time.time() - start_time) * 1000
                audit.log_command(
                    workspace_id=team_id or "",
                    user_id=user_id,
                    command=f"{command} {subcommand}".strip(),
                    result="error",
                    channel_id=channel_id,
                    response_time_ms=response_time_ms,
                    error="Command execution failed",
                )

            return self._slack_response(
                "An error occurred processing the command. Please try again later.",
                response_type="ephemeral",
            )

    def _command_help(self) -> HandlerResult:
        """Show help message."""
        help_text = """*Aragora Slash Commands*

*Core Commands:*
`/aragora debate "topic"` - Start a multi-agent debate on a topic
`/aragora plan "topic"` - Debate with an implementation plan
`/aragora implement "topic"` - Debate with plan + context snapshot
`/aragora ask "question"` - Quick Q&A without full debate
`/aragora gauntlet "statement"` - Run adversarial stress-test validation
`/aragora stop [debate_id]` - Stop a running debate

*Approval:*
`/aragora approve <debate_id>` - Approve a debate decision
`/aragora reject <debate_id> [reason]` - Reject a debate decision

*Discovery:*
`/aragora search "query"` - Search debates and evidence
`/aragora recent` - Show recent debates
`/aragora leaderboard` - View agent rankings

*Info:*
`/aragora agents` - List available agents
`/aragora status` - Get system status
`/aragora help` - Show this help message

*Thread Interaction:*
React with emoji to vote (thumbs up/down counted)
Reply in thread to add suggestions to ongoing debates

*Examples:*
- `/aragora debate "Should AI be regulated?"`
- `/aragora ask "What is the capital of France?"`
- `/aragora gauntlet "We should migrate to microservices"`
- `/aragora search "machine learning"`
"""
        return self._slack_response(help_text, response_type="ephemeral")

    def _command_status(self) -> HandlerResult:
        """Get system status."""
        try:
            # Get basic stats
            from aragora.ranking.elo import EloSystem

            store = EloSystem()
            agents = store.get_all_ratings()

            blocks: list[dict[str, Any]] = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Aragora System Status",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Agents:* {len(agents)}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": "*Status:* Online",
                        },
                    ],
                },
            ]

            return self._slack_blocks_response(
                blocks,
                text="Aragora is online",
                response_type="ephemeral",
            )

        except ImportError as e:
            logger.warning("ELO system not available for status: %s", e)
            return self._slack_response(
                "Status service temporarily unavailable",
                response_type="ephemeral",
            )
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Data error in status command: %s", e)
            return self._slack_response(
                "Error getting status. Please try again later.",
                response_type="ephemeral",
            )
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("Unexpected status command error: %s", e)
            return self._slack_response(
                "Error getting status. Please try again later.",
                response_type="ephemeral",
            )

    def _command_agents(self) -> HandlerResult:
        """List available agents."""
        try:
            from aragora.ranking.elo import EloSystem

            store = EloSystem()
            agents = store.get_all_ratings()

            if not agents:
                return self._slack_response(
                    "No agents registered yet.",
                    response_type="ephemeral",
                )

            # Sort by ELO
            agents = sorted(agents, key=lambda a: getattr(a, "elo", 1500), reverse=True)

            text = "*Top Agents by ELO:*\n"
            for i, agent in enumerate(agents[:10]):
                name = getattr(agent, "name", "Unknown")
                elo = getattr(agent, "elo", 1500)
                wins = getattr(agent, "wins", 0)
                medal = ["\U0001f947", "\U0001f948", "\U0001f949"][i] if i < 3 else f"{i + 1}."
                text += f"{medal} *{name}* - ELO: {elo:.0f} | Wins: {wins}\n"

            return self._slack_response(text, response_type="ephemeral")

        except ImportError as e:
            logger.warning("ELO system not available for agents listing: %s", e)
            return self._slack_response(
                "Agents service temporarily unavailable",
                response_type="ephemeral",
            )
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Data error in agents command: %s", e)
            return self._slack_response(
                "Error listing agents. Please try again later.",
                response_type="ephemeral",
            )
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("Unexpected agents command error: %s", e)
            return self._slack_response(
                "Error listing agents. Please try again later.",
                response_type="ephemeral",
            )

    def _command_ask(
        self,
        args: str,
        user_id: str,
        channel_id: str,
        response_url: str,
        workspace: Any | None = None,
        team_id: str | None = None,
    ) -> HandlerResult:
        """Quick Q&A without full debate - uses single agent for fast answers.

        Args:
            args: The question to answer
            user_id: Slack user ID
            channel_id: Slack channel ID
            response_url: URL for async responses
            workspace: Resolved workspace object (for multi-workspace)
            team_id: Slack team/workspace ID
        """
        if not args:
            return self._slack_response(
                'Please provide a question. Example: `/aragora ask "What is the capital of France?"`',
                response_type="ephemeral",
            )

        # Strip quotes if present
        question = args.strip().strip("\"'")

        if len(question) < 5:
            return self._slack_response(
                "Question is too short. Please provide more detail.",
                response_type="ephemeral",
            )

        if len(question) > 500:
            return self._slack_response(
                "Question is too long. Please limit to 500 characters.",
                response_type="ephemeral",
            )

        # Acknowledge immediately
        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Processing question:*\n_{question[:200]}{'...' if len(question) > 200 else ''}_",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Asked by <@{user_id}> | Thinking...",
                    },
                ],
            },
        ]

        # Queue the question asynchronously
        if response_url:
            create_tracked_task(
                lambda: self._answer_question_async(question, response_url, user_id, channel_id),
                name=f"slack-ask-{question[:30]}",
            )

        return self._slack_blocks_response(
            blocks,
            text=f"Processing: {question[:50]}...",
            response_type="in_channel",
        )

    async def _answer_question_async(
        self,
        question: str,
        response_url: str,
        user_id: str,
        channel_id: str,
    ) -> None:
        """Answer a question asynchronously using a single agent."""

        try:
            # Call the debate engine directly instead of HTTP self-call.
            # Self-calls hit auth middleware which rejects the API token format.
            from aragora.agents.base import create_agent
            from aragora.core import Environment
            from aragora.debate.orchestrator import Arena, DebateProtocol
            from aragora.cli.commands.quickstart import _detect_agents

            env = Environment(task=question)
            protocol = DebateProtocol(
                rounds=2,
                consensus="majority",
                convergence_detection=True,
                enable_research=False,
                enable_trending_injection=False,
            )

            # Detect available agents from env API keys — use up to 3 for better consensus
            detected = _detect_agents()
            if not detected:
                raise RuntimeError("No API keys configured for debate agents")

            agents = []
            roles = ["proposer", "critic", "synthesizer"]
            for i, (agent_type, model) in enumerate(detected[:3]):
                agents.append(
                    create_agent(
                        cast("AgentType", agent_type),
                        name=f"agent-{i}",
                        role=roles[i % len(roles)],
                        model=model,
                    )
                )

            arena = Arena(env, agents, protocol)
            result = await asyncio.wait_for(arena.run(), timeout=120)

            # Extract answer with confidence check
            answer = str(
                getattr(result, "final_answer", None) or getattr(result, "summary", None) or ""
            )
            confidence = float(getattr(result, "confidence", 0.0) or 0.0)

            # Fail closed: don't post confidently wrong answers
            if not answer or (confidence > 0 and confidence < 0.3):
                answer = (
                    "I wasn't able to reach a confident answer on this question. "
                    "Try rephrasing or using `/aragora debate` for a deeper analysis."
                )

            # Build response blocks
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Question:*\n_{question[:200]}{'...' if len(question) > 200 else ''}_",
                    },
                },
                {
                    "type": "divider",
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Answer:*\n{answer[:2000] if answer else 'No answer available'}",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Asked by <@{user_id}>",
                        },
                    ],
                },
            ]

            await self._post_to_response_url(
                response_url,
                {
                    "response_type": "in_channel",
                    "text": f"Answer: {answer[:100] if answer else 'No answer'}...",
                    "blocks": blocks,
                    "replace_original": False,
                },
            )

        except (
            OSError,
            asyncio.TimeoutError,
            json.JSONDecodeError,
            ValueError,
            KeyError,
        ) as e:
            logger.error("Async question answering failed: %s", e, exc_info=True)
            await self._post_to_response_url(
                response_url,
                {
                    "response_type": "in_channel",
                    "text": "Failed to answer question. Please try again later.",
                    "replace_original": False,
                },
            )

    def _command_search(self, args: str) -> HandlerResult:
        """Search debates and evidence."""
        if not args:
            return self._slack_response(
                'Please provide a search query. Example: `/aragora search "machine learning"`',
                response_type="ephemeral",
            )

        query = args.strip().strip("\"'")

        if len(query) < 2:
            return self._slack_response(
                "Search query is too short.",
                response_type="ephemeral",
            )

        try:
            if get_debates_db is None:
                raise RuntimeError("Debates DB not available")
            db = get_debates_db()
            results: list[Any] = []

            if db and hasattr(db, "search"):
                search_results, _total = db.search(query, limit=5)
                results = list(search_results)
            elif db and hasattr(db, "list"):
                # Fallback: manual search through recent debates
                all_debates = db.list(limit=50)
                query_lower = query.lower()
                for d in all_debates:
                    task = d.get("task", "")
                    answer = d.get("final_answer", "")
                    if query_lower in task.lower() or query_lower in answer.lower():
                        results.append(d)
                        if len(results) >= 5:
                            break

            if not results:
                return self._slack_response(
                    f"No results found for: `{query}`",
                    response_type="ephemeral",
                )

            blocks: list[dict[str, Any]] = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"Search Results: {query[:30]}",
                        "emoji": True,
                    },
                },
            ]

            for i, item in enumerate(results[:5]):
                # Handle both dict and object formats
                if isinstance(item, dict):
                    topic = item.get("task", "Unknown")[:60]
                    consensus = "\u2705" if item.get("consensus_reached") else "\u274c"
                    debate_id = str(item.get("id", "unknown"))
                    confidence = item.get("confidence", 0)
                else:
                    # Object format
                    topic = str(getattr(item, "task", "Unknown"))[:60]
                    consensus = "\u2705" if getattr(item, "consensus_reached", False) else "\u274c"
                    debate_id = str(getattr(item, "id", "unknown"))
                    confidence = getattr(item, "confidence", 0)

                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{i + 1}. {consensus} {topic}*\nConfidence: {confidence:.0%} | ID: `{debate_id[:8]}`",
                        },
                    }
                )

            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Found {len(results)} result(s)",
                        },
                    ],
                }
            )

            return self._slack_blocks_response(
                blocks,
                text=f"Found {len(results)} results for '{query}'",
                response_type="ephemeral",
            )

        except ImportError as e:
            logger.warning("Storage not available for search: %s", e)
            return self._slack_response(
                "Search service temporarily unavailable",
                response_type="ephemeral",
            )
        except (KeyError, TypeError, AttributeError, ValueError, RuntimeError) as e:
            logger.exception("Unexpected search error: %s", e)
            return self._slack_response(
                "Search failed. Please try again later.",
                response_type="ephemeral",
            )

    def _command_leaderboard(self) -> HandlerResult:
        """Show agent rankings leaderboard."""
        try:
            from aragora.ranking.elo import EloSystem

            store = EloSystem()
            agents = store.get_all_ratings()

            if not agents:
                return self._slack_response(
                    "No agents ranked yet. Start some debates first!",
                    response_type="ephemeral",
                )

            # Sort by ELO
            agents = sorted(agents, key=lambda a: getattr(a, "elo", 1500), reverse=True)

            blocks: list[dict[str, Any]] = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Agent Leaderboard",
                        "emoji": True,
                    },
                },
            ]

            # Build leaderboard table
            leaderboard_text = "```\n"
            leaderboard_text += f"{'Rank':<5} {'Agent':<20} {'ELO':<8} {'W/L':<10}\n"
            leaderboard_text += "-" * 45 + "\n"

            for i, agent in enumerate(agents[:10]):
                name = getattr(agent, "name", "Unknown")[:18]
                elo = getattr(agent, "elo", 1500)
                wins = getattr(agent, "wins", 0)
                losses = getattr(agent, "losses", 0)
                medal = ["\U0001f947", "\U0001f948", "\U0001f949"][i] if i < 3 else f"{i + 1}."
                leaderboard_text += f"{medal:<5} {name:<20} {elo:<8.0f} {wins}/{losses}\n"

            leaderboard_text += "```"

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": leaderboard_text,
                    },
                }
            )

            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Total agents: {len(agents)} | Rankings based on debate performance",
                        },
                    ],
                }
            )

            return self._slack_blocks_response(
                blocks,
                text="Agent Leaderboard",
                response_type="in_channel",
            )

        except ImportError as e:
            logger.warning("ELO system not available for leaderboard: %s", e)
            return self._slack_response(
                "Leaderboard service temporarily unavailable",
                response_type="ephemeral",
            )
        except (KeyError, TypeError, AttributeError, ValueError) as e:
            logger.exception("Unexpected leaderboard error: %s", e)
            return self._slack_response(
                "Leaderboard failed. Please try again later.",
                response_type="ephemeral",
            )

    def _command_recent(self) -> HandlerResult:
        """Show recent debates."""
        try:
            if get_debates_db is None:
                raise RuntimeError("Debates DB not available")
            db = get_debates_db()
            if not db or not hasattr(db, "list"):
                return self._slack_response(
                    "Debate history not available",
                    response_type="ephemeral",
                )

            debates = db.list(limit=10)

            if not debates:
                return self._slack_response(
                    'No recent debates found. Start one with `/aragora debate "Your topic"`',
                    response_type="ephemeral",
                )

            blocks: list[dict[str, Any]] = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Recent Debates",
                        "emoji": True,
                    },
                },
            ]

            for i, debate in enumerate(debates[:10]):
                # Handle both dict and object formats
                if isinstance(debate, dict):
                    full_topic = debate.get("task", "Unknown topic")
                    consensus = "\u2705" if debate.get("consensus_reached") else "\u274c"
                    confidence = debate.get("confidence", 0)
                    debate_id = str(debate.get("id", "unknown"))
                    created = str(debate.get("created_at", ""))[:10]
                else:
                    full_topic = str(getattr(debate, "task", "Unknown topic"))
                    consensus = (
                        "\u2705" if getattr(debate, "consensus_reached", False) else "\u274c"
                    )
                    confidence = getattr(debate, "confidence", 0)
                    debate_id = str(getattr(debate, "id", "unknown"))
                    created = str(getattr(debate, "created_at", ""))[:10]

                topic = full_topic[:50]
                needs_ellipsis = len(full_topic) > 50

                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{i + 1}. {consensus} {topic}{'...' if needs_ellipsis else ''}*\n{confidence:.0%} confidence | {created} | `{debate_id[:8]}`",
                        },
                        "accessory": {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Details"},
                            "action_id": "view_details",
                            "value": debate_id,
                        },
                    }
                )

            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Showing {len(debates)} most recent debates",
                        },
                    ],
                }
            )

            return self._slack_blocks_response(
                blocks,
                text="Recent Debates",
                response_type="ephemeral",
            )

        except ImportError as e:
            logger.warning("Storage not available for recent debates: %s", e)
            return self._slack_response(
                "Recent debates service temporarily unavailable",
                response_type="ephemeral",
            )
        except (KeyError, TypeError, AttributeError, ValueError, RuntimeError) as e:
            logger.exception("Unexpected recent debates error: %s", e)
            return self._slack_response(
                "Failed to get recent debates. Please try again later.",
                response_type="ephemeral",
            )

    def _command_gauntlet(
        self,
        args: str,
        user_id: str,
        channel_id: str,
        response_url: str,
        workspace: Any | None = None,
        team_id: str | None = None,
    ) -> HandlerResult:
        """Run gauntlet adversarial validation on a statement.

        Args:
            args: The statement to validate
            user_id: Slack user ID
            channel_id: Slack channel ID
            response_url: URL for async responses
            workspace: Resolved workspace object (for multi-workspace)
            team_id: Slack team/workspace ID
        """
        if not args:
            return self._slack_response(
                'Please provide a statement to stress-test. Example: `/aragora gauntlet "We should migrate to microservices"`',
                response_type="ephemeral",
            )

        # Strip quotes if present
        statement = args.strip().strip("\"'")

        if len(statement) < 10:
            return self._slack_response(
                "Statement is too short. Please provide more detail.",
                response_type="ephemeral",
            )

        if len(statement) > 1000:
            return self._slack_response(
                "Statement is too long. Please limit to 1000 characters.",
                response_type="ephemeral",
            )

        # Acknowledge immediately
        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Running Gauntlet stress-test on:*\n_{statement[:200]}{'...' if len(statement) > 200 else ''}_",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Requested by <@{user_id}> | Running adversarial validation...",
                    },
                ],
            },
        ]

        # Queue the gauntlet run asynchronously
        if response_url:
            create_tracked_task(
                lambda: self._run_gauntlet_async(
                    statement,
                    response_url,
                    user_id,
                    channel_id,
                    team_id,
                ),
                name=f"slack-gauntlet-{statement[:30]}",
            )

        return self._slack_blocks_response(
            blocks,
            text=f"Running Gauntlet: {statement[:50]}...",
            response_type="in_channel",
        )

    async def _run_gauntlet_async(
        self,
        statement: str,
        response_url: str,
        user_id: str,
        channel_id: str,
        workspace_id: str | None = None,
    ) -> None:
        """Run gauntlet asynchronously and POST result to Slack."""
        from aragora.server.http_client_pool import get_http_pool

        try:
            pool = get_http_pool()
            async with pool.get_session("slack") as client:
                resp = await client.post(
                    f"{ARAGORA_API_BASE_URL}/api/gauntlet/run",
                    json={
                        "statement": statement,
                        "intensity": "medium",
                        "metadata": {
                            "source": "slack",
                            "channel_id": channel_id,
                            "user_id": user_id,
                        },
                    },
                    timeout=120,
                )
                data = resp.json()

                if resp.status_code != 200:
                    await self._post_to_response_url(
                        response_url,
                        {
                            "response_type": "in_channel",
                            "text": f"Gauntlet failed: {data.get('error', 'Unknown error')}",
                            "replace_original": False,
                        },
                    )
                    return

                # Build result blocks
                run_id = data.get("run_id", "unknown")
                score = data.get("score", 0)
                passed = data.get("passed", False)
                vulnerabilities = data.get("vulnerabilities", [])

                score_bar = "\u2b50" * int(score * 5) + "\u2606" * (5 - int(score * 5))
                status_emoji = "\u2705" if passed else "\u274c"

                blocks = [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{status_emoji} Gauntlet Results",
                            "emoji": True,
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Statement:*\n_{statement[:200]}{'...' if len(statement) > 200 else ''}_",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Score:* {score_bar} {score:.1%}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Status:* {'Passed' if passed else 'Failed'}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Vulnerabilities:* {len(vulnerabilities)}",
                            },
                        ],
                    },
                ]

                if vulnerabilities:
                    vuln_text = "*Issues Found:*\n"
                    for v in vulnerabilities[:5]:
                        vuln_text += f"\u2022 {v.get('description', 'Unknown issue')[:100]}\n"
                    if len(vulnerabilities) > 5:
                        vuln_text += f"_...and {len(vulnerabilities) - 5} more_"

                    blocks.append(
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": vuln_text},
                        }
                    )

                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Run ID: `{run_id}` | Requested by <@{user_id}>",
                            },
                        ],
                    }
                )

                await self._post_to_response_url(
                    response_url,
                    {
                        "response_type": "in_channel",
                        "text": f"Gauntlet complete: {statement[:50]}...",
                        "blocks": blocks,
                        "replace_original": False,
                    },
                )

        except (
            OSError,
            asyncio.TimeoutError,
            json.JSONDecodeError,
            ValueError,
            KeyError,
        ) as e:
            logger.error("Async gauntlet failed: %s", e, exc_info=True)
            await self._post_to_response_url(
                response_url,
                {
                    "response_type": "in_channel",
                    "text": "Gauntlet failed. Please try again later.",
                    "replace_original": False,
                },
            )

    def _command_debate(
        self,
        args: str,
        user_id: str,
        channel_id: str,
        response_url: str,
        workspace: Any | None = None,
        team_id: str | None = None,
        decision_integrity: dict[str, Any] | bool | None = None,
        mode_label: str = "debate",
        command_label: str | None = None,
    ) -> HandlerResult:
        """Start a debate on a topic.

        Args:
            args: The topic text (may be quoted)
            user_id: Slack user ID
            channel_id: Slack channel ID
            response_url: URL for async responses
            workspace: Resolved workspace object (for multi-workspace)
            team_id: Slack team/workspace ID
        """
        if not args:
            command_label = command_label or mode_label
            return self._slack_response(
                f'Please provide a topic. Example: `/aragora {command_label} "Should AI be regulated?"`',
                response_type="ephemeral",
            )

        # Strip quotes if present
        topic = args.strip().strip("\"'")

        if len(topic) < 10:
            return self._slack_response(
                "Topic is too short. Please provide a more detailed topic.",
                response_type="ephemeral",
            )

        if len(topic) > 500:
            return self._slack_response(
                "Topic is too long. Please limit to 500 characters.",
                response_type="ephemeral",
            )

        # Acknowledge immediately (Slack requires response within 3 seconds)
        # The actual debate will be processed asynchronously

        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Starting {mode_label} on:*\n_{topic}_",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Requested by <@{user_id}> | Processing...",
                    },
                ],
            },
        ]

        # Queue the debate creation asynchronously
        if response_url:
            create_tracked_task(
                lambda: self._create_debate_async(
                    topic,
                    response_url,
                    user_id,
                    channel_id,
                    team_id,
                    decision_integrity=decision_integrity,
                ),
                name=f"slack-debate-{topic[:30]}",
            )

        return self._slack_blocks_response(
            blocks,
            text=f"Starting debate: {topic}",
            response_type="in_channel",
        )

    async def _create_debate_async(
        self,
        topic: str,
        response_url: str,
        user_id: str,
        channel_id: str,
        workspace_id: str | None = None,
        decision_integrity: dict[str, Any] | bool | None = None,
    ) -> None:
        """Create debate asynchronously with thread-based progress updates.

        Posts an initial message to start a thread, then posts progress
        updates and final result to that thread.
        """
        import uuid

        debate_id = f"slack-{uuid.uuid4().hex[:8]}"
        thread_ts: str | None = None

        # Register debate origin for tracking and cross-system integration
        try:
            from aragora.server.debate_origin import register_debate_origin

            register_debate_origin(
                debate_id=debate_id,
                platform="slack",
                channel_id=channel_id,
                user_id=user_id,
                metadata={
                    "topic": topic,
                    "workspace_id": workspace_id,
                    "response_url": response_url,
                },
            )
        except ImportError:
            logger.debug("Debate origin tracking not available")
        except (RuntimeError, OSError, ValueError, TypeError) as e:
            logger.warning("Failed to register debate origin: %s", e)

        try:
            from aragora import Arena, DebateProtocol, Environment
            from aragora.agents import get_agents_by_names

            # Determine agents and protocol early for thread header
            agent_names = ["anthropic-api", "openai-api"]
            expected_rounds = DEFAULT_ROUNDS

            # Post initial "starting" message to create thread with rich metadata
            starting_blocks = self._build_starting_blocks(
                topic=topic,
                user_id=user_id,
                debate_id=debate_id,
                agents=agent_names,
                expected_rounds=expected_rounds,
            )
            starting_text = f"Starting debate: {topic}"

            # Use Web API if bot token available (to capture thread_ts for tracking)
            if SLACK_BOT_TOKEN and channel_id:
                thread_ts = await self._post_message_async(
                    channel=channel_id,
                    text=starting_text,
                    blocks=starting_blocks,
                )
                if thread_ts:
                    logger.debug("Debate %s started thread: %s", debate_id, thread_ts)
                    # Update origin with thread_ts for proper threaded routing
                    try:
                        from aragora.server.debate_origin import get_debate_origin

                        origin = get_debate_origin(debate_id)
                        if origin:
                            origin.thread_id = thread_ts
                    except (ImportError, AttributeError):
                        pass
                else:
                    # Fall back to response_url if Web API failed
                    logger.warning("Web API post failed, falling back to response_url")
                    await self._post_to_response_url(
                        response_url,
                        {
                            "response_type": "in_channel",
                            "text": starting_text,
                            "blocks": starting_blocks,
                            "replace_original": False,
                        },
                    )
            else:
                # No bot token - use response_url (can't track thread_ts)
                await self._post_to_response_url(
                    response_url,
                    {
                        "response_type": "in_channel",
                        "text": starting_text,
                        "blocks": starting_blocks,
                        "replace_original": False,
                    },
                )

            # Store active debate for tracking (if workspace_id available)
            if workspace_id:
                try:
                    from aragora.storage.slack_debate_store import (
                        SlackActiveDebate,
                        get_slack_debate_store,
                    )

                    active_debate = SlackActiveDebate(
                        debate_id=debate_id,
                        workspace_id=workspace_id,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        topic=topic,
                        user_id=user_id,
                        status="running",
                    )
                    store = get_slack_debate_store()
                    store.save(active_debate)
                except ImportError:
                    logger.debug("Slack debate store not available")

            # Create debate using pre-defined agent names and rounds
            env = Environment(task=f"Debate: {topic}")
            agents = get_agents_by_names(agent_names)
            protocol = DebateProtocol(
                rounds=expected_rounds,
                consensus="majority",
                convergence_detection=False,
                early_stopping=False,
            )

            if not agents:
                await self._post_to_response_url(
                    response_url,
                    {
                        "response_type": "in_channel",
                        "text": "Failed to create debate: No agents available",
                        "replace_original": False,
                    },
                )
                self._update_debate_status(debate_id, "failed", error="No agents available")
                return

            # Track progress for thread updates
            last_round = 0
            # Capture thread_ts for closure (may be None if Web API not used)
            debate_thread_ts = thread_ts

            def on_round_complete(round_num: int, agent: str, response: str) -> None:
                nonlocal last_round
                # Post individual agent response to thread (fire-and-forget)
                create_tracked_task(
                    lambda: self._post_agent_response(
                        response_url,
                        agent,
                        response,
                        round_num,
                        channel_id=channel_id,
                        thread_ts=debate_thread_ts,
                    ),
                    name=f"slack-agent-{debate_id}-{agent}-{round_num}",
                )

                # Post round progress update when round changes
                if round_num > last_round:
                    last_round = round_num
                    create_tracked_task(
                        lambda: self._post_round_update(
                            response_url,
                            topic,
                            round_num,
                            protocol.rounds,
                            agent,
                            channel_id=channel_id,
                            thread_ts=debate_thread_ts,
                        ),
                        name=f"slack-round-{debate_id}-{round_num}",
                    )

            arena = Arena.from_env(env, agents, protocol)
            result = await arena.run()

            # Generate decision receipt if enabled
            receipt_id: str | None = None
            receipt_url: str | None = None
            try:
                from aragora.gauntlet.receipt import DecisionReceipt

                receipt = DecisionReceipt.from_debate_result(result)
                receipt_id = receipt.receipt_id

                # Build receipt URL
                receipt_url = public_receipt_url(receipt_id)

                # Persist receipt
                try:
                    from aragora.storage.receipt_store import get_receipt_store

                    receipt_store = get_receipt_store()
                    receipt_store.save(receipt.to_dict())
                except ImportError:
                    logger.debug("Receipt store not available")
            except ImportError:
                logger.debug("Receipt generation not available")

            # Build and post result blocks
            result_blocks = self._build_result_blocks(topic, result, user_id, receipt_url)
            result_text = f"Debate complete: {topic}"

            # Use Web API with thread_ts for proper threading when available
            if SLACK_BOT_TOKEN and channel_id and thread_ts:
                await self._post_message_async(
                    channel=channel_id,
                    text=result_text,
                    thread_ts=thread_ts,
                    blocks=result_blocks,
                )
            else:
                await self._post_to_response_url(
                    response_url,
                    {
                        "response_type": "in_channel",
                        "text": result_text,
                        "blocks": result_blocks,
                        "replace_original": False,
                    },
                )

            # Update debate status to completed
            self._update_debate_status(debate_id, "completed", receipt_id=receipt_id)

            # Mark result sent in origin tracking
            try:
                from aragora.server.debate_origin import mark_result_sent

                mark_result_sent(debate_id)
            except (ImportError, AttributeError):
                pass

            # Optionally emit decision integrity package
            from aragora.server.decision_integrity_utils import (
                maybe_emit_decision_integrity,
            )

            ctx = getattr(self, "ctx", {}) or {}
            document_store = ctx.get("document_store")
            evidence_store = ctx.get("evidence_store")

            await maybe_emit_decision_integrity(
                result=result,
                debate_id=debate_id,
                arena=arena,
                decision_integrity=decision_integrity,
                document_store=document_store,
                evidence_store=evidence_store,
            )

        except (ValueError, KeyError, TypeError, RuntimeError, OSError, ConnectionError) as e:
            logger.error("Async debate creation failed: %s", e, exc_info=True)
            error_text = "Debate failed. Please try again later."

            # Use Web API with thread_ts for error message when available
            if SLACK_BOT_TOKEN and channel_id and thread_ts:
                await self._post_message_async(
                    channel=channel_id,
                    text=error_text,
                    thread_ts=thread_ts,
                )
            else:
                await self._post_to_response_url(
                    response_url,
                    {
                        "response_type": "in_channel",
                        "text": error_text,
                        "replace_original": False,
                    },
                )
            self._update_debate_status(debate_id, "failed", error="Debate execution failed")

    def _command_stop(
        self,
        args: str,
        user_id: str,
        channel_id: str,
        response_url: str,
        workspace: Any | None = None,
        team_id: str | None = None,
    ) -> HandlerResult:
        """Stop a running debate.

        Stops either by debate ID or by channel context (most recent debate).

        Args:
            args: Optional debate ID to stop.
            user_id: Slack user ID.
            channel_id: Slack channel ID.
            response_url: URL for async responses.
            workspace: Resolved workspace object.
            team_id: Slack team/workspace ID.
        """
        debate_id_arg = args.strip().strip("\"'") if args else ""

        try:
            from aragora.integrations.slack_debate import (
                stop_debate,
            )

            stopped_id: str | None = None

            if debate_id_arg:
                # Stop specific debate by ID
                if stop_debate(debate_id_arg):
                    stopped_id = debate_id_arg
            else:
                # Try to find and stop a debate in the current channel
                # For slash commands we don't have a thread_ts, but we can
                # try matching by channel_id
                from aragora.integrations.slack_debate import _active_debates

                for state in _active_debates.values():
                    if state.channel_id == channel_id and state.status == "running":
                        state.request_stop()
                        stopped_id = state.debate_id
                        break

            if stopped_id:
                self._update_debate_status(stopped_id, "stopped")
                return self._slack_response(
                    f":octagonal_sign: Debate `{stopped_id[:12]}...` has been stopped.",
                    response_type="in_channel",
                )
            else:
                return self._slack_response(
                    "No running debate found to stop."
                    + (f" Debate ID `{debate_id_arg}` not found." if debate_id_arg else "")
                    + " Use `/aragora stop <debate_id>` to stop a specific debate.",
                    response_type="ephemeral",
                )

        except ImportError:
            logger.debug("Slack debate lifecycle module not available")
            return self._slack_response(
                "Stop command is not available.",
                response_type="ephemeral",
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.error("Stop command failed: %s", e)
            return self._slack_response(
                "Failed to stop debate. Please try again.",
                response_type="ephemeral",
            )

    def _command_approve(
        self,
        args: str,
        user_id: str,
        channel_id: str,
    ) -> HandlerResult:
        """Approve a debate decision.

        Usage: /aragora approve <debate_id>

        Args:
            args: Debate ID to approve.
            user_id: Slack user ID.
            channel_id: Slack channel ID.
        """
        debate_id = args.strip().strip("\"'") if args else ""
        if not debate_id:
            return self._slack_response(
                "Please provide a debate ID. Usage: `/aragora approve <debate_id>`",
                response_type="ephemeral",
            )

        try:
            from aragora.integrations.approval_flow import ApprovalFlowManager

            manager = ApprovalFlowManager()
            flow = manager.get_status_by_debate(debate_id)
            if flow is None:
                return self._slack_response(
                    f"No approval flow found for debate `{debate_id[:12]}...`",
                    response_type="ephemeral",
                )

            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Already in async context -- run synchronously via the manager
                # (record_decision is a coroutine, but we schedule it)
                _future = asyncio.ensure_future(
                    manager.record_decision(
                        flow_id=flow.flow_id,
                        user_id=f"slack:{user_id}",
                        decision="approved",
                    )
                )
                # Cannot await here in sync handler; return optimistic response
                return self._slack_response(
                    f":white_check_mark: Approval recorded for debate `{debate_id[:12]}...` by <@{user_id}>.",
                    response_type="in_channel",
                )
            else:
                updated = asyncio.run(
                    manager.record_decision(
                        flow_id=flow.flow_id,
                        user_id=f"slack:{user_id}",
                        decision="approved",
                    )
                )
                if updated is None:
                    return self._slack_response(
                        "Failed to record approval.",
                        response_type="ephemeral",
                    )
                return self._slack_response(
                    f":white_check_mark: Decision for debate `{debate_id[:12]}...` approved by <@{user_id}>. "
                    f"Status: *{updated.state}* ({updated.approval_count}/{updated.required_approvers} approvals)",
                    response_type="in_channel",
                )

        except ImportError:
            logger.debug("Approval flow module not available")
            return self._slack_response(
                "Approval flow is not available.",
                response_type="ephemeral",
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.error("Approve command failed: %s", e)
            return self._slack_response(
                "Failed to process approval. Please try again.",
                response_type="ephemeral",
            )

    def _command_reject(
        self,
        args: str,
        user_id: str,
        channel_id: str,
    ) -> HandlerResult:
        """Reject a debate decision.

        Usage: /aragora reject <debate_id> [reason]

        Args:
            args: Debate ID and optional reason.
            user_id: Slack user ID.
            channel_id: Slack channel ID.
        """
        if not args:
            return self._slack_response(
                "Please provide a debate ID. Usage: `/aragora reject <debate_id> [reason]`",
                response_type="ephemeral",
            )

        parts = args.strip().split(maxsplit=1)
        debate_id = parts[0].strip("\"'")
        reason = parts[1].strip("\"'") if len(parts) > 1 else ""

        try:
            from aragora.integrations.approval_flow import ApprovalFlowManager

            manager = ApprovalFlowManager()
            flow = manager.get_status_by_debate(debate_id)
            if flow is None:
                return self._slack_response(
                    f"No approval flow found for debate `{debate_id[:12]}...`",
                    response_type="ephemeral",
                )

            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                _future = asyncio.ensure_future(
                    manager.record_decision(
                        flow_id=flow.flow_id,
                        user_id=f"slack:{user_id}",
                        decision="rejected",
                        reason=reason,
                    )
                )
                reason_text = f" Reason: _{reason}_" if reason else ""
                return self._slack_response(
                    f":x: Decision for debate `{debate_id[:12]}...` rejected by <@{user_id}>.{reason_text}",
                    response_type="in_channel",
                )
            else:
                updated = asyncio.run(
                    manager.record_decision(
                        flow_id=flow.flow_id,
                        user_id=f"slack:{user_id}",
                        decision="rejected",
                        reason=reason,
                    )
                )
                if updated is None:
                    return self._slack_response(
                        "Failed to record rejection.",
                        response_type="ephemeral",
                    )
                reason_text = f" Reason: _{reason}_" if reason else ""
                return self._slack_response(
                    f":x: Decision for debate `{debate_id[:12]}...` rejected by <@{user_id}>.{reason_text} "
                    f"Status: *{updated.state}*",
                    response_type="in_channel",
                )

        except ImportError:
            logger.debug("Approval flow module not available")
            return self._slack_response(
                "Approval flow is not available.",
                response_type="ephemeral",
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.error("Reject command failed: %s", e)
            return self._slack_response(
                "Failed to process rejection. Please try again.",
                response_type="ephemeral",
            )

    def _update_debate_status(
        self,
        debate_id: str,
        status: str,
        receipt_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update debate status in the store."""
        try:
            from aragora.storage.slack_debate_store import get_slack_debate_store

            store = get_slack_debate_store()
            store.update_status(debate_id, status, receipt_id=receipt_id, error_message=error)
        except ImportError:
            pass  # Store not available
