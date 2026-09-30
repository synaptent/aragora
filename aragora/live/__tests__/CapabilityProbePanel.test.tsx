/**
 * Tests for CapabilityProbePanel component
 *
 * Tests cover:
 * - Collapsed/expanded states
 * - Agent loading from leaderboard
 * - Agent selection
 * - Probe type selection (multi-select)
 * - Probes per type validation
 * - POST request with probe configuration
 * - Results display (summary, by-type)
 * - Loading and error states
 * - onComplete callback
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CapabilityProbePanel } from '../src/components/CapabilityProbePanel';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock data
const mockAgents = [
  { name: 'claude-3-opus', elo: 1650 },
  { name: 'gemini-2.0-flash', elo: 1580 },
  { name: 'gpt-4', elo: 1620 },
];

const mockProbeReport = {
  report_id: 'probe-report-001',
  target_agent: 'claude-3-opus',
  probes_configured: 6,
  by_type: {
    contradiction: [
      {
        probe_id: 'p1',
        type: 'contradiction',
        passed: true,
        description: 'Consistent position on AI safety',
        severity: 'low',
      },
      {
        probe_id: 'p2',
        type: 'contradiction',
        passed: false,
        description: 'Conflicting views on regulation',
        severity: 'medium',
        details: 'Position shifted between rounds',
      },
      {
        probe_id: 'p3',
        type: 'contradiction',
        passed: true,
        description: 'Stable technical reasoning',
        severity: 'low',
      },
    ],
    hallucination: [
      {
        probe_id: 'p4',
        type: 'hallucination',
        passed: true,
        description: 'Accurate citation of sources',
        severity: 'low',
      },
      {
        probe_id: 'p5',
        type: 'hallucination',
        passed: true,
        description: 'No fabricated statistics',
        severity: 'low',
      },
      {
        probe_id: 'p6',
        type: 'hallucination',
        passed: true,
        description: 'Correct technical facts',
        severity: 'low',
      },
    ],
  },
  summary: { total: 6, passed: 5, failed: 1, pass_rate: 0.833 },
};

function setupSuccessfulFetch() {
  mockFetch.mockImplementation((url: string, _options?: RequestInit) => {
    if (url.includes('/api/leaderboard')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: mockAgents }) });
    }
    if (url.includes('/api/probes/run') && _options?.method === 'POST') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockProbeReport) });
    }
    return Promise.resolve({ ok: false });
  });
}

const waitForAgentSelection = async () => {
  await waitFor(() => {
    expect(screen.getByRole('combobox')).toHaveValue('claude-3-opus');
  });
};
const expandPanel = async () => {
  fireEvent.click(screen.getByText(/CAPABILITY_PROBES/));
  await waitForAgentSelection();
};
const expandPanelWithoutSelection = async () => {
  fireEvent.click(screen.getByText(/CAPABILITY_PROBES/));
  await waitFor(() => {
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });
};

describe('CapabilityProbePanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Initial State', () => {
    it('shows collapsed view by default', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {}));
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      expect(screen.getByText(/CAPABILITY_PROBES/)).toBeInTheDocument();
      expect(screen.getByText('[EXPAND]')).toBeInTheDocument();
    });

    it('fetches agents on mount', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        const calls = mockFetch.mock.calls.map((call: string[]) => call[0]);
        expect(calls.some((url: string) => url.includes('/api/leaderboard'))).toBe(true);
      });

      await expandPanel();
    });
  });

  describe('Expand/Collapse', () => {
    it('expands panel on click', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByText('[COLLAPSE]')).toBeInTheDocument();
      });
    });

    it('collapses panel when collapse clicked', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      // Expand first
      await expandPanel();
      await waitFor(() => {
        expect(screen.getByText('[COLLAPSE]')).toBeInTheDocument();
      });

      // Collapse
      fireEvent.click(screen.getByText('[COLLAPSE]'));

      expect(screen.getByText('[EXPAND]')).toBeInTheDocument();
    });
  });

  describe('Agent Selection', () => {
    it('shows agent dropdown when expanded', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByText('Target Agent')).toBeInTheDocument();
      });
    });

    it('populates dropdown with agents from API', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        const select = screen.getByRole('combobox');
        expect(select).toBeInTheDocument();
      });

      // First agent should be auto-selected
    });

    it('allows selecting different agents', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      // Wait for agents to load and first one to be selected

      fireEvent.change(screen.getByRole('combobox'), { target: { value: 'gpt-4' } });

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('gpt-4');
      });
    });
  });

  describe('Probe Type Selection', () => {
    it('shows all probe types', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByText('Contradiction')).toBeInTheDocument();
        expect(screen.getByText('Hallucination')).toBeInTheDocument();
        expect(screen.getByText('Sycophancy')).toBeInTheDocument();
        expect(screen.getByText('Persistence')).toBeInTheDocument();
        expect(screen.getByText('Calibration')).toBeInTheDocument();
        expect(screen.getByText('Reasoning Depth')).toBeInTheDocument();
        expect(screen.getByText('Edge Cases')).toBeInTheDocument();
      });
    });

    it('has contradiction and hallucination selected by default', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        // Check that the buttons have the selected class
        const contradictionBtn = screen.getByText('Contradiction').closest('button');
        const hallucinationBtn = screen.getByText('Hallucination').closest('button');
        expect(contradictionBtn).toHaveClass('border-purple-500');
        expect(hallucinationBtn).toHaveClass('border-purple-500');
      });
    });

    it('toggles probe selection on click', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByText('Sycophancy')).toBeInTheDocument();
      });

      // Click Sycophancy to select it
      fireEvent.click(screen.getByText('Sycophancy').closest('button')!);

      // Should now have selected class
      const sycophancyBtn = screen.getByText('Sycophancy').closest('button');
      expect(sycophancyBtn).toHaveClass('border-purple-500');
    });

    it('deselects probe on second click', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByText('Contradiction')).toBeInTheDocument();
      });

      // Click Contradiction to deselect it
      fireEvent.click(screen.getByText('Contradiction').closest('button')!);

      // Should now have unselected class
      const contradictionBtn = screen.getByText('Contradiction').closest('button');
      expect(contradictionBtn).not.toHaveClass('border-purple-500');
    });
  });

  describe('Probes Per Type Input', () => {
    it('shows probes per type input', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByText(/Probes per Type/)).toBeInTheDocument();
      });
    });

    it('has default value of 3', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        const input = screen.getByRole('spinbutton');
        expect(input).toHaveValue(3);
      });
    });

    it('allows changing probes per type', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByRole('spinbutton')).toBeInTheDocument();
      });

      fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '5' } });

      expect(screen.getByRole('spinbutton')).toHaveValue(5);
    });
  });

  describe('Run Probes', () => {
    it('shows run button', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByText('Run Capability Probes')).toBeInTheDocument();
      });
    });

    it('sends POST request with configuration when clicked', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('claude-3-opus');
      });

      fireEvent.click(screen.getByText('Run Capability Probes'));

      await waitFor(() => {
        const postCall = mockFetch.mock.calls.find(
          (call: [string, RequestInit?]) =>
            call[0].includes('/api/probes/run') && call[1]?.method === 'POST',
        );
        expect(postCall).toBeDefined();

        const body = JSON.parse(postCall![1]!.body as string);
        expect(body.agent_name).toBe('claude-3-opus');
        expect(body.probe_types).toContain('contradiction');
        expect(body.probe_types).toContain('hallucination');
      });
    });

    it('shows loading state during probe', async () => {
      mockFetch.mockImplementation((url: string, _options?: RequestInit) => {
        if (url.includes('/api/leaderboard')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: mockAgents }) });
        }
        if (url.includes('/api/probes/run')) {
          return new Promise(() => {}); // Never resolves
        }
        return Promise.resolve({ ok: false });
      });

      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('claude-3-opus');
      });

      fireEvent.click(screen.getByText('Run Capability Probes'));

      await waitFor(() => {
        expect(screen.getByText('Running Probes...')).toBeInTheDocument();
      });
    });

    it('disables button when no agent selected', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/leaderboard')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
        }
        return Promise.resolve({ ok: false });
      });

      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanelWithoutSelection();

      await waitFor(() => {
        expect(screen.getByText('Run Capability Probes')).toBeDisabled();
      });
    });
  });

  describe('Results Display', () => {
    it('displays probe summary', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('claude-3-opus');
      });

      fireEvent.click(screen.getByText('Run Capability Probes'));

      await waitFor(() => {
        expect(screen.getByText('6')).toBeInTheDocument(); // Total Probes
        expect(screen.getByText('5')).toBeInTheDocument(); // Passed
        expect(screen.getByText('1')).toBeInTheDocument(); // Failed
        expect(screen.getByText('83%')).toBeInTheDocument(); // Pass Rate
      });
    });

    it('displays results by type', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('claude-3-opus');
      });

      fireEvent.click(screen.getByText('Run Capability Probes'));

      await waitFor(() => {
        expect(screen.getByText('2/3 passed')).toBeInTheDocument(); // Contradiction
        expect(screen.getByText('3/3 passed')).toBeInTheDocument(); // Hallucination
      });
    });

    it('shows individual probe descriptions', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('claude-3-opus');
      });

      fireEvent.click(screen.getByText('Run Capability Probes'));

      await waitFor(() => {
        expect(screen.getByText(/Consistent position on AI safety/)).toBeInTheDocument();
        expect(screen.getByText(/Conflicting views on regulation/)).toBeInTheDocument();
      });
    });

    it('shows report ID', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('claude-3-opus');
      });

      fireEvent.click(screen.getByText('Run Capability Probes'));

      await waitFor(() => {
        expect(screen.getByText(/Report ID: probe-report-001/)).toBeInTheDocument();
      });
    });

    it('shows pass rate in collapsed view after run', async () => {
      setupSuccessfulFetch();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('claude-3-opus');
      });

      fireEvent.click(screen.getByText('Run Capability Probes'));

      await waitFor(() => {
        expect(screen.getByText('83%')).toBeInTheDocument();
      });

      // Collapse
      fireEvent.click(screen.getByText('[COLLAPSE]'));

      // Should show pass rate in collapsed header
      expect(screen.getByText(/83% pass/)).toBeInTheDocument();
    });
  });

  describe('Error Handling', () => {
    it('shows error on probe failure', async () => {
      mockFetch.mockImplementation((url: string, _options?: RequestInit) => {
        if (url.includes('/api/leaderboard')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: mockAgents }) });
        }
        if (url.includes('/api/probes/run')) {
          return Promise.resolve({
            ok: false,
            statusText: 'Internal Server Error',
            json: () => Promise.resolve({ error: 'Agent unavailable' }),
          });
        }
        return Promise.resolve({ ok: false });
      });

      render(<CapabilityProbePanel apiBase="http://localhost:8080" />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('claude-3-opus');
      });

      fireEvent.click(screen.getByText('Run Capability Probes'));

      await waitFor(() => {
        expect(screen.getByText('Agent unavailable')).toBeInTheDocument();
      });
    });
  });

  describe('Callback', () => {
    it('calls onComplete with report data', async () => {
      setupSuccessfulFetch();
      const onComplete = jest.fn();
      render(<CapabilityProbePanel apiBase="http://localhost:8080" onComplete={onComplete} />);

      await expandPanel();

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('claude-3-opus');
      });

      fireEvent.click(screen.getByText('Run Capability Probes'));

      await waitFor(() => {
        expect(onComplete).toHaveBeenCalledWith(mockProbeReport);
      });
    });
  });
});
