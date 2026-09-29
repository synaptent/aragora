'use client';

import React, { createContext, useContext, ReactNode } from 'react';
import { useFeatures, type FeaturesResponse, type FeatureInfo } from '@/hooks/useFeatures';

interface FeaturesContextType {
  features: FeaturesResponse | null;
  loading: boolean;
  error: string | null;
  isAvailable: (featureId: string) => boolean;
  getFeatureInfo: (featureId: string) => FeatureInfo | undefined;
  getAvailableFeatures: () => string[];
  getUnavailableFeatures: () => string[];
  refetch: () => Promise<void>;
}

const FeaturesContext = createContext<FeaturesContextType | undefined>(undefined);

interface FeaturesProviderProps {
  children: ReactNode;
  apiBase?: string;
}

/**
 * Provider component for feature availability context
 *
 * Wraps the application to provide feature detection capabilities
 * to all child components. Fetches features once on mount and
 * caches results.
 *
 * @example
 * // In app layout or page
 * <FeaturesProvider apiBase="https://api.aragora.ai">
 *   <App />
 * </FeaturesProvider>
 *
 * // In child components
 * const { isAvailable } = useFeatureContext();
 * if (isAvailable('pulse')) {
 *   // Show trending topics
 * }
 */
export function FeaturesProvider({ children, apiBase }: FeaturesProviderProps) {
  const featuresState = useFeatures(apiBase);

  return <FeaturesContext.Provider value={featuresState}>{children}</FeaturesContext.Provider>;
}

/**
 * Hook to access feature context
 *
 * Must be used within a FeaturesProvider. Returns all feature
 * utilities including availability checks and feature info.
 *
 * @throws Error if used outside of FeaturesProvider
 */
export function useFeatureContext() {
  const context = useContext(FeaturesContext);
  if (context === undefined) {
    throw new Error('useFeatureContext must be used within a FeaturesProvider');
  }
  return context;
}

/**
 * Hook to check if a specific feature is available
 *
 * Convenience wrapper that returns just the availability status.
 * Safe to use - returns true if context is unavailable (graceful degradation).
 *
 * @example
 * const isPulseAvailable = useFeatureStatus('pulse');
 * if (isPulseAvailable) {
 *   // Render pulse panel
 * }
 */
export function useFeatureStatus(featureId: string): boolean {
  const context = useContext(FeaturesContext);
  // Return true by default for graceful degradation
  return context?.isAvailable(featureId) ?? true;
}

/**
 * Hook to get detailed info about a feature
 *
 * Returns feature metadata including name, description, and install hints.
 * Safe to use - returns undefined if context is unavailable.
 *
 * @example
 * const pulseInfo = useFeatureInfo('pulse');
 * console.log(pulseInfo?.install_hint);
 */
export function useFeatureInfo(featureId: string): FeatureInfo | undefined {
  const context = useContext(FeaturesContext);
  return context?.getFeatureInfo(featureId);
}
