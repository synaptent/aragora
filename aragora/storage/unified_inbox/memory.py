"""In-memory unified inbox store for testing."""

from __future__ import annotations

import threading
from typing import Any, cast

from aragora.storage.unified_inbox.base import UnifiedInboxStoreBackend


class InMemoryUnifiedInboxStore(UnifiedInboxStoreBackend):
    """In-memory unified inbox store for testing."""

    def __init__(self) -> None:
        self._accounts: dict[str, dict[str, dict[str, Any]]] = {}
        self._messages: dict[str, dict[str, dict[str, Any]]] = {}
        self._triage: dict[str, dict[str, dict[str, Any]]] = {}
        self._message_index: dict[tuple[str, str, str], str] = {}
        self._lock = threading.Lock()

    async def save_account(self, tenant_id: str, account: dict[str, Any]) -> None:
        with self._lock:
            self._accounts.setdefault(tenant_id, {})[account["id"]] = dict(account)

    async def get_account(self, tenant_id: str, account_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._accounts.get(tenant_id, {}).get(account_id)

    async def list_accounts(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._accounts.get(tenant_id, {}).values())

    async def delete_account(self, tenant_id: str, account_id: str) -> bool:
        with self._lock:
            accounts = self._accounts.get(tenant_id, {})
            if account_id not in accounts:
                return False
            del accounts[account_id]
            messages = self._messages.get(tenant_id, {})
            for message_id, message in list(messages.items()):
                if message.get("account_id") == account_id:
                    del messages[message_id]
                    self._triage.get(tenant_id, {}).pop(message_id, None)
            self._message_index = {
                key: val for key, val in self._message_index.items() if key[0] != tenant_id
            }
            return True

    async def update_account_fields(
        self, tenant_id: str, account_id: str, updates: dict[str, Any]
    ) -> None:
        with self._lock:
            account = self._accounts.get(tenant_id, {}).get(account_id)
            if account:
                account.update(updates)

    async def increment_account_counts(
        self,
        tenant_id: str,
        account_id: str,
        total_delta: int = 0,
        unread_delta: int = 0,
        sync_error_delta: int = 0,
    ) -> None:
        with self._lock:
            account = self._accounts.get(tenant_id, {}).get(account_id)
            if not account:
                return
            account["total_messages"] = max(0, int(account.get("total_messages", 0)) + total_delta)
            account["unread_count"] = max(0, int(account.get("unread_count", 0)) + unread_delta)
            account["sync_errors"] = max(0, int(account.get("sync_errors", 0)) + sync_error_delta)

    async def save_message(self, tenant_id: str, message: dict[str, Any]) -> tuple[str, bool]:
        with self._lock:
            key = (tenant_id, message["account_id"], message["external_id"])
            messages = self._messages.setdefault(tenant_id, {})
            existing_id = self._message_index.get(key)
            if existing_id and existing_id in messages:
                existing = messages[existing_id]
                old_read = bool(existing.get("is_read"))
                new_read = bool(message.get("is_read"))
                messages[existing_id] = dict(message, id=existing_id)
                if old_read != new_read:
                    delta = -1 if new_read else 1
                    await self.increment_account_counts(
                        tenant_id, message["account_id"], unread_delta=delta
                    )
                return existing_id, False

            message_id = message["id"]
            messages[message_id] = dict(message)
            self._message_index[key] = message_id
            await self.increment_account_counts(
                tenant_id,
                message["account_id"],
                total_delta=1,
                unread_delta=0 if message.get("is_read") else 1,
            )
            return message_id, True

    async def get_message(self, tenant_id: str, message_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._messages.get(tenant_id, {}).get(message_id)

    async def list_messages(
        self,
        tenant_id: str,
        limit: int | None = None,
        offset: int = 0,
        priority_tier: str | None = None,
        account_id: str | None = None,
        unread_only: bool = False,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            messages = list(self._messages.get(tenant_id, {}).values())
        if priority_tier:
            messages = [m for m in messages if m.get("priority_tier") == priority_tier]
        if account_id:
            messages = [m for m in messages if m.get("account_id") == account_id]
        if unread_only:
            messages = [m for m in messages if not m.get("is_read")]
        if search:
            q = search.lower()
            messages = [
                m
                for m in messages
                if q in (m.get("subject") or "").lower()
                or q in (m.get("sender_email") or "").lower()
                or q in (m.get("snippet") or "").lower()
            ]
        messages.sort(
            key=lambda m: (-(m.get("priority_score") or 0.0), m.get("received_at") or ""),
            reverse=False,
        )
        total = len(messages)
        if limit is not None:
            messages = messages[offset : offset + limit]
        return messages, total

    async def delete_message(self, tenant_id: str, message_id: str) -> bool:
        with self._lock:
            messages = self._messages.get(tenant_id, {})
            message = messages.pop(message_id, None)
            if not message:
                return False
            self._triage.get(tenant_id, {}).pop(message_id, None)
            message_key = cast(
                tuple[str, str, str],
                (
                    tenant_id,
                    message.get("account_id"),
                    message.get("external_id"),
                ),
            )
            if message_key in self._message_index:
                self._message_index.pop(message_key, None)
        unread_delta = -1 if not message.get("is_read") else 0
        await self.increment_account_counts(
            tenant_id, message["account_id"], total_delta=-1, unread_delta=unread_delta
        )
        return True

    async def update_message_flags(
        self,
        tenant_id: str,
        message_id: str,
        is_read: bool | None = None,
        is_starred: bool | None = None,
    ) -> bool:
        with self._lock:
            message = self._messages.get(tenant_id, {}).get(message_id)
            if not message:
                return False
            old_read = bool(message.get("is_read"))
            if is_read is not None:
                message["is_read"] = is_read
            if is_starred is not None:
                message["is_starred"] = is_starred
            new_read = bool(message.get("is_read"))
        if old_read != new_read:
            delta = -1 if new_read else 1
            await self.increment_account_counts(
                tenant_id, message["account_id"], unread_delta=delta
            )
        return True

    async def update_message_triage(
        self,
        tenant_id: str,
        message_id: str,
        triage_action: str | None,
        triage_rationale: str | None,
    ) -> None:
        with self._lock:
            message = self._messages.get(tenant_id, {}).get(message_id)
            if not message:
                return
            message["triage_action"] = triage_action
            message["triage_rationale"] = triage_rationale

    async def save_triage_result(self, tenant_id: str, triage: dict[str, Any]) -> None:
        with self._lock:
            self._triage.setdefault(tenant_id, {})[triage["message_id"]] = dict(triage)

    async def get_triage_result(self, tenant_id: str, message_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._triage.get(tenant_id, {}).get(message_id)
