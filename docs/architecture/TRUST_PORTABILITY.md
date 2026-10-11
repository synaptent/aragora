# ERC-8004 Trust Portability

> How agent reputation transfers between organizations using on-chain identity and calibration attestation.

## Overview

Aragora uses [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004) to give AI agents portable, verifiable identities. An agent's debate performance, calibration accuracy, and decision quality are recorded on-chain as reputation feedback — making trust transferable across organizations without sharing proprietary data.

```
Org A                          Blockchain                        Org B
┌─────────────┐    register    ┌──────────────┐    query        ┌─────────────┐
│ Agent X      │───────────────│ Token #42    │────────────────│ Agent X      │
│ ELO: 1720    │  push ELO     │ owner: 0xA   │  get reputation│ (trusted)    │
│ Brier: 0.18  │───────────────│ rep: 820     │────────────────│ rep: 820     │
│ 47 debates   │  push calib   │ calib: 820   │  get validations│ calib: 820  │
└─────────────┘               └──────────────┘                └─────────────┘
```

## Agent Identity

Each agent is represented as an ERC-721 NFT on the Identity Registry.

**Registration** (`aragora/blockchain/contracts/identity.py`):

```python
# Request registration with metadata
action = client.blockchain.register_agent(
    agent_uri="https://org-a.com/agents/analyst-1.json",
    metadata={"aragora_agent_id": "analyst-1", "capabilities": "security,compliance"},
    approval_id="cap-approval-123",
)
```

The public API now queues a durable chain action and returns an `action_id`. An admin-approved signer lane submits the transaction asynchronously, and the portable `token_id` only exists after the queued action is mined and confirmed.

**Wallet binding**: Agents can bind to wallet addresses via EIP-191 signed messages using `setAgentWallet()`. Supports private key, encrypted keystore, or external (hardware wallet) signers.

**SDK surface** (`sdk/python/aragora_sdk/namespaces/blockchain.py`):

```python
# Queue registration
result = client.blockchain.register_agent(
    agent_uri="https://org-a.com/agents/analyst-1.json",
    metadata={"aragora_agent_id": "analyst-1"},
)

# List all agents (paginated)
agents = client.blockchain.list_agents(skip=0, limit=50)
```

The registration request returns queue metadata such as `action_id`, `status="queued"`, and `requires_approval=True`. Consequential chain writes are not performed inline in the request-serving path.

## Reputation Scoring

Reputation is stored as feedback records on the Reputation Registry, tagged by domain.

### ELO → Reputation

Agents that perform well in adversarial debates earn ELO ratings. These are normalized and pushed on-chain:

| ELO Range | Reputation (0–1000) | Meaning |
|-----------|-------------------|---------|
| 1000 | 0 | Baseline (no signal) |
| 1500 | 500 | Competent |
| 1750 | 750 | Strong |
| 2000+ | 1000 | Expert |

**Formula**: `reputation = max(0, min(1000, elo - 1000))`

**Thresholds**: Minimum 3 completed debates and ELO >= 1500 before reputation is pushed.

**Domain tags**: Primary tag is `aragora_elo`, secondary tag is the agent's best domain (e.g., `security`, `database_migration`), selected by highest domain-specific ELO.

### Calibration → Reputation

Agents that make well-calibrated predictions (confidence matches actual outcomes) earn calibration reputation:

| Brier Score | Reputation | Meaning |
|-------------|-----------|---------|
| 0.00 | 1000 | Perfect calibration |
| 0.20 | 800 | Well-calibrated |
| 0.50 | 500 | Moderate |
| 1.00 | 0 | No calibration signal |

**Formula**: `reputation = (1 - brier_score) * 1000`

**Thresholds**: Minimum 5 total predictions globally, 3 per domain.

**Per-domain scores**: Each domain (e.g., `security`, `compliance`) gets its own calibration reputation feedback record with `tag1="calibration"` and `tag2=<domain>`.

### Feedback Integrity

Every reputation push includes a SHA-256 content hash for on-chain verification:

- ELO: `SHA-256(agent_id:elo:debates_count)`
- Calibration: `SHA-256(agent_id:calibration:brier_score:total_predictions)`

This allows anyone to verify that the on-chain reputation value matches the off-chain source data.

## Cross-Organization Trust Transfer

### Identity Bridge

The `AgentBlockchainLink` (`aragora/control_plane/blockchain_identity.py`) connects internal Aragora agent IDs to on-chain token IDs:

```python
from aragora.control_plane.blockchain_identity import link_agent, get_agent_by_token

# Org A: link internal agent to on-chain identity
link = link_agent("analyst-1", token_id=42, chain_id=1, verify=True)
# → AgentBlockchainLink(aragora_agent_id="analyst-1", token_id=42, owner="0xOrgA")

# Org B: look up agent by token
agent = get_agent_by_token(token_id=42, chain_id=1)
# → "analyst-1" (portable identity resolved)

# Query all agents owned by an address
agents = get_agents_by_owner("0xOrgA")
# → Returns all agents linked to that wallet
```

### Trust Transfer Flow

