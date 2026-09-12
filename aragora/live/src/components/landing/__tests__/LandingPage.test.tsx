import { render, screen } from '@testing-library/react';
import { LandingPage } from '../LandingPage';

const mockUseBackend = jest.fn(() => ({
  config: { api: 'http://localhost:8080', ws: 'ws://localhost:8765/ws' },
}));

jest.mock('@/context/ThemeContext', () => ({
  useTheme: () => ({ theme: 'dark', setTheme: jest.fn() }),
}));

jest.mock('../../BackendSelector', () => ({
  BACKENDS: { production: { api: 'https://api.example.com', ws: 'wss://api.example.com/ws' } },
  useBackend: () => mockUseBackend(),
}));

// Mock all child components to isolate LandingPage logic
jest.mock('../Header', () => ({ Header: () => <header data-testid="header">Header</header> }));

jest.mock('../HeroSection', () => ({
  HeroSection: () => <div data-testid="hero-section">Hero</div>,
}));

const mockLiveDebatePanel = jest.fn(() => (
  <section data-testid="live-debate-panel">Live Debate</section>
));

jest.mock('../LiveDebatePanel', () => ({
  LiveDebatePanel: (props: Record<string, unknown>) => {
    mockLiveDebatePanel(props);
    return <section data-testid="live-debate-panel">Live Debate</section>;
  },
}));

jest.mock('../LiveDemoSection', () => ({
  LiveDemoSection: () => <section data-testid="live-demo-section">Live Demo</section>,
}));

jest.mock('../HowItWorksSection', () => ({
  HowItWorksSection: () => <section data-testid="how-it-works">How It Works</section>,
}));

jest.mock('../ProblemSection', () => ({
  ProblemSection: () => <section data-testid="problem">Problem</section>,
}));

jest.mock('../PricingSection', () => ({
  PricingSection: () => <section data-testid="pricing-section">Pricing</section>,
}));

jest.mock('../Footer', () => ({ Footer: () => <footer data-testid="footer">Footer</footer> }));

describe('LandingPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseBackend.mockReturnValue({
      config: { api: 'http://localhost:8080', ws: 'ws://localhost:8765/ws' },
    });
  });

  describe('initial render', () => {
    it('renders all page sections', () => {
      render(<LandingPage />);

      expect(screen.getByTestId('header')).toBeInTheDocument();
      expect(screen.getByTestId('hero-section')).toBeInTheDocument();
      expect(screen.getByTestId('live-debate-panel')).toBeInTheDocument();
      expect(screen.getByTestId('live-demo-section')).toBeInTheDocument();
      expect(screen.getByTestId('how-it-works')).toBeInTheDocument();
      expect(screen.getByTestId('problem')).toBeInTheDocument();
      expect(screen.getByTestId('pricing-section')).toBeInTheDocument();
      expect(screen.getByTestId('footer')).toBeInTheDocument();
    });

    it('renders the themed container with min-h-screen', () => {
      const { container } = render(<LandingPage />);

      const wrapper = container.firstElementChild;
      expect(wrapper).toHaveClass('min-h-screen');
      expect(wrapper).toHaveAttribute('data-landing-theme', 'dark');
    });

    it('passes resolved backend settings to the live debate panel', () => {
      render(<LandingPage />);

      expect(mockLiveDebatePanel).toHaveBeenCalledWith(
        expect.objectContaining({
          apiBase: 'http://localhost:8080',
          wsUrl: 'ws://localhost:8765/ws',
        }),
      );
    });
  });
});
