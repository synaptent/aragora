import { fireEvent, render, screen } from '@testing-library/react';

import { useAgentBridgeRuns } from '@/hooks/useAgentBridgeRuns';

import type { AgentBridgeRunSummary } from '../types';
import { BridgeRunList } from '../BridgeRunList';

jest.mock('@/hooks/useAgentBridgeRuns');

const mockUseAgentBridgeRuns = useAgentBridgeRuns as jest.MockedFunction<typeof useAgentBridgeRuns>;

function buildRunSummary(overrides: Partial<AgentBridgeRunSummary> = {}): AgentBridgeRunSummary {
  return {
    schema_version: 1,
    run_id: 'bridge_20260421T191953Z_pr6306',
    task: 'Review and refine the protocol orchestrator implementation plan.',
    status: 'running',
    created_at: '2026-04-21T19:19:53Z',
    updated_at: '2026-04-21T19:24:10Z',
    completed_at: null,
    last_turn_index: 3,
    next_actor: 'reviewer',
    repair_budget_per_turn: 1,
    footer_mode: 'prompt_injected',
    worktree_cleanup_mode: 'operator_triggered',
    participants: [
      { role: 'implementer', harness: 'codex', model: 'gpt-5.4' },
      { role: 'reviewer', harness: 'claude', model: 'claude-opus-4-8' },
    ],
    last_event_id: 'bridge:event:003',
    ...overrides,
  };
}

describe('BridgeRunList', () => {
  beforeEach(() => {
    mockUseAgentBridgeRuns.mockReturnValue({
      schemaVersion: 1,
      runs: [buildRunSummary()],
      nextCursor: null,
      hasMore: false,
      isLoading: false,
      isLoadingMore: false,
      error: null,
      errorStatus: null,
      loadMore: jest.fn(),
      retry: jest.fn(),
    });
  });

  it('renders bridge runs in the table', () => {
    render(<BridgeRunList />);

    expect(screen.getByText('bridge_20260421T191953Z_pr6306')).toBeInTheDocument();
    expect(screen.getByText('running')).toBeInTheDocument();
    expect(screen.getByText('reviewer')).toBeInTheDocument();
    expect(screen.getByText('implementer · codex')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders the empty state', () => {
    mockUseAgentBridgeRuns.mockReturnValue({
      schemaVersion: 1,
      runs: [],
      nextCursor: null,
      hasMore: false,
      isLoading: false,
      isLoadingMore: false,
      error: null,
      errorStatus: null,
      loadMore: jest.fn(),
      retry: jest.fn(),
    });

    render(<BridgeRunList />);

    expect(screen.getByText('No agent-bridge runs yet')).toBeInTheDocument();
  });

  it('calls loadMore when the cursor button is clicked', () => {
    const loadMore = jest.fn();
    mockUseAgentBridgeRuns.mockReturnValue({
      schemaVersion: 1,
      runs: [buildRunSummary()],
      nextCursor: 'cursor-2',
      hasMore: true,
      isLoading: false,
      isLoadingMore: false,
      error: null,
      errorStatus: null,
      loadMore,
      retry: jest.fn(),
    });

    render(<BridgeRunList />);

    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

    expect(loadMore).toHaveBeenCalledTimes(1);
  });

  it('renders the explicit bridge API error banner', () => {
    mockUseAgentBridgeRuns.mockReturnValue({
      schemaVersion: null,
      runs: [],
      nextCursor: null,
      hasMore: false,
      isLoading: false,
      isLoadingMore: false,
      error: Object.assign(new Error('bridge store unavailable'), { status: 500 }),
      errorStatus: 500,
      loadMore: jest.fn(),
      retry: jest.fn(),
    });

    render(<BridgeRunList />);

    expect(screen.getByText('Bridge API unreachable')).toBeInTheDocument();
  });
});
