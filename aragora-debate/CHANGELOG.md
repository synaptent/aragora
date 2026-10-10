# Changelog

All notable changes to `aragora-debate` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Built-in Claude, OpenAI, Mistral, and Gemini agents now give their SDK clients a transport timeout equal to the per-attempt timeout, `ARAGORA_DEBATE_TIMEOUT_S` (30-second default per attempt): `timeout=` for Anthropic and OpenAI, `timeout_ms=` for Mistral, and `http_options={"timeout": ...}` in milliseconds for Gemini. SDK transport timeouts now match the wrapper timeout; the SDK defaults were several minutes, so a timed-out call could keep its worker thread busy long after the attempt was abandoned.
- `CircuitOpenError` is now raised `from` the provider failure that opened the circuit, so `__cause__` carries the original error.

### Fixed

- `redact()` also masks `key: value` forms (`Authorization: Bearer …`, JSON such as `{"api_key": "…"}`, and Python reprs), and masks the whole `Authorization` or `Proxy-Authorization` value for any scheme rather than only Bearer/Basic, without parsing its parameters: everything to the end of the line, including continuation lines that start with a space or tab, or to the closing quote when the header line is inside a JSON or Python-repr string, so no parameter such as a Digest `response` is left visible.
- The log formatters no longer raise, which made `logging` print the raw, unredacted record: mapping keys JSON cannot encode become redacted strings, self-referencing containers are logged as `<cycle>`, arguments that do not fit the format string or cannot be converted are replaced by a note, and any other formatting failure (extras too deeply nested to encode, an unprintable extra or message, malformed exception, stack or timestamp data) writes one JSON line with the redacted message template and a `format_error` field. The handler from `configure_logging()` reports a failed stream write by error type, without the record's arguments.

## [0.2.3] - 2026-02-24

### Changed

- Model references updated to latest Claude 4.5/4.6 and GPT-5.2 lineup.
- Test suite expanded to 236 tests with full coverage of all public APIs.

### Fixed

- Improved documentation examples with current model IDs.

## [0.2.0] - 2026-02-12

### Added

- **Mistral agent** (`MistralAgent`) -- debate with Mistral Large and Codestral models via `pip install aragora-debate[mistral]`.
- **Gemini agent** (`GeminiAgent`) -- debate with Google Gemini models via `pip install aragora-debate[gemini]`.
- **Trickster hollow-consensus detection** (`EvidencePoweredTrickster`) -- automatically detects when agents agree without substantive evidence and injects challenge prompts to force deeper reasoning.
- **Convergence tracking** (`ConvergenceDetector`) -- measures semantic similarity across proposals each round; emits `convergence_detected` events when agents converge.
- **Evidence quality analysis** (`EvidenceQualityAnalyzer`) -- scores proposals on citation density, specificity, recency, and source diversity (0.0--1.0 scale).
- **Cross-proposal analysis** (`CrossProposalAnalyzer`) -- identifies shared evidence, contradictions, evidence gaps, and the weakest agent across all proposals.
- **Event system** (`EventEmitter`, `EventType`, `DebateEvent`) -- subscribe to real-time debate events including `debate_start`, `round_start`, `proposal`, `critique`, `vote`, `consensus_check`, `convergence_detected`, `trickster_intervention`, `round_end`, and `debate_end`.
- **Styled mock agents** (`StyledMockAgent`) -- deterministic agents with personality styles (`supportive`, `critical`, `balanced`, `contrarian`) for testing and demos.
- **CLI flags** -- `python -m aragora_debate --trickster --convergence` enables detection features in the built-in demo.
- **`TricksterConfig`** dataclass for fine-grained control over intervention sensitivity, evidence thresholds, and challenge generation.
- **`ConvergenceResult`** dataclass with per-pair similarity scores and convergence history.

### Changed

- `DebateConfig` now accepts `enable_trickster`, `enable_convergence`, `convergence_threshold`, and `trickster_sensitivity` parameters.
- `DebateResult` now includes `trickster_interventions` (int), `convergence_detected` (bool), and `final_similarity` (float) fields.
- `Arena` emits events for all debate lifecycle stages when an `on_event` callback is provided.
- Development status classifier updated from Alpha to Beta.

## [0.1.0] - 2026-02-11

### Added

- **Arena** -- core debate orchestrator running propose/critique/vote rounds with configurable consensus methods (majority, supermajority, unanimous, weighted, judge).
- **Agent** abstract base class with `generate()`, `critique()`, and `vote()` methods.
- **MockAgent** -- deterministic agent for testing (zero dependencies, always available).
- **ReceiptBuilder** -- generates `DecisionReceipt` artifacts with HMAC-SHA256 signing, Markdown/JSON/HTML export, and tamper detection.
- **ClaudeAgent** (`pip install aragora-debate[anthropic]`) -- Anthropic Claude integration.
- **OpenAIAgent** (`pip install aragora-debate[openai]`) -- OpenAI GPT integration.
- **High-level `Debate` API** -- 5-line interface wrapping the full Arena orchestrator.
- **`create_agent()` factory** -- create agents by provider name with sensible defaults.
- **`DebateConfig`** with rounds, consensus method, early stopping, min rounds, timeout, and require-reasoning options.
- **`DecisionReceipt`** with verdict, confidence, dissent records, and cryptographic signature.
- **`DissentRecord`** tracking agent disagreements with reasons and alternative views.
- **CLI demo** -- `python -m aragora_debate` runs a full debate with zero API keys.
- **PEP 561** `py.typed` marker for type checker support.
- **235 tests** covering Arena, Receipt, types, agents, events, convergence, trickster, evidence, cross-analysis, and mock styles.

[0.2.3]: https://github.com/synaptent/aragora/compare/aragora-debate-v0.2.0...aragora-debate-v0.2.3
[0.2.0]: https://github.com/synaptent/aragora/compare/aragora-debate-v0.1.0...aragora-debate-v0.2.0
[0.1.0]: https://github.com/synaptent/aragora/releases/tag/aragora-debate-v0.1.0
