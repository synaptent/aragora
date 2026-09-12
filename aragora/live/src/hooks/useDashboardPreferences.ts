'use client';

import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';

export type DashboardMode = 'focus' | 'explorer';

export interface DashboardPreferences {
  mode: DashboardMode;
  hasSeenOnboarding: boolean;
  expandedSections: string[];
  gauntletFirstRun: boolean;
}

const DEFAULT_PREFERENCES: DashboardPreferences = {
  mode: 'focus', // New users start in focus mode
  hasSeenOnboarding: false,
  expandedSections: ['core-debate'], // Only core debate expanded by default
  gauntletFirstRun: true, // Show gauntlet prompt on first run
};

const STORAGE_KEY = 'aragora-dashboard-prefs';

export function useDashboardPreferences() {
  const [preferences, setPreferences] = useState<DashboardPreferences>(DEFAULT_PREFERENCES);
  const [isLoaded, setIsLoaded] = useState(false);

  // Load preferences from localStorage on mount
  useEffect(() => {
    if (typeof window === 'undefined') return;

    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        setPreferences({ ...DEFAULT_PREFERENCES, ...parsed });
      }
    } catch (e) {
      logger.error('Failed to load dashboard preferences:', e);
    }
    setIsLoaded(true);
  }, []);

  // Save preferences to localStorage when they change
  useEffect(() => {
    if (!isLoaded) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
    } catch (e) {
      logger.error('Failed to save dashboard preferences:', e);
    }
  }, [preferences, isLoaded]);

  const setMode = useCallback((mode: DashboardMode) => {
    setPreferences((prev) => ({
      ...prev,
      mode,
      // When switching to explorer mode, expand more sections
      expandedSections:
        mode === 'explorer'
          ? ['core-debate', 'browse-discover', 'agent-analysis', 'insights-learning']
          : ['core-debate'],
    }));
  }, []);

  const toggleSection = useCallback((sectionId: string) => {
    setPreferences((prev) => ({
      ...prev,
      expandedSections: prev.expandedSections.includes(sectionId)
        ? prev.expandedSections.filter((id) => id !== sectionId)
        : [...prev.expandedSections, sectionId],
    }));
  }, []);

  const isSectionExpanded = useCallback(
    (sectionId: string) => {
      return preferences.expandedSections.includes(sectionId);
    },
    [preferences.expandedSections],
  );

  const markOnboardingComplete = useCallback(() => {
    setPreferences((prev) => ({ ...prev, hasSeenOnboarding: true, gauntletFirstRun: false }));
  }, []);

  const resetToDefaults = useCallback(() => {
    setPreferences(DEFAULT_PREFERENCES);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return {
    preferences,
    isLoaded,
    setMode,
    toggleSection,
    isSectionExpanded,
    markOnboardingComplete,
    resetToDefaults,
    isFocusMode: preferences.mode === 'focus',
    isExplorerMode: preferences.mode === 'explorer',
  };
}
