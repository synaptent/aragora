/**
 * Tests for SettingsPanel component
 *
 * Tests cover:
 * - Tab navigation
 * - Feature toggles
 * - Theme selection
 * - API key management
 * - Logout all devices
 */

import { renderWithProviders, screen, fireEvent, waitFor, act } from '@/test-utils';
import { SettingsPanel } from '@/components/settings-panel';

// Mock the hooks – keep the real AuthContext so renderWithProviders can wrap with AuthContext.Provider
jest.mock('../src/context/AuthContext', () => {
  const actual = jest.requireActual('../src/context/AuthContext');
  return { ...actual, useAuth: () => mockAuth };
});

jest.mock('../src/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://localhost:8080' } }),
}));

const mockAuth = {
  user: {
    email: 'test@example.com',
    name: 'Test User',
    role: 'user',
    created_at: '2026-01-01T00:00:00Z',
  },
  isAuthenticated: true,
};

// Mock fetch
global.fetch = jest.fn();

// Mock localStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// Mock window.confirm
window.confirm = jest.fn();

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: jest
    .fn()
    .mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: jest.fn(),
      removeListener: jest.fn(),
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      dispatchEvent: jest.fn(),
    })),
});

function setupMocks() {
  (global.fetch as jest.Mock).mockResolvedValue({
    ok: true,
    json: async () => ({ preferences: {} }),
  });
  localStorageMock.getItem.mockReturnValue(null);
}

describe('SettingsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupMocks();
  });

  describe('Tab Navigation', () => {
    it('renders all tabs', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      expect(screen.getByText('FEATURES')).toBeInTheDocument();
      expect(screen.getByText('DEBATE')).toBeInTheDocument();
      expect(screen.getByText('APPEARANCE')).toBeInTheDocument();
      expect(screen.getByText('NOTIFICATIONS')).toBeInTheDocument();
      expect(screen.getByText('API KEYS')).toBeInTheDocument();
      expect(screen.getByText('INTEGRATIONS')).toBeInTheDocument();
      expect(screen.getByText('ACCOUNT')).toBeInTheDocument();
    });

    it('starts on features tab', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      await waitFor(() => {
        expect(screen.getByText('Analysis Features')).toBeInTheDocument();
      });
    });

    it('switches to appearance tab', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('APPEARANCE'));

      await waitFor(() => {
        expect(screen.getByText('Theme')).toBeInTheDocument();
      });
    });

    it('switches to account tab', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('ACCOUNT'));

      await waitFor(() => {
        expect(screen.getByText('Account Information')).toBeInTheDocument();
      });
    });
  });

  describe('Features Tab', () => {
    it('shows feature toggle sections', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      await waitFor(() => {
        expect(screen.getByText('Analysis Features')).toBeInTheDocument();
        expect(screen.getByText('Learning & Memory')).toBeInTheDocument();
        expect(screen.getByText('Panels & UI')).toBeInTheDocument();
      });
    });

    it('shows calibration toggle', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      await waitFor(() => {
        expect(screen.getByText('Calibration Tracking')).toBeInTheDocument();
      });
    });
  });

  describe('Appearance Tab', () => {
    it('shows theme options', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('APPEARANCE'));

      await waitFor(() => {
        expect(screen.getByText('dark')).toBeInTheDocument();
        expect(screen.getByText('light')).toBeInTheDocument();
        expect(screen.getByText('system')).toBeInTheDocument();
      });
    });

    it('shows display options', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('APPEARANCE'));

      await waitFor(() => {
        expect(screen.getByText('Display Options')).toBeInTheDocument();
        expect(screen.getByText('Compact Mode')).toBeInTheDocument();
      });
    });
  });

  describe('API Keys Tab', () => {
    it('shows API key generation controls', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('API KEYS'));

      await waitFor(() => {
        expect(screen.getByText('Personal API Key')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /generate key/i })).toBeInTheDocument();
        expect(screen.getByText(/Active keys:\s*0 \/ 1/i)).toBeInTheDocument();
      });
    });

    it('shows API documentation', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('API KEYS'));

      await waitFor(() => {
        expect(screen.getByText('API Documentation')).toBeInTheDocument();
      });
    });
  });

  describe('Account Tab', () => {
    it('shows user information when authenticated', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('ACCOUNT'));

      await waitFor(() => {
        expect(screen.getByText('test@example.com')).toBeInTheDocument();
        expect(screen.getByText('Test User')).toBeInTheDocument();
      });
    });

    it('shows logout all devices button', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('ACCOUNT'));

      await waitFor(() => {
        expect(screen.getByText(/Logout All Devices/i)).toBeInTheDocument();
      });
    });

    it('shows danger zone', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('ACCOUNT'));

      await waitFor(() => {
        expect(screen.getByText('Danger Zone')).toBeInTheDocument();
        expect(screen.getByText('Delete Account')).toBeInTheDocument();
      });
    });
  });

  describe('Integrations Tab', () => {
    it('shows Slack integration', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('INTEGRATIONS'));

      await waitFor(() => {
        expect(screen.getByText('Slack Integration')).toBeInTheDocument();
      });
    });

    it('shows Discord integration', async () => {
      await act(async () => {
        renderWithProviders(<SettingsPanel />);
      });

      fireEvent.click(screen.getByText('INTEGRATIONS'));

      await waitFor(() => {
        expect(screen.getByText('Discord Integration')).toBeInTheDocument();
      });
    });
  });
});
