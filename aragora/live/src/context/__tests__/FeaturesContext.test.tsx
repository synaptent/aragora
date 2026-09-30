/**
 * Tests for FeaturesContext
 *
 * Tests cover:
 * - FeaturesProvider renders children
 * - useFeatureContext returns features state
 * - isAvailable checks feature availability
 * - getFeatureInfo returns feature details
 * - getAvailableFeatures lists available features
 * - getUnavailableFeatures lists unavailable features
 * - useFeatureStatus convenience hook
 * - useFeatureInfo convenience hook
 * - Error when used outside provider
 */

import React from 'react';
import { renderHook } from '@testing-library/react';
import {
  FeaturesProvider,
  useFeatureContext,
  useFeatureStatus,
  useFeatureInfo,
} from '../FeaturesContext';

// Mock the useFeatures hook
jest.mock('@/hooks/useFeatures', () => ({ useFeatures: jest.fn() }));

import { useFeatures } from '@/hooks/useFeatures';
const mockUseFeatures = useFeatures as jest.Mock;

// Sample mock data
const mockFeaturesResponse = {
  features: {
    pulse: {
      available: true,
      name: 'Trending Topics',
      description: 'Real-time trending topic tracking',
      install_hint: null,
    },
    evidence: {
      available: true,
      name: 'Evidence Collection',
      description: 'Collect and track evidence',
      install_hint: null,
    },
    transcription: {
      available: false,
      name: 'Audio Transcription',
      description: 'Transcribe audio files',
      install_hint: 'Set OPENAI_API_KEY to enable',
    },
    slack: {
      available: false,
      name: 'Slack Integration',
      description: 'Connect to Slack',
      install_hint: 'Set SLACK_BOT_TOKEN to enable',
    },
  },
  total: 4,
  available_count: 2,
  unavailable_count: 2,
};

