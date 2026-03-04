import { render, screen } from '@testing-library/react';
import { LandingPage } from '../LandingPage';

jest.mock('@/context/ThemeContext', () => ({
  useTheme: () => ({ theme: 'dark', setTheme: jest.fn() }),
}));

// Mock all child components to isolate LandingPage logic
jest.mock('../Header', () => ({
  Header: () => <header data-testid="header">Header</header>,
}));

jest.mock('../HeroSection', () => ({
  HeroSection: () => (
    <div data-testid="hero-section">Hero</div>
  ),
}));

jest.mock('../HowItWorksSection', () => ({
  HowItWorksSection: () => <section data-testid="how-it-works">How It Works</section>,
}));

jest.mock('../ProblemSection', () => ({
  ProblemSection: () => <section data-testid="problem">Problem</section>,
}));

jest.mock('../FeatureShowcase', () => ({
  FeatureShowcase: () => <section data-testid="features">Features</section>,
}));

jest.mock('../IntegrationsGrid', () => ({
  IntegrationsGrid: () => <section data-testid="integrations">Integrations</section>,
}));

jest.mock('../LiveDemoSection', () => ({
  LiveDemoSection: () => <section data-testid="live-demo">Live Demo</section>,
}));

jest.mock('../PricingSection', () => ({
  PricingSection: () => <section data-testid="pricing-section">Pricing</section>,
}));

jest.mock('../Footer', () => ({
  Footer: () => <footer data-testid="footer">Footer</footer>,
}));

describe('LandingPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial render', () => {
    it('renders all page sections', () => {
      render(<LandingPage />);

      expect(screen.getByTestId('header')).toBeInTheDocument();
      expect(screen.getByTestId('hero-section')).toBeInTheDocument();
      expect(screen.getByTestId('how-it-works')).toBeInTheDocument();
      expect(screen.getByTestId('problem')).toBeInTheDocument();
      expect(screen.getByTestId('features')).toBeInTheDocument();
      expect(screen.getByTestId('integrations')).toBeInTheDocument();
      expect(screen.getByTestId('live-demo')).toBeInTheDocument();
      expect(screen.getByTestId('pricing-section')).toBeInTheDocument();
      expect(screen.getByTestId('footer')).toBeInTheDocument();
    });

    it('renders container with min-h-screen', () => {
      const { container } = render(<LandingPage />);

      const wrapper = container.firstElementChild;
      expect(wrapper).toHaveClass('min-h-screen');
    });

    it('does not render a sidebar', () => {
      render(<LandingPage />);

      // Landing page should not include any sidebar
      expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    });
  });
});
