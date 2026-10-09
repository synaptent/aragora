/**
 * Every mounted logout control goes through the real AuthProvider logout:
 * auth storage is cleared before the full-page navigation to /auth/login.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider } from '@/context/AuthContext';
import { hardNavigate } from '@/utils/navigation';
import { UserMenu } from '../UserMenu';
import { TopBar } from '@/components/layout/TopBar';
import { Sidebar } from '@/components/Sidebar';

jest.mock('@/utils/navigation', () => ({
  hardNavigate: jest.fn(),
  reloadDocument: jest.fn(),
}));

jest.mock('next/link', () => {
  const React = require('react');
  return React.forwardRef(function MockLink(
    { children, href, onClick, ...props }: { children: React.ReactNode; href: string; onClick?: () => void },
    ref: React.Ref<HTMLAnchorElement>
  ) {
    return (
      <a
        href={href}
        ref={ref}
        onClick={(e) => {
          e.preventDefault();
          onClick?.();
        }}
        {...props}
      >
        {children}
      </a>
    );
  });
});

jest.mock('@/context/LayoutContext', () => ({
  useLayout: () => ({
    isMobile: false,
    toggleLeftSidebar: jest.fn(),
    toggleRightSidebar: jest.fn(),
    rightSidebarOpen: false,
  }),
}));
jest.mock('@/context/CommandPaletteContext', () => ({
  useCommandPalette: () => ({ open: jest.fn() }),
}));
jest.mock('@/components/Logo', () => ({ Logo: () => null }));
jest.mock('@/components/ThemeToggle', () => ({ ThemeToggle: () => null }));
jest.mock('@/components/layout/BudgetBadge', () => ({ BudgetBadge: () => null }));
jest.mock('@/components/GlobalConnectionStatus', () => ({ GlobalConnectionStatus: () => null }));

const mockSidebarClose = jest.fn();
jest.mock('@/context/SidebarContext', () => ({
  useSidebar: () => ({ isOpen: true, close: mockSidebarClose, open: jest.fn() }),
}));
jest.mock('@/context/ProgressiveModeContext', () => ({
  useProgressiveMode: () => ({ isFeatureVisible: () => false, modeLabel: 'Simple' }),
}));
jest.mock('@/components/ui/FeatureCard', () => ({ ModeSelector: () => null }));
jest.mock('@/hooks/useSwipeGesture', () => ({
  useEdgeSwipe: jest.fn(),
  useSwipeGesture: () => ({ current: null }),
}));
jest.mock('@/store/onboardingStore', () => ({
  useOnboardingStore: () => ({}),
  selectIsOnboardingNeeded: () => false,
}));

const mockHardNavigate = hardNavigate as jest.MockedFunction<typeof hardNavigate>;

const AUTH_KEYS = ['aragora_tokens', 'aragora_user', 'aragora_active_org', 'aragora_user_orgs'];

const userA = {
  id: 'user-a',
  email: 'owner-a@example.test',
  name: 'Owner A',
  role: 'owner',
  org_id: 'org-a',
  is_active: true,
  created_at: '2026-10-01T00:00:00Z',
};
const orgA = { id: 'org-a', name: 'Org A', slug: 'org-a', tier: 'professional', owner_id: 'user-a' };
const orgsA = [
  {
    user_id: 'user-a',
    org_id: 'org-a',
    organization: orgA,
    role: 'owner',
    is_default: true,
    joined_at: '2026-10-01T00:00:00Z',
  },
];

function seedSession() {
  localStorage.setItem(
    'aragora_tokens',
    JSON.stringify({
      access_token: 'access-a',
      refresh_token: 'refresh-a',
      expires_at: new Date(Date.now() + 3_600_000).toISOString(),
    }),
  );
  localStorage.setItem('aragora_user', JSON.stringify(userA));
  localStorage.setItem('aragora_active_org', JSON.stringify(orgA));
  localStorage.setItem('aragora_user_orgs', JSON.stringify(orgsA));
}

function recordStorageAtNavigation(): { snapshot: (string | null)[] | null } {
  const seen: { snapshot: (string | null)[] | null } = { snapshot: null };
  mockHardNavigate.mockImplementationOnce(() => {
    seen.snapshot = AUTH_KEYS.map((key) => localStorage.getItem(key));
  });
  return seen;
}

async function expectLoggedOutAndNavigated(seen: { snapshot: (string | null)[] | null }) {
  await waitFor(() => {
    expect(mockHardNavigate).toHaveBeenCalledWith('/auth/login');
  });
  expect(mockHardNavigate).toHaveBeenCalledTimes(1);
  expect(seen.snapshot).toEqual(AUTH_KEYS.map(() => null));
  expect(global.fetch).toHaveBeenCalledWith(
    expect.stringContaining('/api/auth/logout'),
    expect.objectContaining({
      method: 'POST',
      headers: { Authorization: 'Bearer access-a' },
    }),
  );
}

describe('logout callers', () => {
  beforeEach(() => {
    localStorage.clear();
    seedSession();
    mockHardNavigate.mockReset();
    (global.fetch as jest.Mock).mockReset();
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ user: userA, organization: orgA, organizations: orgsA }),
        });
      }
      if (url.includes('/api/auth/logout')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('UserMenu logout clears the session and loads /auth/login', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <UserMenu />
      </AuthProvider>,
    );

    await user.click(await screen.findByRole('button', { name: /user menu/i }));
    const seen = recordStorageAtNavigation();
    await user.click(screen.getByRole('menuitem', { name: /logout/i }));

    await expectLoggedOutAndNavigated(seen);
  });

  it('TopBar logout clears the session and loads /auth/login', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <TopBar />
      </AuthProvider>,
    );

    const logoutButton = await screen.findByRole('button', { name: 'Logout' });
    expect(screen.getByText('owner-a@example.test')).toBeInTheDocument();
    const seen = recordStorageAtNavigation();
    await user.click(logoutButton);

    await expectLoggedOutAndNavigated(seen);
  });

  it('Sidebar logout clears the session, loads /auth/login and closes the menu', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <Sidebar />
      </AuthProvider>,
    );

    const logoutButton = await screen.findByRole('button', { name: 'Logout' });
    const seen = recordStorageAtNavigation();
    await user.click(logoutButton);

    await expectLoggedOutAndNavigated(seen);
    await waitFor(() => {
      expect(mockSidebarClose).toHaveBeenCalled();
    });
  });
});
