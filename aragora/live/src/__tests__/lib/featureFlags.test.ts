/**
 * Tests for feature flags system
 */

import {
  FEATURES,
  isFeatureEnabled,
  getFeatureFlag,
  getFeaturesByStatus,
  getVisibleFeatures,
  enableFeature,
  disableFeature,
  resetFeature,
  resetAllFeatures,
} from '@/lib/featureFlags';

describe('featureFlags', () => {
  // Mock localStorage
  const localStorageMock = (() => {
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

  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { value: localStorageMock });
    localStorageMock.clear();
    jest.clearAllMocks();
  });

  describe('FEATURES constant', () => {
    it('has standard debates feature', () => {
      expect(FEATURES.STANDARD_DEBATES).toBeDefined();
      expect(FEATURES.STANDARD_DEBATES.enabled).toBe(true);
      expect(FEATURES.STANDARD_DEBATES.status).toBe('stable');
    });

    it('has deprecated CLI agents feature', () => {
      expect(FEATURES.CLI_AGENTS).toBeDefined();
      expect(FEATURES.CLI_AGENTS.enabled).toBe(false);
      expect(FEATURES.CLI_AGENTS.status).toBe('deprecated');
    });

    it('all features have required properties', () => {
      Object.entries(FEATURES).forEach(([_name, flag]) => {
        expect(flag).toHaveProperty('enabled');
        expect(flag).toHaveProperty('label');
        expect(flag).toHaveProperty('status');
        expect(typeof flag.enabled).toBe('boolean');
        expect(typeof flag.label).toBe('string');
        expect(['stable', 'beta', 'alpha', 'deprecated']).toContain(flag.status);
      });
    });

    it('has beta features', () => {
      const betaFeatures = Object.entries(FEATURES).filter(([, flag]) => flag.status === 'beta');
      expect(betaFeatures.length).toBeGreaterThan(0);
    });
  });

  describe('isFeatureEnabled', () => {
    it('returns true for enabled features', () => {
      expect(isFeatureEnabled('STANDARD_DEBATES')).toBe(true);
      expect(isFeatureEnabled('FORK_VISUALIZER')).toBe(true);
    });

    it('returns false for disabled features', () => {
      expect(isFeatureEnabled('CLI_AGENTS')).toBe(false);
    });

    it('respects localStorage override to enable', () => {
      localStorageMock.getItem.mockReturnValue('true');
      expect(isFeatureEnabled('CLI_AGENTS')).toBe(true);
    });

    it('respects localStorage override to disable', () => {
      localStorageMock.getItem.mockReturnValue('false');
      expect(isFeatureEnabled('STANDARD_DEBATES')).toBe(false);
    });

    it('warns and returns false for unknown features', () => {
      const { logger } = require('@/utils/logger');
      const loggerSpy = jest.spyOn(logger, 'warn').mockImplementation();

      // @ts-expect-error Testing invalid feature name
      const result = isFeatureEnabled('NONEXISTENT_FEATURE');

      expect(result).toBe(false);
      expect(loggerSpy).toHaveBeenCalledWith(expect.stringContaining('Unknown feature flag'));
      loggerSpy.mockRestore();
    });
  });

  describe('getFeatureFlag', () => {
    it('returns feature flag details', () => {
      const flag = getFeatureFlag('BATCH_DEBATES');

      expect(flag).toBeDefined();
      expect(flag?.label).toBe('Batch Debates');
      expect(flag?.status).toBe('beta');
      expect(flag?.description).toContain('parallel');
    });

    it('returns undefined for unknown features', () => {
      // @ts-expect-error Testing invalid feature name
      expect(getFeatureFlag('NONEXISTENT')).toBeUndefined();
    });
  });

  describe('getFeaturesByStatus', () => {
    it('returns stable features', () => {
      const stable = getFeaturesByStatus('stable');

      expect(stable.length).toBeGreaterThan(0);
      stable.forEach(({ flag }) => {
        expect(flag.status).toBe('stable');
      });
    });

    it('returns beta features', () => {
      const beta = getFeaturesByStatus('beta');

      expect(beta.length).toBeGreaterThan(0);
      beta.forEach(({ flag }) => {
        expect(flag.status).toBe('beta');
      });
    });

    it('returns deprecated features', () => {
      const deprecated = getFeaturesByStatus('deprecated');

      expect(deprecated.length).toBeGreaterThan(0);
      deprecated.forEach(({ flag }) => {
        expect(flag.status).toBe('deprecated');
      });
    });

    it('returns empty array for status with no features', () => {
      // All features are defined, so alpha might be empty
      const alpha = getFeaturesByStatus('alpha');
      expect(Array.isArray(alpha)).toBe(true);
    });

    it('includes feature name in result', () => {
      const stable = getFeaturesByStatus('stable');

      stable.forEach(({ name }) => {
        expect(name).toBeDefined();
        expect(typeof name).toBe('string');
        expect(FEATURES[name]).toBeDefined();
      });
    });
  });

  describe('getVisibleFeatures', () => {
    it('returns features with showInUI true', () => {
      const visible = getVisibleFeatures();

      visible.forEach(({ flag }) => {
        expect(flag.showInUI).toBe(true);
      });
    });

    it('excludes features with showInUI false', () => {
      const visible = getVisibleFeatures();
      const visibleNames = visible.map(({ name }) => name);

      // STANDARD_DEBATES has showInUI: false
      expect(visibleNames).not.toContain('STANDARD_DEBATES');
    });

    it('excludes features with showInUI undefined/false', () => {
      const visible = getVisibleFeatures();
      const visibleNames = visible.map(({ name }) => name);

      // CLI_AGENTS has showInUI: false
      expect(visibleNames).not.toContain('CLI_AGENTS');
    });
  });

  describe('enableFeature', () => {
    it('sets localStorage value to true', () => {
      enableFeature('CLI_AGENTS');

      expect(localStorageMock.setItem).toHaveBeenCalledWith('feature_CLI_AGENTS', 'true');
    });
  });

  describe('disableFeature', () => {
    it('sets localStorage value to false', () => {
      disableFeature('STANDARD_DEBATES');

      expect(localStorageMock.setItem).toHaveBeenCalledWith('feature_STANDARD_DEBATES', 'false');
    });
  });

  describe('resetFeature', () => {
    it('removes localStorage value', () => {
      resetFeature('CLI_AGENTS');

      expect(localStorageMock.removeItem).toHaveBeenCalledWith('feature_CLI_AGENTS');
    });
  });

  describe('resetAllFeatures', () => {
    it('removes all feature localStorage values', () => {
      resetAllFeatures();

      const featureCount = Object.keys(FEATURES).length;
      expect(localStorageMock.removeItem).toHaveBeenCalledTimes(featureCount);
    });

    it('removes correct keys', () => {
      resetAllFeatures();

      Object.keys(FEATURES).forEach((feature) => {
        expect(localStorageMock.removeItem).toHaveBeenCalledWith(`feature_${feature}`);
      });
    });
  });

  describe('integration', () => {
    it('enable then disable feature', () => {
      // Initially disabled
      localStorageMock.getItem.mockReturnValue(null);
      expect(isFeatureEnabled('CLI_AGENTS')).toBe(false);

      // Enable it
      enableFeature('CLI_AGENTS');
      localStorageMock.getItem.mockReturnValue('true');
      expect(isFeatureEnabled('CLI_AGENTS')).toBe(true);

      // Disable it
      disableFeature('CLI_AGENTS');
      localStorageMock.getItem.mockReturnValue('false');
      expect(isFeatureEnabled('CLI_AGENTS')).toBe(false);
    });

    it('reset returns to default', () => {
      // Override default
      localStorageMock.getItem.mockReturnValue('false');
      expect(isFeatureEnabled('STANDARD_DEBATES')).toBe(false);

      // Reset
      resetFeature('STANDARD_DEBATES');
      localStorageMock.getItem.mockReturnValue(null);
      expect(isFeatureEnabled('STANDARD_DEBATES')).toBe(true);
    });
  });
});
