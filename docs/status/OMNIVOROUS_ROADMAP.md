# Aragora: Control Plane for Multi-Agent Vetted Decisionmaking

## Mission Statement

Aragora is the **control plane for multi-agent vetted decisionmaking across organizational knowledge and channels** - a system designed to:

1. **Ingest broadly**: Accept inputs from any source - 25+ document formats, databases, APIs, chat platforms, voice, real-time data feeds
2. **Vet deeply**: Orchestrate 43 agent types in structured debate to reach well-reasoned conclusions with full audit trails
3. **Deliver anywhere**: Route outputs through multiple channels - Slack, Teams, Discord, Telegram, WhatsApp, voice, webhooks

Unlike chatbots, Aragora builds institutional memory that compounds over time. The control plane architecture orchestrates knowledge and communication channels across your organization.

---

## Architecture Overview

```
                    ┌─────────────────────────────────────────────┐
                    │              INPUT CHANNELS                  │
                    │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────────┐│
                    │  │ STT │ │ Web │ │ API │ │Chat │ │Documents││
                    │  │Voice│ │  UI │ │REST │ │Bots │ │PDF/Word ││
                    │  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘ └────┬────┘│
                    └─────┼───────┼───────┼───────┼─────────┼─────┘
                          │       │       │       │         │
                    ┌─────▼───────▼───────▼───────▼─────────▼─────┐
                    │           ARAGORA DEBATE ENGINE              │
                    │  ┌──────────────────────────────────────┐   │
                    │  │       Multi-Agent Orchestrator        │   │
                    │  │  ┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐ │   │
                    │  │  │Claude││ GPT ││Gemini││ Grok││Qwen │ │   │
                    │  │  └─────┘└─────┘└─────┘└─────┘└─────┘ │   │
                    │  └──────────────────────────────────────┘   │
                    │  ┌──────────────────────────────────────┐   │
                    │  │         Knowledge Systems             │   │
                    │  │  Memory │ Evidence │ Learning │ Prefs │   │
                    │  └──────────────────────────────────────┘   │
                    └─────┬───────┬───────┬───────┬─────────┬─────┘
                          │       │       │       │         │
                    ┌─────▼───────▼───────▼───────▼─────────▼─────┐
                    │            OUTPUT CHANNELS                   │
                    │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────────┐│
                    │  │ TTS │ │ Web │ │ API │ │Chat │ │Webhooks ││
                    │  │Voice│ │  UI │ │REST │ │Bots │ │Notifs   ││
                    │  └─────┘ └─────┘ └─────┘ └─────┘ └─────────┘│
                    └─────────────────────────────────────────────┘
```

---

## Current Capabilities (v2.5.x)

### Input Channels
| Channel | Status | Notes |
|---------|--------|-------|
| REST API | Stable | 3,000+ API operations |
| WebSocket | Stable | Real-time streaming |
| Slack | Stable | Commands + webhooks |
| Discord | Stable | Bot integration |
| Teams | Stable | Bot Framework |
| Google Chat | Stable | Webhooks |
| **Telegram** | **NEW** | Commands + webhooks |
| **WhatsApp** | **NEW** | Meta/Twilio APIs |
| Voice (STT) | Stable | Whisper transcription |
| Documents | Partial | PDF, code, markdown |

### Output Channels
| Channel | Status | Notes |
|---------|--------|-------|
| REST API | Stable | JSON responses |
| WebSocket | Stable | Stream events |
| Chat Platforms | Stable | All major platforms |
| **Voice (TTS)** | **NEW** | ElevenLabs, Edge-TTS, Polly |
| Webhooks | Stable | Event notifications |
| Email | Stable | SMTP integration |

### Debate Engine
| Feature | Status |
|---------|--------|
| Multi-model debates | Stable |
| Consensus detection | Stable |
| Evidence collection | Stable |
| Memory persistence | Stable |
| **Workflow checkpoints** | **NEW** |
| ELO rankings | Stable |
| Gauntlet mode | Stable |

---

## Roadmap Phases

### Phase 1: Foundation (Complete)
Core debate engine with multi-agent orchestration, consensus detection, and basic API.

### Phase 2: Enterprise (Complete)
Authentication (OIDC/SAML), multi-tenancy, RBAC v2, audit logging, compliance controls.

### Phase 3: Knowledge Systems (Complete)
Knowledge Mound, cross-debate memory, meta-learning, evidence bridges.

### Phase 4: Omnivorous Infrastructure (In Progress)

#### 4.1 Bidirectional Chat (Complete)
- [x] Telegram webhook handler
- [x] WhatsApp webhook handler
- [x] Platform-agnostic ChatWebhookRouter
- [x] Unified command handling (/aragora debate, /aragora status)

#### 4.2 Voice Integration (Complete)
- [x] STT via VoiceBridge (Whisper)
- [x] TTS via TTSBridge (ElevenLabs, Edge-TTS, Polly)
- [x] Voice stream WebSocket handler
- [x] send_voice_message() in chat connectors

#### 4.3 Workflow Persistence (Complete)
- [x] CheckpointStore protocol
- [x] FileCheckpointStore implementation
- [x] KnowledgeMoundCheckpointStore implementation
- [x] WorkflowEngine checkpoint wiring

#### 4.4 Document Ingestion (Complete)
- [x] PDF/Word/Excel/PowerPoint parsing (DocumentParser)
- [x] DocumentConnector for evidence collection
- [x] EvidenceCollector integration with auto-detection
- [x] Format-specific reliability scoring
- [x] Table extraction with structured evidence

