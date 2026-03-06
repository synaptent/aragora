"""
HTTP Handlers for Real-Time Collaboration.

Provides REST endpoints for session management, participant tracking,
and collaboration features.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from aragora.server.collaboration import (
    CollaborationSession,
    ParticipantRole,
    SessionManager,
    get_session_manager,
)
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import error_response, json_response
from aragora.server.handlers.utils.lazy_stores import LazyStore
from aragora.server.handlers.utils.rate_limit import RateLimiter, get_client_ip
from aragora.rbac.checker import get_permission_checker
from aragora.rbac.models import AuthorizationContext
from aragora.server.handlers.utils.responses import error_dict

logger = logging.getLogger(__name__)

# Rate limiter for collaboration endpoints (60 requests per minute)
_collab_limiter = RateLimiter(requests_per_minute=60)


def _check_permission(
    user_id: str,
    permission: str,
    org_id: str | None = None,
    roles: set[str] | None = None,
) -> dict[str, Any] | None:
    """Check RBAC permission for collaboration operations.

    Returns None if allowed, or error dict if denied.
    """
    try:
        context = AuthorizationContext(
            user_id=user_id,
            org_id=org_id,
            roles=roles if roles else {"member"},
            permissions=set(),
        )
        checker = get_permission_checker()
        decision = checker.check_permission(context, permission)
        if not decision.allowed:
            logger.warning("RBAC denied %s for user %s: %s", permission, user_id, decision.reason)
            return error_dict("Permission denied", code="FORBIDDEN", status=403)
        return None
    except (ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.error("RBAC check failed: %s", e)
        return error_dict("Authorization check failed", code="INTERNAL_ERROR", status=500)


class CollaborationHandlers:
    """
    HTTP handlers for collaboration features.

    Endpoints:
        POST /api/collaboration/sessions - Create session
        GET  /api/collaboration/sessions/{id} - Get session
        GET  /api/collaboration/sessions - List sessions
        POST /api/collaboration/sessions/{id}/join - Join session
        POST /api/collaboration/sessions/{id}/leave - Leave session
        POST /api/collaboration/sessions/{id}/presence - Update presence
        POST /api/collaboration/sessions/{id}/typing - Set typing indicator
        POST /api/collaboration/sessions/{id}/role - Change participant role
        POST /api/collaboration/sessions/{id}/approve - Approve/deny join
        POST /api/collaboration/sessions/{id}/close - Close session
        GET  /api/collaboration/stats - Get statistics
    """

    def __init__(self, manager: SessionManager | None = None):
        self.manager = manager or get_session_manager()

    async def create_session(
        self,
        debate_id: str,
        user_id: str,
        *,
        title: str = "",
        description: str = "",
        is_public: bool = False,
        max_participants: int = 50,
        org_id: str = "",
        expires_in: float | None = None,
        allow_anonymous: bool = False,
        require_approval: bool = False,
    ) -> dict[str, Any]:
        """
        Create a new collaboration session for a debate.

        POST /api/collaboration/sessions
        Body: {
            "debate_id": str,
            "title": str (optional),
            "description": str (optional),
            "is_public": bool (default: false),
            "max_participants": int (default: 50),
            "expires_in": float (seconds, optional),
            "allow_anonymous": bool (default: false),
            "require_approval": bool (default: false)
        }
        """
        if not debate_id:
            return error_dict("debate_id is required", code="VALIDATION_ERROR")
        if not user_id:
            return error_dict("user_id is required", code="VALIDATION_ERROR")

        # RBAC check
        if denied := _check_permission(user_id, "collaboration:create", org_id):
            return denied

        try:
            session = self.manager.create_session(
                debate_id=debate_id,
                created_by=user_id,
                title=title,
                description=description,
                is_public=is_public,
                max_participants=max_participants,
                org_id=org_id,
                expires_in=expires_in,
                allow_anonymous=allow_anonymous,
                require_approval=require_approval,
            )
            return {
                "success": True,
                "session": session.to_dict(),
            }
        except (ValueError, TypeError, RuntimeError, OSError) as e:
            logger.error("Failed to create session: %s", e)
            return error_dict("Failed to create session", code="INTERNAL_ERROR")

    async def get_session(self, session_id: str, user_id: str = "") -> dict[str, Any]:
        """
        Get a collaboration session by ID.

        GET /api/collaboration/sessions/{session_id}
        """
        if not session_id:
            return error_dict("session_id is required", code="VALIDATION_ERROR")

        # RBAC check (optional user_id for backward compatibility)
        if user_id:
            if denied := _check_permission(user_id, "collaboration:read"):
                return denied

        session = self.manager.get_session(session_id)
        if not session:
            return error_dict("Session not found", code="NOT_FOUND", status=404)

        return {"session": session.to_dict()}

    async def list_sessions(
        self,
        debate_id: str = "",
        user_id: str = "",
        include_closed: bool = False,
        requesting_user_id: str = "",
    ) -> dict[str, Any]:
        """
        List collaboration sessions.

        GET /api/collaboration/sessions
        Query params:
            debate_id: Filter by debate (optional)
            user_id: Filter by participant (optional)
            include_closed: Include closed sessions (default: false)
        """
        # RBAC check
        if requesting_user_id:
            if denied := _check_permission(requesting_user_id, "collaboration:read"):
                return denied

        sessions: list[CollaborationSession] = []

        if debate_id:
            sessions = self.manager.get_sessions_for_debate(debate_id)
        elif user_id:
            sessions = self.manager.get_sessions_for_user(user_id)
        else:
            # Return all active sessions (paginated in production)
            sessions = list(self.manager._sessions.values())

        # Filter closed sessions if not requested
        if not include_closed:
            sessions = [s for s in sessions if s.state.value != "closed"]

        return {
            "sessions": [s.to_dict(include_participants=False) for s in sessions],
            "count": len(sessions),
        }

    async def join_session(
        self,
        session_id: str,
        user_id: str,
        *,
        role: str = "voter",
        display_name: str = "",
        avatar_url: str = "",
    ) -> dict[str, Any]:
        """
        Join a collaboration session.

        POST /api/collaboration/sessions/{session_id}/join
        Body: {
            "role": str (viewer/voter/contributor, default: voter),
            "display_name": str (optional),
            "avatar_url": str (optional)
        }
        """
        if not session_id:
            return error_dict("session_id is required", code="VALIDATION_ERROR")
        if not user_id:
            return error_dict("user_id is required", code="VALIDATION_ERROR")

        # RBAC check
        if denied := _check_permission(user_id, "collaboration:join"):
            return denied

        try:
            participant_role = ParticipantRole(role)
        except ValueError:
            return error_dict(f"Invalid role: {role}", code="VALIDATION_ERROR")

        success, message, participant = self.manager.join_session(
            session_id=session_id,
            user_id=user_id,
            role=participant_role,
            display_name=display_name,
            avatar_url=avatar_url,
        )

        return {
            "success": success,
            "message": message,
            "participant": participant.to_dict() if participant else None,
        }

    async def leave_session(
        self,
        session_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """
        Leave a collaboration session.

        POST /api/collaboration/sessions/{session_id}/leave
        """
        if not session_id:
            return error_dict("session_id is required", code="VALIDATION_ERROR")
        if not user_id:
            return error_dict("user_id is required", code="VALIDATION_ERROR")

        # RBAC check - users can leave their own sessions
        if denied := _check_permission(user_id, "collaboration:leave"):
            return denied

        success = self.manager.leave_session(session_id, user_id)
        return {
            "success": success,
            "message": "Left session" if success else "Failed to leave session",
        }

    async def update_presence(
        self,
        session_id: str,
        user_id: str,
        is_online: bool = True,
    ) -> dict[str, Any]:
        """
        Update participant presence.

        POST /api/collaboration/sessions/{session_id}/presence
        Body: {"is_online": bool}
        """
        if not session_id:
            return error_dict("session_id is required", code="VALIDATION_ERROR")
        if not user_id:
            return error_dict("user_id is required", code="VALIDATION_ERROR")

        success = self.manager.update_presence(session_id, user_id, is_online)
        return {
            "success": success,
            "message": "Presence updated" if success else "Failed to update presence",
        }

    async def set_typing(
        self,
        session_id: str,
        user_id: str,
        is_typing: bool = True,
        context: str = "",
    ) -> dict[str, Any]:
        """
        Set typing indicator.

        POST /api/collaboration/sessions/{session_id}/typing
        Body: {"is_typing": bool, "context": str (e.g., "vote", "suggestion")}
        """
        if not session_id:
            return error_dict("session_id is required", code="VALIDATION_ERROR")
        if not user_id:
            return error_dict("user_id is required", code="VALIDATION_ERROR")

        success = self.manager.set_typing(session_id, user_id, is_typing, context)
        return {
            "success": success,
            "message": "Typing indicator updated" if success else "Failed to update",
        }

    async def change_role(
        self,
        session_id: str,
        target_user_id: str,
        new_role: str,
        changed_by: str,
    ) -> dict[str, Any]:
        """
        Change a participant's role.

        POST /api/collaboration/sessions/{session_id}/role
        Body: {"target_user_id": str, "new_role": str}
        """
        if not session_id:
            return error_dict("session_id is required", code="VALIDATION_ERROR")
        if not target_user_id:
            return error_dict("target_user_id is required", code="VALIDATION_ERROR")
        if not changed_by:
            return error_dict("Moderator user_id required", code="VALIDATION_ERROR")

        # RBAC check - requires admin permission
        if denied := _check_permission(changed_by, "collaboration:admin"):
            return denied

        try:
            participant_role = ParticipantRole(new_role)
        except ValueError:
            return error_dict(f"Invalid role: {new_role}", code="VALIDATION_ERROR")

        success, message = self.manager.change_role(
            session_id=session_id,
            target_user_id=target_user_id,
            new_role=participant_role,
            changed_by=changed_by,
        )

        return {"success": success, "message": message}

    async def approve_join(
        self,
        session_id: str,
        user_id: str,
        approved_by: str,
        approved: bool = True,
        role: str = "voter",
    ) -> dict[str, Any]:
        """
        Approve or deny a join request.

        POST /api/collaboration/sessions/{session_id}/approve
        Body: {"user_id": str, "approved": bool, "role": str (optional)}
        """
        if not session_id:
            return error_dict("session_id is required", code="VALIDATION_ERROR")
        if not user_id:
            return error_dict("user_id is required", code="VALIDATION_ERROR")
        if not approved_by:
            return error_dict("Moderator user_id required", code="VALIDATION_ERROR")

        # RBAC check - requires admin permission
        if denied := _check_permission(approved_by, "collaboration:admin"):
            return denied

        try:
            participant_role = ParticipantRole(role)
        except ValueError:
            participant_role = ParticipantRole.VOTER

        success, message = self.manager.approve_join(
            session_id=session_id,
            user_id=user_id,
            approved_by=approved_by,
            approved=approved,
            role=participant_role,
        )

        return {"success": success, "message": message}

    async def close_session(
        self,
        session_id: str,
        closed_by: str,
    ) -> dict[str, Any]:
        """
        Close a collaboration session.

        POST /api/collaboration/sessions/{session_id}/close
        """
        if not session_id:
            return error_dict("session_id is required", code="VALIDATION_ERROR")
        if not closed_by:
            return error_dict("Moderator user_id required", code="VALIDATION_ERROR")

        # RBAC check - requires admin permission
        if denied := _check_permission(closed_by, "collaboration:admin"):
            return denied

        success = self.manager.close_session(session_id, closed_by)
        return {
            "success": success,
            "message": "Session closed" if success else "Failed to close session",
        }

    async def get_stats(self, user_id: str = "") -> dict[str, Any]:
        """
        Get collaboration statistics.

        GET /api/collaboration/stats
        """
        # RBAC check for stats access
        if user_id:
            if denied := _check_permission(user_id, "collaboration:read"):
                return denied

        return self.manager.get_stats()

    async def get_participants(self, session_id: str, user_id: str = "") -> dict[str, Any]:
        """
        Get participants for a session.

        GET /api/collaboration/sessions/{session_id}/participants
        """
        if not session_id:
            return error_dict("session_id is required", code="VALIDATION_ERROR")

        # RBAC check
        if user_id:
            if denied := _check_permission(user_id, "collaboration:read"):
                return denied

        session = self.manager.get_session(session_id)
        if not session:
            return error_dict("Session not found", code="NOT_FOUND", status=404)

        return {
            "participants": [p.to_dict() for p in session.participants.values()],
            "count": session.participant_count,
            "online_count": session.online_count,
        }


# === Sync social collaboration handler (API v1) ===


@dataclass
class SocialCollaborationSession:
    """Lightweight collaboration session record for social endpoints."""

    id: str
    org_id: str
    name: str
    description: str
    channel_id: str
    platform: str
    created_by: str
    participants: list[str] = field(default_factory=list)
    status: str = "active"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "name": self.name,
            "description": self.description,
            "channel_id": self.channel_id,
            "platform": self.platform,
            "created_by": self.created_by,
            "participants": self.participants,
            "status": self.status,
            "created_at": self.created_at,
        }


class SocialCollaborationStore:
    """In-memory store for social collaboration sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, SocialCollaborationSession] = {}
        self._messages: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get_by_org(self, org_id: str) -> list[SocialCollaborationSession]:
        with self._lock:
            return [s for s in self._sessions.values() if s.org_id == org_id]

    def get_by_id(self, session_id: str) -> SocialCollaborationSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def create(self, session: SocialCollaborationSession) -> SocialCollaborationSession:
        with self._lock:
            self._sessions[session.id] = session
            self._messages.setdefault(session.id, [])
            return session

    def update(self, session_id: str, updates: dict[str, Any]) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            for key, value in updates.items():
                if hasattr(session, key):
                    setattr(session, key, value)
            return True

    def delete(self, session_id: str) -> bool:
        with self._lock:
            self._messages.pop(session_id, None)
            return self._sessions.pop(session_id, None) is not None

    def list_participants(self, session_id: str) -> list[str]:
        with self._lock:
            session = self._sessions.get(session_id)
            return list(session.participants) if session else []

    def add_participant(self, session_id: str, user_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            if user_id not in session.participants:
                session.participants.append(user_id)
            return True

    def remove_participant(self, session_id: str, user_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            if user_id in session.participants:
                session.participants.remove(user_id)
            return True

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._messages.get(session_id, []))

    def add_message(self, session_id: str, message: dict[str, Any]) -> bool:
        with self._lock:
            if session_id not in self._messages:
                return False
            self._messages[session_id].append(message)
            return True


_social_collab_store_lazy = LazyStore(
    factory=SocialCollaborationStore,
    store_name="social_collaboration_store",
    logger_context="Collaboration",
)


def _get_social_collab_store() -> SocialCollaborationStore:
    return _social_collab_store_lazy.get()


class CollaborationHandler:
    """Handler for social collaboration endpoints."""

    ROUTES = ["/api/v1/social/collaboration/sessions"]

    def __init__(self, server_context: dict[str, Any] | None = None) -> None:
        self.ctx = server_context or {}
        self._store = self.ctx.get("collaboration_store") or _get_social_collab_store()

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/v1/social/collaboration/sessions")

    def _parse_json_body(self, handler: Any) -> tuple[dict[str, Any] | None, Any | None]:
        import json as json_lib

        try:
            body = handler.rfile.read(int(handler.headers.get("Content-Length", 0)))
            data = json_lib.loads(body.decode("utf-8")) if body else {}
            return data, None
        except (json_lib.JSONDecodeError, ValueError):
            return None, error_response("Invalid JSON body", 400)

    def handle(
        self,
        path: str,
        query_params: dict,
        handler: Any,
        method: str = "GET",
    ) -> Any:
        if hasattr(handler, "command"):
            method = handler.command

        client_ip = get_client_ip(handler)
        if not _collab_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for collaboration: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/v1/social/collaboration/sessions":
            if method == "GET":
                return self._list_sessions()
            if method == "POST":
                return self._create_session(handler)
            return error_response("Method not allowed", 405)

        if path.startswith("/api/v1/social/collaboration/sessions/"):
            parts = path.split("/")
            # parts: ['', 'api', 'v1', 'social', 'collaboration', 'sessions', '{id}', ...]
            if len(parts) >= 7:
                session_id = parts[6]
                # Participant management
                if len(parts) >= 8 and parts[7] == "participants":
                    if len(parts) == 8:
                        if method == "GET":
                            return self._list_participants(session_id)
                        if method == "POST":
                            return self._add_participant(session_id, handler)
                        return error_response("Method not allowed", 405)
                    if len(parts) == 9:
                        participant_id = parts[8]
                        if method == "DELETE":
                            return self._remove_participant(session_id, participant_id)
                        return error_response("Method not allowed", 405)

                # Messages
                if len(parts) >= 8 and parts[7] == "messages":
                    if method == "GET":
                        return self._list_messages(session_id)
                    if method == "POST":
                        return self._send_message(session_id, handler)
                    return error_response("Method not allowed", 405)

                # Session detail
                if len(parts) == 7:
                    if method == "GET":
                        return self._get_session(session_id)
                    if method == "PATCH":
                        return self._update_session(session_id, handler)
                    if method == "DELETE":
                        return self._delete_session(session_id)
                    return error_response("Method not allowed", 405)

        return error_response("Not found", 404)

    def _list_sessions(self) -> Any:
        sessions = self._store.get_by_org("") if hasattr(self._store, "get_by_org") else []
        return json_response({"sessions": [s.to_dict() for s in sessions], "total": len(sessions)})

    def _get_session(self, session_id: str) -> Any:
        session = self._store.get_by_id(session_id)
        if not session:
            return error_response("Session not found", 404)
        return json_response({"session": session.to_dict()})

    def _create_session(self, handler: Any) -> Any:
        data, err = self._parse_json_body(handler)
        if err:
            return err
        data = data or {}

        name = data.get("name")
        channel_id = data.get("channel_id")
        platform = data.get("platform")
        if not name:
            return error_response("name is required", 400)
        if not channel_id:
            return error_response("channel_id is required", 400)

        session = SocialCollaborationSession(
            id=secrets.token_urlsafe(8),
            org_id=data.get("org_id", ""),
            name=name,
            description=data.get("description", ""),
            channel_id=channel_id,
            platform=platform or "",
            created_by=data.get("created_by", "unknown"),
            participants=data.get("participants") or [],
        )
        created = self._store.create(session)
        return json_response({"session": created.to_dict()}, status=201)

    def _update_session(self, session_id: str, handler: Any) -> Any:
        data, err = self._parse_json_body(handler)
        if err:
            return err
        data = data or {}
        updated = self._store.update(session_id, data)
        if not updated:
            return error_response("Session not found", 404)
        session = self._store.get_by_id(session_id)
        return json_response({"session": session.to_dict() if session else {}})

    @require_permission("collaboration:delete")
    def _delete_session(self, session_id: str) -> Any:
        deleted = self._store.delete(session_id)
        if not deleted:
            return error_response("Session not found", 404)
        return json_response({"deleted": True, "session_id": session_id})

    def _list_participants(self, session_id: str) -> Any:
        participants = self._store.list_participants(session_id)
        return json_response({"participants": participants, "total": len(participants)})

    def _add_participant(self, session_id: str, handler: Any) -> Any:
        data, err = self._parse_json_body(handler)
        if err:
            return err
        data = data or {}
        user_id = data.get("user_id")
        if not user_id:
            return error_response("user_id is required", 400)
        success = self._store.add_participant(session_id, user_id)
        if not success:
            return error_response("Session not found", 404)
        return json_response({"added": True, "user_id": user_id})

    def _remove_participant(self, session_id: str, user_id: str) -> Any:
        success = self._store.remove_participant(session_id, user_id)
        if not success:
            return error_response("Session not found", 404)
        return json_response({"removed": True, "user_id": user_id})

    def _list_messages(self, session_id: str) -> Any:
        messages = self._store.list_messages(session_id)
        return json_response({"messages": messages, "total": len(messages)})

    def _send_message(self, session_id: str, handler: Any) -> Any:
        data, err = self._parse_json_body(handler)
        if err:
            return err
        data = data or {}
        content = data.get("content")
        if not content:
            return error_response("content is required", 400)
        message = {
            "id": secrets.token_urlsafe(6),
            "content": content,
            "created_at": time.time(),
        }
        success = self._store.add_message(session_id, message)
        if not success:
            return error_response("Session not found", 404)
        return json_response({"message": message}, status=201)


# Singleton handler instance
_handlers: CollaborationHandlers | None = None


def get_collaboration_handlers() -> CollaborationHandlers:
    """Get the global collaboration handlers instance."""
    global _handlers
    if _handlers is None:
        _handlers = CollaborationHandlers()
    return _handlers


__all__ = [
    "CollaborationHandler",
    "CollaborationHandlers",
    "get_collaboration_handlers",
]
