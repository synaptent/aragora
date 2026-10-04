"""Tests for org membership lookups in aragora.tenancy.membership."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.storage.user_store.sqlite_store import UserStore
from aragora.tenancy import membership
from aragora.tenancy.membership import (
    MembershipLookupError,
    register_user_store,
    user_org_ids,
)


@pytest.fixture(autouse=True)
def _no_registered_store():
    register_user_store(None)
    yield
    register_user_store(None)


@pytest.fixture
def user_store(tmp_path: Path) -> UserStore:
    return UserStore(tmp_path / "users.db")


def _user(store: UserStore, email: str) -> str:
    return store.create_user(email, "hash", "salt", name=email).id


def test_member_of_one_org(user_store: UserStore) -> None:
    owner = _user(user_store, "owner@example.com")
    org = user_store.create_organization("Org A", owner_id=owner)

    assert user_org_ids(owner, user_store) == frozenset({org.id})


def test_user_without_org_and_unknown_user_have_no_org(user_store: UserStore) -> None:
    lonely = _user(user_store, "lonely@example.com")

    assert user_org_ids(lonely, user_store) == frozenset()
    assert user_org_ids("user-that-does-not-exist", user_store) == frozenset()
    assert user_org_ids("", user_store) == frozenset()


def test_org_missing_from_store_is_not_a_membership() -> None:
    store = SimpleNamespace(
        get_user_by_id=lambda user_id: SimpleNamespace(id=user_id, org_id="org-gone"),
        get_organization_by_id=lambda org_id: None,
    )

    assert user_org_ids("user-1", store) == frozenset()


def test_store_failure_is_a_lookup_error() -> None:
    def _boom(user_id: str) -> Any:
        raise RuntimeError("database is locked")

    with pytest.raises(MembershipLookupError):
        user_org_ids("user-1", SimpleNamespace(get_user_by_id=_boom))


def test_registered_store_is_used_before_the_singleton(
    user_store: UserStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _user(user_store, "owner@example.com")
    org = user_store.create_organization("Org A", owner_id=owner)
    monkeypatch.setattr(
        membership,
        "_singleton_user_store",
        lambda: pytest.fail("singleton consulted although a store is registered"),
    )

    register_user_store(user_store)

    assert user_org_ids(owner) == frozenset({org.id})


def test_no_store_available_is_a_lookup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(membership, "_singleton_user_store", lambda: None)

    with pytest.raises(MembershipLookupError):
        user_org_ids("user-1")
