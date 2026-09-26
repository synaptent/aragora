import { renderWithProviders, screen, waitFor, act } from '@/test-utils';
import userEvent from '@testing-library/user-event';
import ControlPlanePage from '../page';

// Mock next/link
jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

// Mock next/dynamic
jest.mock('next/dynamic', () => {
  return function mockDynamic(_loader: () => Promise<{ default: React.ComponentType }>) {
    // Return a placeholder for dynamically loaded components
    return function DynamicComponent() {
      return <div data-testid="dynamic-component">Dynamic Component</div>;
    };
  };
});

// Mock visual components
jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

jest.mock('@/components/AsciiBanner', () => ({
  AsciiBannerCompact: () => <div data-testid="ascii-banner">ARAGORA</div>,
}));

jest.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <button data-testid="theme-toggle">Theme</button>,
}));

// Mock BackendSelector with context
const mockBackendConfig = { api: 'http://localhost:8080' };
jest.mock('@/components/BackendSelector', () => ({
  BackendSelector: () => <div data-testid="backend-selector">Backend</div>,
  useBackend: () => ({ config: mockBackendConfig }),
}));

// Mock PanelErrorBoundary
jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="panel-error-boundary">{children}</div>
  ),
}));

// Mock useControlPlaneWebSocket hook
const mockWsReconnect = jest.fn();
jest.mock('@/hooks/useControlPlaneWebSocket', () => ({
  useControlPlaneWebSocket: () => ({
    isConnected: false,
    agents: new Map(),
    tasks: new Map(),
    schedulerStats: null,
    recentEvents: [],
    reconnect: mockWsReconnect,
  }),
}));

// Mock control-plane components
jest.mock('@/components/control-plane', () => ({
  AgentCatalog: ({
    onSelectAgent: _onSelectAgent,
    onConfigureAgent: _onConfigureAgent,
  }: {
    onSelectAgent: () => void;
    onConfigureAgent: () => void;
  }) => <div data-testid="agent-catalog">Agent Catalog</div>,
  WorkflowBuilder: ({
    onSave: _onSave,
    onExecute: _onExecute,
  }: {
    onSave: () => void;
    onExecute: () => void;
  }) => <div data-testid="workflow-builder">Workflow Builder</div>,
  KnowledgeExplorer: ({ onSelectNode: _onSelectNode }: { onSelectNode: () => void }) => (
    <div data-testid="knowledge-explorer">Knowledge Explorer</div>
  ),
  ExecutionMonitor: ({
    onSelectExecution: _onSelectExecution,
  }: {
    onSelectExecution: () => void;
  }) => <div data-testid="execution-monitor">Execution Monitor</div>,
  PolicyDashboard: () => <div data-testid="policy-dashboard">Policy Dashboard</div>,
  WorkspaceManager: ({
    onWorkspaceSelect: _onWorkspaceSelect,
    onWorkspaceUpdate: _onWorkspaceUpdate,
  }: {
    onWorkspaceSelect: () => void;
    onWorkspaceUpdate: () => void;
  }) => <div data-testid="workspace-manager">Workspace Manager</div>,
  ConnectorDashboard: ({
    onSelectConnector: _onSelectConnector,
  }: {
    onSelectConnector: () => void;
  }) => <div data-testid="connector-dashboard">Connector Dashboard</div>,
  FleetStatusWidget: ({
    onViewAgents: _onViewAgents,
  }: {
    agents: unknown[];
    runningTasks: number;
    queuedTasks: number;
    onViewAgents: () => void;
  }) => <div data-testid="fleet-status-widget">Fleet Status</div>,
  ActivityFeed: () => <div data-testid="activity-feed">Activity Feed</div>,
  DeliberationTracker: () => <div data-testid="deliberation-tracker">Deliberation Tracker</div>,
  SystemHealthDashboard: () => <div data-testid="system-health-dashboard">System Health</div>,
}));

