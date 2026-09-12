'use client';

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
  type ReactNode,
} from 'react';

// ============================================================================
// Types
// ============================================================================

export type Theme = 'warm' | 'dark' | 'professional';

/** Legacy type aliases for backward compatibility */
export type ThemePreference = 'dark' | 'light' | 'system' | Theme;
export type EffectiveTheme = 'dark' | 'light';

export interface ThemeContextValue {
  /** The current active theme */
  theme: Theme;
  /** Set the theme (also accepts legacy 'light'/'system' values) */
  setTheme: (theme: Theme | 'light' | 'system') => void;
  /** Whether the theme context has initialized */
  isInitialized: boolean;
  /** @deprecated Legacy compat — maps to theme. 'warm'/'professional' report as theme name */
  preference: ThemePreference;
  /** @deprecated Legacy compat — 'dark' for dark theme, 'light' for warm/professional */
  effectiveTheme: EffectiveTheme;
  /** @deprecated Legacy compat — toggles between dark and warm */
  toggleTheme: () => void;
}

// ============================================================================
// Constants
// ============================================================================

const STORAGE_KEY = 'aragora-theme';
const DATA_ATTRIBUTE = 'data-theme';
const DEFAULT_THEME: Theme = 'warm';

// ============================================================================
// Context
// ============================================================================

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

// ============================================================================
// Utilities
// ============================================================================

function isValidTheme(value: string): value is Theme {
  return value === 'warm' || value === 'dark' || value === 'professional';
}

function getSystemDefaultTheme(): Theme {
  if (typeof window === 'undefined') return DEFAULT_THEME;
  const mediaQuery =
    typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : null;
  return mediaQuery?.matches ? 'dark' : 'warm';
}

function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute(DATA_ATTRIBUTE, theme);

  // Update meta theme-color for mobile browsers
  const metaThemeColor = document.querySelector('meta[name="theme-color"]');
  if (metaThemeColor) {
    const themeColors: Record<Theme, string> = {
      warm: '#faf9f7',
      dark: '#0a0a0a',
      professional: '#ffffff',
    };
    metaThemeColor.setAttribute('content', themeColors[theme]);
  }
}

function getStoredTheme(): Theme | null {
  if (typeof localStorage === 'undefined') return null;

  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && isValidTheme(stored)) {
      return stored;
    }
    // Legacy compat: map old 'light' to 'warm', 'dark' stays 'dark'
    if (stored === 'light') return 'warm';
    if (stored === 'dark') return 'dark';
  } catch {
    // Ignore storage errors
  }

  return null;
}

function storeTheme(theme: Theme): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Ignore storage errors
  }
}

// ============================================================================
// Provider
// ============================================================================

interface ThemeProviderProps {
  children: ReactNode;
  /** Default theme if none stored. Defaults to 'warm' */
  defaultTheme?: Theme;
  /** @deprecated Legacy prop name — use defaultTheme instead */
  defaultPreference?: string;
}

export function ThemeProvider({ children, defaultTheme, defaultPreference }: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(DEFAULT_THEME);
  const [isInitialized, setIsInitialized] = useState(false);

  // Initialize from storage on mount
  useEffect(() => {
    const stored = getStoredTheme();
    // Resolve legacy defaultPreference if defaultTheme not provided
    let fallback: Theme | undefined = defaultTheme;
    if (!fallback && defaultPreference) {
      if (defaultPreference === 'light') fallback = 'warm';
      else if (defaultPreference === 'dark') fallback = 'dark';
      else if (isValidTheme(defaultPreference)) fallback = defaultPreference;
    }
    const initial = stored ?? fallback ?? getSystemDefaultTheme();
    setThemeState(initial);
    applyTheme(initial);
    setIsInitialized(true);
  }, [defaultTheme, defaultPreference]);

  // Listen for system preference changes (when no explicit choice was stored)
  useEffect(() => {
    const mediaQuery =
      typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-color-scheme: dark)')
        : null;
    if (!mediaQuery) {
      return;
    }

    const handleChange = (e: MediaQueryListEvent) => {
      // Only auto-switch if user hasn't explicitly set a theme
      const stored = getStoredTheme();
      if (!stored) {
        const newTheme: Theme = e.matches ? 'dark' : 'warm';
        setThemeState(newTheme);
        applyTheme(newTheme);
      }
    };

    if (
      typeof mediaQuery.addEventListener === 'function' &&
      typeof mediaQuery.removeEventListener === 'function'
    ) {
      mediaQuery.addEventListener('change', handleChange);
      return () => mediaQuery.removeEventListener('change', handleChange);
    }

    if (
      typeof mediaQuery.addListener === 'function' &&
      typeof mediaQuery.removeListener === 'function'
    ) {
      mediaQuery.addListener(handleChange);
      return () => mediaQuery.removeListener(handleChange);
    }

    return;
  }, []);

  // Set theme handler — also accepts legacy 'light'/'system' values
  const setTheme = useCallback((newTheme: Theme | 'light' | 'system') => {
    let resolved: Theme;
    if (newTheme === 'light') {
      resolved = 'warm';
    } else if (newTheme === 'system') {
      resolved = getSystemDefaultTheme();
    } else {
      resolved = newTheme;
    }
    setThemeState(resolved);
    storeTheme(resolved);
    applyTheme(resolved);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      setTheme,
      isInitialized,
      // Legacy compat properties
      preference: theme,
      effectiveTheme: theme === 'dark' ? 'dark' : 'light',
      toggleTheme: () => setTheme(theme === 'dark' ? 'warm' : 'dark'),
    }),
    [theme, setTheme, isInitialized],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

// ============================================================================
// Hook
// ============================================================================

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}

// ============================================================================
// SSR-Safe Initialization Script
// ============================================================================

/**
 * Inline script to prevent flash of wrong theme.
 * Should be placed in the <head> before CSS loads.
 */
export const themeInitScript = `
(function() {
  try {
    var theme = localStorage.getItem('aragora-theme');
    if (theme === 'light') theme = 'warm';
    if (theme !== 'warm' && theme !== 'dark' && theme !== 'professional') {
      theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'warm';
    }
    document.documentElement.setAttribute('data-theme', theme);
  } catch (e) {}
})();
`;
