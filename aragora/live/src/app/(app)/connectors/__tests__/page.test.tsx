import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ConnectorsPage from '../page';
import type { Connector, SchedulerStats, SyncHistoryEntry } from '../types';

// Mock next/link
jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
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

// Mock ToastContext
const mockShowToast = jest.fn();
jest.mock('@/context/ToastContext', () => ({
  useToastContext: () => ({
    showToast: mockShowToast,
    showError: jest.fn(),
    showSuccess: jest.fn(),
    clearToasts: jest.fn(),
  }),
}));

// Mock config
jest.mock('@/config', () => ({ API_BASE_URL: 'http://localhost:8080' }));

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock window.confirm
const mockConfirm = jest.fn();
window.confirm = mockConfirm;

// Sample test data
const mockConnector: Connector = {
  id: 'github:aragora-repo',
  job_id: 'job-123',
  tenant_id: 'tenant-1',
  type: 'github',
  name: 'aragora-repo',
  status: 'connected',
  schedule: { interval_minutes: 60, enabled: true },
  last_run: new Date(Date.now() - 30 * 60 * 1000).toISOString(), // 30 min ago
  next_run: new Date(Date.now() + 30 * 60 * 1000).toISOString(), // 30 min from now
  consecutive_failures: 0,
  items_synced: 150,
};

const mockConnectorSyncing: Connector = {
  ...mockConnector,
  id: 'postgres:mydb',
  name: 'mydb',
  type: 'postgres',
  status: 'syncing',
  is_running: true,
  sync_progress: 0.5,
  current_run_id: 'run-456',
};

const mockConnectorWithError: Connector = {
  ...mockConnector,
  id: 's3:backup-bucket',
  name: 'backup-bucket',
  type: 's3',
  status: 'error',
  error_message: 'Authentication failed',
  consecutive_failures: 3,
};

const mockStats: SchedulerStats = {
  total_jobs: 5,
  running_syncs: 1,
  pending_syncs: 2,
  completed_syncs: 100,
  failed_syncs: 5,
  success_rate: 0.95,
};

const mockHistory: SyncHistoryEntry[] = [
  {
    run_id: 'run-1',
    job_id: 'github:aragora-repo',
    status: 'completed',
    started_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    completed_at: new Date(Date.now() - 59 * 60 * 1000).toISOString(),
    items_synced: 50,
    error: null,
  },
  {
    run_id: 'run-2',
    job_id: 's3:backup-bucket',
    status: 'failed',
    started_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    completed_at: new Date(Date.now() - 2 * 60 * 60 * 1000 + 30000).toISOString(),
    items_synced: 0,
    error: 'Connection timeout',
  },
];

