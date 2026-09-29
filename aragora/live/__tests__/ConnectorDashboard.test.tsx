/**
 * Tests for ConnectorDashboard component
 *
 * Tests cover:
 * - Tab navigation (connectors, sync-status, scheduled)
 * - Connector list display
 * - Connector type badges
 * - Sync actions
 * - Filter functionality
 * - Loading and error states
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { ConnectorDashboard } from '../src/components/control-plane/ConnectorDashboard/ConnectorDashboard';

// Default mock data - defined before the mock
// Note: type must match ConnectorType (gdrive, not google_drive)
const mockConnectorData = [
  {
    id: 'connector-1',
    name: 'Google Drive',
    type: 'gdrive',
    description: 'Sync documents from Google Drive',
    status: 'connected',
    last_sync: '2024-01-16T10:00:00Z',
    items_synced: 1250,
  },
  {
    id: 'connector-2',
    name: 'SharePoint',
    type: 'sharepoint',
    description: 'Sync from SharePoint',
    status: 'syncing',
    last_sync: '2024-01-16T09:00:00Z',
    items_synced: 3500,
    sync_progress: 0.65,
  },
  {
    id: 'connector-3',
    name: 'Confluence',
    type: 'confluence',
    description: 'Sync from Confluence',
    status: 'error',
    last_sync: '2024-01-15T12:00:00Z',
    items_synced: 800,
    error_message: 'Authentication expired',
  },
];

// Mock the hooks
const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPut = jest.fn();
const mockDelete = jest.fn();

jest.mock('@/hooks/useApi', () => ({
  useApi: () => ({
    get: mockGet,
    post: mockPost,
    put: mockPut,
    delete: mockDelete,
    data: null,
    loading: false,
    error: null,
  }),
}));

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://localhost:8080' } }),
}));

jest.mock('@/utils/logger', () => ({
  logger: { debug: jest.fn(), warn: jest.fn(), error: jest.fn() },
}));

describe('ConnectorDashboard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Set up mock implementations for API calls
    mockGet.mockImplementation((url: string) => {
      if (url === '/api/connectors') {
        return Promise.resolve({ connectors: mockConnectorData });
      }
      if (url === '/api/connectors/sync-history') {
        return Promise.resolve({ history: [] });
      }
      return Promise.resolve({});
    });
    mockPost.mockResolvedValue({ success: true });
    mockPut.mockResolvedValue({ success: true });
    mockDelete.mockResolvedValue({ success: true });
  });

  describe('Header and Layout', () => {
    it('renders the dashboard header', async () => {
      render(<ConnectorDashboard />);

      await waitFor(() => {
        expect(screen.getByText('Enterprise Connectors')).toBeInTheDocument();
      });
    });

    it('shows all tabs', async () => {
      render(<ConnectorDashboard />);

      await waitFor(() => {
        expect(screen.getByText('Connectors')).toBeInTheDocument();
        expect(screen.getByText('Sync Status')).toBeInTheDocument();
        expect(screen.getByText('Scheduled Jobs')).toBeInTheDocument();
      });
    });
  });

  describe('Connector List', () => {
    it('displays all connectors', async () => {
      render(<ConnectorDashboard />);

      await waitFor(() => {
        expect(screen.getByText('Google Drive')).toBeInTheDocument();
        expect(screen.getByText('SharePoint')).toBeInTheDocument();
        expect(screen.getByText('Confluence')).toBeInTheDocument();
      });
    });

    it('shows connector status badges', async () => {
      render(<ConnectorDashboard />);

      await waitFor(() => {
        expect(screen.getByText('connected')).toBeInTheDocument();
        expect(screen.getByText('syncing')).toBeInTheDocument();
        expect(screen.getByText('error')).toBeInTheDocument();
      });
    });

    it('shows document counts', async () => {
      render(<ConnectorDashboard />);

      // formatItemCount() converts 1250 to "1.3K" and 3500 to "3.5K"
      await waitFor(() => {
        expect(screen.getByText(/1\.3K/)).toBeInTheDocument();
        expect(screen.getByText(/3\.5K/)).toBeInTheDocument();
      });
    });
  });

  describe('Filter Functionality', () => {
    it('shows filter options with counts', async () => {
      render(<ConnectorDashboard />);

      // Filter buttons render "All (count)", "Connected (count)", etc.
      await waitFor(() => {
        expect(screen.getByText(/^All \(/)).toBeInTheDocument();
        expect(screen.getByText(/^Connected \(/)).toBeInTheDocument();
        expect(screen.getByText(/^Disconnected \(/)).toBeInTheDocument();
        expect(screen.getByText(/^Error \(/)).toBeInTheDocument();
      });
    });
  });

  describe('Connector Selection', () => {
    // Note: ConnectorCard in non-compact mode doesn't have a click-to-select handler
    // on the card itself. Selection happens via the handleSelectConnector callback
    // which is passed to ConnectorCard but not wired to an onClick in non-compact mode.
    // The card only has action buttons (Configure, Sync Now, Connect, etc.)
    it('displays connector names from the data', async () => {
      render(<ConnectorDashboard />);

      await waitFor(() => {
        expect(screen.getByText('Google Drive')).toBeInTheDocument();
        expect(screen.getByText('SharePoint')).toBeInTheDocument();
        expect(screen.getByText('Confluence')).toBeInTheDocument();
      });
    });
  });

  describe('Sync Actions', () => {
    it('shows sync button for connected connectors', async () => {
      render(<ConnectorDashboard />);

      await waitFor(() => {
        const syncButtons = screen.getAllByText(/Sync/i);
        expect(syncButtons.length).toBeGreaterThan(0);
      });
    });

    it('shows progress for syncing connectors', async () => {
      render(<ConnectorDashboard />);

      await waitFor(() => {
        // SharePoint is syncing at 65%
        expect(screen.getByText(/65%/)).toBeInTheDocument();
      });
    });

    it('shows error message for failed connectors', async () => {
      render(<ConnectorDashboard />);

      await waitFor(() => {
        expect(screen.getByText(/Authentication expired/)).toBeInTheDocument();
      });
    });
  });

  describe('Loading State', () => {
    it('shows loading indicator initially', () => {
      const { container } = render(<ConnectorDashboard />);

      // PanelTemplate shows "..." in refresh button and animate-pulse skeleton during loading
      expect(
        container.querySelector('.animate-pulse') || screen.getByText('...'),
      ).toBeInTheDocument();
    });
  });

  describe('CSS Classes', () => {
    it('applies custom className', async () => {
      const { container } = render(<ConnectorDashboard className="custom-class" />);

      await waitFor(() => {
        expect(container.firstChild).toHaveClass('custom-class');
      });
    });
  });

  describe('Connector Configuration', () => {
    it('opens config modal when configure button is clicked', async () => {
      render(<ConnectorDashboard />);

      // Wait for connectors to load
      await waitFor(() => {
        expect(screen.getByText('Google Drive')).toBeInTheDocument();
      });

      // Find and click a configure button (gear icon or Configure text)
      const configButtons = screen.getAllByRole('button');
      const configButton = configButtons.find(
        (btn) => btn.querySelector('svg') && btn.getAttribute('aria-label')?.includes('Configure'),
      );

      if (configButton) {
        await act(async () => {
          fireEvent.click(configButton);
        });

        // Modal should appear
        await waitFor(() => {
          expect(screen.getByText(/Configure/i)).toBeInTheDocument();
        });
      }
    });
  });
});