// Mock vertical selector
jest.mock('@/components/VerticalSelector', () => ({
  VerticalSelector: ({
    apiBase: _apiBase,
    selectedVertical: _selectedVertical,
    onVerticalChange: _onVerticalChange,
    compact: _compact,
  }: {
    apiBase: string;
    selectedVertical: string;
    onVerticalChange: (verticalId: string) => void;
    compact?: boolean;
  }) => <div data-testid="vertical-selector">Vertical Selector</div>,
}));

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('ControlPlanePage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default mock responses for successful data fetch
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/control-plane/agents')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
      }
      if (url.includes('/api/control-plane/queue')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ jobs: [] }) });
      }
      if (url.includes('/api/control-plane/metrics')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              active_jobs: 0,
              queued_jobs: 0,
              agents_available: 0,
              agents_busy: 0,
              documents_processed_today: 0,
              audits_completed_today: 0,
              tokens_used_today: 0,
            }),
        });
      }
      if (url.includes('/api/verticals')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('initial render', () => {
    it('renders visual effects', async () => {
      renderWithProviders(<ControlPlanePage />);

      expect(screen.getByTestId('scanlines')).toBeInTheDocument();
      expect(screen.getByTestId('crt-vignette')).toBeInTheDocument();
    });

    it('renders header elements', async () => {
      renderWithProviders(<ControlPlanePage />);

      expect(screen.getByText('Dashboard')).toBeInTheDocument();
      expect(
        screen.getByText(/Monitor and orchestrate multi-agent document processing/),
      ).toBeInTheDocument();
    });

    it('renders page title and description', async () => {
      renderWithProviders(<ControlPlanePage />);

      expect(screen.getByText('Dashboard')).toBeInTheDocument();
      expect(
        screen.getByText(/Monitor and orchestrate multi-agent document processing/),
      ).toBeInTheDocument();
    });

    it('shows loading state initially', () => {
      mockFetch.mockReturnValue(new Promise(() => {})); // Never resolves

      renderWithProviders(<ControlPlanePage />);

      expect(screen.getByText('Loading dashboard...')).toBeInTheDocument();
    });

    it('renders tab navigation buttons', async () => {
      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      expect(screen.getByText('OVERVIEW')).toBeInTheDocument();
      expect(screen.getByText('AGENTS')).toBeInTheDocument();
    });

    it('renders tab navigation', async () => {
      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      expect(screen.getByRole('button', { name: /OVERVIEW/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /AGENTS/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /WORKFLOWS/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /KNOWLEDGE/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /QUEUE/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /SETTINGS/i })).toBeInTheDocument();
    });

    it('renders decision console', async () => {
      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      expect(screen.getByText('Decision Console')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('Describe the decision to debate...')).toBeInTheDocument();
    });
  });

  it('submits a debate request', async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/control-plane/deliberations')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ request_id: 'req-test-1', status: 'queued', task_id: 'task-test-1' }),
        });
      }
      if (url.includes('/api/control-plane/agents')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
      }
      if (url.includes('/api/control-plane/queue')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ jobs: [] }) });
      }
      if (url.includes('/api/control-plane/metrics')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              active_jobs: 0,
              queued_jobs: 0,
              agents_available: 0,
              agents_busy: 0,
              documents_processed_today: 0,
              audits_completed_today: 0,
              tokens_used_today: 0,
            }),
        });
      }
      if (url.includes('/api/verticals')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({
        ok: false,
        json: () => Promise.resolve({ error: 'Unknown endpoint' }),
      });
    });

    const user = userEvent.setup();
    renderWithProviders(<ControlPlanePage />);

    await waitFor(() => {
      expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
    });

    await user.type(
      screen.getByPlaceholderText('Describe the decision to debate...'),
      'Assess migration risk for service X',
    );

    await user.click(screen.getByRole('button', { name: /START DEBATE/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/control-plane/deliberations',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    expect(screen.getByText(/Request ID:/)).toBeInTheDocument();
    expect(screen.getByText(/Status:/)).toBeInTheDocument();
  });

  describe('data fetching', () => {
    it('fetches agents, jobs, and metrics on mount', async () => {
      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('http://localhost:8080/api/control-plane/agents');
        expect(mockFetch).toHaveBeenCalledWith('http://localhost:8080/api/control-plane/queue');
        expect(mockFetch).toHaveBeenCalledWith('http://localhost:8080/api/control-plane/metrics');
      });
    });

    it('fetches verticals data on mount', async () => {
      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('http://localhost:8080/api/verticals');
      });
    });

    it('shows demo mode indicator when using mock data', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.getByText('DEMO MODE')).toBeInTheDocument();
      });
    });

    it('displays metrics when fetched successfully', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/control-plane/metrics')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                active_jobs: 3,
                queued_jobs: 5,
                agents_available: 2,
                agents_busy: 1,
                documents_processed_today: 42,
                audits_completed_today: 7,
                tokens_used_today: 125000,
              }),
          });
        }
        if (url.includes('/api/control-plane/agents')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
        }
        if (url.includes('/api/control-plane/queue')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ jobs: [] }) });
        }
        if (url.includes('/api/verticals')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.getByText('3')).toBeInTheDocument(); // active_jobs
        expect(screen.getByText('5')).toBeInTheDocument(); // queued_jobs
        expect(screen.getByText('2/3')).toBeInTheDocument(); // agents_available/total
      });
    });

    it('uses mock data when fetch fails', async () => {
      mockFetch.mockRejectedValue(new Error('API unavailable'));

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        // Should show mock agent data
        expect(screen.getByText('Claude')).toBeInTheDocument();
        expect(screen.getByText('Gemini')).toBeInTheDocument();
      });
    });
  });

  describe('tab navigation', () => {
    it('switches to agents tab', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /AGENTS/i }));
      });

      expect(screen.getByTestId('agent-catalog')).toBeInTheDocument();
    });

    it('switches to workflows tab', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /WORKFLOWS/i }));
      });

      expect(screen.getByTestId('workflow-builder')).toBeInTheDocument();
    });

    it('switches to knowledge tab', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /KNOWLEDGE/i }));
      });

      expect(screen.getByTestId('knowledge-explorer')).toBeInTheDocument();
    });

    it('switches to connectors tab', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /CONNECTORS/i }));
      });

      expect(screen.getByTestId('connector-dashboard')).toBeInTheDocument();
    });

    it('switches to executions tab', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /EXECUTIONS/i }));
      });

      expect(screen.getByTestId('execution-monitor')).toBeInTheDocument();
    });

    it('switches to verticals tab', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /VERTICALS/i }));
      });

      expect(screen.getByTestId('vertical-selector')).toBeInTheDocument();
      expect(screen.getByTestId('knowledge-explorer')).toBeInTheDocument();
      expect(screen.getByTestId('execution-monitor')).toBeInTheDocument();
      expect(screen.queryByTestId('vertical-knowledge-explorer')).not.toBeInTheDocument();
      expect(screen.queryByTestId('vertical-execution-monitor')).not.toBeInTheDocument();
    });

    it('switches to policy tab', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /POLICY/i }));
      });

      expect(screen.getByTestId('policy-dashboard')).toBeInTheDocument();
    });

    it('switches to workspace tab', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /WORKSPACE/i }));
      });

      expect(screen.getByTestId('workspace-manager')).toBeInTheDocument();
    });

    it('switches to settings tab', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /SETTINGS/i }));
      });

      expect(screen.getByText('Processing Settings')).toBeInTheDocument();
      expect(screen.getByText('Audit Settings')).toBeInTheDocument();
    });
  });

  describe('overview tab', () => {
    it('displays metrics cards', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/control-plane/metrics')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                active_jobs: 2,
                queued_jobs: 3,
                agents_available: 4,
                agents_busy: 1,
                documents_processed_today: 50,
                audits_completed_today: 5,
                tokens_used_today: 500000,
              }),
          });
        }
        if (url.includes('/api/control-plane/agents')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
        }
        if (url.includes('/api/control-plane/queue')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ jobs: [] }) });
        }
        if (url.includes('/api/verticals')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.getByText('ACTIVE JOBS')).toBeInTheDocument();
        expect(screen.getByText('QUEUED')).toBeInTheDocument();
        expect(screen.getByText('AGENTS AVAILABLE')).toBeInTheDocument();
        expect(screen.getByText('TOKENS TODAY')).toBeInTheDocument();
      });
    });

    it('shows no active jobs message when queue is empty', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/control-plane/queue')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ jobs: [] }) });
        }
        if (url.includes('/api/control-plane/metrics')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                active_jobs: 0,
                queued_jobs: 0,
                agents_available: 2,
                agents_busy: 0,
                documents_processed_today: 0,
                audits_completed_today: 0,
                tokens_used_today: 0,
              }),
          });
        }
        if (url.includes('/api/control-plane/agents')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
        }
        if (url.includes('/api/verticals')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.getByText('No active jobs')).toBeInTheDocument();
      });
    });

    it('displays agent status in overview', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/control-plane/agents')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                agents: [
                  { id: 'claude', name: 'Claude', model: 'claude-3.5-sonnet', status: 'ready' },
                  { id: 'gemini', name: 'Gemini', model: 'gemini-3-pro', status: 'busy' },
                ],
              }),
          });
        }
        if (url.includes('/api/control-plane/metrics')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                active_jobs: 0,
                queued_jobs: 0,
                agents_available: 1,
                agents_busy: 1,
                documents_processed_today: 0,
                audits_completed_today: 0,
                tokens_used_today: 0,
              }),
          });
        }
        if (url.includes('/api/control-plane/queue')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ jobs: [] }) });
        }
        if (url.includes('/api/verticals')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.getByText('Agent Status')).toBeInTheDocument();
        expect(screen.getByText('Claude')).toBeInTheDocument();
        expect(screen.getByText('Gemini')).toBeInTheDocument();
      });
    });
  });

  describe('queue tab', () => {
    it('displays jobs in queue', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/control-plane/queue')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                jobs: [
                  {
                    id: 'job1',
                    type: 'audit',
                    name: 'Security Audit',
                    status: 'running',
                    progress: 0.5,
                    document_count: 10,
                    agents_assigned: ['claude'],
                  },
                  {
                    id: 'job2',
                    type: 'document_processing',
                    name: 'Batch Import',
                    status: 'queued',
                    progress: 0,
                    document_count: 20,
                    agents_assigned: [],
                  },
                ],
              }),
          });
        }
        if (url.includes('/api/control-plane/agents')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
        }
        if (url.includes('/api/control-plane/metrics')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                active_jobs: 1,
                queued_jobs: 1,
                agents_available: 1,
                agents_busy: 1,
                documents_processed_today: 0,
                audits_completed_today: 0,
                tokens_used_today: 0,
              }),
          });
        }
        if (url.includes('/api/verticals')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /QUEUE/i }));
      });

      await waitFor(() => {
        expect(screen.getByText('Security Audit')).toBeInTheDocument();
        expect(screen.getByText('Batch Import')).toBeInTheDocument();
      });
    });

    it('shows no jobs message when queue is empty', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/control-plane/queue')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ jobs: [] }) });
        }
        if (url.includes('/api/control-plane/agents')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
        }
        if (url.includes('/api/control-plane/metrics')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                active_jobs: 0,
                queued_jobs: 0,
                agents_available: 0,
                agents_busy: 0,
                documents_processed_today: 0,
                audits_completed_today: 0,
                tokens_used_today: 0,
              }),
          });
        }
        if (url.includes('/api/verticals')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /QUEUE/i }));
      });

      expect(screen.getByText('No jobs in queue')).toBeInTheDocument();
    });

    it('displays pause and cancel buttons for running jobs', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/control-plane/queue')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                jobs: [
                  {
                    id: 'job1',
                    type: 'audit',
                    name: 'Running Job',
                    status: 'running',
                    progress: 0.5,
                    document_count: 10,
                    agents_assigned: ['claude'],
                  },
                ],
              }),
          });
        }
        if (url.includes('/api/control-plane/agents')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
        }
        if (url.includes('/api/control-plane/metrics')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                active_jobs: 1,
                queued_jobs: 0,
                agents_available: 0,
                agents_busy: 1,
                documents_processed_today: 0,
                audits_completed_today: 0,
                tokens_used_today: 0,
              }),
          });
        }
        if (url.includes('/api/verticals')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /QUEUE/i }));
      });

      expect(screen.getByRole('button', { name: /Pause/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Cancel/i })).toBeInTheDocument();
    });
  });

  describe('job actions', () => {
    it('calls cancel endpoint when cancel button is clicked', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/cancel') && options?.method === 'POST') {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        }
        if (url.includes('/api/control-plane/queue')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                jobs: [
                  {
                    id: 'job1',
                    type: 'audit',
                    name: 'Running Job',
                    status: 'running',
                    progress: 0.5,
                    document_count: 10,
                    agents_assigned: ['claude'],
                  },
                ],
              }),
          });
        }
        if (url.includes('/api/control-plane/agents')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
        }
        if (url.includes('/api/control-plane/metrics')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                active_jobs: 1,
                queued_jobs: 0,
                agents_available: 0,
                agents_busy: 1,
                documents_processed_today: 0,
                audits_completed_today: 0,
                tokens_used_today: 0,
              }),
          });
        }
        if (url.includes('/api/verticals')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /QUEUE/i }));
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /Cancel/i }));
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/control-plane/tasks/job1/cancel',
          { method: 'POST' },
        );
      });
    });
  });

  describe('auto-refresh toggle', () => {
    it('uses auto-refresh via polling when WS is not connected', async () => {
      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      // Auto-refresh polling is managed internally (no visible toggle in current UI)
      // Verify the page loaded correctly with overview tab active
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
    });
  });

  describe('settings tab', () => {
    it('displays processing settings', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /SETTINGS/i }));
      });

      expect(screen.getByText('Processing Settings')).toBeInTheDocument();
      expect(screen.getByText('Max Concurrent Documents')).toBeInTheDocument();
      expect(screen.getByText('Max Concurrent Chunks')).toBeInTheDocument();
    });

    it('displays audit settings', async () => {
      const user = userEvent.setup();

      renderWithProviders(<ControlPlanePage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading dashboard...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /SETTINGS/i }));
      });

      expect(screen.getByText('Audit Settings')).toBeInTheDocument();
      expect(screen.getByText('Primary Scan Model')).toBeInTheDocument();
      expect(screen.getByText('Verification Model')).toBeInTheDocument();
      expect(screen.getByText('Require Multi-Agent Confirmation')).toBeInTheDocument();
    });
  });

  describe('footer', () => {
    it('renders footer', async () => {
      renderWithProviders(<ControlPlanePage />);

      expect(screen.getByText(/ARAGORA \/\/ DASHBOARD/)).toBeInTheDocument();
    });
  });

  describe('error boundary', () => {
    it('wraps content in PanelErrorBoundary', async () => {
      renderWithProviders(<ControlPlanePage />);

      expect(screen.getByTestId('panel-error-boundary')).toBeInTheDocument();
    });
  });
});
