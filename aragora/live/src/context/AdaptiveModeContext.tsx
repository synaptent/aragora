'use client';

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  ReactNode,
  useEffect,
} from 'react';

/**
 * Adaptive UI Mode - Simple binary toggle for user experience level
 *
 * - simple: Wizard-driven workflows, auto agent selection, summary results
 * - advanced: Full configuration, custom protocols, raw API explorer
 *
 * This complements the ProgressiveModeContext by providing a simpler
 * user-facing toggle while maintaining granular internal control.
 */
export type AdaptiveMode = 'simple' | 'advanced';

/**
 * Features hidden in simple mode that become visible in advanced mode
 */
export const ADVANCED_FEATURES = [
  'graph-debates',
  'matrix-debates',
  'memory-inspector',
  'plugin-marketplace',
  'workflow-builder',
  'raw-api-explorer',
  'protocol-tuning',
  'custom-agents',
  'evidence-chains',
  'admin-features',
] as const;

export type AdvancedFeature = (typeof ADVANCED_FEATURES)[number];

interface AdaptiveModeContextType {
  /** Current mode: simple or advanced */
  mode: AdaptiveMode;
  /** Toggle between modes */
  toggleMode: () => void;
  /** Set mode explicitly */
  setMode: (mode: AdaptiveMode) => void;
  /** Check if currently in simple mode */
  isSimple: boolean;
  /** Check if currently in advanced mode */
  isAdvanced: boolean;
  /** Check if a specific advanced feature is visible */
  isFeatureEnabled: (feature: AdvancedFeature) => boolean;
  /** Get human-readable mode label */
  modeLabel: string;
  /** Get mode description */
  modeDescription: string;
}

const MODE_LABELS: Record<AdaptiveMode, string> = { simple: 'Simple', advanced: 'Advanced' };

const MODE_DESCRIPTIONS: Record<AdaptiveMode, string> = {
  simple: 'Streamlined interface with guided workflows',
  advanced: 'Full control with all features and configuration options',
};

const STORAGE_KEY = 'aragora-adaptive-mode';

const AdaptiveModeContext = createContext<AdaptiveModeContextType | undefined>(undefined);

export function AdaptiveModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<AdaptiveMode>('simple');

  // Load mode from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'simple' || stored === 'advanced') {
      setModeState(stored);
    }
  }, []);

  // Save mode to localStorage when it changes
  const setMode = useCallback((newMode: AdaptiveMode) => {
    setModeState(newMode);
    localStorage.setItem(STORAGE_KEY, newMode);
  }, []);

  // Toggle between modes
  const toggleMode = useCallback(() => {
    setMode(mode === 'simple' ? 'advanced' : 'simple');
  }, [mode, setMode]);

  // Check if a specific advanced feature is visible
  const isFeatureEnabled = useCallback(
    (_feature: AdvancedFeature) => {
      return mode === 'advanced';
    },
    [mode],
  );

  const value = useMemo<AdaptiveModeContextType>(
    () => ({
      mode,
      toggleMode,
      setMode,
      isSimple: mode === 'simple',
      isAdvanced: mode === 'advanced',
      isFeatureEnabled,
      modeLabel: MODE_LABELS[mode],
      modeDescription: MODE_DESCRIPTIONS[mode],
    }),
    [mode, toggleMode, setMode, isFeatureEnabled],
  );

  return <AdaptiveModeContext.Provider value={value}>{children}</AdaptiveModeContext.Provider>;
}

/**
 * Hook to access the adaptive mode context
 *
 * @throws Error if used outside of AdaptiveModeProvider
 */
export function useAdaptiveMode() {
  const context = useContext(AdaptiveModeContext);
  if (context === undefined) {
    throw new Error('useAdaptiveMode must be used within an AdaptiveModeProvider');
  }
  return context;
}

/**
 * Hook to check if in advanced mode - safe to use outside provider
 *
 * Returns false (simple mode) if context unavailable
 */
export function useIsAdvanced(): boolean {
  const context = useContext(AdaptiveModeContext);
  return context?.isAdvanced ?? false;
}

/**
 * Hook to conditionally render based on mode
 *
 * Returns true if in simple mode or if context unavailable (graceful degradation)
 */
export function useIsSimple(): boolean {
  const context = useContext(AdaptiveModeContext);
  return context?.isSimple ?? true;
}
