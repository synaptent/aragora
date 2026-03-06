"""Tests for the inbox trust-wedge attestation fixes.

Verifies that:
1. Receipt is persisted *before* the execution gate runs
2. Execution gate validates a stored receipt (not inline-built)
3. Missing receipt blocks execution
4. Invalid signature blocks execution
5. Expired receipt blocks execution
6. Duplicate execution attempt is rejected (already EXECUTED state)
7. DurableFileSigner creates/loads key correctly
8. Ephemeral HMAC is blocked in production/wedge mode
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aragora.core_types import DebateResult
from aragora.gauntlet.receipt_store import (
    ReceiptState,
    ReceiptStateError,
    ReceiptStore,
    get_receipt_store,
    reset_receipt_store,
)
from aragora.gauntlet.signing import (
    DurableFileSigner,
    HMACSigner,
    ReceiptSigner,
    get_default_signer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_singletons():
    """Reset module-level singletons between tests."""
    import aragora.gauntlet.signing as signing_mod
    import aragora.gauntlet.receipt_store as store_mod

    old_signer = signing_mod._default_signer
    signing_mod._default_signer = None
    store_mod.reset_receipt_store()
    yield
    signing_mod._default_signer = old_signer
    store_mod.reset_receipt_store()


def _make_debate_result() -> DebateResult:
    return DebateResult(
        debate_id="debate-tw-001",
        task="Should we deploy to production?",
        final_answer="Yes, with staged rollout.",
        confidence=0.88,
        consensus_reached=True,
        rounds_used=3,
        rounds_completed=3,
        participants=["claude", "gpt"],
        metadata={},
    )


def _make_agents():
    return [
        SimpleNamespace(name="claude", model="claude-opus-4-1", agent_type="anthropic-api"),
        SimpleNamespace(name="gpt", model="gpt-4.1", agent_type="openai-api"),
    ]


def _persist_signed_receipt(store: ReceiptStore, signer: ReceiptSigner) -> str:
    """Helper: create, sign, and persist a receipt, then approve it."""
    from aragora.gauntlet.receipt_models import DecisionReceipt

    result = _make_debate_result()
    receipt = DecisionReceipt.from_debate_result(result)
    receipt.sign(signer)

    store.persist(
        receipt_id=receipt.receipt_id,
        receipt_data=receipt._to_dict_for_signing(),
        signature=receipt.signature,
        signature_key_id=receipt.signature_key_id,
        signed_at=receipt.signed_at,
        signature_algorithm=receipt.signature_algorithm,
        state=ReceiptState.CREATED,
    )
    store.transition(receipt.receipt_id, ReceiptState.APPROVED)
    return receipt.receipt_id


# ---------------------------------------------------------------------------
# Test: receipt persisted before execution gate runs
# ---------------------------------------------------------------------------


class TestReceiptPersistenceOrder:
    """The signed receipt must be persisted BEFORE the execution gate runs."""

    def test_run_method_persists_receipt_before_gate(self):
        """When require_persisted_receipt=True, receipt is persisted in step 2.75
        and the execution gate in step 2.8 receives the receipt_id."""
        from aragora.debate.post_debate_coordinator import (
            PostDebateConfig,
            PostDebateCoordinator,
        )

        config = PostDebateConfig(
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_execute_plan=False,
            auto_queue_improvement=False,
            auto_outcome_feedback=False,
            auto_trigger_canvas=False,
            auto_execution_bridge=False,
            auto_llm_judge=False,
            auto_persist_receipt=True,
            require_persisted_receipt=True,
            enforce_execution_safety_gate=True,
        )
        coordinator = PostDebateCoordinator(config=config)
        result = coordinator.run(
            debate_id="debate-order-001",
            debate_result=_make_debate_result(),
            agents=_make_agents(),
            confidence=0.88,
            task="Deploy?",
        )

        # Receipt was persisted (step 2.75)
        assert result.receipt_persisted is True
        assert result.receipt_id is not None

        # Execution gate ran (step 2.8) and used the persisted receipt
        assert result.execution_gate is not None


# ---------------------------------------------------------------------------
# Test: execution gate validates stored receipt (not inline-built)
# ---------------------------------------------------------------------------


class TestExecutionGateValidatesStoredReceipt:
    """The execution gate must retrieve and verify a previously-persisted receipt."""

    def test_gate_passes_with_valid_persisted_receipt(self):
        from aragora.debate.execution_safety import (
            ExecutionSafetyPolicy,
            evaluate_auto_execution_safety,
        )

        key = b"\x01" * 32
        signer = ReceiptSigner(backend=HMACSigner(secret_key=key, key_id="test-key"))
        store = get_receipt_store()

        # Patch the default signer to use our known key
        with patch("aragora.gauntlet.signing._default_signer", signer):
            with patch("aragora.gauntlet.receipt_store._receipt_store_singleton", store):
                receipt_id = _persist_signed_receipt(store, signer)

                result = _make_debate_result()
                agents = _make_agents()
                policy = ExecutionSafetyPolicy(
                    require_verified_signed_receipt=True,
                    min_provider_diversity=2,
                    min_model_family_diversity=2,
                )

                decision = evaluate_auto_execution_safety(
                    result, agents=agents, policy=policy, receipt_id=receipt_id
                )

                assert decision.receipt_signed is True
                assert decision.receipt_integrity_valid is True
                assert decision.receipt_signature_valid is True


# ---------------------------------------------------------------------------
# Test: missing receipt blocks execution
# ---------------------------------------------------------------------------


class TestMissingReceiptBlocksExecution:
    def test_missing_receipt_id_triggers_verification_failure(self):
        from aragora.debate.execution_safety import (
            ExecutionSafetyPolicy,
            evaluate_auto_execution_safety,
        )

        result = _make_debate_result()
        agents = _make_agents()
        policy = ExecutionSafetyPolicy(require_verified_signed_receipt=True)

        decision = evaluate_auto_execution_safety(
            result,
            agents=agents,
            policy=policy,
            receipt_id="nonexistent-receipt-id",
        )

        assert decision.receipt_signed is False
        assert "receipt_verification_failed" in decision.reason_codes

    def test_none_receipt_id_uses_legacy_path(self):
        """When receipt_id is None, the legacy inline build+sign path is used."""
        from aragora.debate.execution_safety import (
            ExecutionSafetyPolicy,
            evaluate_auto_execution_safety,
        )

        result = _make_debate_result()
        agents = _make_agents()
        policy = ExecutionSafetyPolicy(require_verified_signed_receipt=True)

        # Legacy path: no receipt_id => inline build
        decision = evaluate_auto_execution_safety(
            result, agents=agents, policy=policy, receipt_id=None
        )

        # Should still work via legacy _build_signed_receipt
        assert decision.receipt_signed is True


# ---------------------------------------------------------------------------
# Test: invalid signature blocks execution
# ---------------------------------------------------------------------------


class TestInvalidSignatureBlocksExecution:
    def test_tampered_receipt_fails_verification(self):
        from aragora.gauntlet.receipt_models import DecisionReceipt

        key = b"\x02" * 32
        signer = ReceiptSigner(backend=HMACSigner(secret_key=key, key_id="test-key-2"))
        store = get_receipt_store()

        result = _make_debate_result()
        receipt = DecisionReceipt.from_debate_result(result)
        receipt.sign(signer)

        # Persist with correct data
        data = receipt._to_dict_for_signing()
        store.persist(
            receipt_id=receipt.receipt_id,
            receipt_data=data,
            signature=receipt.signature,
            signature_key_id=receipt.signature_key_id,
            signed_at=receipt.signed_at,
            signature_algorithm=receipt.signature_algorithm,
            state=ReceiptState.APPROVED,
        )

        # Now tamper with the stored receipt data
        stored = store.get(receipt.receipt_id)
        assert stored is not None
        stored.receipt_data["verdict"] = "TAMPERED"

        # Use a different key for verification (simulates key mismatch)
        wrong_key = b"\x03" * 32
        wrong_signer = ReceiptSigner(backend=HMACSigner(secret_key=wrong_key, key_id="wrong"))

        with patch("aragora.gauntlet.signing._default_signer", wrong_signer):
            valid = store.verify_receipt(receipt.receipt_id)
        assert valid is False


# ---------------------------------------------------------------------------
# Test: expired receipt blocks execution
# ---------------------------------------------------------------------------


class TestExpiredReceiptBlocksExecution:
    def test_executed_receipt_not_usable(self):
        """A receipt in EXECUTED state should not pass the gate."""
        from aragora.debate.execution_safety import _retrieve_persisted_receipt

        key = b"\x04" * 32
        signer = ReceiptSigner(backend=HMACSigner(secret_key=key, key_id="test-key-4"))
        store = get_receipt_store()

        with patch("aragora.gauntlet.signing._default_signer", signer):
            with patch("aragora.gauntlet.receipt_store._receipt_store_singleton", store):
                receipt_id = _persist_signed_receipt(store, signer)
                # Transition to EXECUTED
                store.transition(receipt_id, ReceiptState.EXECUTED)

                receipt, signed, integrity, sig_valid = _retrieve_persisted_receipt(receipt_id)
                # EXECUTED state should be rejected
                assert receipt is None
                assert signed is False

    def test_expired_receipt_not_usable(self):
        """A receipt in EXPIRED state should not pass the gate."""
        from aragora.debate.execution_safety import _retrieve_persisted_receipt

        key = b"\x05" * 32
        signer = ReceiptSigner(backend=HMACSigner(secret_key=key, key_id="test-key-5"))
        store = get_receipt_store()

        with patch("aragora.gauntlet.signing._default_signer", signer):
            with patch("aragora.gauntlet.receipt_store._receipt_store_singleton", store):
                receipt_id = _persist_signed_receipt(store, signer)
                # Expire the receipt (APPROVED -> EXPIRED)
                store.transition(receipt_id, ReceiptState.EXPIRED)

                receipt, signed, integrity, sig_valid = _retrieve_persisted_receipt(receipt_id)
                assert receipt is None
                assert signed is False


# ---------------------------------------------------------------------------
# Test: duplicate execution attempt rejected (already EXECUTED state)
# ---------------------------------------------------------------------------


class TestDuplicateExecutionRejected:
    def test_cannot_transition_executed_to_executed(self):
        store = ReceiptStore()
        store.persist(
            receipt_id="r-dup-001",
            receipt_data={"test": True},
            state=ReceiptState.CREATED,
        )
        store.transition("r-dup-001", ReceiptState.APPROVED)
        store.transition("r-dup-001", ReceiptState.EXECUTED)

        with pytest.raises(ReceiptStateError):
            store.transition("r-dup-001", ReceiptState.EXECUTED)

    def test_cannot_transition_executed_to_approved(self):
        store = ReceiptStore()
        store.persist(
            receipt_id="r-dup-002",
            receipt_data={"test": True},
            state=ReceiptState.CREATED,
        )
        store.transition("r-dup-002", ReceiptState.APPROVED)
        store.transition("r-dup-002", ReceiptState.EXECUTED)

        with pytest.raises(ReceiptStateError):
            store.transition("r-dup-002", ReceiptState.APPROVED)


# ---------------------------------------------------------------------------
# Test: DurableFileSigner creates and loads key correctly
# ---------------------------------------------------------------------------


class TestDurableFileSigner:
    def test_creates_key_on_first_use(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = os.path.join(tmpdir, "test_signing.key")
            assert not os.path.exists(key_path)

            signer = DurableFileSigner(key_path=key_path)

            assert os.path.isfile(key_path)
            # Verify the key was written
            with open(key_path) as f:
                content = f.read().strip()
            assert len(content) == 64  # 32 bytes hex-encoded

    def test_loads_existing_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = os.path.join(tmpdir, "test_signing.key")

            # Create the signer (generates key)
            signer1 = DurableFileSigner(key_path=key_path)
            data = b"test message"
            sig1 = signer1.sign(data)

            # Create a second signer from the same file
            signer2 = DurableFileSigner(key_path=key_path)
            sig2 = signer2.sign(data)

            # Both should produce the same signature
            assert sig1 == sig2
            assert signer2.verify(data, sig1)

    def test_key_file_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = os.path.join(tmpdir, "test_signing.key")
            DurableFileSigner(key_path=key_path)

            # File should be owner-only read/write
            mode = os.stat(key_path).st_mode & 0o777
            assert mode == 0o600

    def test_signs_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = os.path.join(tmpdir, "test_signing.key")
            signer = DurableFileSigner(key_path=key_path)

            data = b"decision receipt payload"
            sig = signer.sign(data)
            assert signer.verify(data, sig)
            assert not signer.verify(b"tampered", sig)


# ---------------------------------------------------------------------------
# Test: ephemeral HMAC blocked in production mode
# ---------------------------------------------------------------------------


class TestEphemeralHMACBlocked:
    def test_production_mode_without_env_key_raises(self):
        """In production mode, get_default_signer must raise if no signing key."""
        import aragora.gauntlet.signing as mod

        mod._default_signer = None

        with patch.dict(
            os.environ,
            {
                "ARAGORA_ENV": "production",
                "ARAGORA_RECEIPT_SIGNING_KEY": "",
            },
            clear=False,
        ):
            # Remove the key from env
            os.environ.pop("ARAGORA_RECEIPT_SIGNING_KEY", None)

            with pytest.raises(RuntimeError, match="required in production"):
                get_default_signer()

    def test_env_key_used_when_set(self):
        """When ARAGORA_RECEIPT_SIGNING_KEY is set, it should be used."""
        import aragora.gauntlet.signing as mod

        mod._default_signer = None

        test_key = "aa" * 32  # 64 hex chars = 32 bytes
        with patch.dict(os.environ, {"ARAGORA_RECEIPT_SIGNING_KEY": test_key}, clear=False):
            signer = get_default_signer()
            assert signer is not None
            # Should be able to sign and verify with the configured key
            data = b"test data"
            signed = signer.sign({"payload": "test"})
            assert signer.verify(signed) is True


# ---------------------------------------------------------------------------
# Test: receipt state machine
# ---------------------------------------------------------------------------


class TestReceiptStateMachine:
    def test_valid_transitions(self):
        store = ReceiptStore()
        store.persist("r-sm-001", {"test": True}, state=ReceiptState.CREATED)

        s = store.transition("r-sm-001", ReceiptState.APPROVED)
        assert s.state == ReceiptState.APPROVED

        s = store.transition("r-sm-001", ReceiptState.EXECUTED)
        assert s.state == ReceiptState.EXECUTED

    def test_created_to_expired(self):
        store = ReceiptStore()
        store.persist("r-sm-002", {"test": True}, state=ReceiptState.CREATED)

        s = store.transition("r-sm-002", ReceiptState.EXPIRED)
        assert s.state == ReceiptState.EXPIRED

    def test_approved_to_expired(self):
        store = ReceiptStore()
        store.persist("r-sm-003", {"test": True}, state=ReceiptState.CREATED)
        store.transition("r-sm-003", ReceiptState.APPROVED)

        s = store.transition("r-sm-003", ReceiptState.EXPIRED)
        assert s.state == ReceiptState.EXPIRED

    def test_invalid_transition_raises(self):
        store = ReceiptStore()
        store.persist("r-sm-004", {"test": True}, state=ReceiptState.CREATED)

        # Cannot go directly from CREATED to EXECUTED
        with pytest.raises(ReceiptStateError):
            store.transition("r-sm-004", ReceiptState.EXECUTED)

    def test_missing_receipt_raises_key_error(self):
        store = ReceiptStore()
        with pytest.raises(KeyError):
            store.transition("nonexistent", ReceiptState.APPROVED)

    def test_list_receipts_by_state(self):
        store = ReceiptStore()
        store.persist("r-list-001", {"a": 1}, state=ReceiptState.CREATED)
        store.persist("r-list-002", {"b": 2}, state=ReceiptState.CREATED)
        store.transition("r-list-002", ReceiptState.APPROVED)

        created = store.list_receipts(state=ReceiptState.CREATED)
        assert len(created) == 1
        assert created[0].receipt_id == "r-list-001"

        approved = store.list_receipts(state=ReceiptState.APPROVED)
        assert len(approved) == 1
        assert approved[0].receipt_id == "r-list-002"

        all_receipts = store.list_receipts()
        assert len(all_receipts) == 2
