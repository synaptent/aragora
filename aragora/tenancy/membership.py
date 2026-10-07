"""Org membership lookups against the user store.

Answers "which organizations does this user belong to right now" from the user
store, for code that holds a user id but no request: ownership backfills and
background re-checks of a scheduling user.

The user store is, in order: the one passed explicitly, the one the server
registered with :func:`register_user_store` (the store it authenticates
against), else the process-wide ``get_user_store()`` singleton. "No membership"
(unknown user, user without an org, org missing from the store) is an empty
set; "could not check" raises :class:`MembershipLookupError` so callers can
defer instead of recording a wrong answer.

A store registered as provisional (a startup fallback that a later
registration replaces) answers :func:`user_org_ids`, but
:func:`backfill_org_ids` treats it as "could not check": a one-time backfill
must not finalize against memberships the fallback may not hold.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

OrgMembershipResolver = Callable[[str], frozenset[str]]

_registered_user_store: Any | None = None
_registered_store_is_provisional = False


class MembershipLookupError(RuntimeError):
    """The user store could not be consulted, so membership is undetermined."""


def register_user_store(user_store: Any | None, *, provisional: bool = False) -> None:
    """Make ``user_store`` the default for membership lookups (None clears it)."""
    global _registered_user_store, _registered_store_is_provisional
    _registered_user_store = user_store
    _registered_store_is_provisional = provisional and user_store is not None


def backfill_org_ids(user_id: str) -> frozenset[str]:
    """:func:`user_org_ids` for one-time ownership backfills.

    Raises :class:`MembershipLookupError` while the registered store is provisional.
    """
    if _registered_store_is_provisional:
        raise MembershipLookupError("the authoritative user store is not registered yet")
    return user_org_ids(user_id)


def user_org_ids(user_id: str, user_store: Any | None = None) -> frozenset[str]:
    """Return the ids of the orgs ``user_id`` currently belongs to."""
    if not isinstance(user_id, str) or not user_id.strip():
        return frozenset()
    store = user_store if user_store is not None else _registered_user_store
    if store is None:
        store = _singleton_user_store()
    if store is None:
        raise MembershipLookupError("no user store is available")
    try:
        user = store.get_user_by_id(user_id)
        org_id = getattr(user, "org_id", None) if user is not None else None
        if not isinstance(org_id, str) or not org_id.strip():
            return frozenset()
        get_organization = getattr(store, "get_organization_by_id", None)
        if callable(get_organization) and get_organization(org_id) is None:
            return frozenset()
    except Exception as exc:  # noqa: BLE001 - any store failure leaves membership undetermined
        raise MembershipLookupError(f"user store lookup failed: {type(exc).__name__}") from exc
    return frozenset({org_id})


def _singleton_user_store() -> Any | None:
    try:
        from aragora.storage.user_store.singleton import get_user_store

        return get_user_store()
    except Exception as exc:  # noqa: BLE001 - an unusable store means "could not check"
        raise MembershipLookupError(f"user store unavailable: {type(exc).__name__}") from exc


__all__ = [
    "MembershipLookupError",
    "OrgMembershipResolver",
    "backfill_org_ids",
    "register_user_store",
    "user_org_ids",
]
