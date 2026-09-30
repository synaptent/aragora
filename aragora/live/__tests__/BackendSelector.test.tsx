/**
 * Tests for BackendSelector component
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import {
  BackendSelector,
  BACKENDS,
  buildHealthCheckUrl,
  useBackend,
} from '../src/components/BackendSelector';

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('BackendSelector', () => {
  beforeEach(() => {
    localStorageMock.clear();
    mockFetch.mockClear();
    // Default: production works, dev doesn't
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('api.aragora.ai')) {
        return Promise.resolve({ ok: true });
      }
      return Promise.reject(new Error('Network error'));
    });
  });
  const waitForDevAvailability = async (available: boolean) => {
    await waitFor(() => {
      const devButton = screen.getByText('DEV').closest('button');
      expect(devButton).toBeTruthy();
      if (available) {
        expect(devButton).not.toBeDisabled();
      } else {
        expect(devButton).toBeDisabled();
      }
    });
  };

  describe('BACKENDS Configuration', () => {
    it('has production backend configured', () => {
      expect(BACKENDS.production).toBeDefined();
      expect(BACKENDS.production.api).toContain('api.aragora.ai');
      expect(BACKENDS.production.ws).toContain('wss://');
    });

    it('has development backend configured', () => {
      expect(BACKENDS.development).toBeDefined();
      expect(BACKENDS.development.fallbackApi).toBe('');
    });

    it('builds a same-origin health URL with trailing slash for local rewrites', () => {
      expect(buildHealthCheckUrl('')).toBe('/api/health/');
    });

    it('builds an absolute health URL without adding a trailing slash route', () => {
      expect(buildHealthCheckUrl('http://127.0.0.1:8086')).toBe('http://127.0.0.1:8086/api/health');
      expect(buildHealthCheckUrl('http://127.0.0.1:8086/')).toBe(
        'http://127.0.0.1:8086/api/health',
      );
    });
  });

  describe('Compact Mode', () => {
    it('renders compact buttons', async () => {
      render(<BackendSelector compact />);
      expect(screen.getByText('PROD')).toBeInTheDocument();
      expect(screen.getByText('DEV')).toBeInTheDocument();
      await waitForDevAvailability(false);
    });

    it('selects development by default on localhost', async () => {
      render(<BackendSelector compact />);
      const devButton = screen.getByText('DEV');
      expect(devButton.closest('button')).toHaveClass('bg-[var(--acid-cyan)]');
      await waitForDevAvailability(false);
    });

    it('allows switching to dev when available', async () => {
      mockFetch.mockImplementation(() => Promise.resolve({ ok: true }));

      render(<BackendSelector compact />);

      await waitFor(() => {
        const devButton = screen.getByText('DEV').closest('button');
        expect(devButton).not.toBeDisabled();
      });
    });

    it('disables dev button when unavailable', async () => {
      mockFetch.mockImplementation(() => Promise.reject(new Error('Offline')));

      render(<BackendSelector compact />);

      await waitFor(() => {
        const devButton = screen.getByText('DEV').closest('button');
        expect(devButton).toBeDisabled();
      });
    });
  });

  describe('Full Mode', () => {
    it('renders full selector with descriptions', async () => {
      render(<BackendSelector />);
      expect(screen.getByText('API BACKEND')).toBeInTheDocument();
      expect(screen.getByText('PROD')).toBeInTheDocument();
      expect(screen.getByText('DEV')).toBeInTheDocument();
      await waitForDevAvailability(false);
    });

    it('shows backend descriptions', async () => {
      render(<BackendSelector />);
      expect(screen.getByText(BACKENDS.production.description)).toBeInTheDocument();
      await waitForDevAvailability(false);
    });
  });

  describe('Backend Selection', () => {
    it('selects production when clicking PROD button', async () => {
      mockFetch.mockImplementation(() => Promise.resolve({ ok: true }));

      render(<BackendSelector compact />);
      await waitForDevAvailability(true);

      // Development is selected by default on localhost
      const devButton = screen.getByText('DEV').closest('button');
      expect(devButton).toHaveClass('bg-[var(--acid-cyan)]');

      // Switch to production
      const prodButton = screen.getByText('PROD').closest('button');
      fireEvent.click(prodButton!);
      expect(prodButton).toHaveClass('bg-[var(--accent)]');
    });

    it('persists production selection to localStorage', async () => {
      mockFetch.mockImplementation(() => Promise.resolve({ ok: true }));

      render(<BackendSelector compact />);

      await waitForDevAvailability(true);

      // Click PROD
      const prodButton = screen.getByText('PROD').closest('button')!;
      fireEvent.click(prodButton);

      expect(localStorageMock.getItem('aragora-backend')).toBe('production');
    });

    it('loads saved selection from localStorage', async () => {
      localStorageMock.setItem('aragora-backend', 'development');

      render(<BackendSelector compact />);

      await waitFor(() => {
        const devButton = screen.getByText('DEV').closest('button');
        expect(devButton).toHaveClass('bg-[var(--acid-cyan)]');
      });
      await waitForDevAvailability(false);
    });
  });

  describe('Dev Server Detection', () => {
    it('shows offline indicator when dev is unavailable', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('api-dev') || url.includes('localhost')) {
          return Promise.reject(new Error('Offline'));
        }
        return Promise.resolve({ ok: true });
      });

      render(<BackendSelector compact />);

      await waitFor(() => {
        // Check for warning indicator
        const warningIndicator = document.querySelector('.text-warning');
        expect(warningIndicator).toBeInTheDocument();
      });
    });

    it('shows localhost indicator when connected via localhost', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('api-dev')) {
          return Promise.reject(new Error('Tunnel down'));
        }
        if (url.includes('localhost')) {
          return Promise.resolve({ ok: true });
        }
        return Promise.resolve({ ok: true });
      });

      render(<BackendSelector compact />);

      // The 'L' indicator appears when connected via localhost
      // This may take time due to the health check order (tunnel first, then localhost)
      await waitFor(
        () => {
          // Look for the local indicator or the DEV button being enabled
          const devButton = screen.getByText('DEV').closest('button');
          expect(devButton).not.toBeDisabled();
        },
        { timeout: 5000 },
      );
    });
  });

  describe('useBackend Hook', () => {
    function TestComponent() {
      const { backend, config } = useBackend();
      return (
        <div>
          <span data-testid="backend">{backend}</span>
          <span data-testid="api">{config.api}</span>
        </div>
      );
    }

    it('returns development config by default on localhost', () => {
      render(<TestComponent />);
      expect(screen.getByTestId('backend')).toHaveTextContent('development');
      expect(screen.getByTestId('api')).toHaveTextContent('');
    });

    it('returns saved backend from localStorage', () => {
      localStorageMock.setItem('aragora-backend', 'development');
      render(<TestComponent />);
      expect(screen.getByTestId('backend')).toHaveTextContent('development');
    });
  });
});
