/**
 * Tests for ThemeToggle component (3-way segmented control).
 *
 * The component renders a radiogroup with three radio buttons —
 * Warm / Dark / Pro — each mapping to a Theme value:
 * 'warm' | 'dark' | 'professional'.
 *
 * Contract:
 *   - <div role="radiogroup" aria-label="Theme selector">
 *   - Three <button role="radio" aria-checked={active}> children
 *   - Click → setTheme(opt.value), persists to localStorage 'aragora-theme',
 *     and sets data-theme on document.documentElement
 *   - Uses text glyphs (no SVG icons)
 */

import { renderWithProviders, screen, fireEvent, act } from '@/test-utils';
import { ThemeToggle } from '../src/components/ThemeToggle';

const STORAGE_KEY = 'aragora-theme';

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

// Mock matchMedia
const mockMatchMedia = (matches: boolean) => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: jest
      .fn()
      .mockImplementation((query) => ({
        matches,
        media: query,
        onchange: null,
        addListener: jest.fn(),
        removeListener: jest.fn(),
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
        dispatchEvent: jest.fn(),
      })),
  });
};

const flush = async () => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
};

describe('ThemeToggle (3-way segmented control)', () => {
  beforeEach(() => {
    localStorageMock.clear();
    document.documentElement.removeAttribute('data-theme');
    mockMatchMedia(true); // system prefers dark
  });

  describe('Structure', () => {
    it('renders a radiogroup with three radio buttons', async () => {
      renderWithProviders(<ThemeToggle />);
      await flush();

      const group = screen.getByRole('radiogroup', { name: /theme/i });
      expect(group).toBeInTheDocument();

      const radios = screen.getAllByRole('radio');
      expect(radios).toHaveLength(3);
    });

    it('labels each radio Warm, Dark, and Pro', async () => {
      renderWithProviders(<ThemeToggle />);
      await flush();

      expect(screen.getByRole('radio', { name: /warm/i })).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: /dark/i })).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: /pro/i })).toBeInTheDocument();
    });

    it('has an aria-label on the radiogroup for accessibility', async () => {
      renderWithProviders(<ThemeToggle />);
      await flush();

      const group = screen.getByRole('radiogroup');
      expect(group).toHaveAttribute('aria-label', 'Theme selector');
    });
  });

  describe('Selected state', () => {
    it('marks the dark radio aria-checked when theme is dark', async () => {
      localStorageMock.setItem(STORAGE_KEY, 'dark');
      renderWithProviders(<ThemeToggle />);
      await flush();

      const darkRadio = screen.getByRole('radio', { name: /dark/i });
      expect(darkRadio).toHaveAttribute('aria-checked', 'true');

      const warmRadio = screen.getByRole('radio', { name: /warm/i });
      expect(warmRadio).toHaveAttribute('aria-checked', 'false');
    });

    it('marks the warm radio aria-checked when theme is warm', async () => {
      localStorageMock.setItem(STORAGE_KEY, 'warm');
      renderWithProviders(<ThemeToggle />);
      await flush();

      const warmRadio = screen.getByRole('radio', { name: /warm/i });
      expect(warmRadio).toHaveAttribute('aria-checked', 'true');

      const darkRadio = screen.getByRole('radio', { name: /dark/i });
      expect(darkRadio).toHaveAttribute('aria-checked', 'false');
    });

    it('marks the pro radio aria-checked when theme is professional', async () => {
      localStorageMock.setItem(STORAGE_KEY, 'professional');
      renderWithProviders(<ThemeToggle />);
      await flush();

      const proRadio = screen.getByRole('radio', { name: /pro/i });
      expect(proRadio).toHaveAttribute('aria-checked', 'true');
    });
  });

  describe('Click behavior', () => {
    it('clicking Warm persists "warm" to localStorage and sets data-theme', async () => {
      localStorageMock.setItem(STORAGE_KEY, 'dark');
      renderWithProviders(<ThemeToggle />);
      await flush();

      fireEvent.click(screen.getByRole('radio', { name: /warm/i }));

      expect(localStorageMock.getItem(STORAGE_KEY)).toBe('warm');
      expect(document.documentElement.getAttribute('data-theme')).toBe('warm');
    });

    it('clicking Dark persists "dark" to localStorage and sets data-theme', async () => {
      localStorageMock.setItem(STORAGE_KEY, 'warm');
      renderWithProviders(<ThemeToggle />);
      await flush();

      fireEvent.click(screen.getByRole('radio', { name: /dark/i }));

      expect(localStorageMock.getItem(STORAGE_KEY)).toBe('dark');
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });

    it('clicking Pro persists "professional" to localStorage and sets data-theme', async () => {
      localStorageMock.setItem(STORAGE_KEY, 'warm');
      renderWithProviders(<ThemeToggle />);
      await flush();

      fireEvent.click(screen.getByRole('radio', { name: /pro/i }));

      expect(localStorageMock.getItem(STORAGE_KEY)).toBe('professional');
      expect(document.documentElement.getAttribute('data-theme')).toBe('professional');
    });

    it('updates aria-checked when switching between radios', async () => {
      localStorageMock.setItem(STORAGE_KEY, 'warm');
      renderWithProviders(<ThemeToggle />);
      await flush();

      const warmRadio = screen.getByRole('radio', { name: /warm/i });
      const darkRadio = screen.getByRole('radio', { name: /dark/i });

      expect(warmRadio).toHaveAttribute('aria-checked', 'true');
      expect(darkRadio).toHaveAttribute('aria-checked', 'false');

      fireEvent.click(darkRadio);

      expect(warmRadio).toHaveAttribute('aria-checked', 'false');
      expect(darkRadio).toHaveAttribute('aria-checked', 'true');
    });
  });

  describe('Persistence on reload', () => {
    it('loads dark theme from localStorage on mount', async () => {
      localStorageMock.setItem(STORAGE_KEY, 'dark');
      renderWithProviders(<ThemeToggle />);
      await flush();

      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
      expect(screen.getByRole('radio', { name: /dark/i })).toHaveAttribute('aria-checked', 'true');
    });

    it('loads professional theme from localStorage on mount', async () => {
      localStorageMock.setItem(STORAGE_KEY, 'professional');
      renderWithProviders(<ThemeToggle />);
      await flush();

      expect(document.documentElement.getAttribute('data-theme')).toBe('professional');
      expect(screen.getByRole('radio', { name: /pro/i })).toHaveAttribute('aria-checked', 'true');
    });
  });

  describe('Rendering', () => {
    it('uses text glyphs (aria-hidden) rather than SVG icons', async () => {
      renderWithProviders(<ThemeToggle />);
      await flush();

      // The 3-way selector is text-only — no SVG elements.
      const svg = document.querySelector('svg');
      expect(svg).toBeNull();
    });
  });
});