1. **Org A registers** Agent X on-chain → receives `token_id=42`
2. **Org A pushes reputation** — ELO, calibration, gauntlet results → on-chain feedback
3. **Org B queries** `get_reputation(token_id=42, tag1="calibration")` → sees score 820
4. **Org B decides** to trust Agent X for security tasks based on on-chain evidence
5. **No proprietary data shared** — only aggregated scores and content hashes

### Auto-Discovery

`sync_from_blockchain()` scans the Identity Registry for tokens with `aragora_agent_id` metadata and automatically creates internal links:

```python
# Discover agents registered on-chain
await erc8004_adapter.sync_from_blockchain(limit=100)
```

## CbKVC Pre-Commitment

**Credential-Based Key-Value Commitment** prevents agents from cherry-picking favorable topics after seeing debate results.

### How It Works

1. **Before debate**: Agent commits to a topic on-chain
   ```python
   await register_prediction_commitment(
       agent_id="analyst-1",
       token_id=42,
       topic="security-architecture",
       debate_id="debate-789",
   )
   ```
   Records: `SHA-256(agent_id:commitment:topic:debate_id)` as feedback with `tag1="commitment"`, `value=0`

2. **After debate**: Calibration score is pushed
   Records: actual calibration with `tag1="calibration"`, `tag2=topic_hash`

3. **Verification**: Compare commitment hash from step 1 with calibration topic from step 2
   - Match → agent honored pre-commitment
   - Mismatch → agent cherry-picked domains (detectable on-chain)

## Attestation Flow

Decision receipts are anchored on-chain for tamper-evident audit trails.

### Receipt → On-Chain Anchor

```
Debate → Receipt (HMAC-SHA256 signed) → Content Hash → ERC-8004 Validation Registry
```

1. **Debate completes** → generates `DecisionReceipt` with verdict, confidence, dissent
2. **Receipt signed** → HMAC-SHA256 with secret key, content hash = SHA-256(sorted JSON)
3. **Anchored on-chain** → `ValidationRegistry.submit_response(request_hash, response, response_hash)`
4. **Verifiable forever** → anyone can fetch tx, extract content_hash, re-verify receipt

### Gauntlet Receipt Mapping

Gauntlet (adversarial stress-test) results are mapped to validation codes:

| Gauntlet Result | Validation Code | Condition |
|----------------|----------------|-----------|
| PASS | 1 | claims_ingested > 0 |
| FAIL | 2 | findings only, no valid claims |
| PENDING | 0 | Inconclusive |

## Knowledge Mound Sync

### Forward (Blockchain → KM)

Fetches identities, reputation summaries, and validation records from ERC-8004 contracts and stores them as Knowledge Mound nodes:

```python
await erc8004_adapter.sync_from_km()
# Events: identity_synced, reputation_synced, validation_synced
```

### Reverse (KM → Blockchain)

Pushes internal metrics to on-chain registries (requires signer configuration, disabled by default):

```python
await erc8004_adapter.sync_from_km(
    push_elo_ratings=True,
    push_calibration=True,
    push_receipts=True,
)
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ERC8004_RPC_URL` | JSON-RPC endpoint | — |
| `ERC8004_CHAIN_ID` | Chain ID | 1 (Ethereum mainnet) |
| `ERC8004_IDENTITY_REGISTRY` | Identity contract address | — |
| `ERC8004_REPUTATION_REGISTRY` | Reputation contract address | — |
| `ERC8004_VALIDATION_REGISTRY` | Validation contract address | — |
| `ERC8004_WALLET_KEY` | Private key (testing only) | — |
| `ERC8004_KEYSTORE_PATH` | Encrypted keystore file | — |
| `ERC8004_BLOCK_CONFIRMATIONS` | Blocks to wait for finality | 12 |

**Supported chains**: Ethereum Mainnet (1), Sepolia (11155111), Polygon (137), Arbitrum (42161), Base (8453), Optimism (10).

## SDK Reference

```python
# Python SDK
client.blockchain.list_agents(skip=0, limit=50)
client.blockchain.register_agent(agent_uri, metadata)
client.blockchain.get_agent(token_id)
client.blockchain.get_reputation(token_id, tag1="calibration", tag2="security")
client.blockchain.get_validations(token_id, tag="gauntlet")
client.blockchain.sync(sync_identities=True, sync_reputation=True)
client.blockchain.get_config()
client.blockchain.get_health()
```

```typescript
// TypeScript SDK
client.blockchain.listAgents({ skip: 0, limit: 50 })
client.blockchain.registerAgent({ agentUri, metadata })
client.blockchain.getAgent(tokenId)
client.blockchain.getReputation(tokenId, { tag1: "calibration" })
client.blockchain.getValidations(tokenId, { tag: "gauntlet" })
```

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/blockchain/agents` | List agents (paginated) |
| POST | `/api/v1/blockchain/agents` | Register agent |
| GET | `/api/v1/blockchain/agents/{token_id}` | Get identity |
| GET | `/api/v1/blockchain/agents/{token_id}/reputation` | Get reputation (tag filter) |
| GET | `/api/v1/blockchain/agents/{token_id}/validations` | Get validations (tag filter) |
| POST | `/api/v1/blockchain/sync` | Trigger KM sync |
| GET | `/api/v1/blockchain/config` | Chain configuration |
| GET | `/api/v1/blockchain/health` | Health check |
