"""Revision content hashing for workspace decisions."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from aragora.gauntlet.odr_jcs import jcs_canonicalize

ORIGIN_DEBATE = "debate"
ORIGIN_USER_EDIT = "user_edit"
REVISION_ORIGINS = (ORIGIN_DEBATE, ORIGIN_USER_EDIT)

REVISION_DRAFT = "draft"
REVISION_CURRENT = "current"
REVISION_SUPERSEDED = "superseded"
REVISION_STATUSES = (REVISION_DRAFT, REVISION_CURRENT, REVISION_SUPERSEDED)


def revision_content_hash(
    plan_id: str, number: int, parent_revision_id: str | None, content: Mapping[str, Any]
) -> str:
    """SHA-256 hex of the JCS form of ``{plan_id, number, parent_revision_id, content}``."""
    document = {
        "plan_id": plan_id,
        "number": number,
        "parent_revision_id": parent_revision_id,
        "content": content,
    }
    return hashlib.sha256(jcs_canonicalize(document)).hexdigest()


__all__ = [
    "ORIGIN_DEBATE",
    "ORIGIN_USER_EDIT",
    "REVISION_CURRENT",
    "REVISION_DRAFT",
    "REVISION_ORIGINS",
    "REVISION_STATUSES",
    "REVISION_SUPERSEDED",
    "revision_content_hash",
]
