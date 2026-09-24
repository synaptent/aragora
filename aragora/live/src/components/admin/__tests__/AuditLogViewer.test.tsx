import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuditLogViewer } from '../AuditLogViewer';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockEvents = [
  {
    id: 'event-1',
    timestamp: '2024-01-15T10:30:00Z',
    category: 'auth',
    action: 'user.login',
    actor_id: 'user-123',
    actor_type: 'user',
    outcome: 'success',
    resource_type: 'session',
    resource_id: 'session-456',
    org_id: 'org-789',
    ip_address: '192.168.1.1',
    details: { browser: 'Chrome' },
    hash: 'abc123def456',
  },
  {
    id: 'event-2',
    timestamp: '2024-01-15T10:25:00Z',
    category: 'data',
    action: 'debate.create',
    actor_id: 'user-123',
    actor_type: 'user',
    outcome: 'success',
    resource_type: 'debate',
    resource_id: 'debate-001',
    org_id: null,
    ip_address: null,
    details: {},
    hash: 'xyz789',
  },
];

const mockStats = {
  total_events: 1500,
  events_by_category: { auth: 500, data: 800, admin: 200 },
  events_by_outcome: { success: 1400, failure: 100 },
  recent_events_24h: 75,
  integrity_verified: true,
};

describe('AuditLogViewer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default mock for events and stats
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/audit/stats')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
      }
      if (url.includes('/audit/events')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: mockEvents }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
  });

  describe('initial render', () => {
    it('shows loading state initially', () => {
      mockFetch.mockImplementation(() => new Promise(() => {}));
      render(<AuditLogViewer />);

      expect(screen.getByText('LOADING EVENTS...')).toBeInTheDocument();
    });

    it('renders header with title', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText(/AUDIT LOG VIEWER/)).toBeInTheDocument();
      });
    });

    it('renders verify and export buttons', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('VERIFY')).toBeInTheDocument();
        expect(screen.getByText('EXPORT')).toBeInTheDocument();
      });
    });
  });

  describe('events display', () => {
    it('displays audit events after loading', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('user.login')).toBeInTheDocument();
        expect(screen.getByText('debate.create')).toBeInTheDocument();
      });
    });

    it('displays event categories', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('AUTH')).toBeInTheDocument();
        expect(screen.getByText('DATA')).toBeInTheDocument();
      });
    });

    it('displays event outcomes', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        const successElements = screen.getAllByText('SUCCESS');
        expect(successElements.length).toBeGreaterThan(0);
      });
    });

    it('shows "No audit events found" when empty', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/audit/stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
        }
        if (url.includes('/audit/events')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: [] }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('No audit events found')).toBeInTheDocument();
      });
    });
  });

  describe('stats display', () => {
    it('displays total events count', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('1,500 total events')).toBeInTheDocument();
      });
    });

    it('displays 24h event count', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('75')).toBeInTheDocument();
      });
    });

    it('displays integrity status', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('OK')).toBeInTheDocument();
      });
    });

    it('shows CHECK when integrity not verified', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/audit/stats')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ ...mockStats, integrity_verified: false }),
          });
        }
        if (url.includes('/audit/events')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: mockEvents }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('CHECK')).toBeInTheDocument();
      });
    });
  });

  describe('filters', () => {
    it('renders search input', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Search events...')).toBeInTheDocument();
      });
    });

    it('renders date range inputs', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('FROM:')).toBeInTheDocument();
        expect(screen.getByText('TO:')).toBeInTheDocument();
      });
    });

    it('renders category filter', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('CATEGORY:')).toBeInTheDocument();
      });
    });

    it('renders outcome filter', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('OUTCOME:')).toBeInTheDocument();
      });
    });

    it('filters by category when changed', async () => {
      const user = userEvent.setup();
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('user.login')).toBeInTheDocument();
      });

      // Get selects and change category filter
      const selects = screen.getAllByRole('combobox');
      const categoryCombobox = selects[0]; // First select is category

      await act(async () => {
        await user.selectOptions(categoryCombobox, 'auth');
      });

      // Verify fetch was called with category param
      await waitFor(() => {
        const calls = mockFetch.mock.calls;
        const lastEventCall = calls.filter((c: string[]) => c[0].includes('/audit/events')).pop();
        expect(lastEventCall?.[0]).toContain('category=auth');
      });
    });
  });

  describe('pagination', () => {
    it('renders prev and next buttons', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('PREV')).toBeInTheDocument();
        expect(screen.getByText('NEXT')).toBeInTheDocument();
      });
    });

    it('disables prev button on first page', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        const prevButton = screen.getByText('PREV');
        expect(prevButton).toBeDisabled();
      });
    });

    it('shows pagination info', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText(/Showing 1-2/)).toBeInTheDocument();
      });
    });
  });

  describe('event detail panel', () => {
    it('opens detail panel when event is clicked', async () => {
      const user = userEvent.setup();
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('user.login')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('user.login'));
      });

      expect(screen.getByText('EVENT DETAILS')).toBeInTheDocument();
    });

    it('shows event details in panel', async () => {
      const user = userEvent.setup();
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('user.login')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('user.login'));
      });

      // Check for detail fields
      expect(screen.getByText('ACTOR ID')).toBeInTheDocument();
      expect(screen.getByText('IP ADDRESS')).toBeInTheDocument();
      expect(screen.getByText('RESOURCE TYPE')).toBeInTheDocument();
    });

    it('closes detail panel when close button clicked', async () => {
      const user = userEvent.setup();
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('user.login')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('user.login'));
      });

      expect(screen.getByText('EVENT DETAILS')).toBeInTheDocument();

      await act(async () => {
        await user.click(screen.getByText('CLOSE'));
      });

      expect(screen.queryByText('EVENT DETAILS')).not.toBeInTheDocument();
    });
  });

  describe('error handling', () => {
    it('shows error message on fetch failure', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/audit/stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
        }
        if (url.includes('/audit/events')) {
          return Promise.resolve({ ok: false, status: 500 });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText(/ERROR:/)).toBeInTheDocument();
        expect(screen.getByText(/Failed to fetch audit events/)).toBeInTheDocument();
      });
    });

    it('shows retry button on error', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/audit/stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
        }
        if (url.includes('/audit/events')) {
          return Promise.resolve({ ok: false, status: 500 });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('RETRY')).toBeInTheDocument();
      });
    });

    it('retries fetch when retry button clicked', async () => {
      let eventCallCount = 0;
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/audit/stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
        }
        if (url.includes('/audit/events')) {
          eventCallCount++;
          if (eventCallCount === 1) {
            return Promise.resolve({ ok: false, status: 500 });
          }
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: mockEvents }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      const user = userEvent.setup();
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('RETRY')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('RETRY'));
      });

      await waitFor(() => {
        expect(screen.getByText('user.login')).toBeInTheDocument();
      });
    });
  });

  describe('custom apiBase', () => {
    it('uses custom apiBase for requests', async () => {
      render(<AuditLogViewer apiBase="/custom-api" />);

      await waitFor(() => {
        const calls = mockFetch.mock.calls;
        expect(calls.some((c: string[]) => c[0].includes('/custom-api/audit/'))).toBe(true);
      });
    });
  });
});
