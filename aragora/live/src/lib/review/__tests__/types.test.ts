/**
 * Tests for aragora/live/src/lib/review/types.ts.
 *
 * The critical property is CANONICAL-STRING DISCIPLINE: every enum string
 * in this module must match exactly the ``to_dict()`` output of the Python
 * dataclasses in ``aragora/review/{protocol,receipt,policy}.py``.  Drift
 * breaks JSON interop silently.  Each test below hard-codes the Python
 * string value, so a refactor that touches one side will fail loudly if
 * the other is not updated.
 *
 * Python counterpart values are drawn from the canonical test suites in
 * ``tests/review/test_protocol.py``, ``tests/review/test_receipt.py``,
 * and ``tests/review/test_policy.py`` — which are themselves the source
 * of truth.
 */

import {
  BRIEF_RECEIPT_ADVISORY_NOTE,
  BudgetScope,
  DissentPosition,
  EvidenceKind,
  ProviderSlotStatus,
  QueueLane,
  Recommendation,
  REVIEW_BRIEF_ADVISORY_NOTE,
  REVIEW_PACKET_ADVISORY_NOTE,
  ReviewDepth,
  ReviewPolicyDecision,
  ReviewRole,
  RiskClass,
  SettlementAction,
  SynthesisPolicy,
  ValidationKind,
  ValidationResult,
  type BriefReceipt,
  type CostMeter,
  type DissentingView,
  type EvidenceRef,
  type PRReviewBinding,
  type PRReviewFinding,
  type PRReviewProtocolPacket,
  type ProtocolCostEstimate,
  type ProtocolValidationSummary,
  type ProviderSlotAvailabilitySummary,
  type ProviderSlotResolution,
  type QueueItem,
  type ReviewBrief,
  type ReviewBudget,
  type ReviewPacket,
  type ReviewPolicy,
  type RoleFinding,
  type SettlementActionRequest,
  type SettlementActionResponse,
  type SettlementLinkage,
  type SettlementReceipt,
  type ValidationRef,
} from '../types';

// ---------------------------------------------------------------------------
// Enum canonical-string discipline (each value must match Python exactly)
// ---------------------------------------------------------------------------

