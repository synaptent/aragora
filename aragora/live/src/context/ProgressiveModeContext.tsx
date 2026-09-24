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
 * Progressive disclosure modes for the UI
 *
 * - simple: Quick debate creation, basic results view
 * - standard: Full debate controls, agent selection, analytics
 * - advanced: Memory config, protocol tuning, workflows, integrations
 * - expert: All 69 pages, API access, admin features, genesis
 */
export type ProgressiveMode = 'simple' | 'standard' | 'advanced' | 'expert';

interface ProgressiveModeContextType {
  mode: ProgressiveMode;
  setMode: (mode: ProgressiveMode) => void;
  isFeatureVisible: (minMode: ProgressiveMode) => boolean;
  modeLabel: string;
  modeDescription: string;
}

const MODE_ORDER: ProgressiveMode[] = ['simple', 'standard', 'advanced', 'expert'];

const MODE_LABELS: Record<ProgressiveMode, string> = {
  simple: 'Simple',
  standard: 'Standard',
  advanced: 'Advanced',
  expert: 'Expert',
};

const MODE_DESCRIPTIONS: Record<ProgressiveMode, string> = {
  simple: 'Quick debate creation with basic results',
  standard: 'Full debate controls and agent selection',
  advanced: 'Memory config, workflows, and integrations',
  expert: 'All features including API access and admin tools',
};

const STORAGE_KEY = 'aragora-progressive-mode';

const ProgressiveModeContext = createContext<ProgressiveModeContextType | undefined>(undefined);

export function ProgressiveModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ProgressiveMode>('simple');

  // Load mode from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && MODE_ORDER.includes(stored as ProgressiveMode)) {
      setModeState(stored as ProgressiveMode);
    }
  }, []);

  // Save mode to localStorage when it changes
  const setMode = useCallback((newMode: ProgressiveMode) => {
    setModeState(newMode);
    localStorage.setItem(STORAGE_KEY, newMode);
  }, []);

  // Check if a feature requiring minMode should be visible
  const isFeatureVisible = useCallback(
    (minMode: ProgressiveMode) => {
      const currentIndex = MODE_ORDER.indexOf(mode);
      const minIndex = MODE_ORDER.indexOf(minMode);
      return currentIndex >= minIndex;
    },
    [mode],
  );

  const value = useMemo<ProgressiveModeContextType>(
    () => ({
      mode,
      setMode,
      isFeatureVisible,
      modeLabel: MODE_LABELS[mode],
      modeDescription: MODE_DESCRIPTIONS[mode],
    }),
    [mode, setMode, isFeatureVisible],
  );

  return (
    <ProgressiveModeContext.Provider value={value}>{children}</ProgressiveModeContext.Provider>
  );
}

/**
 * Hook to access the progressive mode context
 *
 * @throws Error if used outside of ProgressiveModeProvider
 */
export function useProgressiveMode() {
  const context = useContext(ProgressiveModeContext);
  if (context === undefined) {
    throw new Error('useProgressiveMode must be used within a ProgressiveModeProvider');
  }
  return context;
}

/**
 * Hook to check if current mode meets minimum requirement
 *
 * Safe to use - returns true if context unavailable (graceful degradation)
 */
export function useMinMode(minMode: ProgressiveMode): boolean {
  const context = useContext(ProgressiveModeContext);
  if (!context) return true; // Graceful degradation
  return context.isFeatureVisible(minMode);
}

/**
 * Helper to get all modes and their info
 */
export function getModeInfo(): Array<{
  mode: ProgressiveMode;
  label: string;
  description: string;
}> {
  return MODE_ORDER.map((mode) => ({
    mode,
    label: MODE_LABELS[mode],
    description: MODE_DESCRIPTIONS[mode],
  }));
}
