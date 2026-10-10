"""Ownership of queued plan executions and backbone runs.

A queued execution records the org and user that scheduled it, and the plan it
runs must belong to that org. Before a queued execution runs (possibly much
later, in a background task), the plan is reloaded and the execution is refused
when the plan's org no longer equals the execution's org or when the scheduling
user is no longer a member of that org. A refused execution is marked
``failed`` with the reason and the executor is never invoked.

Executions and plans created without any org (internal callers that have no
authenticated user) keep running as before: there is no owner to compare.
"""

from __future__ import annotations

import logging
from typing import Any, NoReturn, TypedDict

logger = logging.getLogger(__name__)

EXECUTION_ORG_MISMATCH = "execution_org_mismatch"
EXECUTION_SCHEDULER_NOT_MEMBER = "execution_scheduler_not_member"
EXECUTION_MEMBERSHIP_UNVERIFIED = "execution_membership_unverified"


class RecordOwner(TypedDict):
    """Ownership keyword arguments for PlanStore execution/run writes."""

    org_id: str | None
    created_by: str | None


class ExecutionNotAuthorizedError(PermissionError):
    """A plan execution may not be queued or run for the scheduling org/user."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _clean(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def resolve_execution_owner(
    auth_context: Any | None,
    *,
    org_id: str | None = None,
    created_by: str | None = None,
) -> tuple[str | None, str | None]:
    """Return ``(org_id, created_by)`` for a new execution or run.

    Explicit values win over the auth context. Without an org there is no
    owner, so both values are None.
    """
    org = _clean(org_id) or _clean(getattr(auth_context, "org_id", None))
    if org is None:
        return None, None
    user = _clean(created_by) or _clean(getattr(auth_context, "user_id", None))
    return org, user


def owner_for_plan(plan: Any, auth_context: Any | None) -> RecordOwner:
    """Ownership kwargs for records created on behalf of ``plan``.

    Records for an owned plan always belong to the plan's org; the creator is
    the acting user when known, otherwise the plan's creator.
    """
    org = _clean(getattr(plan, "org_id", None))
    if org is None:
        return {"org_id": None, "created_by": None}
    user = _clean(getattr(auth_context, "user_id", None)) or _clean(
        getattr(plan, "created_by", None)
    )
    return {"org_id": org, "created_by": user}


def claim_plan_for_scheduler(
    plan: Any,
    stored_plan: Any | None,
    *,
    org_id: str | None,
    created_by: str | None,
) -> None:
    """Check that the scheduler may queue ``plan`` and give an unowned plan its org.

    ``stored_plan`` is the persisted copy (None when the plan is new). An owned
    plan may only be queued by its own org; a plan whose owner is unknown may
    not be queued by any org. Raises :class:`ExecutionNotAuthorizedError`
    before anything is written.
    """
    if stored_plan is not None:
        stored_org = _clean(getattr(stored_plan, "org_id", None))
        stored_source = getattr(stored_plan, "ownership_source", None)
        if stored_org is not None and stored_org != org_id:
            raise ExecutionNotAuthorizedError(
                EXECUTION_ORG_MISMATCH, "Plan belongs to a different organization"
            )
        if stored_org is None and stored_source is not None and org_id is not None:
            raise ExecutionNotAuthorizedError(
                EXECUTION_ORG_MISMATCH, "Plan has no known owning organization"
            )
    if org_id is not None and _clean(getattr(plan, "org_id", None)) is None:
        if stored_plan is None or getattr(stored_plan, "ownership_source", None) is None:
            plan.org_id = org_id
            plan.created_by = created_by


def ensure_execution_still_authorized(
    store: Any,
    *,
    plan_id: str,
    execution_id: str,
    user_store: Any | None = None,
) -> None:
    """Re-check a queued execution's ownership right before it runs.

    Raises :class:`ExecutionNotAuthorizedError` after recording the refusal on
    the execution (status ``failed``) and its backbone run.
    """
    record = store.get_execution_record(execution_id) if execution_id else None
    plan = store.get(plan_id)
    execution_org = _clean(record.get("org_id")) if isinstance(record, dict) else None
    plan_org = _clean(getattr(plan, "org_id", None)) if plan is not None else None

    if execution_org != plan_org:
        _refuse(
            store,
            record,
            EXECUTION_ORG_MISMATCH,
            "The plan no longer belongs to the organization that scheduled this execution",
        )
    if execution_org is None:
        return

    scheduler = _clean(record.get("created_by")) if isinstance(record, dict) else None
    if scheduler is None:
        _refuse(
            store,
            record,
            EXECUTION_MEMBERSHIP_UNVERIFIED,
            "The user who scheduled this execution is unknown",
        )

    from aragora.tenancy.membership import MembershipLookupError, user_org_ids

    try:
        orgs = user_org_ids(scheduler, user_store)
    except MembershipLookupError as exc:
        logger.warning(
            "Refusing execution %s: membership of its scheduler could not be checked (%s)",
            execution_id,
            exc,
        )
        _refuse(
            store,
            record,
            EXECUTION_MEMBERSHIP_UNVERIFIED,
            "Could not verify that the scheduling user still belongs to the organization",
        )
    if execution_org not in orgs:
        _refuse(
            store,
            record,
            EXECUTION_SCHEDULER_NOT_MEMBER,
            "The user who scheduled this execution is no longer a member of the organization",
        )


def _refuse(store: Any, record: dict[str, Any] | None, code: str, message: str) -> NoReturn:
    if isinstance(record, dict):
        execution_id = str(record.get("execution_id") or "")
        logger.warning("Refusing queued execution %s: %s", execution_id, code)
        try:
            store.update_execution_record(
                execution_id,
                status="failed",
                error={"code": code, "message": message},
            )
        except Exception as exc:  # noqa: BLE001 - the refusal itself must still stand
            logger.warning("Failed to record refusal for execution %s: %s", execution_id, exc)
        run_id = str((record.get("metadata") or {}).get("backbone_run_id") or "")
        if run_id:
            try:
                from aragora.pipeline.backbone_runtime import BackboneRuntime

                BackboneRuntime(store).record_execution_stage(
                    run_id,
                    status="refused",
                    artifact_ref=execution_id,
                    run_status="execution_failed",
                    details={"code": code},
                )
            except Exception as exc:  # noqa: BLE001 - best-effort ledger update
                logger.debug("Failed to record refusal on backbone run %s: %s", run_id, exc)
    raise ExecutionNotAuthorizedError(code, message)


__all__ = [
    "EXECUTION_MEMBERSHIP_UNVERIFIED",
    "EXECUTION_ORG_MISMATCH",
    "EXECUTION_SCHEDULER_NOT_MEMBER",
    "ExecutionNotAuthorizedError",
    "claim_plan_for_scheduler",
    "ensure_execution_still_authorized",
    "RecordOwner",
    "owner_for_plan",
    "resolve_execution_owner",
]
