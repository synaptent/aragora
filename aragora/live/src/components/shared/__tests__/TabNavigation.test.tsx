import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TabNavigation, Tab } from '../TabNavigation';

const mockTabs: Tab[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'details', label: 'Details' },
  { id: 'settings', label: 'Settings' },
];

describe('TabNavigation', () => {
  describe('rendering', () => {
    it('renders all tabs', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={() => {}} />);

      expect(screen.getByText('Overview')).toBeInTheDocument();
      expect(screen.getByText('Details')).toBeInTheDocument();
      expect(screen.getByText('Settings')).toBeInTheDocument();
    });

    it('renders with tablist role', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={() => {}} />);

      expect(screen.getByRole('tablist')).toBeInTheDocument();
    });

    it('renders tabs with tab role', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={() => {}} />);

      const tabs = screen.getAllByRole('tab');
      expect(tabs).toHaveLength(3);
    });

    it('sets correct aria-label on tablist', () => {
      render(
        <TabNavigation
          tabs={mockTabs}
          activeTab="overview"
          onTabChange={() => {}}
          ariaLabel="Main navigation"
        />,
      );

      expect(screen.getByRole('tablist')).toHaveAttribute('aria-label', 'Main navigation');
    });

    it('uses default aria-label when not provided', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={() => {}} />);

      expect(screen.getByRole('tablist')).toHaveAttribute('aria-label', 'Tab navigation');
    });
  });

  describe('active state', () => {
    it('marks active tab with aria-selected true', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="details" onTabChange={() => {}} />);

      const detailsTab = screen.getByRole('tab', { name: 'Details' });
      expect(detailsTab).toHaveAttribute('aria-selected', 'true');
    });

    it('marks inactive tabs with aria-selected false', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="details" onTabChange={() => {}} />);

      const overviewTab = screen.getByRole('tab', { name: 'Overview' });
      const settingsTab = screen.getByRole('tab', { name: 'Settings' });

      expect(overviewTab).toHaveAttribute('aria-selected', 'false');
      expect(settingsTab).toHaveAttribute('aria-selected', 'false');
    });

    it('applies active styling to selected tab', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={() => {}} />);

      const overviewTab = screen.getByRole('tab', { name: 'Overview' });
      expect(overviewTab).toHaveClass('bg-accent');
    });
  });

  describe('interaction', () => {
    it('calls onTabChange when tab is clicked', async () => {
      const onTabChange = jest.fn();
      const user = userEvent.setup();

      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={onTabChange} />);

      await user.click(screen.getByRole('tab', { name: 'Details' }));

      expect(onTabChange).toHaveBeenCalledWith('details');
    });

    it('calls onTabChange with correct id', async () => {
      const onTabChange = jest.fn();
      const user = userEvent.setup();

      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={onTabChange} />);

      await user.click(screen.getByRole('tab', { name: 'Settings' }));

      expect(onTabChange).toHaveBeenCalledWith('settings');
    });
  });

  describe('variants', () => {
    it('uses default variant by default', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={() => {}} />);

      const tab = screen.getByRole('tab', { name: 'Overview' });
      expect(tab).toHaveClass('px-3', 'py-1', 'text-sm');
    });

    it('applies compact variant styles', () => {
      render(
        <TabNavigation
          tabs={mockTabs}
          activeTab="overview"
          onTabChange={() => {}}
          variant="compact"
        />,
      );

      const tab = screen.getByRole('tab', { name: 'Overview' });
      expect(tab).toHaveClass('px-2', 'py-0.5', 'text-xs');
    });
  });

  describe('aria attributes', () => {
    it('sets correct id on tabs', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={() => {}} />);

      expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('id', 'overview-tab');
      expect(screen.getByRole('tab', { name: 'Details' })).toHaveAttribute('id', 'details-tab');
    });

    it('sets aria-controls on tabs', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={() => {}} />);

      expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute(
        'aria-controls',
        'overview-panel',
      );
    });
  });

  describe('icons', () => {
    it('renders icon when provided', () => {
      const tabsWithIcon: Tab[] = [
        { id: 'home', label: 'Home', icon: <span data-testid="home-icon">🏠</span> },
        { id: 'profile', label: 'Profile' },
      ];

      render(<TabNavigation tabs={tabsWithIcon} activeTab="home" onTabChange={() => {}} />);

      expect(screen.getByTestId('home-icon')).toBeInTheDocument();
    });

    it('does not render icon container when not provided', () => {
      render(<TabNavigation tabs={mockTabs} activeTab="overview" onTabChange={() => {}} />);

      // Tab should only contain label text, no icon span
      const tab = screen.getByRole('tab', { name: 'Overview' });
      expect(tab.querySelector('[class*="mr-1"]')).toBeNull();
    });
  });

  describe('custom className', () => {
    it('applies custom className', () => {
      render(
        <TabNavigation
          tabs={mockTabs}
          activeTab="overview"
          onTabChange={() => {}}
          className="custom-class"
        />,
      );

      expect(screen.getByRole('tablist')).toHaveClass('custom-class');
    });
  });
});
