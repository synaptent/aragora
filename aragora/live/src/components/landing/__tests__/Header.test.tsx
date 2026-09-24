import { renderWithProviders, screen } from '@/test-utils';
import userEvent from '@testing-library/user-event';
import { Header } from '../Header';

jest.mock('next/navigation', () => ({ usePathname: () => '/landing' }));

jest.mock('@/components/Logo', () => ({ Logo: () => <div data-testid="logo">Logo</div> }));

jest.mock('../ThemeSelector', () => ({
  ThemeSelector: () => <div data-testid="theme-selector">Theme selector</div>,
}));

const renderHeader = () => renderWithProviders(<Header />);

describe('Header', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial render', () => {
    it('renders the logo, wordmark, and theme selector', () => {
      renderHeader();

      expect(screen.getByTestId('logo')).toBeInTheDocument();
      expect(screen.getByText('> ARAGORA')).toBeInTheDocument();
      expect(screen.getByTestId('theme-selector')).toBeInTheDocument();
    });
  });

  describe('navigation', () => {
    it('renders the current landing navigation links', () => {
      renderHeader();

      expect(screen.getAllByRole('link', { name: /how it works/i }).length).toBeGreaterThan(0);
      expect(screen.getAllByRole('link', { name: /quickstart/i }).length).toBeGreaterThan(0);
      expect(screen.getAllByRole('link', { name: /docs/i }).length).toBeGreaterThan(0);
      expect(screen.getAllByRole('link', { name: /pricing/i }).length).toBeGreaterThan(0);
      expect(screen.getAllByRole('link', { name: /log in/i }).length).toBeGreaterThan(0);
    });

    it('uses the current href targets', () => {
      renderHeader();

      expect(screen.getAllByRole('link', { name: /quickstart/i })[0]).toHaveAttribute(
        'href',
        '/quickstart',
      );
      expect(screen.getAllByRole('link', { name: /docs/i })[0]).toHaveAttribute('href', '/docs');
      expect(screen.getAllByRole('link', { name: /pricing/i })[0]).toHaveAttribute(
        'href',
        '/pricing',
      );
      expect(screen.getAllByRole('link', { name: /log in/i })[0]).toHaveAttribute('href', '/login');
    });

    it('uses the login callback when provided', async () => {
      const user = userEvent.setup();
      const onLoginClick = jest.fn();
      renderWithProviders(<Header onLoginClick={onLoginClick} />);

      await user.click(screen.getAllByRole('button', { name: /log in/i })[0]);

      expect(onLoginClick).toHaveBeenCalledTimes(1);
    });
  });

  describe('mobile menu', () => {
    it('renders the mobile menu toggle button', () => {
      renderHeader();

      expect(screen.getByRole('button', { name: /open menu/i })).toBeInTheDocument();
    });

    it('opens the mobile panel and shows the signup CTA', async () => {
      const user = userEvent.setup();
      renderHeader();

      const button = screen.getByRole('button', { name: /open menu/i });
      expect(button).toHaveAttribute('aria-expanded', 'false');
      await user.click(button);

      expect(screen.getByRole('button', { name: /close menu/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /close menu/i })).toHaveAttribute(
        'aria-expanded',
        'true',
      );
      expect(screen.getByRole('link', { name: /sign up free/i })).toHaveAttribute(
        'href',
        '/signup',
      );
    });
  });
});
