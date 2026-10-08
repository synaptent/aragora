import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import { ImpasseDetectionPanel, ImpasseStatusBadge } from '../ImpasseDetectionPanel';
import { BatchExplainabilityPanel } from '../BatchExplainabilityPanel';
import { GauntletHeatmap } from '../GauntletHeatmap';
import { GauntletDashboard } from '../GauntletDashboard';
import { EnterpriseMetricsCards } from '../EnterpriseMetricsCards';
import { GauntletPanel } from '../GauntletPanel';

jest.mock('next/dynamic', () => () => () => null);

const API = 'http://backend.test';
const bearer = `Bearer ${TEST_SESSION_TOKEN}`;
const mockFetch = global.fetch as jest.Mock;

const gauntletResult = {
  gauntlet_id: 'gauntlet-org-a-0001',
  input_summary: 'Org A gauntlet run',
  input_hash: 'hash-a',
  verdict: 'PASS',
  confidence: 0.9,
  robustness_score: 0.8,
  critical_count: 0,
  high_count: 0,
  medium_count: 0,
  low_count: 0,
  total_findings: 0,
  created_at: '2026-10-01T00:00:00Z',
};

beforeEach(() => {
  storeTestSession();
  mockFetch.mockImplementation(async (input: string) => {
    const url = String(input);
    if (url.includes('/api/gauntlet/results')) {
      return { ok: true, status: 200, json: async () => ({ results: [gauntletResult], total: 1 }) };
    }
    if (url.endsWith('/heatmap')) {
      return { ok: true, status: 200, json: async () => ({ cells: [], categories: [], severities: [], total_findings: 0 }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
});

afterEach(() => clearTestSession());

describe('debate analysis components send the session token', () => {
  it('ImpasseDetectionPanel loads impasse data with the token', async () => {
    render(<ImpasseDetectionPanel debateId="debate-a" apiBase={API} autoRefresh={false} />);

    await waitFor(() => expect(authHeaderOf(mockFetch, `${API}/api/debates/debate-a/impasse`)).toBe(bearer));
  });

  it('ImpasseStatusBadge checks impasse status with the token', async () => {
    render(<ImpasseStatusBadge debateId="debate-b" apiBase={API} />);

    await waitFor(() => expect(authHeaderOf(mockFetch, `${API}/api/debates/debate-b/impasse`)).toBe(bearer));
  });

  it('BatchExplainabilityPanel lists completed debates with the token', async () => {
    render(<BatchExplainabilityPanel apiBase={API} />);

    await waitFor(() =>
      expect(authHeaderOf(mockFetch, `${API}/api/debates?limit=50&status=completed`)).toBe(bearer),
    );
  });
});

describe('gauntlet and receipt components send the session token', () => {
  it('GauntletHeatmap loads the heatmap with the token', async () => {
    render(<GauntletHeatmap gauntletId="gauntlet-a" apiBase={API} />);

    await waitFor(() => expect(authHeaderOf(mockFetch, `${API}/api/gauntlet/gauntlet-a/heatmap`)).toBe(bearer));
  });

  it('GauntletDashboard loads results and the selected heatmap with the token', async () => {
    render(<GauntletDashboard apiBase={API} />);

    fireEvent.click(await screen.findByText('Org A gauntlet run'));

    await waitFor(() =>
      expect(authHeaderOf(mockFetch, `${API}/api/gauntlet/gauntlet-org-a-0001/heatmap`)).toBe(bearer),
    );
    expect(authHeaderOf(mockFetch, `${API}/api/gauntlet/results`)).toBe(bearer);
  });

  it('GauntletDashboard keeps an explicit authToken prop', async () => {
    render(<GauntletDashboard apiBase={API} authToken="prop-token" />);

    fireEvent.click(await screen.findByText('Org A gauntlet run'));

    await waitFor(() =>
      expect(authHeaderOf(mockFetch, `${API}/api/gauntlet/gauntlet-org-a-0001/heatmap`)).toBe('Bearer prop-token'),
    );
    expect(authHeaderOf(mockFetch, `${API}/api/gauntlet/results`)).toBe('Bearer prop-token');
  });

  it('EnterpriseMetricsCards loads receipts, compliance, workflow and team data with the token', async () => {
    render(<EnterpriseMetricsCards apiBase={API} />);

    await waitFor(() => expect(authHeaderOf(mockFetch, `${API}/api/gauntlet/results?limit=5`)).toBe(bearer));
    await waitFor(() => expect(authHeaderOf(mockFetch, `${API}/api/gauntlet/results?limit=50`)).toBe(bearer));
    await waitFor(() => expect(authHeaderOf(mockFetch, `${API}/api/workflows/stats`)).toBe(bearer));
    await waitFor(() => expect(authHeaderOf(mockFetch, `${API}/api/leaderboard-view?limit=5`)).toBe(bearer));
  });

  it('GauntletPanel loads results and expanded details with the token', async () => {
    render(<GauntletPanel apiBase={API} />);

    fireEvent.click(await screen.findByText('Org A gauntlet run'));

    await waitFor(() => expect(authHeaderOf(mockFetch, `${API}/api/gauntlet/gauntlet-org-a-0001`)).toBe(bearer));
    expect(authHeaderOf(mockFetch, `${API}/api/gauntlet/results`)).toBe(bearer);
  });
});
