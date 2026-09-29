/**
 * Tests for PhaseProgress component
 */

import { renderWithProviders, screen, waitFor, act } from '@/test-utils';
import { PhaseProgress } from '../src/components/PhaseProgress';
import type { StreamEvent } from '../src/types/events';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('PhaseProgress', () => {
  const mockTimestamp = Date.now() / 1000;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  // Helper to create phase events
  const createPhaseStartEvent = (phase: string): StreamEvent => ({
    type: 'phase_start',
    data: { phase },
    timestamp: mockTimestamp,
  });

  const createPhaseEndEvent = (phase: string, success: boolean): StreamEvent => ({
    type: 'phase_end',
    data: { phase, success },
    timestamp: mockTimestamp,
  });

  describe('Rendering', () => {
    it('renders all phase blocks', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={[]} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      expect(screen.getByText('Debate')).toBeInTheDocument();
      expect(screen.getByText('Design')).toBeInTheDocument();
      expect(screen.getByText('Implement')).toBeInTheDocument();
      expect(screen.getByText('Verify')).toBeInTheDocument();
      expect(screen.getByText('Commit')).toBeInTheDocument();
    });

    it('renders phase progress header', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={[]} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      expect(screen.getByText('Phase Progress')).toBeInTheDocument();
    });
  });

  describe('Phase Status from Events', () => {
    it('marks current phase as active', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={[]} currentPhase="design" apiBase="http://localhost:3001" />,
        );
      });

      const designBlock = screen.getByText('Design');
      expect(designBlock).toHaveClass('text-accent');
    });

    it('marks phase as complete when phase_end event with success exists', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });
      const events: StreamEvent[] = [
        createPhaseStartEvent('debate'),
        createPhaseEndEvent('debate', true),
      ];

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={events} currentPhase="design" apiBase="http://localhost:3001" />,
        );
      });

      const debateBlock = screen.getByText('Debate');
      expect(debateBlock).toHaveClass('text-success');
    });

    it('marks phase as failed when phase_end event with success=false exists', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });
      const events: StreamEvent[] = [
        createPhaseStartEvent('design'),
        createPhaseEndEvent('design', false),
      ];

      await act(async () => {
        renderWithProviders(
          <PhaseProgress
            events={events}
            currentPhase="implement"
            apiBase="http://localhost:3001"
          />,
        );
      });

      const designBlock = screen.getByText('Design');
      expect(designBlock).toHaveClass('text-warning');
    });

    it('marks phase as active when only phase_start event exists', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });
      const events: StreamEvent[] = [createPhaseStartEvent('implement')];

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={events} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      const implementBlock = screen.getByText('Implement');
      expect(implementBlock).toHaveClass('text-accent');
    });

    it('marks unstarted phases as pending', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={[]} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      const commitBlock = screen.getByText('Commit');
      expect(commitBlock).toHaveClass('text-text-muted');
    });
  });

  describe('API State Integration', () => {
    it('fetches nomic state on mount', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            phase: 'design',
            stage: 'in_progress',
            cycle: 5,
            saved_at: '2024-01-15T10:30:00Z',
          }),
      });

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={[]} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:3001/api/nomic/state',
          expect.anything(),
        );
      });
    });

    it('displays cycle count from API state', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            phase: 'design',
            stage: 'analyzing',
            cycle: 12,
            saved_at: '2024-01-15T10:30:00Z',
          }),
      });

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={[]} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      await waitFor(() => {
        expect(screen.getByText('Cycle 12')).toBeInTheDocument();
      });
    });

    it('displays stage from API state', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            phase: 'design',
            stage: 'code_review',
            cycle: 5,
            saved_at: '2024-01-15T10:30:00Z',
          }),
      });

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={[]} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      await waitFor(() => {
        expect(screen.getByText(/code review/)).toBeInTheDocument();
      });
    });

    it('displays last update time when saved_at is present', async () => {
      const savedAt = '2024-01-15T10:30:00Z';
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ phase: 'design', cycle: 5, saved_at: savedAt }),
      });

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={[]} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      await waitFor(() => {
        expect(screen.getByText(/Last update:/)).toBeInTheDocument();
      });
    });

    it('overrides event-based status with API state', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ phase: 'implement', cycle: 3, saved_at: '2024-01-15T10:30:00Z' }),
      });

      // Events say debate is active, but API says we're in implement phase
      const events: StreamEvent[] = [createPhaseStartEvent('debate')];

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={events} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      await waitFor(() => {
        // Debate should be complete (before current phase)
        const debateBlock = screen.getByText('Debate');
        expect(debateBlock).toHaveClass('text-success');
      });

      // Design should also be complete
      const designBlock = screen.getByText('Design');
      expect(designBlock).toHaveClass('text-success');

      // Implement should be active
      const implementBlock = screen.getByText('Implement');
      expect(implementBlock).toHaveClass('text-accent');
    });

    it('handles API fetch error gracefully', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={[]} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      // Component should still render without crashing
      expect(screen.getByText('Phase Progress')).toBeInTheDocument();
      expect(screen.getByText('Debate')).toBeInTheDocument();
    });

    it('polls for updates every 10 seconds', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({ phase: 'debate', cycle: 1, saved_at: '2024-01-15T10:30:00Z' }),
      });

      await act(async () => {
        renderWithProviders(
          <PhaseProgress events={[]} currentPhase="debate" apiBase="http://localhost:3001" />,
        );
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);

      // Advance by 10 seconds
      await act(async () => {
        jest.advanceTimersByTime(10000);
      });

      expect(mockFetch).toHaveBeenCalledTimes(2);

      // Advance by another 10 seconds
      await act(async () => {
        jest.advanceTimersByTime(10000);
      });

      expect(mockFetch).toHaveBeenCalledTimes(3);
    });
  });
});
