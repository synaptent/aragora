import { renderHook, act } from '@testing-library/react';
import { useDashboardPreferences } from '@/hooks/useDashboardPreferences';

// Mock localStorage
const mockLocalStorage = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: jest.fn((key: string) => store[key] || null),
    setItem: jest.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: jest.fn((key: string) => {
      delete store[key];
    }),
    clear: jest.fn(() => {
      store = {};
    }),
  };
})();

Object.defineProperty(window, 'localStorage', { value: mockLocalStorage });

describe('useDashboardPreferences', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockLocalStorage.clear();
  });

  describe('initial state', () => {
    it('starts with default preferences', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      expect(result.current.preferences.mode).toBe('focus');
      expect(result.current.preferences.hasSeenOnboarding).toBe(false);
      expect(result.current.preferences.expandedSections).toContain('core-debate');
      expect(result.current.preferences.gauntletFirstRun).toBe(true);
    });

    it('has correct computed values initially', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      expect(result.current.isFocusMode).toBe(true);
      expect(result.current.isExplorerMode).toBe(false);
    });

    it('loads preferences from localStorage', () => {
      const storedPrefs = {
        mode: 'explorer',
        hasSeenOnboarding: true,
        expandedSections: ['core-debate', 'insights-learning'],
        gauntletFirstRun: false,
      };
      mockLocalStorage.getItem.mockReturnValueOnce(JSON.stringify(storedPrefs));

      const { result } = renderHook(() => useDashboardPreferences());

      // Wait for effect to run
      expect(result.current.preferences.mode).toBe('explorer');
      expect(result.current.preferences.hasSeenOnboarding).toBe(true);
    });
  });

  describe('setMode', () => {
    it('changes mode to explorer', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      act(() => {
        result.current.setMode('explorer');
      });

      expect(result.current.preferences.mode).toBe('explorer');
      expect(result.current.isFocusMode).toBe(false);
      expect(result.current.isExplorerMode).toBe(true);
    });

    it('expands more sections when switching to explorer mode', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      act(() => {
        result.current.setMode('explorer');
      });

      expect(result.current.preferences.expandedSections).toContain('core-debate');
      expect(result.current.preferences.expandedSections).toContain('browse-discover');
      expect(result.current.preferences.expandedSections).toContain('agent-analysis');
      expect(result.current.preferences.expandedSections).toContain('insights-learning');
    });

    it('collapses to only core-debate when switching to focus mode', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      act(() => {
        result.current.setMode('explorer');
      });
      act(() => {
        result.current.setMode('focus');
      });

      expect(result.current.preferences.expandedSections).toEqual(['core-debate']);
    });
  });

  describe('toggleSection', () => {
    it('expands a collapsed section', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      expect(result.current.isSectionExpanded('insights-learning')).toBe(false);

      act(() => {
        result.current.toggleSection('insights-learning');
      });

      expect(result.current.isSectionExpanded('insights-learning')).toBe(true);
    });

    it('collapses an expanded section', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      expect(result.current.isSectionExpanded('core-debate')).toBe(true);

      act(() => {
        result.current.toggleSection('core-debate');
      });

      expect(result.current.isSectionExpanded('core-debate')).toBe(false);
    });
  });

  describe('isSectionExpanded', () => {
    it('returns true for expanded sections', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      expect(result.current.isSectionExpanded('core-debate')).toBe(true);
    });

    it('returns false for collapsed sections', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      expect(result.current.isSectionExpanded('nonexistent')).toBe(false);
    });
  });

  describe('markOnboardingComplete', () => {
    it('sets hasSeenOnboarding to true', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      expect(result.current.preferences.hasSeenOnboarding).toBe(false);

      act(() => {
        result.current.markOnboardingComplete();
      });

      expect(result.current.preferences.hasSeenOnboarding).toBe(true);
    });

    it('sets gauntletFirstRun to false', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      expect(result.current.preferences.gauntletFirstRun).toBe(true);

      act(() => {
        result.current.markOnboardingComplete();
      });

      expect(result.current.preferences.gauntletFirstRun).toBe(false);
    });
  });

  describe('resetToDefaults', () => {
    it('resets all preferences to defaults', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      act(() => {
        result.current.setMode('explorer');
        result.current.markOnboardingComplete();
      });

      expect(result.current.preferences.mode).toBe('explorer');
      expect(result.current.preferences.hasSeenOnboarding).toBe(true);

      act(() => {
        result.current.resetToDefaults();
      });

      expect(result.current.preferences.mode).toBe('focus');
      expect(result.current.preferences.hasSeenOnboarding).toBe(false);
      expect(result.current.preferences.gauntletFirstRun).toBe(true);
    });

    it('removes preferences from localStorage', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      act(() => {
        result.current.resetToDefaults();
      });

      expect(mockLocalStorage.removeItem).toHaveBeenCalledWith('aragora-dashboard-prefs');
    });
  });

  describe('localStorage persistence', () => {
    it('saves preferences to localStorage when changed', () => {
      const { result } = renderHook(() => useDashboardPreferences());

      // Wait for isLoaded to be true
      act(() => {
        result.current.setMode('explorer');
      });

      expect(mockLocalStorage.setItem).toHaveBeenCalled();
      const savedValue = mockLocalStorage.setItem.mock.calls.find(
        (call: string[]) => call[0] === 'aragora-dashboard-prefs',
      );
      expect(savedValue).toBeDefined();
    });
  });
});
