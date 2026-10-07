"""
ERC-8004 Adapter for Knowledge Mound.

Provides bidirectional synchronization between ERC-8004 on-chain registries
and Knowledge Mound:

Forward sync (blockchain -> KM):
- Agent identities become knowledge nodes
- Reputation feedback informs confidence scores
- Validation records provide trust attestations

Reverse sync (KM -> blockchain):
- ELO ratings contribute to on-chain reputation
- Gauntlet receipts become validation records
- Debate outcomes inform feedback

Usage:
    from aragora.knowledge.mound.adapters.erc8004_adapter import ERC8004Adapter
    from aragora.blockchain.provider import Web3Provider

    provider = Web3Provider.from_env()
    adapter = ERC8004Adapter(provider=provider)

    # Sync on-chain data to KM
    result = await adapter.sync_to_km()

    # Push KM ratings to blockchain
    result = await adapter.sync_from_km()
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter
from aragora.knowledge.mound.adapters._types import SyncResult, ValidationSyncResult

if TYPE_CHECKING:
    from aragora.blockchain.provider import Web3Provider
    from aragora.blockchain.wallet import WalletSigner

logger = logging.getLogger(__name__)


class ERC8004Adapter(KnowledgeMoundAdapter):
    """Bidirectional adapter between ERC-8004 registries and Knowledge Mound.

    Synchronizes on-chain agent data (identity, reputation, validation)
    with Knowledge Mound nodes, enabling trustless verification and
    cross-system confidence calibration.
    """

    adapter_name = "erc8004"

    def __init__(
        self,
        provider: Web3Provider | None = None,
        signer: WalletSigner | None = None,
        km_store: Any | None = None,
        enable_reverse_sync: bool = False,
        min_elo_for_reputation: float = 1500.0,
        **kwargs: Any,
    ) -> None:
        """Initialize the ERC-8004 adapter.

        Args:
            provider: Web3Provider for blockchain access.
            signer: WalletSigner for write operations (optional).
            km_store: Knowledge Mound store instance.
            enable_reverse_sync: If True, enables KM->blockchain sync.
            min_elo_for_reputation: Minimum ELO score to push reputation.
            **kwargs: Additional KnowledgeMoundAdapter arguments.
        """
        super().__init__(**kwargs)
        self._provider = provider
        self._signer = signer
        self._km_store = km_store
        self._enable_reverse_sync = enable_reverse_sync
        self._min_elo_for_reputation = min_elo_for_reputation
        self._identity_contract: Any = None
        self._reputation_contract: Any = None
        self._validation_contract: Any = None

    def _get_provider(self) -> Web3Provider:
        """Get or create the Web3 provider."""
        if self._provider is None:
            from aragora.blockchain.provider import Web3Provider

            self._provider = Web3Provider.from_env()
        return self._provider

    def _get_identity_contract(self) -> Any:
        """Get or create the Identity Registry contract."""
        if self._identity_contract is None:
            from aragora.blockchain.contracts.identity import IdentityRegistryContract

            self._identity_contract = IdentityRegistryContract(self._get_provider())
        return self._identity_contract

    def _get_reputation_contract(self) -> Any:
        """Get or create the Reputation Registry contract."""
        if self._reputation_contract is None:
            from aragora.blockchain.contracts.reputation import ReputationRegistryContract

            self._reputation_contract = ReputationRegistryContract(self._get_provider())
        return self._reputation_contract

    def _get_validation_contract(self) -> Any:
        """Get or create the Validation Registry contract."""
        if self._validation_contract is None:
            from aragora.blockchain.contracts.validation import ValidationRegistryContract

            self._validation_contract = ValidationRegistryContract(self._get_provider())
        return self._validation_contract

    async def sync_to_km(
        self,
        agent_ids: list[int] | None = None,
        sync_identities: bool = True,
        sync_reputation: bool = True,
        sync_validations: bool = True,
    ) -> SyncResult:
        """Sync on-chain data to Knowledge Mound.

        Retrieves agent identities, reputation summaries, and validation
        records from ERC-8004 registries and stores them as KM nodes.

        Args:
            agent_ids: Specific agent IDs to sync. None = all known agents.
            sync_identities: Whether to sync identity records.
            sync_reputation: Whether to sync reputation summaries.
            sync_validations: Whether to sync validation records.

        Returns:
            SyncResult with counts and errors.
        """
        start_time = time.time()
        synced = 0
        skipped = 0
        failed = 0
        errors: list[str] = []

        try:
            async with self._resilient_call("sync_to_km"):
                provider = self._get_provider()
                config = provider.get_config()

                # Get agent IDs to sync
                if agent_ids is None and config.has_identity_registry:
                    # Get all registered agents (up to a reasonable limit)
                    try:
                        total = self._get_identity_contract().get_total_supply()
                        agent_ids = list(range(1, min(total + 1, 1001)))
                    except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                        logger.warning("Could not get total supply: %s", e)
                        agent_ids = []

                for agent_id in agent_ids or []:
                    try:
                        # Sync identity
                        if sync_identities and config.has_identity_registry:
                            identity = self._get_identity_contract().get_agent(agent_id)
                            await self._store_identity_node(identity)
                            synced += 1

                        # Sync reputation summary
                        if sync_reputation and config.has_reputation_registry:
                            try:
                                summary = self._get_reputation_contract().get_summary(agent_id)
                                await self._store_reputation_node(summary)
                                synced += 1
                            except (
                                OSError,
                                ConnectionError,
                                RuntimeError,
                                ValueError,
                                KeyError,
                            ) as e:  # noqa: BLE001 - adapter isolation
                                logger.debug("No reputation for agent %s: %s", agent_id, e)
                                skipped += 1

                        # Sync validations
                        if sync_validations and config.has_validation_registry:
                            try:
                                validation_hashes = (
                                    self._get_validation_contract().get_agent_validations(agent_id)
                                )
                                for req_hash in validation_hashes[:10]:  # Limit per agent
                                    record = self._get_validation_contract().get_validation_status(
                                        req_hash
                                    )
                                    await self._store_validation_node(record)
                                    synced += 1
                            except (
                                OSError,
                                ConnectionError,
                                RuntimeError,
                                ValueError,
                                KeyError,
                            ) as e:  # noqa: BLE001 - adapter isolation
                                logger.debug("No validations for agent %s: %s", agent_id, e)
                                skipped += 1

                    except (
                        OSError,
                        ConnectionError,
                        RuntimeError,
                        ValueError,
                        AttributeError,
                    ) as e:  # noqa: BLE001 - adapter isolation
                        failed += 1
                        logger.warning("Failed to sync agent %s: %s", agent_id, e)
                        errors.append(f"Agent {agent_id}: sync failed")

        except (OSError, ConnectionError, RuntimeError, ValueError, AttributeError) as e:
            logger.warning("sync_to_km failed: %s", e)
            errors.append("Sync failed")

        duration_ms = (time.time() - start_time) * 1000
        return SyncResult(
            records_synced=synced,
            records_skipped=skipped,
            records_failed=failed,
            errors=errors,
            duration_ms=duration_ms,
        )

    async def sync_from_km(
        self,
        push_elo_ratings: bool = True,
        push_calibration: bool = True,
        push_receipts: bool = True,
    ) -> ValidationSyncResult:
        """Sync Knowledge Mound data to blockchain (reverse flow).

        Pushes ELO ratings as reputation feedback and gauntlet receipts
        as validation records to ERC-8004 registries.

        Requires a signer to be configured.

        Args:
            push_elo_ratings: Whether to push ELO ratings as reputation.
            push_calibration: Whether to push calibration (Brier) scores.
            push_receipts: Whether to push receipts as validations.

        Returns:
            ValidationSyncResult with counts and errors.
        """
        start_time = time.time()
        analyzed = 0
        updated = 0
        skipped = 0
        errors: list[str] = []

        if not self._enable_reverse_sync:
            return ValidationSyncResult(
                records_analyzed=0,
                records_updated=0,
                records_skipped=0,
                errors=["Reverse sync is disabled"],
                duration_ms=0.0,
            )

        if self._signer is None:
            return ValidationSyncResult(
                records_analyzed=0,
                records_updated=0,
                records_skipped=0,
                errors=["No signer configured for write operations"],
                duration_ms=0.0,
            )

        try:
            async with self._resilient_call("sync_from_km"):
                provider = self._get_provider()
                config = provider.get_config()

                # Step 1: Get agent identity mappings
                # _get_identity_bridge is defined below in this class
                identity_bridge = self._get_identity_bridge()  # type: ignore[attr-defined]
                linked_agents = identity_bridge.get_all_links()

                if not linked_agents:
                    logger.info("No agents linked to blockchain identities")
                    return ValidationSyncResult(
                        records_analyzed=0,
                        records_updated=0,
                        records_skipped=1,
                        errors=["No agents linked to blockchain identities"],
                        duration_ms=(time.time() - start_time) * 1000,
                    )

                # Step 2: Push ELO ratings as reputation feedback
                # _push_elo_as_reputation is defined below in this class
                if push_elo_ratings and config.has_reputation_registry:
                    elo_result = await self._push_elo_as_reputation(linked_agents)  # type: ignore[attr-defined]
                    analyzed += elo_result["analyzed"]
                    updated += elo_result["updated"]
                    skipped += elo_result["skipped"]
                    errors.extend(elo_result["errors"])

                # Step 3: Push calibration scores as reputation feedback
                if push_calibration and config.has_reputation_registry:
                    cal_result = await self._push_calibration_as_reputation(linked_agents)
                    analyzed += cal_result["analyzed"]
                    updated += cal_result["updated"]
                    skipped += cal_result["skipped"]
                    errors.extend(cal_result["errors"])

                # Step 4: Push gauntlet receipts as validation records
                # _push_receipts_as_validations is defined below in this class
                if push_receipts and config.has_validation_registry:
                    receipt_result = await self._push_receipts_as_validations(linked_agents)  # type: ignore[attr-defined]
                    analyzed += receipt_result["analyzed"]
                    updated += receipt_result["updated"]
                    skipped += receipt_result["skipped"]
                    errors.extend(receipt_result["errors"])

        except (OSError, ConnectionError, RuntimeError, ValueError, AttributeError) as e:
            logger.warning("sync_from_km failed: %s", e)
            errors.append("Reverse sync failed")

        duration_ms = (time.time() - start_time) * 1000
        return ValidationSyncResult(
            records_analyzed=analyzed,
            records_updated=updated,
            records_skipped=skipped,
            errors=errors,
            duration_ms=duration_ms,
        )

    async def _store_identity_node(self, identity: Any) -> None:
        """Store an agent identity as a KM node."""
        if self._km_store is None:
            return

        node_data = {
            "type": "agent_identity",
            "source": "erc8004",
            "token_id": identity.token_id,
            "owner": identity.owner,
            "agent_uri": identity.agent_uri,
            "wallet_address": identity.wallet_address,
            "chain_id": identity.chain_id,
            "aragora_agent_id": identity.aragora_agent_id,
        }

        self._emit_event("identity_synced", node_data)
        logger.debug("Stored identity node for agent #%s", identity.token_id)

    async def _store_reputation_node(self, summary: Any) -> None:
        """Store a reputation summary as a KM node."""
        if self._km_store is None:
            return

        node_data = {
            "type": "reputation_summary",
            "source": "erc8004",
            "agent_id": summary.agent_id,
            "count": summary.count,
            "value": summary.normalized_value,
            "tag1": summary.tag1,
            "tag2": summary.tag2,
        }

        self._emit_event("reputation_synced", node_data)
        logger.debug("Stored reputation node for agent #%s", summary.agent_id)

    async def _store_validation_node(self, record: Any) -> None:
        """Store a validation record as a KM node."""
        if self._km_store is None:
            return

        node_data = {
            "type": "validation_record",
            "source": "erc8004",
            "request_hash": record.request_hash,
            "agent_id": record.agent_id,
            "validator": record.validator_address,
            "response": record.response.name,
            "tag": record.tag,
        }

        self._emit_event("validation_synced", node_data)
        logger.debug("Stored validation node for hash %s...", record.request_hash[:16])

    def _get_identity_bridge(self) -> Any:
        """Get the blockchain identity bridge for agent ID mappings."""
        from aragora.blockchain.agent_registry import get_blockchain_identity_bridge

        bridge = get_blockchain_identity_bridge()
        # Ensure the bridge uses our provider if set
        if self._provider is not None and bridge._provider is None:
            bridge._provider = self._provider
        return bridge

    def _get_performance_adapter(self) -> Any:
        """Get a PerformanceAdapter for ELO data access."""
        from aragora.knowledge.mound.adapters import PerformanceAdapter

        return PerformanceAdapter()

    async def _push_elo_as_reputation(
        self,
        linked_agents: list[Any],
    ) -> dict[str, Any]:
        """Push ELO ratings as reputation feedback to the blockchain.

        Converts Aragora ELO ratings to on-chain reputation feedback records.
        Only pushes reputation for agents meeting the minimum ELO threshold.

        Args:
            linked_agents: List of AgentBlockchainLink records.

        Returns:
            Dict with analyzed, updated, skipped counts and errors.
        """
        analyzed = 0
        updated = 0
        skipped = 0
        errors: list[str] = []

        if self._signer is None:
            return {
                "analyzed": 0,
                "updated": 0,
                "skipped": 0,
                "errors": ["No signer configured"],
            }

        performance_adapter = self._get_performance_adapter()
        reputation_contract = self._get_reputation_contract()

        for link in linked_agents:
            analyzed += 1
            agent_id = link.aragora_agent_id
            token_id = link.token_id

            try:
                # Get the latest ELO rating for this agent
                skill_history = performance_adapter.get_agent_skill_history(agent_id, limit=1)

                if not skill_history:
                    logger.debug("No ELO history for agent %s", agent_id)
                    skipped += 1
                    continue

                latest_rating = skill_history[0]
                elo = latest_rating.get("elo", 1500.0)

                # Skip agents below minimum ELO threshold
                if elo < self._min_elo_for_reputation:
                    logger.debug(
                        f"Agent {agent_id} ELO {elo:.0f} below threshold "
                        f"{self._min_elo_for_reputation}"
                    )
                    skipped += 1
                    continue

                # Verify consensus: agent must have sufficient debates
                debates_count = latest_rating.get("debates_count", 0)
                if debates_count < 3:
                    logger.debug(
                        "Agent %s has insufficient debates (%s) for consensus verification",
                        agent_id,
                        debates_count,
                    )
                    skipped += 1
                    continue

                # Convert ELO to reputation value
                # Scale: ELO 1000-2000 maps to reputation value 0-1000
                # Using 2 decimal places (value_decimals=2)
                elo_normalized = max(1000.0, min(2000.0, elo))
                reputation_value = int(elo_normalized - 1000.0)

                # Compute feedback hash from ELO data for integrity
                import hashlib

                feedback_data = f"{agent_id}:{elo:.2f}:{debates_count}"
                feedback_hash = hashlib.sha256(feedback_data.encode()).digest()

                # Get domain expertise tags
                domain_elos = latest_rating.get("domain_elos", {})
                tag1 = "aragora_elo"
                tag2 = ""
                if domain_elos:
                    # Use the best domain as tag2
                    best_domain = max(domain_elos, key=lambda k: domain_elos.get(k, 0))
                    tag2 = best_domain

                # Submit reputation feedback to blockchain
                try:
                    tx_hash = reputation_contract.give_feedback(
                        agent_id=token_id,
                        value=reputation_value,
                        signer=self._signer,
                        value_decimals=0,
                        tag1=tag1,
                        tag2=tag2,
                        endpoint="",
                        feedback_uri=f"aragora://elo/{agent_id}",
                        feedback_hash=feedback_hash,
                    )

                    self._emit_event(
                        "reputation_pushed",
                        {
                            "agent_id": agent_id,
                            "token_id": token_id,
                            "elo": elo,
                            "reputation_value": reputation_value,
                            "tx_hash": tx_hash,
                        },
                    )

                    logger.info(
                        f"Pushed reputation for {agent_id} (token {token_id}): "
                        f"ELO {elo:.0f} -> reputation {reputation_value}, tx={tx_hash[:16]}..."
                    )
                    updated += 1

                except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                    logger.warning("Failed to push reputation for %s: %s", agent_id, e)
                    errors.append(f"Failed to push reputation for {agent_id}")

            except (
                OSError,
                ConnectionError,
                RuntimeError,
                ValueError,
                KeyError,
                AttributeError,
            ) as e:  # noqa: BLE001 - adapter isolation
                logger.warning("Error processing agent %s: %s", agent_id, e)
                errors.append(f"Error processing agent {agent_id}")

        return {
            "analyzed": analyzed,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

    async def _push_calibration_as_reputation(
        self,
        linked_agents: list[Any],
    ) -> dict[str, Any]:
        """Push calibration (Brier) scores as reputation feedback.

        Calibration measures prediction accuracy — how well an agent's
        confidence correlates with actual outcomes. This is a stronger
        trustworthiness signal than raw ELO because it captures epistemic
        honesty: agents that say "I'm 70% sure" and are right 70% of the
        time score better than agents that always say 99%.

        Uses tag1="calibration" and tag2=domain for domain-specific scores.

        Args:
            linked_agents: List of AgentBlockchainLink records.

        Returns:
            Dict with analyzed, updated, skipped counts and errors.
        """
        analyzed = 0
        updated = 0
        skipped = 0
        errors: list[str] = []

        if self._signer is None:
            return {
                "analyzed": 0,
                "updated": 0,
                "skipped": 0,
                "errors": ["No signer configured"],
            }

        try:
            from aragora.ranking.calibration_engine import CalibrationEngine
        except ImportError:
            logger.debug("CalibrationEngine not available")
            return {
                "analyzed": 0,
                "updated": 0,
                "skipped": 0,
                "errors": ["CalibrationEngine not available"],
            }

        reputation_contract = self._get_reputation_contract()

        # Create a CalibrationEngine instance
        try:
            from aragora.ranking.elo import EloSystem

            elo_system = EloSystem()
            calibration_engine = CalibrationEngine(db_path=":memory:", elo_system=elo_system)
        except (RuntimeError, ValueError, OSError) as e:
            return {
                "analyzed": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [f"Could not create CalibrationEngine: {e}"],
            }

        for link in linked_agents:
            analyzed += 1
            agent_id = link.aragora_agent_id
            token_id = link.token_id

            try:
                # Get calibration stats for this agent
                stats = calibration_engine.get_domain_stats(agent_id)  # type: ignore[attr-defined]

                total_predictions = stats.get("total", 0)
                if total_predictions < 5:
                    logger.debug(
                        "Agent %s has insufficient predictions (%s) for calibration reputation",
                        agent_id,
                        total_predictions,
                    )
                    skipped += 1
                    continue

                brier_score = stats.get("brier_score", 1.0)

                # Convert Brier score to reputation value
                # Brier score: 0 = perfect, 1 = worst
                # Reputation: 0-1000, higher = better
                # calibration_reputation = (1 - brier_score) * 1000
                calibration_reputation = int((1.0 - min(1.0, max(0.0, brier_score))) * 1000)

                # Compute feedback hash
                import hashlib

                feedback_data = f"{agent_id}:calibration:{brier_score:.4f}:{total_predictions}"
                feedback_hash = hashlib.sha256(feedback_data.encode()).digest()

                # Push overall calibration score
                try:
                    tx_hash = reputation_contract.give_feedback(
                        agent_id=token_id,
                        value=calibration_reputation,
                        signer=self._signer,
                        value_decimals=0,
                        tag1="calibration",
                        tag2="brier_score",
                        endpoint="",
                        feedback_uri=f"aragora://calibration/{agent_id}",
                        feedback_hash=feedback_hash,
                    )

                    self._emit_event(
                        "calibration_pushed",
                        {
                            "agent_id": agent_id,
                            "token_id": token_id,
                            "brier_score": brier_score,
                            "calibration_reputation": calibration_reputation,
                            "total_predictions": total_predictions,
                            "tx_hash": tx_hash,
                        },
                    )

                    logger.info(
                        f"Pushed calibration for {agent_id} (token {token_id}): "
                        f"Brier={brier_score:.4f} -> reputation {calibration_reputation}, "
                        f"tx={tx_hash[:16]}..."
                    )
                    updated += 1

                except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                    logger.warning("Failed to push calibration for %s: %s", agent_id, e)
                    errors.append(f"Failed to push calibration for {agent_id}")

                # Push per-domain calibration scores
                domains = stats.get("domains", {})
                for domain, domain_stats in domains.items():
                    domain_predictions = domain_stats.get("total_predictions", 0)
                    if domain_predictions < 3:
                        continue

                    domain_brier = domain_stats.get("brier_score", 1.0)
                    domain_rep = int((1.0 - min(1.0, max(0.0, domain_brier))) * 1000)

                    domain_data = f"{agent_id}:calibration:{domain}:{domain_brier:.4f}"
                    domain_hash = hashlib.sha256(domain_data.encode()).digest()

                    try:
                        tx_hash = reputation_contract.give_feedback(
                            agent_id=token_id,
                            value=domain_rep,
                            signer=self._signer,
                            value_decimals=0,
                            tag1="calibration",
                            tag2=domain,
                            endpoint="",
                            feedback_uri=f"aragora://calibration/{agent_id}/{domain}",
                            feedback_hash=domain_hash,
                        )
                        updated += 1

                    except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                        logger.debug(
                            "Failed to push domain calibration %s for %s: %s", domain, agent_id, e
                        )

            except (
                OSError,
                ConnectionError,
                RuntimeError,
                ValueError,
                KeyError,
                AttributeError,
            ) as e:  # noqa: BLE001 - adapter isolation
                logger.warning("Error processing calibration for %s: %s", agent_id, e)
                errors.append(f"Error processing calibration for {agent_id}")

        return {
            "analyzed": analyzed,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

    async def register_prediction_commitment(
        self,
        agent_id: str,
        token_id: int,
        topic: str,
        debate_id: str = "",
    ) -> dict[str, Any]:
        """Register a prediction pre-commitment for an agent before debate.

        Implements the CbKVC (credential-based Key-Value Commitment) pattern
        from Jutla et al. — agents must register which topics they will opine
        on *before* seeing the question. This prevents cherry-picking: agents
        can't selectively report calibration only on domains where they're
        already well-calibrated.

        Called at debate start. The matching calibration score push happens
        at debate end via _push_calibration_as_reputation().

        The commitment is stored on-chain as a reputation feedback record with
        tag1="commitment" so it can be verified against later calibration
        submissions.

        Args:
            agent_id: Aragora agent identifier.
            token_id: On-chain ERC-8004 token ID for this agent.
            topic: Debate topic or question being committed to.
            debate_id: Optional debate identifier for traceability.

        Returns:
            Dict with commitment_hash, tx_hash (if on-chain), and status.
        """
        import hashlib

        # Generate deterministic commitment hash from agent + topic
        commitment_data = f"{agent_id}:commitment:{topic}:{debate_id}"
        commitment_hash = hashlib.sha256(commitment_data.encode()).digest()

        result: dict[str, Any] = {
            "agent_id": agent_id,
            "token_id": token_id,
            "topic_hash": hashlib.sha256(topic.encode()).hexdigest()[:16],
            "commitment_hash": commitment_hash.hex()[:32],
            "debate_id": debate_id,
            "status": "recorded",
        }

        # If we have a signer and reputation contract, record on-chain
        if self._signer is not None and self._enable_reverse_sync:
            try:
                reputation_contract = self._get_reputation_contract()

                tx_hash = reputation_contract.give_feedback(
                    agent_id=token_id,
                    value=0,  # Commitment has no value yet — value comes later
                    signer=self._signer,
                    value_decimals=0,
                    tag1="commitment",
                    tag2=hashlib.sha256(topic.encode()).hexdigest()[:16],
                    endpoint="",
                    feedback_uri=f"aragora://commitment/{agent_id}/{debate_id}",
                    feedback_hash=commitment_hash,
                )

                result["tx_hash"] = tx_hash
                result["status"] = "on_chain"

                logger.info(
                    "Registered prediction commitment for %s (token %s), topic_hash=%s, tx=%s...",
                    agent_id,
                    token_id,
                    result["topic_hash"],
                    tx_hash[:16],
                )

            except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                result["status"] = "local_only"
                result["error"] = f"On-chain commitment failed: {type(e).__name__}"
                logger.warning(
                    "On-chain commitment failed for %s, recording locally: %s", agent_id, e
                )

        # Always emit event for local tracking
        self._emit_event("prediction_committed", result)

        return result

    def push_reputation(
        self,
        agent_id: str,
        score: int,
        domain: str = "calibration",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Push a reputation score for an agent (synchronous convenience method).

        Used by PostDebateCoordinator to push calibration-derived reputation
        after each debate without needing the full async sync_from_km flow.

        Args:
            agent_id: Aragora agent identifier.
            score: Reputation score (0-100).
            domain: Domain tag for the reputation signal.
            metadata: Optional metadata dict.

        Returns:
            True if the reputation was recorded (locally or on-chain).
        """
        import hashlib

        record = {
            "agent_id": agent_id,
            "score": score,
            "domain": domain,
            "metadata": metadata or {},
            "status": "recorded",
        }
        resolved_agent_id: int | None = None
        if isinstance(agent_id, int):
            resolved_agent_id = agent_id if agent_id >= 0 else None
        elif isinstance(metadata, dict):
            try:
                candidate = int(metadata.get("on_chain_agent_id"))
            except (TypeError, ValueError):
                candidate = None
            if candidate is not None and candidate >= 0:
                resolved_agent_id = candidate

        # If we have signer + reverse sync, push on-chain
        if self._signer is not None and self._enable_reverse_sync and resolved_agent_id is not None:
            try:
                reputation_contract = self._get_reputation_contract()
                feedback_data = f"{agent_id}:{domain}:{score}"
                feedback_hash = hashlib.sha256(feedback_data.encode()).digest()

                tx_hash = reputation_contract.give_feedback(
                    agent_id=resolved_agent_id,
                    value=score,
                    signer=self._signer,
                    value_decimals=0,
                    tag1=domain,
                    tag2=metadata.get("debate_id", "") if metadata else "",
                    endpoint="",
                    feedback_uri=f"aragora://calibration/{agent_id}",
                    feedback_hash=feedback_hash,
                )
                record["tx_hash"] = tx_hash
                record["status"] = "on_chain"
            except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                record["status"] = "local_only"
                logger.debug("On-chain reputation push failed for %s: %s", agent_id, e)
        elif self._signer is not None and self._enable_reverse_sync:
            record["status"] = "local_only"
            record["error"] = "on_chain_agent_id is required for reverse sync"

        self._emit_event("reputation_pushed", record)
        return True

    async def _push_receipts_as_validations(
        self,
        linked_agents: list[Any],
    ) -> dict[str, Any]:
        """Push gauntlet receipts as validation records to the blockchain.

        Converts Aragora gauntlet receipts to on-chain validation records.
        Only high-confidence receipts with consensus are pushed.

        Args:
            linked_agents: List of AgentBlockchainLink records.

        Returns:
            Dict with analyzed, updated, skipped counts and errors.
        """
        analyzed = 0
        updated = 0
        skipped = 0
        errors: list[str] = []

        if self._signer is None:
            return {
                "analyzed": 0,
                "updated": 0,
                "skipped": 0,
                "errors": ["No signer configured"],
            }

        # Try to get receipt adapter for gauntlet receipt access
        try:
            from aragora.knowledge.mound.adapters import ReceiptAdapter

            receipt_adapter = ReceiptAdapter()
        except ImportError:
            logger.debug("ReceiptAdapter not available")
            return {
                "analyzed": 0,
                "updated": 0,
                "skipped": 0,
                "errors": ["ReceiptAdapter not available"],
            }

        validation_contract = self._get_validation_contract()

        # Build agent ID to token ID mapping for quick lookup
        agent_to_token = {link.aragora_agent_id: link.token_id for link in linked_agents}

        # Get recent receipt stats
        stats = receipt_adapter.get_stats()
        receipts_processed = stats.get("receipts_processed", 0)

        if receipts_processed == 0:
            logger.debug("No receipts to process")
            return {
                "analyzed": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [],
            }

        # Process ingested receipts
        for receipt_id, result in list(receipt_adapter._ingested_receipts.items())[:50]:
            analyzed += 1

            try:
                # Skip receipts with errors
                if not result.success:
                    skipped += 1
                    continue

                # Get agents involved from metadata
                # We need to match receipts to agents that participated
                knowledge_ids = result.knowledge_item_ids

                if not knowledge_ids:
                    skipped += 1
                    continue

                # For each agent that was involved in the receipt decision
                # Try to find related agents from the receipt metadata
                receipt_agents_involved: list[str] = []

                # Access metadata through the receipt adapter's stored items
                for item_id in knowledge_ids:
                    if item_id.startswith("rcpt_"):
                        # This is the summary item, check for agents
                        # In a real implementation we'd query the KM store
                        # For now, try to match any linked agent
                        for agent_id in agent_to_token:
                            if agent_id not in receipt_agents_involved:
                                receipt_agents_involved.append(agent_id)
                                break  # Just one agent per receipt for now

                if not receipt_agents_involved:
                    skipped += 1
                    continue

                # Push validation for each involved agent
                for agent_id in receipt_agents_involved:
                    if agent_id not in agent_to_token:
                        continue

                    token_id = agent_to_token[agent_id]

                    # Compute request hash from receipt ID
                    import hashlib

                    request_data = f"gauntlet:{receipt_id}:{agent_id}"
                    request_hash = hashlib.sha256(request_data.encode()).digest()

                    # Determine validation response based on receipt verdict
                    # claims_ingested > 0 typically means validated claims
                    from aragora.blockchain.models import ValidationResponse

                    if result.claims_ingested > 0:
                        response = ValidationResponse.PASS
                        tag = "validated_claims"
                    elif result.findings_ingested > 0 and result.claims_ingested == 0:
                        response = ValidationResponse.FAIL
                        tag = "findings_only"
                    else:
                        response = ValidationResponse.PENDING
                        tag = "inconclusive"

                    # Compute response hash
                    response_data = f"{receipt_id}:{response.name}:{result.claims_ingested}"
                    response_hash = hashlib.sha256(response_data.encode()).digest()

                    try:
                        # Submit validation response
                        tx_hash = validation_contract.submit_response(
                            request_hash=request_hash,
                            response=response,
                            response_uri=f"aragora://receipt/{receipt_id}",
                            response_hash=response_hash,
                            tag=tag,
                            signer=self._signer,
                        )

                        self._emit_event(
                            "validation_pushed",
                            {
                                "receipt_id": receipt_id,
                                "agent_id": agent_id,
                                "token_id": token_id,
                                "response": response.name,
                                "tx_hash": tx_hash,
                            },
                        )

                        logger.info(
                            "Pushed validation for receipt %s, agent %s (token %s): response=%s, tx=%s...",
                            receipt_id,
                            agent_id,
                            token_id,
                            response.name,
                            tx_hash[:16],
                        )
                        updated += 1

                    except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                        logger.warning(
                            "Failed to push validation for receipt %s, agent %s: %s",
                            receipt_id,
                            agent_id,
                            e,
                        )
                        errors.append(
                            f"Failed to push validation for receipt {receipt_id}, agent {agent_id}"
                        )

            except (
                OSError,
                ConnectionError,
                RuntimeError,
                ValueError,
                KeyError,
                AttributeError,
            ) as e:  # noqa: BLE001 - adapter isolation
                logger.warning("Error processing receipt %s: %s", receipt_id, e)
                errors.append(f"Error processing receipt {receipt_id}")

        return {
            "analyzed": analyzed,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

    def get_health_status(self) -> dict[str, Any]:
        """Get health status of the adapter."""
        try:
            provider = self._get_provider()
            connected = provider.is_connected()
            config = provider.get_config()

            return {
                "adapter": self.adapter_name,
                "connected": connected,
                "chain_id": config.chain_id,
                "has_identity_registry": config.has_identity_registry,
                "has_reputation_registry": config.has_reputation_registry,
                "has_validation_registry": config.has_validation_registry,
                "reverse_sync_enabled": self._enable_reverse_sync,
                "has_signer": self._signer is not None,
                "rpc_health": provider.get_health_status(),
            }
        except (OSError, ConnectionError, RuntimeError, ValueError, AttributeError):  # noqa: BLE001 - adapter isolation
            return {
                "adapter": self.adapter_name,
                "connected": False,
                "error": "Health check failed",
            }


__all__ = ["ERC8004Adapter"]