describe('canonical string discipline — enums match aragora/review/*.py', () => {
  test('ReviewRole values', () => {
    expect(ReviewRole.LOGIC).toBe('logic_reviewer');
    expect(ReviewRole.SECURITY).toBe('security_reviewer');
    expect(ReviewRole.MAINTAINABILITY).toBe('maintainability_reviewer');
    expect(ReviewRole.SKEPTIC).toBe('skeptic');
    expect(ReviewRole.SYNTHESIZER).toBe('synthesizer');
  });

  test('Recommendation values', () => {
    expect(Recommendation.APPROVE_CANDIDATE).toBe('approve_candidate');
    expect(Recommendation.NEEDS_HUMAN_ATTENTION).toBe('needs_human_attention');
    expect(Recommendation.REPAIR_FIRST).toBe('repair_first');
  });

  test('DissentPosition values', () => {
    expect(DissentPosition.APPROVE).toBe('approve');
    expect(DissentPosition.REQUEST_CHANGES).toBe('request_changes');
    expect(DissentPosition.DEFER).toBe('defer');
  });

  test('SynthesisPolicy values', () => {
    expect(SynthesisPolicy.MAJORITY).toBe('majority');
    expect(SynthesisPolicy.WEIGHTED).toBe('weighted');
    expect(SynthesisPolicy.SYNTHESIZER_AGENT).toBe('synthesizer');
    expect(SynthesisPolicy.UNANIMOUS_OR_ESCALATE).toBe('unanimous_or_escalate');
  });

  test('EvidenceKind values', () => {
    expect(EvidenceKind.FILE).toBe('file');
    expect(EvidenceKind.TEST).toBe('test');
    expect(EvidenceKind.COMMIT).toBe('commit');
    expect(EvidenceKind.ARTIFACT).toBe('artifact');
    expect(EvidenceKind.ISSUE).toBe('issue');
    expect(EvidenceKind.PR).toBe('pr');
    expect(EvidenceKind.EXTERNAL).toBe('external');
  });

  test('ValidationKind values', () => {
    expect(ValidationKind.CI_CHECK).toBe('ci_check');
    expect(ValidationKind.TEST_SUITE).toBe('test_suite');
    expect(ValidationKind.RECEIPT).toBe('receipt');
    expect(ValidationKind.BENCHMARK).toBe('benchmark');
    expect(ValidationKind.MANUAL_REVIEW).toBe('manual_review');
  });

  test('ValidationResult values', () => {
    expect(ValidationResult.SUCCESS).toBe('success');
    expect(ValidationResult.FAILURE).toBe('failure');
    expect(ValidationResult.SKIPPED).toBe('skipped');
    expect(ValidationResult.CANCELLED).toBe('cancelled');
    expect(ValidationResult.PENDING).toBe('pending');
  });

  test('SettlementAction values', () => {
    expect(SettlementAction.APPROVE).toBe('approve');
    expect(SettlementAction.REQUEST_CHANGES).toBe('request_changes');
    expect(SettlementAction.DEFER).toBe('defer');
  });

  test('ReviewDepth values', () => {
    expect(ReviewDepth.TRIVIAL).toBe('trivial');
    expect(ReviewDepth.STANDARD).toBe('standard');
    expect(ReviewDepth.DEEP).toBe('deep');
  });

  test('RiskClass values', () => {
    expect(RiskClass.LOW).toBe('low');
    expect(RiskClass.MEDIUM).toBe('medium');
    expect(RiskClass.HIGH).toBe('high');
    expect(RiskClass.CRITICAL).toBe('critical');
  });

  test('ReviewPolicyDecision values', () => {
    expect(ReviewPolicyDecision.ALLOW).toBe('allow');
    expect(ReviewPolicyDecision.DEGRADE).toBe('degrade');
    expect(ReviewPolicyDecision.DENY).toBe('deny');
    expect(ReviewPolicyDecision.ESCALATE).toBe('escalate');
  });

  test('BudgetScope values', () => {
    expect(BudgetScope.PER_PR).toBe('per_pr');
    expect(BudgetScope.PER_REPO_DAILY).toBe('per_repo_daily');
    expect(BudgetScope.PER_ORG_DAILY).toBe('per_org_daily');
  });

  test('QueueLane values', () => {
    // Must match canonical strings in aragora.cli.commands.review_queue
    // LANE_ORDER dict. A drift here silently breaks card grouping.
    expect(QueueLane.READY_NOW).toBe('ready_now');
    expect(QueueLane.NEEDS_ATTENTION).toBe('needs_attention');
    expect(QueueLane.REPAIRABLE).toBe('repairable');
    expect(QueueLane.PARKED).toBe('parked');
  });

  test('ProviderSlotStatus values match aragora/swarm/pr_review_protocol.py', () => {
    // Producer emits exactly these two strings in
    // ``PRReviewProtocol._resolve_slot``; drift would cause successor
    // UI code to branch on values the backend never sends.
    expect(ProviderSlotStatus.AVAILABLE).toBe('available');
    expect(ProviderSlotStatus.UNAVAILABLE).toBe('unavailable');
  });
});

// ---------------------------------------------------------------------------
// ADVISORY_NOTE contract
// ---------------------------------------------------------------------------

describe('advisory-note constants — distinct per backend payload', () => {
  test('REVIEW_BRIEF_ADVISORY_NOTE exact match (aragora/review/protocol.py)', () => {
    expect(REVIEW_BRIEF_ADVISORY_NOTE).toBe(
      'This brief is advisory only. It does not approve or block merge. Human settlement required.',
    );
  });

  test('REVIEW_PACKET_ADVISORY_NOTE exact match (aragora/cli/commands/review_queue.py)', () => {
    expect(REVIEW_PACKET_ADVISORY_NOTE).toBe(
      'This packet is advisory only. It does not approve or block merge. Human settlement required.',
    );
  });

  test('BRIEF_RECEIPT_ADVISORY_NOTE exact match (aragora/review/receipt.py)', () => {
    expect(BRIEF_RECEIPT_ADVISORY_NOTE).toBe(
      'This receipt records an advisory brief. It does not approve or block merge. ' +
        'Human settlement required.',
    );
  });

  test('all three strings are distinct (not reused)', () => {
    // The drift bug codex flagged on revision 1 was the result of one
    // shared string. Explicitly assert that all three are genuinely
    // different so a future refactor can't collapse them by accident.
    expect(REVIEW_BRIEF_ADVISORY_NOTE).not.toBe(REVIEW_PACKET_ADVISORY_NOTE);
    expect(REVIEW_BRIEF_ADVISORY_NOTE).not.toBe(BRIEF_RECEIPT_ADVISORY_NOTE);
    expect(REVIEW_PACKET_ADVISORY_NOTE).not.toBe(BRIEF_RECEIPT_ADVISORY_NOTE);
  });
});

