import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UserMenu } from '../UserMenu';

// Mock next/link with forwardRef and onClick support
jest.mock('next/link', () => {
  const React = require('react');
  return React.forwardRef(function MockLink(
    {
      children,
      href,
      onClick,
      ...props
    }: { children: React.ReactNode; href: string; onClick?: () => void },
    ref: React.Ref<HTMLAnchorElement>,
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

// Mock auth context
const mockLogout = jest.fn();
const mockAuthContext = {
  user: null as { email: string; name?: string } | null,
  organization: null as { name: string; tier: string } | null,
  organizations: [] as Array<{ id: string; name: string }>,
  tokens: null,
  isAuthenticated: false,
  isLoading: false,
  isLoadingOrganizations: false,
  logout: mockLogout,
  login: jest.fn(),
  register: jest.fn(),
  refreshToken: jest.fn(),
  setTokens: jest.fn(),
  switchOrganization: jest.fn(),
  refreshOrganizations: jest.fn(),
  getCurrentOrgRole: jest.fn().mockReturnValue(null),
};

jest.mock('@/context/AuthContext', () => ({ useAuth: () => mockAuthContext }));

describe('UserMenu', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Reset auth context
    mockAuthContext.user = null;
    mockAuthContext.organization = null;
    mockAuthContext.organizations = [];
    mockAuthContext.isAuthenticated = false;
    mockAuthContext.isLoading = false;
  });

  describe('loading state', () => {
    it('shows loading indicator when isLoading is true', () => {
      mockAuthContext.isLoading = true;

      render(<UserMenu />);

      expect(screen.getByText('[LOADING...]')).toBeInTheDocument();
    });
  });

  describe('unauthenticated state', () => {
    it('shows login and sign up links when not authenticated', () => {
      render(<UserMenu />);

      expect(screen.getByRole('link', { name: /login/i })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /sign up/i })).toBeInTheDocument();
    });

    it('login link points to /auth/login', () => {
      render(<UserMenu />);

      const loginLink = screen.getByRole('link', { name: /login/i });
      expect(loginLink).toHaveAttribute('href', '/auth/login');
    });

    it('sign up link points to /signup', () => {
      render(<UserMenu />);

      const signUpLink = screen.getByRole('link', { name: /sign up/i });
      expect(signUpLink).toHaveAttribute('href', '/signup');
    });
  });

  describe('authenticated state', () => {
    beforeEach(() => {
      mockAuthContext.isAuthenticated = true;
      mockAuthContext.user = { email: 'test@example.com', name: 'Test User' };
    });

    it('shows user avatar with first letter of name', () => {
      render(<UserMenu />);

      expect(screen.getByText('T')).toBeInTheDocument();
    });

    it('shows user avatar with first letter of email when no name', () => {
      mockAuthContext.user = { email: 'john@example.com' };

      render(<UserMenu />);

      expect(screen.getByText('J')).toBeInTheDocument();
    });

    it('shows username on desktop (sm:inline)', () => {
      render(<UserMenu />);

      expect(screen.getByText('Test User')).toBeInTheDocument();
    });

    it('shows email prefix when no name', () => {
      mockAuthContext.user = { email: 'john.doe@example.com' };

      render(<UserMenu />);

      expect(screen.getByText('john.doe')).toBeInTheDocument();
    });

    it('has proper aria attributes on menu button', () => {
      render(<UserMenu />);

      const button = screen.getByRole('button', { name: /user menu/i });
      expect(button).toHaveAttribute('aria-haspopup', 'menu');
      expect(button).toHaveAttribute('aria-expanded', 'false');
    });
  });

  describe('dropdown menu', () => {
    beforeEach(() => {
      mockAuthContext.isAuthenticated = true;
      mockAuthContext.user = { email: 'test@example.com', name: 'Test User' };
    });

    it('opens dropdown when button is clicked', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      const button = screen.getByRole('button', { name: /user menu/i });
      await act(async () => {
        await user.click(button);
      });

      expect(screen.getByRole('menu')).toBeInTheDocument();
      expect(button).toHaveAttribute('aria-expanded', 'true');
    });

    it('shows user info in dropdown', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /user menu/i }));
      });

      // User name appears in both button and dropdown - check we have 2 instances
      const userNames = screen.getAllByText('Test User');
      expect(userNames.length).toBe(2);
      expect(screen.getByText('test@example.com')).toBeInTheDocument();
    });

    it('shows organization info when available', async () => {
      mockAuthContext.organization = { name: 'Acme Corp', tier: 'enterprise' };
      const user = userEvent.setup();
      render(<UserMenu />);

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /user menu/i }));
      });

      expect(screen.getByText(/ORG: Acme Corp/)).toBeInTheDocument();
      expect(screen.getByText('enterprise')).toBeInTheDocument();
    });

    it('shows all menu items', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /user menu/i }));
      });

      expect(screen.getByText('[BILLING & USAGE]')).toBeInTheDocument();
      expect(screen.getByText('[SETTINGS]')).toBeInTheDocument();
      expect(screen.getByText('[DEVELOPER]')).toBeInTheDocument();
      expect(screen.getByText('[A/B TESTING]')).toBeInTheDocument();
      expect(screen.getByText('[LOGOUT]')).toBeInTheDocument();
    });

    it('menu links have correct hrefs', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /user menu/i }));
      });

      expect(screen.getByText('[BILLING & USAGE]').closest('a')).toHaveAttribute(
        'href',
        '/billing',
      );
      expect(screen.getByText('[SETTINGS]').closest('a')).toHaveAttribute('href', '/settings');
      expect(screen.getByText('[DEVELOPER]').closest('a')).toHaveAttribute('href', '/developer');
      expect(screen.getByText('[A/B TESTING]').closest('a')).toHaveAttribute('href', '/ab-testing');
    });

    it('closes dropdown when menu item is clicked', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /user menu/i }));
      });

      expect(screen.getByRole('menu')).toBeInTheDocument();

      await act(async () => {
        await user.click(screen.getByText('[SETTINGS]'));
      });

      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });

    it('calls logout when logout button is clicked', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /user menu/i }));
      });

      await act(async () => {
        await user.click(screen.getByRole('menuitem', { name: /logout/i }));
      });

      expect(mockLogout).toHaveBeenCalled();
    });

    it('toggles dropdown on repeated clicks', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      const button = screen.getByRole('button', { name: /user menu/i });

      // Open
      await act(async () => {
        await user.click(button);
      });
      expect(screen.getByRole('menu')).toBeInTheDocument();

      // Close
      await act(async () => {
        await user.click(button);
      });
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });
  });

  describe('keyboard navigation', () => {
    beforeEach(() => {
      mockAuthContext.isAuthenticated = true;
      mockAuthContext.user = { email: 'test@example.com', name: 'Test User' };
    });

    it('opens dropdown with Enter key', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      const button = screen.getByRole('button', { name: /user menu/i });
      button.focus();

      await act(async () => {
        await user.keyboard('{Enter}');
      });

      expect(screen.getByRole('menu')).toBeInTheDocument();
    });

    it('opens dropdown with Space key', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      const button = screen.getByRole('button', { name: /user menu/i });
      button.focus();

      await act(async () => {
        await user.keyboard(' ');
      });

      expect(screen.getByRole('menu')).toBeInTheDocument();
    });

    it('opens dropdown with ArrowDown key', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      const button = screen.getByRole('button', { name: /user menu/i });
      button.focus();

      await act(async () => {
        await user.keyboard('{ArrowDown}');
      });

      expect(screen.getByRole('menu')).toBeInTheDocument();
    });

    it('closes dropdown with Escape key', async () => {
      const user = userEvent.setup();
      render(<UserMenu />);

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /user menu/i }));
      });

      expect(screen.getByRole('menu')).toBeInTheDocument();

      await act(async () => {
        await user.keyboard('{Escape}');
      });

      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });
  });

  describe('click outside', () => {
    beforeEach(() => {
      mockAuthContext.isAuthenticated = true;
      mockAuthContext.user = { email: 'test@example.com', name: 'Test User' };
    });

    it('closes dropdown when clicking outside', async () => {
      const user = userEvent.setup();
      render(
        <div>
          <UserMenu />
          <div data-testid="outside">Outside</div>
        </div>,
      );

      await act(async () => {
        await user.click(screen.getByRole('button', { name: /user menu/i }));
      });

      expect(screen.getByRole('menu')).toBeInTheDocument();

      await act(async () => {
        await user.click(screen.getByTestId('outside'));
      });

      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });
  });
});