describe('FeaturesContext', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseFeatures.mockReturnValue({
      features: mockFeaturesResponse,
      loading: false,
      error: null,
      isAvailable: (id: string) => mockFeaturesResponse.features[id]?.available ?? false,
      getFeatureInfo: (id: string) => mockFeaturesResponse.features[id],
      getAvailableFeatures: () => ['pulse', 'evidence'],
      getUnavailableFeatures: () => ['transcription', 'slack'],
      refetch: jest.fn(),
    });
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <FeaturesProvider>{children}</FeaturesProvider>
  );

  describe('FeaturesProvider', () => {
    it('renders children', () => {
      mockUseFeatures.mockReturnValue({
        features: null,
        loading: true,
        error: null,
        isAvailable: () => false,
        getFeatureInfo: () => undefined,
        getAvailableFeatures: () => [],
        getUnavailableFeatures: () => [],
        refetch: jest.fn(),
      });

      const TestChild = () => <div>Child Content</div>;
      const { result } = renderHook(() => useFeatureContext(), {
        wrapper: ({ children }) => (
          <FeaturesProvider>
            {children}
            <TestChild />
          </FeaturesProvider>
        ),
      });

      expect(result.current).toBeDefined();
    });

    it('passes apiBase to useFeatures', () => {
      const customWrapper = ({ children }: { children: React.ReactNode }) => (
        <FeaturesProvider apiBase="https://custom.api.com">{children}</FeaturesProvider>
      );

      renderHook(() => useFeatureContext(), { wrapper: customWrapper });

      expect(mockUseFeatures).toHaveBeenCalledWith('https://custom.api.com');
    });
  });

  describe('useFeatureContext', () => {
    it('returns features data', () => {
      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      expect(result.current.features).toEqual(mockFeaturesResponse);
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('isAvailable returns true for available feature', () => {
      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      expect(result.current.isAvailable('pulse')).toBe(true);
      expect(result.current.isAvailable('evidence')).toBe(true);
    });

    it('isAvailable returns false for unavailable feature', () => {
      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      expect(result.current.isAvailable('transcription')).toBe(false);
      expect(result.current.isAvailable('slack')).toBe(false);
    });

    it('isAvailable returns false for unknown feature', () => {
      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      expect(result.current.isAvailable('unknown-feature')).toBe(false);
    });

    it('getFeatureInfo returns feature details', () => {
      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      const pulseInfo = result.current.getFeatureInfo('pulse');
      expect(pulseInfo).toEqual({
        available: true,
        name: 'Trending Topics',
        description: 'Real-time trending topic tracking',
        install_hint: null,
      });
    });

    it('getFeatureInfo returns undefined for unknown feature', () => {
      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      expect(result.current.getFeatureInfo('unknown')).toBeUndefined();
    });

    it('getAvailableFeatures returns list of available features', () => {
      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      expect(result.current.getAvailableFeatures()).toEqual(['pulse', 'evidence']);
    });

    it('getUnavailableFeatures returns list of unavailable features', () => {
      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      expect(result.current.getUnavailableFeatures()).toEqual(['transcription', 'slack']);
    });

    it('throws error when used outside FeaturesProvider', () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();

      expect(() => {
        renderHook(() => useFeatureContext());
      }).toThrow('useFeatureContext must be used within a FeaturesProvider');

      consoleSpy.mockRestore();
    });
  });

  describe('useFeatureStatus', () => {
    it('returns true for available feature', () => {
      const { result } = renderHook(() => useFeatureStatus('pulse'), { wrapper });

      expect(result.current).toBe(true);
    });

    it('returns false for unavailable feature', () => {
      const { result } = renderHook(() => useFeatureStatus('transcription'), { wrapper });

      expect(result.current).toBe(false);
    });

    it('returns true (graceful degradation) when outside provider', () => {
      // This hook should NOT throw, instead returns true for graceful degradation
      const { result } = renderHook(() => useFeatureStatus('any-feature'));

      expect(result.current).toBe(true);
    });
  });

  describe('useFeatureInfo', () => {
    it('returns feature info for known feature', () => {
      const { result } = renderHook(() => useFeatureInfo('transcription'), { wrapper });

      expect(result.current).toEqual({
        available: false,
        name: 'Audio Transcription',
        description: 'Transcribe audio files',
        install_hint: 'Set OPENAI_API_KEY to enable',
      });
    });

    it('returns undefined for unknown feature', () => {
      const { result } = renderHook(() => useFeatureInfo('unknown'), { wrapper });

      expect(result.current).toBeUndefined();
    });

    it('returns undefined when outside provider', () => {
      const { result } = renderHook(() => useFeatureInfo('pulse'));

      expect(result.current).toBeUndefined();
    });
  });

  describe('Loading and Error States', () => {
    it('returns loading state', () => {
      mockUseFeatures.mockReturnValue({
        features: null,
        loading: true,
        error: null,
        isAvailable: () => false,
        getFeatureInfo: () => undefined,
        getAvailableFeatures: () => [],
        getUnavailableFeatures: () => [],
        refetch: jest.fn(),
      });

      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      expect(result.current.loading).toBe(true);
      expect(result.current.features).toBeNull();
    });

    it('returns error state', () => {
      mockUseFeatures.mockReturnValue({
        features: null,
        loading: false,
        error: 'Failed to fetch features',
        isAvailable: () => false,
        getFeatureInfo: () => undefined,
        getAvailableFeatures: () => [],
        getUnavailableFeatures: () => [],
        refetch: jest.fn(),
      });

      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      expect(result.current.error).toBe('Failed to fetch features');
    });

    it('provides refetch function', async () => {
      const mockRefetch = jest.fn();
      mockUseFeatures.mockReturnValue({
        features: mockFeaturesResponse,
        loading: false,
        error: null,
        isAvailable: () => true,
        getFeatureInfo: () => undefined,
        getAvailableFeatures: () => [],
        getUnavailableFeatures: () => [],
        refetch: mockRefetch,
      });

      const { result } = renderHook(() => useFeatureContext(), { wrapper });

      await result.current.refetch();

      expect(mockRefetch).toHaveBeenCalled();
    });
  });
});