describe('ConnectorsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockConfirm.mockReturnValue(true);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  // Helper to setup successful fetch responses
  const setupSuccessfulFetch = (
    connectors: Connector[] = [],
    stats: SchedulerStats = mockStats,
    history: SyncHistoryEntry[] = [],
  ) => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/connectors/scheduler/stats')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(stats) });
      }
      if (url.includes('/api/connectors/sync/history')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ history }) });
      }
      if (
        url.includes('/api/connectors') &&
        !url.includes('/sync') &&
        !url.includes('/scheduler')
      ) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ connectors }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
  };

  describe('initial render', () => {
    it('renders without crashing', async () => {
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('Enterprise Connectors')).toBeInTheDocument();
      });
    });

    it('renders page title and description', async () => {
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      expect(screen.getByText('Enterprise Connectors')).toBeInTheDocument();
      expect(screen.getByText('Connect and sync data from external sources')).toBeInTheDocument();
    });

    it('renders Add Connector button', async () => {
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      // Get the header button specifically (with the + icon)
      const addButtons = screen.getAllByRole('button', { name: /Add Connector/i });
      expect(addButtons.length).toBeGreaterThan(0);
    });

    it('shows loading state initially', () => {
      mockFetch.mockReturnValue(new Promise(() => {})); // Never resolves

      render(<ConnectorsPage />);

      expect(screen.getByText('Loading connectors...')).toBeInTheDocument();
    });

    it('renders Active Connectors section', async () => {
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('Active Connectors')).toBeInTheDocument();
      });
    });

    it('renders connectors with missing schedules using safe defaults', async () => {
      setupSuccessfulFetch([
        { ...mockConnector, schedule: undefined as unknown as Connector['schedule'] },
      ]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('Every 60m')).toBeInTheDocument();
      });
    });

    it('renders Recent Syncs section', async () => {
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('Recent Syncs')).toBeInTheDocument();
      });
    });
  });

  describe('stats display', () => {
    it('displays scheduler stats when available', async () => {
      setupSuccessfulFetch([mockConnector], mockStats);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('Total Connectors')).toBeInTheDocument();
      });

      // Check stats values separately to avoid timing issues
      await waitFor(() => {
        expect(screen.getByText('Running Syncs')).toBeInTheDocument();
        expect(screen.getByText('Completed')).toBeInTheDocument();
        expect(screen.getByText('Failed')).toBeInTheDocument();
        expect(screen.getByText('Success Rate')).toBeInTheDocument();
      });
    });
  });

  describe('connector list display', () => {
    it('displays connectors when fetched successfully', async () => {
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('aragora-repo')).toBeInTheDocument();
      });
    });

    it('displays multiple connectors', async () => {
      setupSuccessfulFetch([mockConnector, mockConnectorSyncing, mockConnectorWithError]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('aragora-repo')).toBeInTheDocument();
        expect(screen.getByText('mydb')).toBeInTheDocument();
        expect(screen.getByText('backup-bucket')).toBeInTheDocument();
      });
    });

    it('shows empty state when no connectors', async () => {
      setupSuccessfulFetch([]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('No connectors configured')).toBeInTheDocument();
        expect(
          screen.getByText('Add your first connector to start syncing data'),
        ).toBeInTheDocument();
      });
    });

    it('displays connector type icon', async () => {
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        // GitHub icon
        expect(screen.getByText('github'.toUpperCase(), { exact: false })).toBeInTheDocument();
      });
    });

    it('displays connector schedule information', async () => {
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('Schedule:')).toBeInTheDocument();
        expect(screen.getByText(/Every 60m/)).toBeInTheDocument();
        expect(screen.getByText('ENABLED')).toBeInTheDocument();
      });
    });

    it('displays items synced count', async () => {
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('Items:')).toBeInTheDocument();
        expect(screen.getByText('150')).toBeInTheDocument();
      });
    });
  });

  describe('syncing state display', () => {
    it('displays SYNCING badge for running connectors', async () => {
      setupSuccessfulFetch([mockConnectorSyncing]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText(/SYNCING/)).toBeInTheDocument();
      });
    });

    it('displays sync progress percentage', async () => {
      setupSuccessfulFetch([mockConnectorSyncing]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText(/50%/)).toBeInTheDocument();
      });
    });

    it('displays CANCEL SYNC button for running connectors', async () => {
      setupSuccessfulFetch([mockConnectorSyncing]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'CANCEL SYNC' })).toBeInTheDocument();
      });
    });
  });

  describe('error state display', () => {
    it('displays ERROR badge for connectors with errors', async () => {
      setupSuccessfulFetch([mockConnectorWithError]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('ERROR')).toBeInTheDocument();
      });
    });

    it('displays failure count badge', async () => {
      const connectorWithFailures: Connector = { ...mockConnector, consecutive_failures: 2 };
      setupSuccessfulFetch([connectorWithFailures]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('2 FAILURES')).toBeInTheDocument();
      });
    });
  });

  describe('connector actions', () => {
    it('displays SYNC NOW, EDIT, and DELETE buttons', async () => {
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'SYNC NOW' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'EDIT' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'DELETE' })).toBeInTheDocument();
      });
    });

    it('triggers sync when SYNC NOW is clicked', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'SYNC NOW' })).toBeInTheDocument();
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ run_id: 'new-run' }),
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'SYNC NOW' }));
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/connectors/github:aragora-repo/sync',
          expect.objectContaining({ method: 'POST' }),
        );
      });
    });

    it('shows confirmation dialog and deletes connector', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'DELETE' })).toBeInTheDocument();
      });

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'DELETE' }));
      });

      expect(mockConfirm).toHaveBeenCalledWith('Are you sure you want to delete this connector?');
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/connectors/github:aragora-repo',
          expect.objectContaining({ method: 'DELETE' }),
        );
      });
    });

    it('does not delete when confirmation is cancelled', async () => {
      const user = userEvent.setup();
      mockConfirm.mockReturnValue(false);
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'DELETE' })).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'DELETE' }));
      });

      expect(mockConfirm).toHaveBeenCalled();
      // Should not have made the DELETE call
      expect(mockFetch).not.toHaveBeenCalledWith(
        expect.stringContaining('DELETE'),
        expect.any(Object),
      );
    });
  });

  describe('sync history display', () => {
    it('displays sync history entries', async () => {
      setupSuccessfulFetch([mockConnector], mockStats, mockHistory);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('COMPLETED')).toBeInTheDocument();
        expect(screen.getByText('FAILED')).toBeInTheDocument();
        expect(screen.getByText('50 items')).toBeInTheDocument();
      });
    });

    it('displays error message in failed sync entry', async () => {
      setupSuccessfulFetch([mockConnector], mockStats, mockHistory);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('Connection timeout')).toBeInTheDocument();
      });
    });

    it('shows empty state when no sync history', async () => {
      setupSuccessfulFetch([mockConnector], mockStats, []);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByText('No sync history yet')).toBeInTheDocument();
      });
    });
  });

  describe('Add Connector modal', () => {
    it('opens Add Connector modal when header button is clicked', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]); // Use existing connector so empty state doesn't show

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading connectors...')).not.toBeInTheDocument();
      });

      // Get the first Add Connector button (header button)
      const addButtons = screen.getAllByRole('button', { name: /Add Connector/i });

      await act(async () => {
        await user.click(addButtons[0]);
      });

      await waitFor(() => {
        expect(screen.getByText('Connector Type')).toBeInTheDocument();
      });
    });

    it('displays connector type options in modal', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading connectors...')).not.toBeInTheDocument();
      });

      const addButtons = screen.getAllByRole('button', { name: /Add Connector/i });

      await act(async () => {
        await user.click(addButtons[0]);
      });

      await waitFor(() => {
        // Check for connector types in modal - use getAllByText since github appears both in card and modal
        const githubElements = screen.getAllByText('github');
        expect(githubElements.length).toBeGreaterThanOrEqual(2); // One in card, one in modal
        expect(screen.getAllByText('s3').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('postgres').length).toBeGreaterThanOrEqual(1);
      });
    });

    it('closes modal when Cancel is clicked', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading connectors...')).not.toBeInTheDocument();
      });

      const addButtons = screen.getAllByRole('button', { name: /Add Connector/i });

      await act(async () => {
        await user.click(addButtons[0]);
      });

      await waitFor(() => {
        expect(screen.getByText('Connector Type')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Cancel' }));
      });

      await waitFor(() => {
        expect(screen.queryByText('Connector Type')).not.toBeInTheDocument();
      });
    });

    it('shows config fields for selected connector type', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading connectors...')).not.toBeInTheDocument();
      });

      const addButtons = screen.getAllByRole('button', { name: /Add Connector/i });

      await act(async () => {
        await user.click(addButtons[0]);
      });

      await waitFor(() => {
        // GitHub is selected by default, check for its fields
        expect(screen.getByPlaceholderText('Organization/User')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Repository name')).toBeInTheDocument();
      });
    });
  });

  describe('Edit Connector modal', () => {
    it('opens Edit Connector modal when EDIT is clicked', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'EDIT' })).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'EDIT' }));
      });

      expect(screen.getByText('Edit Connector')).toBeInTheDocument();
      expect(screen.getByText('Schedule Type')).toBeInTheDocument();
    });

    it('displays schedule options in edit modal', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'EDIT' })).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'EDIT' }));
      });

      expect(screen.getByRole('button', { name: 'Interval' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Cron Expression' })).toBeInTheDocument();
      expect(screen.getByText('Enable automatic sync')).toBeInTheDocument();
    });

    it('closes edit modal when Cancel is clicked', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'EDIT' })).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'EDIT' }));
      });

      expect(screen.getByText('Edit Connector')).toBeInTheDocument();

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Cancel' }));
      });

      await waitFor(() => {
        expect(screen.queryByText('Edit Connector')).not.toBeInTheDocument();
      });
    });

    it('saves changes when Save Changes is clicked', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'EDIT' })).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'EDIT' }));
      });

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Save Changes' }));
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/connectors/github:aragora-repo',
          expect.objectContaining({ method: 'PATCH' }),
        );
      });
    });
  });

  describe('error handling', () => {
    it('shows toast error when fetch fails', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(mockShowToast).toHaveBeenCalledWith('Failed to load connector data', 'error');
      });
    });

    it('shows toast error when sync fails', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'SYNC NOW' })).toBeInTheDocument();
      });

      mockFetch.mockRejectedValueOnce(new Error('Sync failed'));

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'SYNC NOW' }));
      });

      await waitFor(() => {
        expect(mockShowToast).toHaveBeenCalledWith('Failed to trigger sync', 'error');
      });
    });

    it('shows toast error when delete fails', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'DELETE' })).toBeInTheDocument();
      });

      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'DELETE' }));
      });

      await waitFor(() => {
        expect(mockShowToast).toHaveBeenCalledWith('Failed to delete connector', 'error');
      });
    });

    it('shows toast error when add connector fails', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading connectors...')).not.toBeInTheDocument();
      });

      const addButtons = screen.getAllByRole('button', { name: /Add Connector/i });

      await act(async () => {
        await user.click(addButtons[0]);
      });

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Organization/User')).toBeInTheDocument();
      });

      // Fill in required fields for github
      const ownerInput = screen.getByPlaceholderText('Organization/User');
      const repoInput = screen.getByPlaceholderText('Repository name');

      await act(async () => {
        await user.type(ownerInput, 'test-org');
        await user.type(repoInput, 'test-repo');
      });

      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      // Click the Add Connector button in the modal
      const modalAddButton = screen.getByRole('button', { name: 'Add Connector' });
      await act(async () => {
        await user.click(modalAddButton);
      });

      await waitFor(() => {
        expect(mockShowToast).toHaveBeenCalledWith('Failed to add connector', 'error');
      });
    });

    it('shows toast error when update connector fails', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'EDIT' })).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'EDIT' }));
      });

      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Save Changes' }));
      });

      await waitFor(() => {
        expect(mockShowToast).toHaveBeenCalledWith('Failed to update connector', 'error');
      });
    });
  });

  describe('data fetching', () => {
    it('fetches connectors, stats, and history on mount', async () => {
      setupSuccessfulFetch([mockConnector], mockStats, mockHistory);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('http://localhost:8080/api/connectors');
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/connectors/scheduler/stats',
        );
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/connectors/sync/history?limit=10',
        );
      });
    });
  });

  describe('success toasts', () => {
    it('shows success toast when sync starts', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'SYNC NOW' })).toBeInTheDocument();
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ run_id: 'new-run' }),
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'SYNC NOW' }));
      });

      await waitFor(() => {
        expect(mockShowToast).toHaveBeenCalledWith('Sync started', 'success');
      });
    });

    it('shows success toast when connector is deleted', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'DELETE' })).toBeInTheDocument();
      });

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'DELETE' }));
      });

      await waitFor(() => {
        expect(mockShowToast).toHaveBeenCalledWith('Connector deleted', 'success');
      });
    });

    it('shows success toast when connector is updated', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'EDIT' })).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'EDIT' }));
      });

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Save Changes' }));
      });

      await waitFor(() => {
        expect(mockShowToast).toHaveBeenCalledWith('Connector updated successfully', 'success');
      });
    });

    it('shows success toast when connector is added', async () => {
      const user = userEvent.setup();
      setupSuccessfulFetch([mockConnector]);

      render(<ConnectorsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading connectors...')).not.toBeInTheDocument();
      });

      const addButtons = screen.getAllByRole('button', { name: /Add Connector/i });

      await act(async () => {
        await user.click(addButtons[0]);
      });

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Organization/User')).toBeInTheDocument();
      });

      const ownerInput = screen.getByPlaceholderText('Organization/User');
      const repoInput = screen.getByPlaceholderText('Repository name');

      await act(async () => {
        await user.type(ownerInput, 'test-org');
        await user.type(repoInput, 'test-repo');
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ id: 'github:test-repo' }),
      });

      const modalAddButton = screen.getByRole('button', { name: 'Add Connector' });
      await act(async () => {
        await user.click(modalAddButton);
      });

      await waitFor(() => {
        expect(mockShowToast).toHaveBeenCalledWith('Connector added successfully', 'success');
      });
    });
  });
});
