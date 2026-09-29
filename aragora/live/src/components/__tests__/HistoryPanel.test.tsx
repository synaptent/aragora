import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HistoryPanel } from '../HistoryPanel';

// Mock the hooks
jest.mock('@/hooks/useSupabaseHistory', () => ({ useSupabaseHistory: jest.fn() }));

jest.mock('@/hooks/useLocalHistory', () => ({ useLocalHistory: jest.fn() }));

import { useSupabaseHistory } from '@/hooks/useSupabaseHistory';
import { useLocalHistory } from '@/hooks/useLocalHistory';

const mockUseSupabaseHistory = useSupabaseHistory as jest.MockedFunction<typeof useSupabaseHistory>;
const mockUseLocalHistory = useLocalHistory as jest.MockedFunction<typeof useLocalHistory>;

describe('HistoryPanel', () => {
  const mockSupabaseHistory = {
    isConfigured: false,
    isLoading: false,
    error: null,
    cycles: [],
    events: [],
    debates: [],
    refresh: jest.fn(),
    recentLoops: [],
    selectedLoopId: null,
    selectLoop: jest.fn(),
  };

  const mockLocalHistory = {
    isLoading: false,
    error: null,
    cycles: [],
    events: [],
    debates: [],
    refresh: jest.fn(),
    summary: null,
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSupabaseHistory.mockReturnValue(mockSupabaseHistory);
    mockUseLocalHistory.mockReturnValue(mockLocalHistory);
  });

  describe('rendering', () => {
    it('renders the History header', () => {
      render(<HistoryPanel />);
      expect(screen.getByText('History')).toBeInTheDocument();
    });

    it('renders loading state when loading', () => {
      mockUseLocalHistory.mockReturnValue({ ...mockLocalHistory, isLoading: true });

      render(<HistoryPanel />);
      // Loading indicator should be present (spinner in header)
      expect(screen.getByText('History')).toBeInTheDocument();
    });

    it('displays error message when there is an error', () => {
      mockUseLocalHistory.mockReturnValue({
        ...mockLocalHistory,
        error: 'Failed to fetch history',
      });

      render(<HistoryPanel />);
      expect(screen.getByText('Failed to fetch history')).toBeInTheDocument();
    });
  });

  describe('with data', () => {
    it('displays stats grid with cycle, event, and debate counts', () => {
      mockUseLocalHistory.mockReturnValue({
        ...mockLocalHistory,
        cycles: [
          { id: '1', cycle_number: 1, phase: 'debate', success: true },
          { id: '2', cycle_number: 2, phase: 'design', success: false },
        ],
        events: [
          {
            id: '1',
            timestamp: new Date().toISOString(),
            event_type: 'agent_message',
            agent: 'claude',
          },
        ],
        debates: [],
      });

      render(<HistoryPanel />);

      expect(screen.getByText('2')).toBeInTheDocument(); // Cycles count
      expect(screen.getByText('Cycles')).toBeInTheDocument();
      expect(screen.getByText('1')).toBeInTheDocument(); // Events count
      expect(screen.getByText('Events')).toBeInTheDocument();
    });

    it('displays cycles list with phase info and status', () => {
      mockUseLocalHistory.mockReturnValue({
        ...mockLocalHistory,
        cycles: [
          { id: '1', cycle_number: 1, phase: 'debate', success: true },
          { id: '2', cycle_number: 2, phase: 'implement', success: false },
          { id: '3', cycle_number: 3, phase: 'verify', success: null },
        ],
      });

      render(<HistoryPanel />);

      expect(screen.getByText('PHASES')).toBeInTheDocument();
      expect(screen.getByText('C1: debate')).toBeInTheDocument();
      expect(screen.getByText('C2: implement')).toBeInTheDocument();
      expect(screen.getByText('C3: verify')).toBeInTheDocument();
      expect(screen.getByText('[OK]')).toBeInTheDocument();
      expect(screen.getByText('[FAIL]')).toBeInTheDocument();
      expect(screen.getByText('[...]')).toBeInTheDocument();
    });

    it('displays events list with timestamps and types', () => {
      const timestamp = new Date().toISOString();
      mockUseLocalHistory.mockReturnValue({
        ...mockLocalHistory,
        events: [
          { id: '1', timestamp, event_type: 'debate_start', agent: null },
          { id: '2', timestamp, event_type: 'agent_message', agent: 'claude' },
        ],
      });

      render(<HistoryPanel />);

      expect(screen.getByText(/EVENTS/)).toBeInTheDocument();
      expect(screen.getByText('debate_start')).toBeInTheDocument();
      expect(screen.getByText('agent_message')).toBeInTheDocument();
      expect(screen.getByText('[claude]')).toBeInTheDocument();
    });

    it('displays debates with consensus status', () => {
      mockUseLocalHistory.mockReturnValue({
        ...mockLocalHistory,
        debates: [
          {
            id: '1',
            phase: 'debate',
            cycle_number: 1,
            task: 'Test debate task',
            consensus_reached: true,
            confidence: 0.85,
            agents: ['claude', 'gpt4'],
          },
          {
            id: '2',
            phase: 'design',
            cycle_number: 2,
            task: 'Another task',
            consensus_reached: false,
            confidence: 0.4,
            agents: ['gemini'],
          },
        ],
      });

      render(<HistoryPanel />);

      expect(screen.getByText('DEBATES')).toBeInTheDocument();
      expect(screen.getByText('debate (C1)')).toBeInTheDocument();
      expect(screen.getByText('design (C2)')).toBeInTheDocument();
      expect(screen.getByText('[85%]')).toBeInTheDocument();
      expect(screen.getByText('[NO_CONSENSUS]')).toBeInTheDocument();
      expect(screen.getByText('agents: claude, gpt4')).toBeInTheDocument();
    });
  });

  describe('Supabase mode', () => {
    it('shows loop selector when Supabase is configured', () => {
      mockUseSupabaseHistory.mockReturnValue({
        ...mockSupabaseHistory,
        isConfigured: true,
        recentLoops: ['nomic-20260101-120000', 'nomic-20260102-091500'],
        selectedLoopId: 'nomic-20260101-120000',
      });

      render(<HistoryPanel />);

      expect(screen.getByLabelText(/SELECT_LOOP/i)).toBeInTheDocument();
    });

    it('calls selectLoop when loop is changed', async () => {
      const selectLoop = jest.fn();
      mockUseSupabaseHistory.mockReturnValue({
        ...mockSupabaseHistory,
        isConfigured: true,
        recentLoops: ['nomic-20260101-120000', 'nomic-20260102-091500'],
        selectedLoopId: 'nomic-20260101-120000',
        selectLoop,
      });

      render(<HistoryPanel />);

      const select = screen.getByLabelText(/SELECT_LOOP/i);
      await userEvent.selectOptions(select, 'nomic-20260102-091500');

      expect(selectLoop).toHaveBeenCalledWith('nomic-20260102-091500');
    });
  });

  describe('local API mode', () => {
    it('shows local API message when not using Supabase', () => {
      mockUseLocalHistory.mockReturnValue({
        ...mockLocalHistory,
        summary: { recent_loop_id: 'nomic-20260105-143000' },
      });

      render(<HistoryPanel />);

      expect(screen.getByText(/Using local API/)).toBeInTheDocument();
    });
  });

  describe('accessibility', () => {
    it('has accessible role list for cycles', () => {
      mockUseLocalHistory.mockReturnValue({
        ...mockLocalHistory,
        cycles: [{ id: '1', cycle_number: 1, phase: 'debate', success: true }],
      });

      render(<HistoryPanel />);

      const list = screen.getByRole('list', { name: /phases/i });
      expect(list).toBeInTheDocument();

      const listItem = screen.getByRole('listitem');
      expect(listItem).toHaveAttribute('aria-label', expect.stringContaining('Cycle 1'));
    });

    it('has accessible log for events', () => {
      mockUseLocalHistory.mockReturnValue({
        ...mockLocalHistory,
        events: [{ id: '1', timestamp: new Date().toISOString(), event_type: 'test', agent: null }],
      });

      render(<HistoryPanel />);

      const log = screen.getByRole('log');
      expect(log).toHaveAttribute('aria-live', 'polite');
    });

    it('has accessible role list for debates', () => {
      mockUseLocalHistory.mockReturnValue({
        ...mockLocalHistory,
        debates: [
          {
            id: '1',
            phase: 'debate',
            cycle_number: 1,
            task: 'Test',
            consensus_reached: true,
            confidence: 0.8,
            agents: ['claude'],
          },
        ],
      });

      render(<HistoryPanel />);

      const debateItem = screen.getByRole('listitem', { name: /debate debate in cycle 1/i });
      expect(debateItem).toBeInTheDocument();
    });
  });
});