// ---------------------------------------------------------------------------
// JSON-payload compatibility — a Python to_dict() output must parse cleanly
// as the corresponding TS interface.  Fixtures below mirror the exact
// field set produced by the Python dataclasses.
// ---------------------------------------------------------------------------

describe('python-json payloads parse as TS types', () => {
  test('RoleFinding shape', () => {
    const payload = {
      role: 'logic_reviewer',
      agent: 'claude-opus-4-8',
      model: 'claude-opus-4-8-1m',
      confidence: 0.9,
      finding_text: 'No regressions found.',
      latency_ms: 1200,
      cost_usd: 0.045,
    };
    const finding: RoleFinding = payload as RoleFinding;
    expect(finding.role).toBe(ReviewRole.LOGIC);
    expect(finding.confidence).toBe(0.9);
  });

  test('DissentingView shape (optional role)', () => {
    const payload = { agent: 'grok-3', position: 'request_changes', reason: 'Security concern.' };
    const view: DissentingView = payload as DissentingView;
    expect(view.position).toBe(DissentPosition.REQUEST_CHANGES);
    expect(view.role).toBeUndefined();
  });

  test('ReviewBrief shape', () => {
    const payload: ReviewBrief = {
      pr_number: 6304,
      repo: 'synaptent/aragora',
      head_sha: 'abc123',
      base_sha: 'def456',
      packet_sha: 'hash789',
      recommendation: 'approve_candidate' as Recommendation,
      top_line: 'Bounded docs PR.',
      role_findings: [],
      dissent: [],
      validation_summary: 'pre-commit clean',
      overall_confidence: 0.88,
      disagreement_score: 0.05,
      total_cost_usd: 0.18,
      total_wall_clock_ms: 4200,
      agent_roster: ['claude-opus-4-8', 'gpt-5-4'],
      generated_at: '2026-04-20T15:00:00+00:00',
      advisory_only: true,
      settlement_note: REVIEW_BRIEF_ADVISORY_NOTE,
    };
    expect(payload.advisory_only).toBe(true);
    expect(payload.recommendation).toBe(Recommendation.APPROVE_CANDIDATE);
  });

  test('EvidenceRef shape', () => {
    const payload: EvidenceRef = {
      kind: 'file' as EvidenceKind,
      path: 'aragora/review/protocol.py',
      sha: '',
      line_range: [42, 58],
      quote: 'def to_dict(self) -> dict[str, Any]:',
    };
    expect(payload.kind).toBe(EvidenceKind.FILE);
    expect(payload.line_range).toEqual([42, 58]);
  });

  test('ValidationRef shape', () => {
    const payload: ValidationRef = {
      kind: 'ci_check' as ValidationKind,
      name: 'Version Alignment',
      result: 'success' as ValidationResult,
      url: 'https://github.com/synaptent/aragora/actions/runs/12345',
    };
    expect(payload.kind).toBe(ValidationKind.CI_CHECK);
    expect(payload.result).toBe(ValidationResult.SUCCESS);
  });

  test('BriefReceipt advisory invariant', () => {
    const brief: ReviewBrief = {
      pr_number: 6304,
      repo: 'synaptent/aragora',
      head_sha: 'abc',
      base_sha: 'def',
      packet_sha: 'h',
      recommendation: 'approve_candidate' as Recommendation,
      top_line: '',
      role_findings: [],
      dissent: [],
      validation_summary: '',
      overall_confidence: 0.9,
      disagreement_score: 0,
      total_cost_usd: 0,
      total_wall_clock_ms: 0,
      agent_roster: [],
      generated_at: '',
      advisory_only: true,
      settlement_note: REVIEW_BRIEF_ADVISORY_NOTE,
    };
    const receipt: BriefReceipt = {
      brief,
      evidence_refs: [],
      validation_refs: [],
      receipt_id: 'receipt-sha',
      created_at: '2026-04-20T15:00:00+00:00',
      advisory_only: true,
      settlement_note: BRIEF_RECEIPT_ADVISORY_NOTE,
    };
    expect(receipt.advisory_only).toBe(true);
    expect(receipt.brief.advisory_only).toBe(true);
  });

  test('SettlementLinkage shape (human settlement is not advisory)', () => {
    const linkage: SettlementLinkage = {
      brief_receipt_id: 'brief-001',
      settlement_receipt_id: 'settlement-001',
      settlement_receipt_path: '.aragora/review-queue/settlements/pr-6304.json',
      head_sha: 'abc',
      packet_sha: 'h',
      pr_number: 6304,
      repo: 'synaptent/aragora',
      action: SettlementAction.APPROVE,
      settled_at: '2026-04-20T15:00:00+00:00',
      repair_receipt_ids: [],
      repair_receipt_paths: [],
      advisory_only: false,
    };
    expect(linkage.advisory_only).toBe(false);
    expect(linkage.action).toBe(SettlementAction.APPROVE);
  });

  test('ReviewBudget default-shape assumptions', () => {
    const budget: ReviewBudget = {
      per_pr_usd_cap: 25.0,
      per_repo_usd_daily_cap: 0.0,
      per_org_usd_daily_cap: 0.0,
      daily_caps_apply_at_or_above_depth: 'standard' as ReviewDepth,
      alert_threshold_pct: 80.0,
      hard_limit: true,
    };
    expect(budget.per_pr_usd_cap).toBe(25.0);
    expect(budget.daily_caps_apply_at_or_above_depth).toBe(ReviewDepth.STANDARD);
  });

  test('ReviewPolicy nests budget and tuple of rules', () => {
    const policy: ReviewPolicy = {
      budget: {
        per_pr_usd_cap: 25.0,
        per_repo_usd_daily_cap: 0.0,
        per_org_usd_daily_cap: 0.0,
        daily_caps_apply_at_or_above_depth: 'standard' as ReviewDepth,
        alert_threshold_pct: 80.0,
        hard_limit: true,
      },
      depth_rules: [
        {
          target_depth: 'deep' as ReviewDepth,
          min_additions_plus_deletions: 500,
          subsystem_prefixes: ['aragora/security/'],
          min_risk_class: 'high' as RiskClass,
        },
      ],
      default_depth: 'standard' as ReviewDepth,
    };
    expect(policy.depth_rules).toHaveLength(1);
    expect(policy.depth_rules[0].target_depth).toBe(ReviewDepth.DEEP);
  });

  test('QueueItem shape (the card payload)', () => {
    const card: QueueItem = {
      number: 6361,
      title: '[#6304] feat(live): TypeScript contracts for PR intelligence brief UI',
      url: 'https://github.com/synaptent/aragora/pull/6361',
      head_sha: '72a79cc74',
      author: 'an0mium',
      is_draft: true,
      mergeable: 'MERGEABLE',
      review_decision: 'REVIEW_REQUIRED',
      labels: ['autonomous'],
      additions: 656,
      deletions: 0,
      changed_files: 3,
      checks_summary: '24/24 green',
      lane: 'ready_now' as QueueLane,
      lane_reason: '24/24 green',
    };
    expect(card.lane).toBe(QueueLane.READY_NOW);
    expect(card.additions).toBe(656);
  });

  test('ReviewPacket shape (the expandable packet)', () => {
    const packet: ReviewPacket = {
      pr_number: 6361,
      title: 'Example',
      url: 'https://github.com/synaptent/aragora/pull/6361',
      head_sha: '72a79cc74',
      base_sha: '1857a9192',
      author: 'an0mium',
      is_draft: true,
      additions: 656,
      deletions: 0,
      changed_files: 3,
      queue_bucket: QueueLane.READY_NOW,
      touched_subsystems: ['aragora/live'],
      high_risk_paths_touched: [],
      validation: ['jest: 24 passed', 'tsc: exit 0'],
      checks_summary: '24/24 green',
      risk_flags: [],
      machine_recommendation: Recommendation.APPROVE_CANDIDATE,
      machine_recommendation_reason: 'Bounded TS foundation; no behavior change',
      packet_sha: 'packet-hash-xyz',
      generated_at: '2026-04-20T15:00:00+00:00',
      protocol: {},
      advisory_only: true,
      settlement_note: REVIEW_PACKET_ADVISORY_NOTE,
    };
    expect(packet.advisory_only).toBe(true);
    expect(packet.settlement_note).toBe(REVIEW_PACKET_ADVISORY_NOTE);
    // Verify the packet string is distinct from the brief string.
    expect(packet.settlement_note).not.toBe(REVIEW_BRIEF_ADVISORY_NOTE);
  });

  test('SettlementReceipt shape (SHA-bound record + typed discriminators)', () => {
    const receipt: SettlementReceipt = {
      session_id: 'session-001',
      reviewed_at: '2026-04-20T15:00:00+00:00',
      actor: 'armand',
      action: SettlementAction.APPROVE,
      reason: '',
      pr_number: 6361,
      pr_url: 'https://github.com/synaptent/aragora/pull/6361',
      head_sha: '72a79cc74',
      base_sha: '1857a9192',
      packet_sha: 'packet-hash-xyz',
      queue_bucket: QueueLane.READY_NOW,
      machine_recommendation: Recommendation.APPROVE_CANDIDATE,
      github_event: 'REVIEW_SUBMITTED',
      elapsed_seconds: 4.2,
      receipt_path: '.aragora/review-queue/receipts/pr-6361-session-001-approve.json',
    };
    // SHA-bound property: head_sha + packet_sha are both part of the
    // record so merge_arbiter can refuse stale settlements.
    expect(receipt.head_sha).toBe('72a79cc74');
    expect(receipt.packet_sha).toBe('packet-hash-xyz');
    expect(receipt.action).toBe(SettlementAction.APPROVE);
    // Discriminator fields typed narrowly (not raw string).
    expect(receipt.queue_bucket).toBe(QueueLane.READY_NOW);
    expect(receipt.machine_recommendation).toBe(Recommendation.APPROVE_CANDIDATE);
  });

  test('SettlementActionRequest APPROVE may omit reason', () => {
    // action=approve: reason is optional.
    const req: SettlementActionRequest = {
      pr_number: 6361,
      head_sha: '72a79cc74',
      packet_sha: 'packet-hash-xyz',
      action: SettlementAction.APPROVE,
    };
    expect(req.head_sha).toBe('72a79cc74');
    expect(req.action).toBe(SettlementAction.APPROVE);
    expect(req.reason).toBeUndefined();
  });

  test('SettlementActionRequest APPROVE may also include reason', () => {
    const req: SettlementActionRequest = {
      pr_number: 6361,
      head_sha: '72a79cc74',
      packet_sha: 'packet-hash-xyz',
      action: SettlementAction.APPROVE,
      reason: 'All checks green, docs synced.',
    };
    expect(req.reason).toBe('All checks green, docs synced.');
  });

  test('SettlementActionRequest REQUEST_CHANGES requires reason (discriminated union)', () => {
    const req: SettlementActionRequest = {
      pr_number: 6361,
      head_sha: '72a79cc74',
      packet_sha: 'packet-hash-xyz',
      action: SettlementAction.REQUEST_CHANGES,
      reason: 'Missing edge-case coverage in policy evaluator.',
    };
    expect(req.action).toBe(SettlementAction.REQUEST_CHANGES);
    expect(req.reason).toBe('Missing edge-case coverage in policy evaluator.');
  });

  test('SettlementActionRequest DEFER requires reason (discriminated union)', () => {
    const req: SettlementActionRequest = {
      pr_number: 6361,
      head_sha: '72a79cc74',
      packet_sha: 'packet-hash-xyz',
      action: SettlementAction.DEFER,
      reason: 'Waiting on upstream dep update.',
    };
    expect(req.action).toBe(SettlementAction.DEFER);
    expect(req.reason).toBe('Waiting on upstream dep update.');
  });

  test('SettlementActionRequest REQUEST_CHANGES without reason is a compile error', () => {
    // P1 regression guard (codex #6361 rev 2): the discriminated union
    // MUST reject REQUEST_CHANGES and DEFER without reason at compile
    // time.  @ts-expect-error confirms the compiler refuses each.
    // @ts-expect-error — REQUEST_CHANGES requires reason.
    const bad1: SettlementActionRequest = {
      pr_number: 6361,
      head_sha: '72a79cc74',
      packet_sha: 'packet-hash-xyz',
      action: SettlementAction.REQUEST_CHANGES,
    };
    // @ts-expect-error — DEFER requires reason.
    const bad2: SettlementActionRequest = {
      pr_number: 6361,
      head_sha: '72a79cc74',
      packet_sha: 'packet-hash-xyz',
      action: SettlementAction.DEFER,
    };
    // Reference bad1 and bad2 so lint doesn't flag them as unused while
    // still exercising the @ts-expect-error on the declarations above.
    expect([bad1, bad2]).toHaveLength(2);
  });

  test('SettlementActionResponse success carries the receipt', () => {
    const receipt: SettlementReceipt = {
      session_id: 'session-001',
      reviewed_at: '2026-04-20T15:00:00+00:00',
      actor: 'armand',
      action: SettlementAction.APPROVE,
      reason: '',
      pr_number: 6361,
      pr_url: 'https://github.com/synaptent/aragora/pull/6361',
      head_sha: '72a79cc74',
      base_sha: '1857a9192',
      packet_sha: 'packet-hash-xyz',
      queue_bucket: QueueLane.READY_NOW,
      machine_recommendation: Recommendation.APPROVE_CANDIDATE,
      github_event: 'REVIEW_SUBMITTED',
      elapsed_seconds: 4.2,
      receipt_path: '.aragora/review-queue/receipts/pr-6361-session-001-approve.json',
    };
    const resp: SettlementActionResponse = { success: true, receipt };
    expect(resp.success).toBe(true);
    // The UI contract: consumers MUST verify head_sha + packet_sha match
    // what they sent. This test documents that property at the type level.
    expect(resp.receipt?.head_sha).toBe('72a79cc74');
    expect(resp.receipt?.packet_sha).toBe('packet-hash-xyz');
  });

  test('SettlementActionResponse failure carries an error', () => {
    const resp: SettlementActionResponse = {
      success: false,
      error: 'stale_packet_sha: request head_sha=abc, current head_sha=def',
    };
    expect(resp.success).toBe(false);
    expect(resp.receipt).toBeUndefined();
    expect(resp.error).toContain('stale_packet_sha');
  });

  test('ReviewPacket protocol field narrows to PRReviewProtocolPacket when populated', () => {
    const binding: PRReviewBinding = {
      repo: 'synaptent/aragora',
      pr_number: 6361,
      base_sha: '1857a9192',
      head_sha: '72a79cc74',
    };
    // PRReviewFinding severity mirrors the strings Python emits in
    // ``_build_findings``: "low" | "medium" | "high" (RiskClass-ish).
    const finding: PRReviewFinding = {
      finding_id: 'bounded-green',
      category: 'summary',
      severity: 'low',
      summary: 'No blocking metadata signals detected for this PR.',
      evidence: ['Example PR', '24/24 green'],
      source: 'metadata_heuristic',
    };
    // Slot status is narrowed to ProviderSlotStatus; values match the
    // exact strings Python's _resolve_slot emits.
    const slot: ProviderSlotResolution = {
      slot_id: 'logic',
      review_role: ReviewRole.LOGIC,
      lens: 'core',
      family: 'claude',
      selected_provider: 'claude',
      status: ProviderSlotStatus.AVAILABLE,
      detail: 'claude CLI available',
      candidates: ['claude', 'anthropic-api'],
    };
    const validation_summary: ProtocolValidationSummary = {
      checks_summary: '24/24 green',
      has_failures: false,
      has_pending: false,
      mergeable: 'MERGEABLE',
      review_decision: 'REVIEW_REQUIRED',
      validation_commands: ['npx jest', 'npx tsc --noEmit'],
      changed_files: 3,
      diffstat: { additions: 656, deletions: 0 },
    };
    const cost_estimate: ProtocolCostEstimate = {
      currency: 'USD',
      low: 3.0,
      high: 5.0,
      basis: 'bounded heterogeneous metadata-first protocol',
    };
    const availability_summary: ProviderSlotAvailabilitySummary = {
      total_slots: 5,
      resolved_slots: 4,
      unresolved_slots: ['skeptic'],
      core_slots_total: 2,
      core_slots_resolved: 2,
      available_families: ['claude', 'gemini', 'gpt', 'mistral'],
      unresolved_families: ['grok'],
      opt_in_slots: ['regulatory'],
      degraded: true,
    };
    const protocol: PRReviewProtocolPacket = {
      protocol_version: 'pr_review_protocol.v1',
      status: 'metadata_heuristic',
      binding,
      review_roles: [ReviewRole.LOGIC, ReviewRole.SECURITY],
      provider_slots: [slot],
      availability_summary,
      recommendation_class: Recommendation.APPROVE_CANDIDATE,
      recommendation_reason: 'All gates green.',
      confidence: 0.9,
      confidence_basis: 'metadata_heuristic',
      dissent_summary: 'unanimous',
      dissenting_views: [],
      validation_summary,
      top_findings: [finding],
      cost_estimate,
    };
    // recommendation_class is typed to Recommendation — cannot be a stray string.
    expect(protocol.recommendation_class).toBe(Recommendation.APPROVE_CANDIDATE);
    expect(protocol.binding.head_sha).toBe('72a79cc74');
    expect(protocol.top_findings[0].finding_id).toBe('bounded-green');
    // Narrow discriminators: slot status and review role are real enum values.
    expect(protocol.provider_slots[0].status).toBe(ProviderSlotStatus.AVAILABLE);
    expect(protocol.provider_slots[0].review_role).toBe(ReviewRole.LOGIC);
    expect(protocol.review_roles).toContain(ReviewRole.SECURITY);
    // Typed validation summary + cost estimate preserve field-level access.
    expect(protocol.validation_summary.diffstat.additions).toBe(656);
    expect(protocol.cost_estimate.currency).toBe('USD');
    expect(protocol.availability_summary.opt_in_slots).toContain('regulatory');
  });

  test('ProviderSlotResolution rejects drift values at compile time', () => {
    // Regression guard (codex #6361 rev 4): status and review_role must
    // not be raw string. If the Python producer is ever extended, the
    // enum must be extended first — TS should fail to compile on drift
    // values like "selected" or "skipped_missing_env" that were in the
    // earlier (now-corrected) UI comment.
    // @ts-expect-error — "selected" is not a ProviderSlotStatus.
    const badStatus: ProviderSlotResolution = {
      slot_id: 'logic',
      review_role: ReviewRole.LOGIC,
      lens: 'core',
      family: 'claude',
      selected_provider: 'claude',
      status: 'selected',
      detail: '',
      candidates: [],
    };
    // @ts-expect-error — "auditor" is not a ReviewRole.
    const badRole: ProviderSlotResolution = {
      slot_id: 'logic',
      review_role: 'auditor',
      lens: 'core',
      family: 'claude',
      selected_provider: 'claude',
      status: ProviderSlotStatus.AVAILABLE,
      detail: '',
      candidates: [],
    };
    expect([badStatus, badRole]).toHaveLength(2);
  });

  test('ReviewPacket protocol field accepts empty-object default', () => {
    // Python producer emits {} when the protocol has not run yet; TS
    // must accept that without a cast.  Narrowing is via presence of
    // "protocol_version".
    const packet: ReviewPacket = {
      pr_number: 6361,
      title: '',
      url: '',
      head_sha: 'a',
      base_sha: 'b',
      author: 'an0mium',
      is_draft: false,
      additions: 0,
      deletions: 0,
      changed_files: 0,
      queue_bucket: QueueLane.READY_NOW,
      touched_subsystems: [],
      high_risk_paths_touched: [],
      validation: [],
      checks_summary: '',
      risk_flags: [],
      machine_recommendation: Recommendation.APPROVE_CANDIDATE,
      machine_recommendation_reason: '',
      packet_sha: '',
      generated_at: '',
      protocol: {},
      advisory_only: true,
      settlement_note: REVIEW_PACKET_ADVISORY_NOTE,
    };
    // Narrow by presence of protocol_version.
    if ('protocol_version' in packet.protocol) {
      // TS knows this is PRReviewProtocolPacket here.
      expect(packet.protocol.protocol_version).toBeDefined();
    } else {
      // empty-object path.
      expect(packet.protocol).toEqual({});
    }
  });

  test('ReviewPacket discriminator fields reject invalid strings at compile time', () => {
    // P1 regression guard (codex #6361 rev 3): queue_bucket and
    // machine_recommendation must be narrowed to QueueLane /
    // Recommendation, not raw string. If a UI tries to read a PR with
    // an unknown lane name, the cast must fail. @ts-expect-error
    // confirms the compiler refuses invalid values.

    // @ts-expect-error — "nonsense_lane" is not a QueueLane.
    const badPacketQueue: ReviewPacket = {
      pr_number: 1,
      title: '',
      url: '',
      head_sha: '',
      base_sha: '',
      author: '',
      is_draft: false,
      additions: 0,
      deletions: 0,
      changed_files: 0,
      queue_bucket: 'nonsense_lane',
      touched_subsystems: [],
      high_risk_paths_touched: [],
      validation: [],
      checks_summary: '',
      risk_flags: [],
      machine_recommendation: Recommendation.APPROVE_CANDIDATE,
      machine_recommendation_reason: '',
      packet_sha: '',
      generated_at: '',
      protocol: {},
      advisory_only: true,
      settlement_note: REVIEW_PACKET_ADVISORY_NOTE,
    };
    // @ts-expect-error — "looks_good" is not a Recommendation.
    const badPacketRec: ReviewPacket = {
      pr_number: 1,
      title: '',
      url: '',
      head_sha: '',
      base_sha: '',
      author: '',
      is_draft: false,
      additions: 0,
      deletions: 0,
      changed_files: 0,
      queue_bucket: QueueLane.READY_NOW,
      touched_subsystems: [],
      high_risk_paths_touched: [],
      validation: [],
      checks_summary: '',
      risk_flags: [],
      machine_recommendation: 'looks_good',
      machine_recommendation_reason: '',
      packet_sha: '',
      generated_at: '',
      protocol: {},
      advisory_only: true,
      settlement_note: REVIEW_PACKET_ADVISORY_NOTE,
    };
    // Reference both so unused-var lint doesn't fire; the @ts-expect-error
    // above is what actually enforces the contract.
    expect([badPacketQueue, badPacketRec]).toHaveLength(2);
  });

  test('CostMeter with multi-pool headroom and binding_scope', () => {
    const meter: CostMeter = {
      depth_chosen: 'standard' as ReviewDepth,
      decision: 'degrade' as ReviewPolicyDecision,
      estimated_cost_usd: 8.0,
      actual_cost_usd: 7.5,
      headroom_by_scope: [
        { scope: 'per_pr' as BudgetScope, cap_usd: 25.0, remaining_usd: 24.0 },
        {
          scope: 'per_repo_daily' as BudgetScope,
          cap_usd: 50.0,
          remaining_usd: 2.0,
          applies_at_or_above_depth: 'standard' as ReviewDepth,
        },
      ],
      binding_scope: 'per_repo_daily' as BudgetScope,
      alert_triggered: true,
    };
    expect(meter.binding_scope).toBe(BudgetScope.PER_REPO_DAILY);
    expect(meter.headroom_by_scope).toHaveLength(2);
    expect(meter.headroom_by_scope[1].remaining_usd).toBe(2.0);
  });
});

