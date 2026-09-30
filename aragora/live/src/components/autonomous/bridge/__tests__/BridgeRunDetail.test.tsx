import { fireEvent, render, screen } from '@testing-library/react';

import { useAgentBridgeEvents } from '@/hooks/useAgentBridgeEvents';
import { useAgentBridgeRun } from '@/hooks/useAgentBridgeRun';
import { useAgentBridgeTranscript } from '@/hooks/useAgentBridgeTranscript';

import type { AgentBridgeEvent, AgentBridgeRunDetail, AgentBridgeTurnRecord } from '../types';
import { BridgeRunDetail } from '../BridgeRunDetail';

jest.mock('@/hooks/useAgentBridgeRun');
jest.mock('@/hooks/useAgentBridgeEvents');
jest.mock('@/hooks/useAgentBridgeTranscript');

const mockUseAgentBridgeRun = useAgentBridgeRun as jest.MockedFunction<typeof useAgentBridgeRun>;
const mockUseAgentBridgeEvents = useAgentBridgeEvents as jest.MockedFunction<
  typeof useAgentBridgeEvents
>;
const mockUseAgentBridgeTranscript = useAgentBridgeTranscript as jest.MockedFunction<
  typeof useAgentBridgeTranscript
>;

function buildRunDetail(overrides: Partial<AgentBridgeRunDetail> = {}): AgentBridgeRunDetail {
  return {
    schema_version: 1,
    run_id: 'bridge_20260421T191953Z_pr6306',
    task: 'Review and refine the protocol orchestrator implementation plan.',
    status: 'running',
    created_at: '2026-04-21T19:19:53Z',
    updated_at: '2026-04-21T19:24:10Z',
    completed_at: null,
    last_turn_index: 2,
    next_actor: 'reviewer',
    repair_budget_per_turn: 1,
    footer_mode: 'prompt_injected',
    worktree_cleanup_mode: 'operator_triggered',
    participants: [
      { role: 'implementer', harness: 'codex', model: 'gpt-5.4' },
      { role: 'reviewer', harness: 'claude', model: 'claude-opus-4-8' },
    ],
    last_event_id: 'bridge:event:002',
    worktree_path: '/tmp/bridge-worktree',
    worktree_agent_slug: 'bridge-pr6306',
    roles: {
      implementer: {
        role: 'implementer',
        harness: 'codex',
        model: 'gpt-5.4',
        session_id: '019db172-4d01-7072-860c-99114afe8792',
        worktree_agent_slug: 'bridge-pr6306-implementer',
        worktree_path: '/tmp/bridge-worktree/implementer',
        branch: 'codex/bridge-pr6306-implementer',
        session_status: 'active',
        started_at: '2026-04-21T19:21:02Z',
        last_turn_index: 2,
        last_completed_at: '2026-04-21T19:24:10Z',
      },
      reviewer: {
        role: 'reviewer',
        harness: 'claude',
        model: 'claude-opus-4-8',
        session_id: null,
        worktree_agent_slug: 'bridge-pr6306-reviewer',
        worktree_path: '/tmp/bridge-worktree/reviewer',
        branch: 'codex/bridge-pr6306-reviewer',
        session_status: 'not_started',
        started_at: null,
        last_turn_index: 0,
        last_completed_at: null,
      },
    },
    ...overrides,
  };
}

function buildTranscriptTurn(
  overrides: Partial<AgentBridgeTurnRecord> = {},
): AgentBridgeTurnRecord {
  return {
    turn_index: 1,
    author_role: 'implementer',
    started_at: '2026-04-21T19:23:40Z',
    completed_at: '2026-04-21T19:24:09Z',
    parse_status: 'ok',
    footer: {
      summary: 'Outlined the persistence and transport slices.',
      next_actor: 'reviewer',
      needs_human: false,
      done: false,
      artifacts: [],
      tests_run: [],
    },
    body_markdown: 'Turn body',
    ...overrides,
  };
}

function buildEvent(overrides: Partial<AgentBridgeEvent> = {}): AgentBridgeEvent {
  return {
    schema_version: 1,
    event_id: 'bridge:event:001',
    run_id: 'bridge_20260421T191953Z_pr6306',
    ts: '2026-04-21T19:24:09Z',
    event_type: 'turn.completed',
    turn_index: 1,
    role: 'implementer',
    harness: 'codex',
    session_id: '019db172-4d01-7072-860c-99114afe8792',
    parse_status: 'ok',
    payload: {
      footer: {
        summary: 'Outlined the persistence and transport slices.',
        next_actor: 'reviewer',
        needs_human: false,
        done: false,
        artifacts: [],
        tests_run: [],
      },
    },
    ...overrides,
  };
}

describe('BridgeRunDetail', () => {
  beforeEach(() => {
    mockUseAgentBridgeRun.mockReturnValue({
      run: buildRunDetail(),
      isLoading: false,
      error: null,
      errorStatus: null,
      retry: jest.fn(),
    });
    mockUseAgentBridgeEvents.mockReturnValue({
      events: [buildEvent()],
      nextCursor: null,
      isLoading: false,
      error: null,
      errorStatus: null,
      retry: jest.fn(),
    });
    mockUseAgentBridgeTranscript.mockReturnValue({
      turns: [buildTranscriptTurn()],
      isLoading: false,
      error: null,
      errorStatus: null,
      retry: jest.fn(),
    });
  });

  it('renders transcript, events, and metadata tabs', () => {
    render(<BridgeRunDetail runId="bridge-run" />);

    expect(screen.getByText('Turn body')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /Events/i }));
    expect(screen.getByText('turn.completed')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /Metadata/i }));
    expect(screen.getByText('run.json')).toBeInTheDocument();
    expect(screen.getByText('sessions.json')).toBeInTheDocument();
  });

  it('renders role cards from the role-keyed registry', () => {
    render(<BridgeRunDetail runId="bridge-run" />);

    expect(screen.getAllByText('implementer').length).toBeGreaterThan(0);
    expect(screen.getAllByText('reviewer').length).toBeGreaterThan(0);
    expect(screen.getAllByText('codex').length).toBeGreaterThan(0);
    expect(screen.getAllByText('claude').length).toBeGreaterThan(0);
  });

  it('stops polling when the run is not running', () => {
    mockUseAgentBridgeRun.mockReturnValue({
      run: buildRunDetail({ status: 'completed' }),
      isLoading: false,
      error: null,
      errorStatus: null,
      retry: jest.fn(),
    });

    render(<BridgeRunDetail runId="bridge-run" />);

    expect(mockUseAgentBridgeEvents).toHaveBeenCalledWith(
      'bridge-run',
      expect.objectContaining({ poll: false }),
    );
    expect(mockUseAgentBridgeTranscript).toHaveBeenCalledWith(
      'bridge-run',
      expect.objectContaining({ poll: false }),
    );
  });
});
