import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import BackupDRPage from '../page';
import { useSWRFetch } from '@/hooks/useSWRFetch';

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const mockBackendConfig = { api: 'https://api-dev.aragora.ai' };
jest.mock('@/components/BackendSelector', () => ({
  getRuntimeBackendConfig: () => ({ backend: 'development', config: mockBackendConfig }),
}));

jest.mock('@/hooks/useSWRFetch', () => ({ useSWRFetch: jest.fn() }));

const mockUseSWRFetch = useSWRFetch as jest.Mock;
const mockFetch = jest.fn();
const mockRefreshBackups = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

describe('BackupDRPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    mockUseSWRFetch.mockImplementation((endpoint: string | null) => {
      if (endpoint === '/api/v2/backups/stats') {
        return {
          data: {
            stats: {
              total_backups: 3,
              verified_backups: 3,
              failed_backups: 0,
              total_size_bytes: 1024,
              total_size_mb: 0.001,
              latest_backup: null,
              retention_policy: { keep_daily: 7, keep_weekly: 4, keep_monthly: 12, min_backups: 3 },
            },
            generated_at: '2026-03-31T10:40:00Z',
          },
          error: null,
          isLoading: false,
          mutate: jest.fn(),
        };
      }

      if (endpoint === '/api/v2/dr/status') {
        return {
          data: {
            status: 'healthy',
            readiness_score: 96,
            backup_status: {
              total_backups: 3,
              verified_backups: 3,
              failed_backups: 0,
              latest_backup: null,
              hours_since_backup: 1,
            },
            rpo_status: { target_hours: 24, compliant: true, current_hours: 1 },
            issues: [],
            recommendations: [],
            checked_at: '2026-03-31T10:40:00Z',
          },
          error: null,
          isLoading: false,
          mutate: jest.fn(),
        };
      }

      if (endpoint === '/api/v2/dr/objectives') {
        return {
          data: {
            rpo: { target_hours: 24, current_hours: 1, compliant: true, violations_last_7_days: 0 },
            rto: { target_minutes: 30, estimated_minutes: 12, compliant: true },
            backup_coverage: { total_backups: 3, backups_last_7_days: 3, latest_backup: null },
            generated_at: '2026-03-31T10:40:00Z',
          },
          error: null,
          isLoading: false,
          mutate: jest.fn(),
        };
      }

      if (endpoint?.startsWith('/api/v2/backups?limit=20&offset=')) {
        return {
          data: {
            backups: [
              {
                id: 'backup-1',
                source_path: '/tmp/source',
                backup_path: '/tmp/backup',
                backup_type: 'full',
                status: 'completed',
                created_at: '2026-03-31T10:40:00Z',
                compressed_size_bytes: 1024,
                verified: true,
                checksum: 'abc123',
                metadata: {},
              },
            ],
            pagination: { limit: 20, offset: 0, total: 1, has_more: false },
          },
          error: null,
          isLoading: false,
          mutate: mockRefreshBackups,
        };
      }

      return { data: null, error: null, isLoading: false, mutate: jest.fn() };
    });
  });

  it('posts backup creation to the selected runtime backend', async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({ ok: true } as Response);

    render(<BackupDRPage />);

    await user.click(screen.getByRole('button', { name: /\[BACKUPS\]/i }));
    await user.click(screen.getByRole('button', { name: '+ CREATE BACKUP' }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api-dev.aragora.ai/api/v2/backups',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ backup_type: 'full' }),
        }),
      );
    });

    expect(mockRefreshBackups).toHaveBeenCalled();
  });

  it('posts DR drills to the selected runtime backend', async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, duration_seconds: 1.23, steps: [] }),
    } as Response);

    render(<BackupDRPage />);

    await user.click(screen.getByRole('button', { name: /\[DISASTER RECOVERY\]/i }));
    await user.click(screen.getByRole('button', { name: 'RESTORE TEST' }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api-dev.aragora.ai/api/v2/dr/drill',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ drill_type: 'restore_test' }),
        }),
      );
    });

    expect(await screen.findByText(/Drill Result:\s*PASSED/i)).toBeInTheDocument();
  });
});
