import { normalizeDecisionPackage } from '../normalizeDecisionPackage';

describe('normalizeDecisionPackage', () => {
  it('fills missing array fields with safe defaults', () => {
    const normalized = normalizeDecisionPackage(
      { id: 'debate-1', question: 'Q', confidence: 0.5 },
      'fallback-id',
    );

    expect(normalized.id).toBe('debate-1');
    expect(normalized.agents).toEqual([]);
    expect(normalized.arguments).toEqual([]);
    expect(normalized.cost_breakdown).toEqual([]);
    expect(normalized.next_steps).toEqual([]);
    expect(normalized.receipt).toBeNull();
  });

  it('uses fallback id when payload id is missing', () => {
    const normalized = normalizeDecisionPackage({}, 'fallback-id');
    expect(normalized.id).toBe('fallback-id');
  });

  it('filters malformed entries in string arrays', () => {
    const normalized = normalizeDecisionPackage(
      {
        id: 'debate-2',
        agents: ['claude', 7, null, 'gpt-5'],
        next_steps: ['step one', { bad: true }, 'step two'],
      },
      'fallback-id',
    );

    expect(normalized.agents).toEqual(['claude', 'gpt-5']);
    expect(normalized.next_steps).toEqual([
      { action: 'step one', priority: 'medium' },
      { action: 'step two', priority: 'medium' },
    ]);
  });

  it('normalizes malformed receipt to null', () => {
    const normalized = normalizeDecisionPackage(
      { id: 'debate-3', receipt: { signers: ['a', 'b'] } },
      'fallback-id',
    );

    expect(normalized.receipt).toBeNull();
  });

  it('accepts the server decision-package shape used by completed debates', () => {
    const normalized = normalizeDecisionPackage(
      {
        debate_id: 'debate-42',
        question: 'Should we ship?',
        status: 'consensus_reached',
        debate_status: 'completed',
        debate_status_source: 'demo',
        verdict: 'APPROVED',
        confidence: 0.91,
        consensus_reached: true,
        explanation_summary: 'Agents aligned on shipping with minor caveats.',
        final_answer: 'Ship the release.',
        participants: ['claude', 'gpt-4'],
        cost: { total_cost_usd: 0.0042, per_agent_cost: { claude: 0.002, 'gpt-4': 0.0022 } },
        next_steps: [
          { action: 'Ship the release.', priority: 'high' },
          { action: 'Monitor logs.', priority: 'medium' },
        ],
        receipt: {
          receipt_id: 'receipt-42',
          checksum: 'abc123',
          created_at: '2026-03-25T12:34:56Z',
        },
        assembled_at: '2026-03-25T12:34:56Z',
      },
      'fallback-id',
    );

    expect(normalized.id).toBe('debate-42');
    expect(normalized.status).toBe('consensus_reached');
    expect(normalized.debate_status).toBe('completed');
    expect(normalized.debate_status_source).toBe('synthetic');
    expect(normalized.synthetic).toBe(true);
    expect(normalized.explanation).toBe('Agents aligned on shipping with minor caveats.');
    expect(normalized.agents).toEqual(['claude', 'gpt-4']);
    expect(normalized.total_cost).toBe(0.0042);
    expect(normalized.cost_breakdown).toEqual([
      { agent: 'claude', tokens: 0, cost: 0.002 },
      { agent: 'gpt-4', tokens: 0, cost: 0.0022 },
    ]);
    expect(normalized.next_steps).toEqual([
      { action: 'Ship the release.', priority: 'high' },
      { action: 'Monitor logs.', priority: 'medium' },
    ]);
    expect(normalized.receipt).toEqual({
      receipt_id: 'receipt-42',
      hash: 'abc123',
      timestamp: '2026-03-25T12:34:56Z',
      signers: [],
      cost_summary: null,
    });
    expect(normalized.created_at).toBe('2026-03-25T12:34:56Z');
  });

  it('preserves receipt cost summary metadata for the receipt tab', () => {
    const normalized = normalizeDecisionPackage(
      {
        debate_id: 'debate-43',
        participants: ['claude', 'gpt-4'],
        receipt: {
          checksum: 'cost123',
          created_at: '2026-03-25T12:34:56Z',
          cost_summary: {
            total_cost_usd: '0.045',
            total_tokens_in: 3000,
            total_tokens_out: 1000,
            total_calls: 6,
            per_agent: {
              claude: {
                agent_name: 'claude',
                total_cost_usd: '0.020',
                total_tokens_in: 1800,
                total_tokens_out: 400,
                call_count: 3,
                models_used: { 'claude-sonnet-4': 3 },
              },
            },
            model_usage: {
              'anthropic/claude-sonnet-4': {
                provider: 'anthropic',
                model: 'claude-sonnet-4',
                total_cost_usd: '0.020',
                total_tokens_in: 2000,
                total_tokens_out: 700,
                call_count: 4,
              },
            },
          },
        },
      },
      'fallback-id',
    );

    const costSummary = normalized.receipt?.cost_summary;

    expect(normalized.total_cost).toBe(0.045);
    expect(costSummary?.total_calls).toBe(6);
    expect(costSummary?.per_agent).toEqual([
      expect.objectContaining({
        agent: 'claude',
        models_used: [{ model: 'claude-sonnet-4', call_count: 3 }],
      }),
    ]);
    expect(costSummary?.model_usage).toEqual([
      expect.objectContaining({ label: 'anthropic/claude-sonnet-4', call_count: 4 }),
    ]);
  });

  it('derives synthetic truth metadata from the legacy mode flag when the explicit source is absent', () => {
    const normalized = normalizeDecisionPackage(
      { debate_id: 'debate-44', mode: 'demo', status: 'completed' },
      'fallback-id',
    );

    expect(normalized.debate_status).toBe('completed');
    expect(normalized.debate_status_source).toBe('synthetic');
    expect(normalized.synthetic).toBe(true);
  });
});
