import React, { type ReactElement, type ReactNode } from 'react';
import { render, type RenderOptions } from '@testing-library/react';
import { ThemeProvider } from '@/context/ThemeContext';
import { AuthContext, type AuthContextType } from '@/context/AuthContext';

/**
 * Default mock values for the AuthContext. These satisfy every field that
 * `useAuth()` consumers can access, without triggering any side effects
 * (no fetch, no localStorage reads/writes).
 *
 * Override per-test via the `authOverrides` option in `renderWithProviders`.
 */
export const defaultAuthValues: AuthContextType = {
  user: null,
  organization: null,
  organizations: [],
  tokens: null,
  isLoading: false,
  isAuthenticated: false,
  isLoadingOrganizations: false,
  login: jest.fn().mockResolvedValue({ success: true }),
  register: jest.fn().mockResolvedValue({ success: true }),
  logout: jest.fn().mockResolvedValue(undefined),
  refreshToken: jest.fn().mockResolvedValue(false),
  setTokens: jest.fn().mockResolvedValue(undefined),
  switchOrganization: jest.fn().mockResolvedValue({ success: true }),
  refreshOrganizations: jest.fn().mockResolvedValue(undefined),
  getCurrentOrgRole: jest.fn().mockReturnValue(null),
};

/**
 * Options for `renderWithProviders`.
 */
interface RenderWithProvidersOptions extends Omit<RenderOptions, 'wrapper'> {
  /**
   * Override default auth context values. For example:
   * ```ts
   * renderWithProviders(<MyComponent />, {
   *   authOverrides: {
   *     isAuthenticated: true,
   *     user: {
   *       id: '1', email: 'test@example.com', name: 'Test',
   *       role: 'admin', org_id: null, is_active: true, created_at: '',
   *     },
   *   },
   * });
   * ```
   */
  authOverrides?: Partial<AuthContextType>;
}

/**
 * Render a React component wrapped in all the context providers needed
 * by the Aragora Live frontend.
 *
 * **AuthProvider** -- Replaced by a lightweight `AuthContext.Provider`
 * that supplies static mock values (no fetch, no localStorage). Pass
 * `authOverrides` to customise the auth state for individual tests.
 *
 * **ThemeProvider** -- Uses the real implementation with
 * `defaultPreference="dark"`. This is safe in JSDOM because
 * `window.matchMedia` is already mocked in `jest.setup.js`.
 *
 * @example
 * ```tsx
 * import { renderWithProviders, screen } from '@/test-utils';
 *
 * it('renders when authenticated', () => {
 *   renderWithProviders(<Dashboard />, {
 *     authOverrides: { isAuthenticated: true, user: mockUser },
 *   });
 *   expect(screen.getByText('Dashboard')).toBeInTheDocument();
 * });
 * ```
 */
export function renderWithProviders(ui: ReactElement, options: RenderWithProvidersOptions = {}) {
  const { authOverrides = {}, ...renderOptions } = options;
  const authValue: AuthContextType = { ...defaultAuthValues, ...authOverrides };

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ThemeProvider defaultPreference="dark">
        <AuthContext.Provider value={authValue}>{children}</AuthContext.Provider>
      </ThemeProvider>
    );
  }

  return render(ui, { wrapper: Wrapper, ...renderOptions });
}

/**
 * Create a wrapper component for `renderHook` that provides auth context.
 * Pass `authOverrides` to customise the auth state.
 */
export function createHookWrapper(authOverrides: Partial<AuthContextType> = {}) {
  const authValue: AuthContextType = { ...defaultAuthValues, ...authOverrides };
  return function HookWrapper({ children }: { children: ReactNode }) {
    return (
      <ThemeProvider defaultPreference="dark">
        <AuthContext.Provider value={authValue}>{children}</AuthContext.Provider>
      </ThemeProvider>
    );
  };
}

/**
 * Default hook wrapper with mock auth context.
 * Usage: `renderHook(() => useMyHook(), { wrapper: hookWrapper })`
 */
export const hookWrapper = createHookWrapper();

// Re-export everything from @testing-library/react so test files can
// import from '@/test-utils' as a drop-in replacement for
// '@testing-library/react'.
export * from '@testing-library/react';