### Phase 5: Autonomous Operations (Complete)

#### 5.1 Nomic Loop Enhancement
- [x] Self-improvement debate automation (SelfImprovementManager)
- [x] Code generation verification (CodeVerifier)
- [x] Rollback safety mechanisms (RollbackManager)
- [x] Human-in-the-loop approval flows (ApprovalFlow)

#### 5.2 Continuous Learning
- [x] Real-time ELO updates (EloUpdater)
- [x] Agent calibration refinement (ContinuousLearner)
- [x] Cross-debate pattern extraction (PatternExtractor)
- [x] Knowledge decay management (KnowledgeDecayManager)

#### 5.3 Proactive Intelligence
- [x] Scheduled debate triggers (ScheduledTrigger)
- [x] Alert-based analysis (AlertAnalyzer)
- [x] Trend monitoring (TrendMonitor)
- [x] Anomaly detection (AnomalyDetector)

### Phase 6: Federation (Future)

#### 6.1 Distributed Debates
- [ ] Cross-instance coordination
- [ ] Knowledge federation
- [ ] Shared agent pools
- [ ] Consensus across clusters

#### 6.2 External Integrations
- [ ] Zapier/Make connectors
- [ ] n8n workflow nodes
- [ ] LangChain integration
- [ ] Custom MCP servers

---

## Integration Guide

### Starting a Debate from Any Channel

```python
# Via REST API
POST /api/debate/start
{"task": "Should we adopt microservices?", "agents": ["claude", "gpt"]}

# Via Slack
/aragora debate Should we adopt microservices?

# Via Telegram
/aragora debate Should we adopt microservices?

# Via WebSocket
{"type": "start_debate", "task": "...", "agents": [...]}

# Via Voice (STT -> Debate -> TTS)
# User speaks -> Whisper transcribes -> Debate runs -> TTS responds
```

### Receiving Results

```python
# REST API response
{"debate_id": "...", "consensus_reached": true, "final_answer": "..."}

# WebSocket events
{"type": "consensus", "confidence": 0.85, "answer": "..."}

# Chat platform notification
"Consensus reached with 85% confidence: ..."

# Voice response (TTS)
await tts_bridge.synthesize_debate_summary(result)
```

---

## Environment Configuration

### Chat Platforms
```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_WEBHOOK_URL=https://your-domain.com/api/chat/telegram/webhook

# WhatsApp (Meta)
WHATSAPP_ACCESS_TOKEN=your_access_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_VERIFY_TOKEN=your_verify_token

# WhatsApp (Twilio)
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_NUMBER=+14155238886
```

### Voice/TTS
```bash
# STT (Speech-to-Text)
OPENAI_API_KEY=sk-...  # For Whisper

# TTS (Text-to-Speech) - priority order
ARAGORA_TTS_ORDER=elevenlabs,polly,edge-tts,pyttsx3
ELEVENLABS_API_KEY=your_key  # Best quality
AWS_REGION=us-east-1  # For Polly
```

### Workflow Persistence
```bash
# File-based (default)
ARAGORA_CHECKPOINT_DIR=.checkpoints

# KnowledgeMound-based
ARAGORA_USE_MOUND_CHECKPOINTS=true
```

---

## Metrics & Monitoring

New Prometheus metrics for omnivorous features:

```
# Chat platform metrics
aragora_chat_messages_received_total{platform="telegram|whatsapp|slack|..."}
aragora_chat_messages_sent_total{platform="..."}
aragora_chat_webhook_latency_seconds{platform="..."}

# Voice metrics
aragora_voice_transcriptions_total
aragora_voice_transcription_duration_seconds
aragora_tts_syntheses_total
aragora_tts_synthesis_duration_seconds

# Workflow metrics
aragora_workflow_checkpoints_created_total
aragora_workflow_checkpoints_restored_total
aragora_workflow_checkpoint_size_bytes
```

---

## Testing

```bash
# Run all omnivorous-related tests
pytest tests/test_telegram_integration.py tests/test_whatsapp_integration.py -v
pytest tests/workflow/ -v -k checkpoint
pytest tests/connectors/chat/ -v

# Verify TTS bridge
python -c "from aragora.connectors.chat import get_tts_bridge; print('TTS OK')"

# Verify chat handlers
python -c "from aragora.server.handlers.chat.router import ChatHandler; print('Chat OK')"
```

---

## Contributing

When adding new omnivorous capabilities:

1. **Input channels**: Add to `aragora/connectors/` or `aragora/integrations/`
2. **Output channels**: Implement in connectors + add server handlers
3. **Server handlers**: Add to `aragora/server/handlers/`
4. **Tests**: Add comprehensive tests with mocks for external services
5. **Documentation**: Update this roadmap and relevant docs

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 2.0.4 | 2026-01-20 | Telegram/WhatsApp handlers, TTS bridge, checkpoint persistence |
| 2.0.3 | 2026-01-20 | Cross-functional integration, knowledge bridges |
| 2.0.2 | 2026-01-19 | UI enhancements, connectors, knowledge mound ops |
| 2.0.1 | 2026-01-18 | OAuth, workflows, workspace management |
| 2.0.0 | 2026-01-17 | Enterprise release, graph/matrix APIs, billing |

---

*"Aragora: Where diverse AI minds collaborate to reach better decisions."*