// ---------------------------------------------------------------------------
// Type-level contract: readonly discipline.  These tests pass at runtime;
// the value they add is compile-time: the TS compiler rejects attempts to
// mutate readonly fields, which guarantees the schema behaves like the
// Python frozen-dataclass + tuple pattern.
// ---------------------------------------------------------------------------

describe('readonly discipline (compile-time)', () => {
  test('readonly tuples reject mutation (TS compile-time check)', () => {
    const brief: ReviewBrief = {
      pr_number: 1,
      repo: '',
      head_sha: '',
      base_sha: '',
      packet_sha: '',
      recommendation: 'approve_candidate' as Recommendation,
      top_line: '',
      role_findings: [],
      dissent: [],
      validation_summary: '',
      overall_confidence: 0,
      disagreement_score: 0,
      total_cost_usd: 0,
      total_wall_clock_ms: 0,
      agent_roster: ['model-a'],
      generated_at: '',
      advisory_only: true,
      settlement_note: REVIEW_BRIEF_ADVISORY_NOTE,
    };
    // @ts-expect-error — agent_roster is readonly; push must fail type-check.
    brief.agent_roster.push('model-b');
    // @ts-expect-error — dissent is readonly.
    brief.dissent.push({ agent: 'x', position: 'defer', reason: '' });
    // @ts-expect-error — pr_number is readonly.
    brief.pr_number = 2;
  });
});
