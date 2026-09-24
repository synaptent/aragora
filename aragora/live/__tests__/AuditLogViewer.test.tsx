/**
 * Tests for AuditLogViewer admin component
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AuditLogViewer } from '../src/components/admin/AuditLogViewer';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock alert
const mockAlert = jest.fn();
global.alert = mockAlert;

// Mock URL methods for export
const mockCreateObjectURL = jest.fn(() => 'blob:mock-url');
const mockRevokeObjectURL = jest.fn();
URL.createObjectURL = mockCreateObjectURL;
URL.revokeObjectURL = mockRevokeObjectURL;

describe('AuditLogViewer', () => {
  const mockEvents = [
    {
      id: 'evt-001',
      timestamp: '2024-01-15T10:30:00Z',
      category: 'auth',
      action: 'login',
      actor_id: 'user-123',
      actor_type: 'user',
      outcome: 'success',
      resource_type: 'session',
      resource_id: 'sess-456',
      org_id: 'org-789',
      ip_address: '192.168.1.1',
      details: { browser: 'Chrome' },
      hash: 'abc123def456',
    },
    {
      id: 'evt-002',
      timestamp: '2024-01-15T10:35:00Z',
      category: 'data',
      action: 'create_debate',
      actor_id: 'user-123',
      actor_type: 'user',
      outcome: 'success',
      resource_type: 'debate',
      resource_id: 'debate-001',
      org_id: 'org-789',
      ip_address: '192.168.1.1',
      details: { topic: 'AI Safety' },
      hash: 'def456ghi789',
    },
    {
      id: 'evt-003',
      timestamp: '2024-01-15T10:40:00Z',
      category: 'admin',
      action: 'user_deactivate',
      actor_id: 'admin-001',
      actor_type: 'admin',
      outcome: 'failure',
      resource_type: 'user',
      resource_id: 'user-999',
      org_id: null,
      ip_address: '10.0.0.1',
      details: { reason: 'User not found' },
      hash: 'ghi789jkl012',
    },
  ];

  const mockStats = {
    total_events: 1500,
    events_by_category: { auth: 500, data: 800, admin: 100, system: 100 },
    events_by_outcome: { success: 1400, failure: 80, error: 20 },
    recent_events_24h: 150,
    integrity_verified: true,
  };

  beforeEach(() => {
    mockFetch.mockClear();
    mockAlert.mockClear();
    mockCreateObjectURL.mockClear();
    mockRevokeObjectURL.mockClear();
  });

  const setupMockFetch = (eventsResponse = mockEvents, statsResponse = mockStats) => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/audit/events')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ events: eventsResponse }),
        });
      }
      if (url.includes('/audit/stats')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(statsResponse) });
      }
      return Promise.reject(new Error('Unknown URL'));
    });
  };

  describe('Loading State', () => {
    it('shows loading indicator while fetching', () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves
      render(<AuditLogViewer />);
      expect(screen.getByText(/loading events/i)).toBeInTheDocument();
    });
  });

  describe('Error State', () => {
    it('shows error message on fetch failure', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText(/error/i)).toBeInTheDocument();
      });
    });

    it('shows retry button on error', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText(/retry/i)).toBeInTheDocument();
      });
    });
  });

  describe('Event List', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('displays all events', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('login')).toBeInTheDocument();
      });
      expect(screen.getByText('create_debate')).toBeInTheDocument();
      expect(screen.getByText('user_deactivate')).toBeInTheDocument();
    });

    it('shows event categories', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('AUTH')).toBeInTheDocument();
      });
      expect(screen.getAllByText('DATA').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('ADMIN')).toBeInTheDocument();
    });

    it('shows event outcomes', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getAllByText('SUCCESS').length).toBeGreaterThanOrEqual(1);
      });
      expect(screen.getAllByText('FAILURE').length).toBeGreaterThanOrEqual(1);
    });

    it('shows actor IDs (truncated)', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        // Multiple events have user-123 as actor
        expect(screen.getAllByText('user-123').length).toBeGreaterThanOrEqual(1);
      });
    });
  });

  describe('Stats Summary', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('displays total events in header', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText(/1,500 total events/)).toBeInTheDocument();
      });
    });

    it('displays 24h event count', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('150')).toBeInTheDocument();
      });
    });

    it('displays integrity status', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('OK')).toBeInTheDocument();
      });
    });
  });

  describe('Filters', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('filters by category', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('login')).toBeInTheDocument();
      });

      // First select is category, second is outcome
      const selects = screen.getAllByRole('combobox');
      fireEvent.change(selects[0], { target: { value: 'auth' } });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('category=auth'));
      });
    });

    it('filters by outcome', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('login')).toBeInTheDocument();
      });

      // First select is category, second is outcome
      const selects = screen.getAllByRole('combobox');
      fireEvent.change(selects[1], { target: { value: 'failure' } });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('outcome=failure'));
      });
    });

    it('filters by search query', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('login')).toBeInTheDocument();
      });

      const searchInput = screen.getByPlaceholderText(/search events/i);
      fireEvent.change(searchInput, { target: { value: 'debate' } });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('search=debate'));
      });
    });

    it('filters by date range', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('login')).toBeInTheDocument();
      });

      // Change is triggered by date input change
      const dateInputs = document.querySelectorAll('input[type="date"]');
      expect(dateInputs.length).toBe(2);
    });
  });

  describe('Pagination', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows pagination controls', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('PREV')).toBeInTheDocument();
      });
      expect(screen.getByText('NEXT')).toBeInTheDocument();
    });

    it('disables PREV button on first page', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        const prevButton = screen.getByText('PREV');
        expect(prevButton).toHaveClass('cursor-not-allowed');
      });
    });

    it('shows current range', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText(/showing 1-3/i)).toBeInTheDocument();
      });
    });
  });

  describe('Event Selection', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows detail panel when event is clicked', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('login')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('login'));

      expect(screen.getByText('EVENT DETAILS')).toBeInTheDocument();
    });

    it('shows event ID in detail panel', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('login')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('login'));

      expect(screen.getByText('evt-001')).toBeInTheDocument();
    });

    it('shows IP address in detail panel', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('login')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('login'));

      expect(screen.getByText('192.168.1.1')).toBeInTheDocument();
    });

    it('shows details JSON in detail panel', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('login')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('login'));

      expect(screen.getByText(/"browser": "Chrome"/)).toBeInTheDocument();
    });

    it('closes detail panel when close button clicked', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('login')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('login'));
      expect(screen.getByText('EVENT DETAILS')).toBeInTheDocument();

      fireEvent.click(screen.getByText('CLOSE'));
      expect(screen.queryByText('EVENT DETAILS')).not.toBeInTheDocument();
    });
  });

  describe('Export', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows export button', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('EXPORT')).toBeInTheDocument();
      });
    });

    it('shows export options on hover', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('JSON')).toBeInTheDocument();
      });
      expect(screen.getByText('CSV')).toBeInTheDocument();
      expect(screen.getByText('SOC2')).toBeInTheDocument();
    });

    it('triggers JSON export', async () => {
      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/audit/events')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: mockEvents }) });
        }
        if (url.includes('/audit/stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
        }
        if (url.includes('/audit/export') && options?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            blob: () => Promise.resolve(new Blob(['test'])),
            headers: new Headers({ 'Content-Disposition': 'attachment; filename="audit.json"' }),
          });
        }
        return Promise.reject(new Error('Unknown URL'));
      });

      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('JSON')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('JSON'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/audit/export'),
          expect.objectContaining({
            method: 'POST',
            body: expect.stringContaining('"format":"json"'),
          }),
        );
      });
    });
  });

  describe('Verify Integrity', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows verify button', async () => {
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('VERIFY')).toBeInTheDocument();
      });
    });

    it('triggers verify on click', async () => {
      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/audit/events')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: mockEvents }) });
        }
        if (url.includes('/audit/stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
        }
        if (url.includes('/audit/verify') && options?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ verified: true, total_errors: 0 }),
          });
        }
        return Promise.reject(new Error('Unknown URL'));
      });

      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('VERIFY')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('VERIFY'));

      await waitFor(() => {
        expect(mockAlert).toHaveBeenCalledWith(expect.stringContaining('verified successfully'));
      });
    });

    it('shows failure message when integrity check fails', async () => {
      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/audit/events')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: mockEvents }) });
        }
        if (url.includes('/audit/stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
        }
        if (url.includes('/audit/verify') && options?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ verified: false, total_errors: 5 }),
          });
        }
        return Promise.reject(new Error('Unknown URL'));
      });

      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText('VERIFY')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('VERIFY'));

      await waitFor(() => {
        expect(mockAlert).toHaveBeenCalledWith(expect.stringContaining('5 errors found'));
      });
    });
  });

  describe('Empty State', () => {
    it('shows empty message when no events', async () => {
      setupMockFetch([], mockStats);
      render(<AuditLogViewer />);

      await waitFor(() => {
        expect(screen.getByText(/no audit events found/i)).toBeInTheDocument();
      });
    });
  });

  describe('Custom API Base', () => {
    it('uses custom apiBase for fetch', async () => {
      setupMockFetch();
      render(<AuditLogViewer apiBase="/custom/api" />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/custom/api/audit/events'));
      });
    });
  });
});
