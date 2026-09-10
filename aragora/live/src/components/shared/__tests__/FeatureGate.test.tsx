/**
 * Tests for FeatureGate component and useFeatureFlag hook
 *
 * Tests cover:
 * - Rendering children when feature is enabled
 * - Rendering fallback when feature is disabled
 * - Hook behavior
 */

import { render, screen } from '@testing-library/react';
import { FeatureGate, useFeatureFlag } from '../FeatureGate';
import { renderHook } from '@testing-library/react';

// Mock the featureFlags module
jest.mock('@/lib/featureFlags', () => ({ isFeatureEnabled: jest.fn() }));

import { isFeatureEnabled } from '@/lib/featureFlags';

const mockIsFeatureEnabled = isFeatureEnabled as jest.MockedFunction<typeof isFeatureEnabled>;

describe('FeatureGate', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('when feature is enabled', () => {
    beforeEach(() => {
      mockIsFeatureEnabled.mockReturnValue(true);
    });

    it('renders children', () => {
      render(
        <FeatureGate feature="GRAPH_DEBATES">
          <div>Feature Content</div>
        </FeatureGate>,
      );

      expect(screen.getByText('Feature Content')).toBeInTheDocument();
    });

    it('does not render fallback', () => {
      render(
        <FeatureGate feature="MATRIX_DEBATES" fallback={<div>Fallback Content</div>}>
          <div>Feature Content</div>
        </FeatureGate>,
      );

      expect(screen.getByText('Feature Content')).toBeInTheDocument();
      expect(screen.queryByText('Fallback Content')).not.toBeInTheDocument();
    });

    it('calls isFeatureEnabled with correct feature name', () => {
      render(
        <FeatureGate feature="PULSE_TOPICS">
          <div>Content</div>
        </FeatureGate>,
      );

      expect(mockIsFeatureEnabled).toHaveBeenCalledWith('PULSE_TOPICS');
    });
  });

  describe('when feature is disabled', () => {
    beforeEach(() => {
      mockIsFeatureEnabled.mockReturnValue(false);
    });

    it('does not render children', () => {
      render(
        <FeatureGate feature="GRAPH_DEBATES">
          <div>Feature Content</div>
        </FeatureGate>,
      );

      expect(screen.queryByText('Feature Content')).not.toBeInTheDocument();
    });

    it('renders fallback when provided', () => {
      render(
        <FeatureGate feature="MATRIX_DEBATES" fallback={<div>Coming Soon</div>}>
          <div>Feature Content</div>
        </FeatureGate>,
      );

      expect(screen.getByText('Coming Soon')).toBeInTheDocument();
      expect(screen.queryByText('Feature Content')).not.toBeInTheDocument();
    });

    it('renders nothing when no fallback provided', () => {
      const { container } = render(
        <FeatureGate feature="GRAPH_DEBATES">
          <div>Feature Content</div>
        </FeatureGate>,
      );

      expect(container.textContent).toBe('');
    });
  });

  describe('with complex children', () => {
    beforeEach(() => {
      mockIsFeatureEnabled.mockReturnValue(true);
    });

    it('renders multiple children', () => {
      render(
        <FeatureGate feature="GRAPH_DEBATES">
          <div>Child 1</div>
          <div>Child 2</div>
          <div>Child 3</div>
        </FeatureGate>,
      );

      expect(screen.getByText('Child 1')).toBeInTheDocument();
      expect(screen.getByText('Child 2')).toBeInTheDocument();
      expect(screen.getByText('Child 3')).toBeInTheDocument();
    });

    it('renders nested components', () => {
      const NestedComponent = () => <span>Nested</span>;

      render(
        <FeatureGate feature="GRAPH_DEBATES">
          <NestedComponent />
        </FeatureGate>,
      );

      expect(screen.getByText('Nested')).toBeInTheDocument();
    });
  });
});

describe('useFeatureFlag', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('returns true when feature is enabled', () => {
    mockIsFeatureEnabled.mockReturnValue(true);

    const { result } = renderHook(() => useFeatureFlag('GRAPH_DEBATES'));

    expect(result.current).toBe(true);
    expect(mockIsFeatureEnabled).toHaveBeenCalledWith('GRAPH_DEBATES');
  });

  it('returns false when feature is disabled', () => {
    mockIsFeatureEnabled.mockReturnValue(false);

    const { result } = renderHook(() => useFeatureFlag('MATRIX_DEBATES'));

    expect(result.current).toBe(false);
  });
});
