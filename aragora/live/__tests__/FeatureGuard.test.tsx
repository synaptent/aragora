/**
 * Tests for FeatureGuard component
 *
 * Tests cover:
 * - Rendering children when feature is available
 * - Showing default fallback when feature unavailable
 * - Custom fallback rendering
 * - hideWhenUnavailable behavior
 * - withFeatureGuard HOC
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { FeatureGuard, withFeatureGuard } from '../src/components/FeatureGuard';

// Mock the FeaturesContext hooks
const mockIsAvailable = jest.fn();
const mockGetFeatureInfo = jest.fn();

jest.mock('../src/context/FeaturesContext', () => ({
  useFeatureStatus: (featureId: string) => mockIsAvailable(featureId),
  useFeatureInfo: (featureId: string) => mockGetFeatureInfo(featureId),
}));

describe('FeatureGuard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('when feature is available', () => {
    beforeEach(() => {
      mockIsAvailable.mockReturnValue(true);
    });

    it('renders children', () => {
      render(
        <FeatureGuard featureId="pulse">
          <div>Pulse content</div>
        </FeatureGuard>,
      );

      expect(screen.getByText('Pulse content')).toBeInTheDocument();
    });

    it('does not render fallback', () => {
      render(
        <FeatureGuard featureId="pulse" fallback={<div>Fallback</div>}>
          <div>Main content</div>
        </FeatureGuard>,
      );

      expect(screen.queryByText('Fallback')).not.toBeInTheDocument();
      expect(screen.getByText('Main content')).toBeInTheDocument();
    });
  });

  describe('when feature is unavailable', () => {
    beforeEach(() => {
      mockIsAvailable.mockReturnValue(false);
    });

    it('renders default unavailable message', () => {
      mockGetFeatureInfo.mockReturnValue(null);

      render(
        <FeatureGuard featureId="pulse">
          <div>Pulse content</div>
        </FeatureGuard>,
      );

      expect(screen.queryByText('Pulse content')).not.toBeInTheDocument();
      expect(screen.getByText(/Unavailable/)).toBeInTheDocument();
    });

    it('renders custom fallback when provided', () => {
      render(
        <FeatureGuard featureId="pulse" fallback={<div>Custom fallback</div>}>
          <div>Pulse content</div>
        </FeatureGuard>,
      );

      expect(screen.queryByText('Pulse content')).not.toBeInTheDocument();
      expect(screen.getByText('Custom fallback')).toBeInTheDocument();
    });

    it('renders nothing when hideWhenUnavailable is true', () => {
      const { container } = render(
        <FeatureGuard featureId="pulse" hideWhenUnavailable>
          <div>Pulse content</div>
        </FeatureGuard>,
      );

      expect(screen.queryByText('Pulse content')).not.toBeInTheDocument();
      expect(container.firstChild).toBeNull();
    });

    it('shows feature name from info', () => {
      mockGetFeatureInfo.mockReturnValue({
        name: 'Trending Topics',
        description: 'Shows trending debate topics',
      });

      render(
        <FeatureGuard featureId="pulse">
          <div>Content</div>
        </FeatureGuard>,
      );

      expect(screen.getByText('Trending Topics Unavailable')).toBeInTheDocument();
    });

    it('shows feature description from info', () => {
      mockGetFeatureInfo.mockReturnValue({
        name: 'Memory',
        description: 'Access to memory systems',
      });

      render(
        <FeatureGuard featureId="memory">
          <div>Content</div>
        </FeatureGuard>,
      );

      expect(screen.getByText('Access to memory systems')).toBeInTheDocument();
    });

    it('shows install hint when available', () => {
      mockGetFeatureInfo.mockReturnValue({
        name: 'Pulse',
        description: 'Trending topics',
        install_hint: 'Run: pip install aragora[pulse]',
      });

      render(
        <FeatureGuard featureId="pulse">
          <div>Content</div>
        </FeatureGuard>,
      );

      expect(screen.getByText('How to enable')).toBeInTheDocument();

      // Click to expand details
      fireEvent.click(screen.getByText('How to enable'));
      expect(screen.getByText('Run: pip install aragora[pulse]')).toBeInTheDocument();
    });

    it('uses featureId as name when info not available', () => {
      mockGetFeatureInfo.mockReturnValue(null);

      render(
        <FeatureGuard featureId="experimental-feature">
          <div>Content</div>
        </FeatureGuard>,
      );

      expect(screen.getByText('experimental-feature Unavailable')).toBeInTheDocument();
    });
  });
});

describe('withFeatureGuard HOC', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  const TestComponent = ({ message }: { message: string }) => <div>Test: {message}</div>;

  it('wraps component with FeatureGuard', () => {
    mockIsAvailable.mockReturnValue(true);

    const GuardedComponent = withFeatureGuard(TestComponent, 'pulse');
    render(<GuardedComponent message="Hello" />);

    expect(screen.getByText('Test: Hello')).toBeInTheDocument();
  });

  it('hides wrapped component when feature unavailable and hideWhenUnavailable', () => {
    mockIsAvailable.mockReturnValue(false);
    mockGetFeatureInfo.mockReturnValue(null);

    const GuardedComponent = withFeatureGuard(TestComponent, 'pulse', {
      hideWhenUnavailable: true,
    });
    const { container } = render(<GuardedComponent message="Hello" />);

    expect(screen.queryByText('Test: Hello')).not.toBeInTheDocument();
    expect(container.firstChild).toBeNull();
  });

  it('shows default fallback when feature unavailable', () => {
    mockIsAvailable.mockReturnValue(false);
    mockGetFeatureInfo.mockReturnValue(null);

    const GuardedComponent = withFeatureGuard(TestComponent, 'pulse');
    render(<GuardedComponent message="Hello" />);

    expect(screen.queryByText('Test: Hello')).not.toBeInTheDocument();
    expect(screen.getByText(/Unavailable/)).toBeInTheDocument();
  });

  it('passes props to wrapped component', () => {
    mockIsAvailable.mockReturnValue(true);

    const GuardedComponent = withFeatureGuard(TestComponent, 'pulse');
    render(<GuardedComponent message="Custom message" />);

    expect(screen.getByText('Test: Custom message')).toBeInTheDocument();
  });
});
