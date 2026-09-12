/**
 * Tests for ScenarioMatrixView component
 *
 * Validates the scenario builder, matrix execution, and result views.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Import after mocks are set up
import { ScenarioMatrixView } from '@/components/scenario-matrix';

const mockMatrixResult = {
  matrix_id: 'matrix-1',
  task: 'Choose a framework for a new web app',
  scenario_count: 2,
  results: [
    {
      scenario_name: 'Baseline',
      parameters: { framework: 'React', timeline: 'short' },
      constraints: ['Ship in 8 weeks'],
      is_baseline: true,
      winner: 'claude',
      final_answer: 'React handles fast iteration and team onboarding.',
      confidence: 0.82,
      consensus_reached: true,
      rounds_used: 3,
    },
    {
      scenario_name: 'Enterprise',
      parameters: { framework: 'Angular' },
      constraints: [],
      is_baseline: false,
      winner: null,
      final_answer: 'No clear winner due to competing priorities.',
      confidence: 0.4,
      consensus_reached: false,
      rounds_used: 2,
    },
  ],
  universal_conclusions: ['Team fit outweighs hype.'],
  conditional_conclusions: [
    {
      condition: 'When compliance is strict',
      parameters: { domain: 'fintech' },
      conclusion: 'Angular policies can help.',
      confidence: 0.6,
    },
  ],
  comparison_matrix: {
    scenarios: ['Baseline', 'Enterprise'],
    consensus_rate: 0.5,
    avg_confidence: 0.61,
    avg_rounds: 2.5,
  },
};

const runMatrix = async () => {
  const taskInput = screen.getByPlaceholderText(/enter the debate topic/i);
  fireEvent.change(taskInput, { target: { value: 'Choose a framework for a new web app' } });

  const runButton = screen.getByRole('button', { name: /run scenario matrix/i });
  fireEvent.click(runButton);

  await waitFor(() => {
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/debates/matrix'),
      expect.objectContaining({ method: 'POST' }),
    );
  });
};

describe('ScenarioMatrixView', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  it('renders the header and empty state by default', () => {
    render(<ScenarioMatrixView />);

    expect(screen.getByRole('heading', { name: /scenario matrix/i })).toBeInTheDocument();
    expect(
      screen.getByText(/configure scenarios above and run the matrix to see results/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /run scenario matrix/i })).toBeDisabled();
  });

  it('allows adding and removing scenarios', () => {
    render(<ScenarioMatrixView />);

    expect(screen.getAllByPlaceholderText('Scenario name...')).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: /\+ add scenario/i }));
    expect(screen.getAllByPlaceholderText('Scenario name...')).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: /remove scenario scenario 2/i }));
    expect(screen.getAllByPlaceholderText('Scenario name...')).toHaveLength(1);
  });

  it('runs the matrix and renders results', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockMatrixResult) });

    render(<ScenarioMatrixView />);

    await runMatrix();

    const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
    expect(body.task).toBe('Choose a framework for a new web app');
    expect(body.scenarios[0]).toMatchObject({ name: 'Baseline', is_baseline: true });

    await waitFor(() => {
      expect(screen.getByText(/scenario results/i)).toBeInTheDocument();
      expect(screen.getAllByText('Baseline').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Enterprise').length).toBeGreaterThan(0);
    });

    expect(screen.getByText(/universal conclusions/i)).toBeInTheDocument();
    expect(screen.getByText(/conditional conclusions/i)).toBeInTheDocument();
    expect(screen.getByText(/comparison grid/i)).toBeInTheDocument();
  });

  it('expands scenario details in list view', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockMatrixResult) });

    render(<ScenarioMatrixView />);

    await runMatrix();

    await waitFor(() => {
      expect(screen.getAllByText('Baseline').length).toBeGreaterThan(0);
    });

    const baselineToggle = screen.getByRole('button', {
      name: /baseline\s+\(baseline\).*82% confidence/i,
    });
    fireEvent.click(baselineToggle);

    expect(
      screen.getByText(/react handles fast iteration and team onboarding/i),
    ).toBeInTheDocument();
  });

  it('filters to consensus scenarios only', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockMatrixResult) });

    render(<ScenarioMatrixView />);

    await runMatrix();

    await waitFor(() => {
      expect(screen.getByText(/scenario results/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('checkbox', { name: /consensus only/i }));

    expect(screen.getByText(/scenario results \(1\/2\)/i)).toBeInTheDocument();
  });

  it('switches to grid view and supports comparisons', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockMatrixResult) });

    render(<ScenarioMatrixView />);

    await runMatrix();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /grid/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /grid/i }));

    expect(screen.getByText(/compare them/i)).toBeInTheDocument();

    const baselineCard = screen.getByRole('gridcell', {
      name: /baseline\s+\(baseline\): consensus reached,\s+82% confidence/i,
    });
    const enterpriseCard = screen.getByRole('gridcell', {
      name: /enterprise: no consensus,\s+40% confidence/i,
    });

    fireEvent.click(baselineCard);
    fireEvent.click(enterpriseCard);

    expect(screen.getByText('SCENARIO COMPARISON')).toBeInTheDocument();
  });
});
