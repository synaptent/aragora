/**
 * Tests for InterventionPanel component
 *
 * Tests cover:
 * - Inactive state rendering
 * - Tab navigation (inject, nudge, control, weights)
 * - Pause/resume toggle with toast feedback
 * - Argument injection with toast and history
 * - Nudge direction input
 * - Challenge claim input
 * - Consensus threshold control with history
 * - Agent weight sliders with colored bars and comparison
 * - Intervention history with status tracking
 * - Toast notifications on success and failure
 * - Weight comparison visualization
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { InterventionPanel } from '../InterventionPanel';

// Mock logger
jest.mock('@/utils/logger', () => ({ logger: { error: jest.fn(), debug: jest.fn() } }));

// Mock config
jest.mock('@/config', () => ({ API_BASE_URL: 'http://localhost:8080' }));

// Mock agentColors
jest.mock('@/utils/agentColors', () => ({
  getAgentColors: (name: string) => {
    if (name.startsWith('claude'))
      return { bg: 'bg-acid-cyan/10', text: 'text-acid-cyan', border: 'border-acid-cyan/40' };
    if (name.startsWith('gpt'))
      return { bg: 'bg-gold/10', text: 'text-gold', border: 'border-gold/40' };
    return { bg: 'bg-acid-green/10', text: 'text-acid-green', border: 'border-acid-green/40' };
  },
}));

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

const defaultProps = {
  debateId: 'test-debate-123',
  isActive: true,
  isPaused: false,
  currentRound: 2,
  totalRounds: 5,
  agents: ['claude', 'gpt-4'],
  consensusThreshold: 0.75,
};

describe('InterventionPanel', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockFetch.mockReset();
    mockFetch.mockResolvedValue({ ok: true });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('inactive state', () => {
    it('shows inactive message when not active', () => {
      render(<InterventionPanel {...defaultProps} isActive={false} />);

      expect(
        screen.getByText(/Intervention controls are only available during active debates/),
      ).toBeInTheDocument();
    });

    it('does not show tabs when inactive', () => {
      render(<InterventionPanel {...defaultProps} isActive={false} />);

      expect(screen.queryByText('Inject')).not.toBeInTheDocument();
      expect(screen.queryByText('Nudge')).not.toBeInTheDocument();
    });
  });

  describe('active state', () => {
    it('renders intervention controls header', () => {
      render(<InterventionPanel {...defaultProps} />);

      expect(screen.getByText('Intervention Controls')).toBeInTheDocument();
    });

    it('shows round progress', () => {
      render(<InterventionPanel {...defaultProps} />);

      expect(screen.getByText('Round 2/5')).toBeInTheDocument();
    });

    it('renders all four tabs', () => {
      render(<InterventionPanel {...defaultProps} />);

      expect(screen.getByText('Inject')).toBeInTheDocument();
      expect(screen.getByText('Nudge')).toBeInTheDocument();
      expect(screen.getByText('Control')).toBeInTheDocument();
      expect(screen.getByText('Weights')).toBeInTheDocument();
    });
  });

  describe('pause/resume', () => {
    it('shows PAUSE button when not paused', () => {
      render(<InterventionPanel {...defaultProps} isPaused={false} />);

      expect(screen.getByText(/PAUSE/)).toBeInTheDocument();
    });

    it('shows RESUME button when paused', () => {
      render(<InterventionPanel {...defaultProps} isPaused={true} />);

      expect(screen.getByText(/RESUME/)).toBeInTheDocument();
    });

    it('calls pause API on toggle', async () => {
      render(<InterventionPanel {...defaultProps} isPaused={false} />);

      fireEvent.click(screen.getByText(/PAUSE/));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/v1/debates/test-debate-123/pause',
          expect.objectContaining({ method: 'POST' }),
        );
      });
    });

    it('shows toast on successful pause', async () => {
      render(<InterventionPanel {...defaultProps} isPaused={false} />);

      await act(async () => {
        fireEvent.click(screen.getByText(/PAUSE/));
      });

      await waitFor(() => {
        // Check for the specific toast message text
        expect(screen.getByText(/agents will hold after current turn/)).toBeInTheDocument();
      });
    });

    it('records pause in history with status', async () => {
      render(<InterventionPanel {...defaultProps} isPaused={false} />);

      await act(async () => {
        fireEvent.click(screen.getByText(/PAUSE/));
      });

      await waitFor(() => {
        // History should show the type label and applied status
        expect(screen.getByText(/History \(1\)/)).toBeInTheDocument();
        expect(screen.getByText('applied')).toBeInTheDocument();
      });
    });

    it('shows error toast on pause failure', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });

      render(<InterventionPanel {...defaultProps} isPaused={false} />);

      await act(async () => {
        fireEvent.click(screen.getByText(/PAUSE/));
      });

      await waitFor(() => {
        expect(screen.getByText(/Failed to pause/i)).toBeInTheDocument();
      });
    });

    it('marks failed pause in history', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });

      render(<InterventionPanel {...defaultProps} isPaused={false} />);

      await act(async () => {
        fireEvent.click(screen.getByText(/PAUSE/));
      });

      await waitFor(() => {
        expect(screen.getByText('failed')).toBeInTheDocument();
      });
    });
  });

  describe('inject tab', () => {
    it('shows argument injection textarea', () => {
      render(<InterventionPanel {...defaultProps} />);

      expect(screen.getByPlaceholderText('Add your argument to the debate...')).toBeInTheDocument();
    });

    it('shows inject button', () => {
      render(<InterventionPanel {...defaultProps} />);

      expect(screen.getByRole('button', { name: /INJECT ARGUMENT/ })).toBeInTheDocument();
    });

    it('calls inject API with argument', async () => {
      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'My argument' } });

      fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/v1/debates/test-debate-123/inject-evidence',
          expect.objectContaining({
            method: 'POST',
            body: expect.stringContaining('"evidence":"My argument"'),
          }),
        );
      });
    });

    it('disables inject button when textarea empty', () => {
      render(<InterventionPanel {...defaultProps} />);

      expect(screen.getByRole('button', { name: /INJECT ARGUMENT/ })).toBeDisabled();
    });

    it('shows success toast after injection', async () => {
      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Test argument' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText(/Evidence injected/)).toBeInTheDocument();
      });
    });

    it('shows error toast on injection failure', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Test argument' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText(/Failed to inject evidence/)).toBeInTheDocument();
      });
    });

    it('adds injection to history with applied status', async () => {
      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Test argument for history' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText(/Evidence Injection/)).toBeInTheDocument();
        expect(screen.getByText('applied')).toBeInTheDocument();
      });
    });

    it('marks failed injection in history', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false });

      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Will fail' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText('failed')).toBeInTheDocument();
      });
    });
  });

  describe('nudge tab', () => {
    it('shows nudge direction input after switching tab', () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Nudge'));

      expect(
        screen.getByPlaceholderText('e.g., Consider the economic implications...'),
      ).toBeInTheDocument();
    });

    it('shows challenge claim textarea', () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Nudge'));

      expect(
        screen.getByPlaceholderText('e.g., The claim that X is incorrect because...'),
      ).toBeInTheDocument();
    });

    it('calls nudge API with direction prefix', async () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Nudge'));

      const input = screen.getByPlaceholderText('e.g., Consider the economic implications...');
      fireEvent.change(input, { target: { value: 'Focus on scalability' } });

      fireEvent.click(screen.getByRole('button', { name: /NUDGE DIRECTION/ }));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/v1/debates/test-debate-123/nudge',
          expect.objectContaining({
            body: expect.stringContaining('"message":"Focus on scalability"'),
          }),
        );
      });
    });

    it('calls challenge API with challenge prefix', async () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Nudge'));

      const textarea = screen.getByPlaceholderText(
        'e.g., The claim that X is incorrect because...',
      );
      fireEvent.change(textarea, { target: { value: 'That claim lacks evidence' } });

      // Use getByRole to specifically target the button (not the label)
      const challengeButton = screen.getByRole('button', { name: /CHALLENGE CLAIM/ });
      fireEvent.click(challengeButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/v1/debates/test-debate-123/challenge',
          expect.objectContaining({
            body: expect.stringContaining('"challenge":"That claim lacks evidence"'),
          }),
        );
      });
    });

    it('shows toast for successful nudge', async () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Nudge'));

      const input = screen.getByPlaceholderText('e.g., Consider the economic implications...');
      fireEvent.change(input, { target: { value: 'Focus on scalability' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /NUDGE DIRECTION/ }));
      });

      await waitFor(() => {
        expect(screen.getByText(/Direction nudge applied/)).toBeInTheDocument();
      });
    });

    it('shows toast for successful challenge', async () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Nudge'));

      const textarea = screen.getByPlaceholderText(
        'e.g., The claim that X is incorrect because...',
      );
      fireEvent.change(textarea, { target: { value: 'That is wrong' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /CHALLENGE CLAIM/ }));
      });

      await waitFor(() => {
        expect(screen.getByText(/Challenge injected/)).toBeInTheDocument();
      });
    });
  });

  describe('control tab', () => {
    it('shows consensus threshold slider', () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Control'));

      expect(screen.getByText(/CONSENSUS THRESHOLD/)).toBeInTheDocument();
    });

    it('shows quick action buttons', () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Control'));

      expect(screen.getByText(/Skip Round/)).toBeInTheDocument();
      expect(screen.getByText(/Add Round/)).toBeInTheDocument();
      expect(screen.getByText(/Force Vote/)).toBeInTheDocument();
      expect(screen.getByText(/End Debate/)).toBeInTheDocument();
    });

    it('shows toast on threshold change', async () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Control'));

      const slider = screen.getByRole('slider');
      await act(async () => {
        fireEvent.change(slider, { target: { value: '0.9' } });
      });

      await waitFor(() => {
        expect(screen.getByText(/Consensus threshold set to 90%/)).toBeInTheDocument();
      });
    });

    it('records threshold change in history', async () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Control'));

      const slider = screen.getByRole('slider');
      await act(async () => {
        fireEvent.change(slider, { target: { value: '0.9' } });
      });

      await waitFor(() => {
        expect(screen.getByText(/Threshold Change/)).toBeInTheDocument();
        expect(screen.getByText(/75% -> 90%/)).toBeInTheDocument();
      });
    });
  });

  describe('weights tab', () => {
    it('shows agent weight sliders', () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Weights'));

      expect(screen.getByText('claude')).toBeInTheDocument();
      expect(screen.getByText('gpt-4')).toBeInTheDocument();
    });

    it('shows default weight values', () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Weights'));

      // Default weights are 1.0x
      const weights = screen.getAllByText('1.0x');
      expect(weights.length).toBe(2);
    });

    it('renders colored weight bar segments', () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Weights'));

      const bars = screen.getAllByTestId('weight-bar');
      expect(bars.length).toBeGreaterThanOrEqual(1);
    });

    it('shows toast on weight change', async () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Weights'));

      const sliders = screen.getAllByRole('slider');
      // First slider is for claude
      await act(async () => {
        fireEvent.change(sliders[0], { target: { value: '1.5' } });
      });

      await waitFor(() => {
        expect(screen.getByText(/claude weight updated to 1.5x/)).toBeInTheDocument();
      });
    });

    it('records weight change in history', async () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Weights'));

      const sliders = screen.getAllByRole('slider');
      await act(async () => {
        fireEvent.change(sliders[0], { target: { value: '1.5' } });
      });

      await waitFor(() => {
        expect(screen.getByText(/Weight Change/)).toBeInTheDocument();
      });
    });

    it('shows weight comparison on change', async () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Weights'));

      const sliders = screen.getAllByRole('slider');
      await act(async () => {
        fireEvent.change(sliders[0], { target: { value: '1.8' } });
      });

      // Weight comparison should be visible
      await waitFor(() => {
        expect(screen.getByTestId('weight-comparison')).toBeInTheDocument();
        expect(screen.getByText('Previous')).toBeInTheDocument();
        expect(screen.getByText('Current')).toBeInTheDocument();
      });
    });

    it('hides weight comparison after timeout', async () => {
      render(<InterventionPanel {...defaultProps} />);

      fireEvent.click(screen.getByText('Weights'));

      const sliders = screen.getAllByRole('slider');
      await act(async () => {
        fireEvent.change(sliders[0], { target: { value: '1.8' } });
      });

      await waitFor(() => {
        expect(screen.getByTestId('weight-comparison')).toBeInTheDocument();
      });

      // Advance timers to hide comparison
      act(() => {
        jest.advanceTimersByTime(3500);
      });

      expect(screen.queryByTestId('weight-comparison')).not.toBeInTheDocument();
    });
  });

  describe('intervention history', () => {
    it('does not show history when empty', () => {
      render(<InterventionPanel {...defaultProps} />);

      expect(screen.queryByText(/History/)).not.toBeInTheDocument();
    });

    it('shows history after an intervention', async () => {
      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Test argument' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText(/History \(1\)/)).toBeInTheDocument();
      });
    });

    it('shows actions count badge in header', async () => {
      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Test argument' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText('1 actions')).toBeInTheDocument();
      });
    });

    it('history can be collapsed and expanded', async () => {
      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Test argument' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText(/Evidence Injection/)).toBeInTheDocument();
      });

      // Collapse
      fireEvent.click(screen.getByText(/History/));

      // History entries should be hidden
      expect(screen.queryByText(/Evidence Injection/)).not.toBeInTheDocument();

      // Expand
      fireEvent.click(screen.getByText(/History/));

      expect(screen.getByText(/Evidence Injection/)).toBeInTheDocument();
    });

    it('shows status for each history entry', async () => {
      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Test' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText('applied')).toBeInTheDocument();
      });
    });

    it('accumulates multiple interventions in history', async () => {
      render(<InterventionPanel {...defaultProps} />);

      // First injection
      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'First argument' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText(/History \(1\)/)).toBeInTheDocument();
      });

      // Second injection
      fireEvent.change(textarea, { target: { value: 'Second argument' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText(/History \(2\)/)).toBeInTheDocument();
      });
    });
  });

  describe('toast notifications', () => {
    it('renders toast with correct type styling', async () => {
      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Test' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        // Success toast should contain [OK]
        expect(screen.getByText('[OK]')).toBeInTheDocument();
      });
    });

    it('renders error toast with [ERR] prefix', async () => {
      mockFetch.mockRejectedValueOnce(new Error('fail'));

      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Test' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        expect(screen.getByText('[ERR]')).toBeInTheDocument();
      });
    });

    it('has accessible toast region', async () => {
      render(<InterventionPanel {...defaultProps} />);

      const textarea = screen.getByPlaceholderText('Add your argument to the debate...');
      fireEvent.change(textarea, { target: { value: 'Test' } });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /INJECT ARGUMENT/ }));
      });

      await waitFor(() => {
        const region = screen.getByRole('region', { name: /Intervention notifications/ });
        expect(region).toBeInTheDocument();
      });
    });
  });

  describe('footer', () => {
    it('shows audit trail message', () => {
      render(<InterventionPanel {...defaultProps} />);

      expect(screen.getByText('Interventions are logged in the audit trail')).toBeInTheDocument();
    });
  });
});
