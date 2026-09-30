/**
 * Tests for settingsStore
 *
 * Tests cover:
 * - Theme management
 * - Notification preferences
 * - Display preferences
 * - Integration configuration
 * - Feature configuration
 * - API key management
 * - Backend configuration
 * - Save status tracking
 * - Reset functionality
 * - Selectors
 */

import { act } from '@testing-library/react';
import {
  useSettingsStore,
  selectTheme,
  selectNotifications,
  selectDisplay,
  selectIntegrations,
  selectFeatureConfig,
  selectApiKeys,
  selectBackend,
  selectSaveStatus,
  APIKey,
} from '../settingsStore';

// Sample test data
const mockApiKey: APIKey = {
  id: 'key-1',
  name: 'Production Key',
  prefix: 'sk-prod',
  createdAt: '2026-01-01T00:00:00Z',
  lastUsed: '2026-01-25T10:00:00Z',
};

const mockApiKey2: APIKey = {
  id: 'key-2',
  name: 'Test Key',
  prefix: 'sk-test',
  createdAt: '2026-01-15T00:00:00Z',
};

describe('settingsStore', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    act(() => {
      useSettingsStore.getState().resetAll();
    });
  });

  describe('Theme Management', () => {
    it('starts with dark theme by default', () => {
      expect(useSettingsStore.getState().preferences.theme).toBe('dark');
    });

    it('setTheme changes theme', () => {
      act(() => {
        useSettingsStore.getState().setTheme('light');
      });

      expect(useSettingsStore.getState().preferences.theme).toBe('light');
    });

    it('setTheme supports system theme', () => {
      act(() => {
        useSettingsStore.getState().setTheme('system');
      });

      expect(useSettingsStore.getState().preferences.theme).toBe('system');
    });
  });

  describe('Notification Preferences', () => {
    it('has default notification settings', () => {
      const notifications = useSettingsStore.getState().preferences.notifications;
      expect(notifications.debateComplete).toBe(true);
      expect(notifications.consensusReached).toBe(true);
      expect(notifications.mentions).toBe(true);
      expect(notifications.systemAlerts).toBe(true);
    });

    it('updateNotifications updates partial settings', () => {
      act(() => {
        useSettingsStore.getState().updateNotifications({ debateComplete: false });
      });

      const notifications = useSettingsStore.getState().preferences.notifications;
      expect(notifications.debateComplete).toBe(false);
      expect(notifications.consensusReached).toBe(true); // Unchanged
    });

    it('updateNotifications merges multiple updates', () => {
      act(() => {
        useSettingsStore.getState().updateNotifications({ debateComplete: false, mentions: false });
      });

      const notifications = useSettingsStore.getState().preferences.notifications;
      expect(notifications.debateComplete).toBe(false);
      expect(notifications.mentions).toBe(false);
      expect(notifications.consensusReached).toBe(true);
    });
  });

  describe('Display Preferences', () => {
    it('has default display settings', () => {
      const display = useSettingsStore.getState().preferences.display;
      expect(display.compactMode).toBe(false);
      expect(display.showTimestamps).toBe(true);
      expect(display.showRounds).toBe(true);
      expect(display.animationsEnabled).toBe(true);
    });

    it('updateDisplay updates partial settings', () => {
      act(() => {
        useSettingsStore.getState().updateDisplay({ compactMode: true });
      });

      const display = useSettingsStore.getState().preferences.display;
      expect(display.compactMode).toBe(true);
      expect(display.showTimestamps).toBe(true); // Unchanged
    });

    it('updateDisplay can disable animations', () => {
      act(() => {
        useSettingsStore.getState().updateDisplay({ animationsEnabled: false });
      });

      expect(useSettingsStore.getState().preferences.display.animationsEnabled).toBe(false);
    });
  });

  describe('Integration Configuration', () => {
    it('has default integration settings', () => {
      const integrations = useSettingsStore.getState().preferences.integrations;
      expect(integrations.slackWebhook).toBe('');
      expect(integrations.discordWebhook).toBe('');
      expect(integrations.slackNotifications.debateComplete).toBe(false);
    });

    it('updateIntegrations sets webhook URLs', () => {
      act(() => {
        useSettingsStore
          .getState()
          .updateIntegrations({ slackWebhook: 'https://hooks.slack.com/services/xxx' });
      });

      expect(useSettingsStore.getState().preferences.integrations.slackWebhook).toBe(
        'https://hooks.slack.com/services/xxx',
      );
    });

    it('updateSlackNotifications updates Slack notification settings', () => {
      act(() => {
        useSettingsStore.getState().updateSlackNotifications({ debateComplete: true });
      });

      expect(
        useSettingsStore.getState().preferences.integrations.slackNotifications.debateComplete,
      ).toBe(true);
    });

    it('updateSlackNotifications preserves other Slack settings', () => {
      act(() => {
        useSettingsStore.getState().updateSlackNotifications({ debateComplete: true });
        useSettingsStore.getState().updateSlackNotifications({ consensusReached: true });
      });

      const slackNotifications =
        useSettingsStore.getState().preferences.integrations.slackNotifications;
      expect(slackNotifications.debateComplete).toBe(true);
      expect(slackNotifications.consensusReached).toBe(true);
    });
  });

  describe('Feature Configuration', () => {
    it('has default feature settings', () => {
      const features = useSettingsStore.getState().featureConfig;
      expect(features.streaming).toBe(true);
      expect(features.calibration).toBe(false);
      expect(features.trickster).toBe(false);
    });

    it('setFeatureConfig replaces all features', () => {
      act(() => {
        useSettingsStore
          .getState()
          .setFeatureConfig({
            calibration: true,
            trickster: true,
            rhetorical: true,
            streaming: false,
            audience: false,
            citations: false,
            memory: false,
            evidenceCollection: false,
          });
      });

      const features = useSettingsStore.getState().featureConfig;
      expect(features.calibration).toBe(true);
      expect(features.streaming).toBe(false);
    });

    it('toggleFeature toggles specific feature', () => {
      expect(useSettingsStore.getState().featureConfig.calibration).toBe(false);

      act(() => {
        useSettingsStore.getState().toggleFeature('calibration');
      });

      expect(useSettingsStore.getState().featureConfig.calibration).toBe(true);

      act(() => {
        useSettingsStore.getState().toggleFeature('calibration');
      });

      expect(useSettingsStore.getState().featureConfig.calibration).toBe(false);
    });

    it('setFeatureLoading updates loading state', () => {
      act(() => {
        useSettingsStore.getState().setFeatureLoading(true);
      });

      expect(useSettingsStore.getState().featureLoading).toBe(true);
    });
  });

  describe('API Key Management', () => {
    it('starts with empty API keys', () => {
      expect(useSettingsStore.getState().apiKeys).toHaveLength(0);
    });

    it('setApiKeys replaces all keys', () => {
      act(() => {
        useSettingsStore.getState().setApiKeys([mockApiKey, mockApiKey2]);
      });

      expect(useSettingsStore.getState().apiKeys).toHaveLength(2);
    });

    it('addApiKey adds new key', () => {
      act(() => {
        useSettingsStore.getState().addApiKey(mockApiKey);
      });

      expect(useSettingsStore.getState().apiKeys).toHaveLength(1);
      expect(useSettingsStore.getState().apiKeys[0].name).toBe('Production Key');
    });

    it('addApiKey appends to existing keys', () => {
      act(() => {
        useSettingsStore.getState().addApiKey(mockApiKey);
        useSettingsStore.getState().addApiKey(mockApiKey2);
      });

      expect(useSettingsStore.getState().apiKeys).toHaveLength(2);
    });

    it('removeApiKey removes key by ID', () => {
      act(() => {
        useSettingsStore.getState().setApiKeys([mockApiKey, mockApiKey2]);
        useSettingsStore.getState().removeApiKey('key-1');
      });

      const keys = useSettingsStore.getState().apiKeys;
      expect(keys).toHaveLength(1);
      expect(keys[0].id).toBe('key-2');
    });
  });

  describe('Backend Configuration', () => {
    it('has default backend settings', () => {
      const backend = useSettingsStore.getState().backend;
      expect(backend.apiUrl).toBeDefined();
      expect(backend.wsUrl).toBeDefined();
      expect(backend.defaultRounds).toBe(9);
    });

    it('setBackendConfig updates partial config', () => {
      act(() => {
        useSettingsStore.getState().setBackendConfig({ apiUrl: 'https://api.aragora.io' });
      });

      const backend = useSettingsStore.getState().backend;
      expect(backend.apiUrl).toBe('https://api.aragora.io');
      expect(backend.defaultRounds).toBe(9); // Unchanged
    });

    it('setBackendConfig can update default agents', () => {
      act(() => {
        useSettingsStore.getState().setBackendConfig({ defaultAgents: ['claude-3', 'gpt-4'] });
      });

      expect(useSettingsStore.getState().backend.defaultAgents).toEqual(['claude-3', 'gpt-4']);
    });
  });

  describe('Save Status', () => {
    it('starts with idle status', () => {
      const state = useSettingsStore.getState();
      expect(state.saveStatus).toBe('idle');
      expect(state.saveError).toBeNull();
    });

    it('setSaveStatus updates status to saving', () => {
      act(() => {
        useSettingsStore.getState().setSaveStatus('saving');
      });

      expect(useSettingsStore.getState().saveStatus).toBe('saving');
    });

    it('setSaveStatus updates status with error', () => {
      act(() => {
        useSettingsStore.getState().setSaveStatus('error', 'Network error');
      });

      const state = useSettingsStore.getState();
      expect(state.saveStatus).toBe('error');
      expect(state.saveError).toBe('Network error');
    });

    it('setSaveStatus clears error when status is not error', () => {
      act(() => {
        useSettingsStore.getState().setSaveStatus('error', 'Some error');
        useSettingsStore.getState().setSaveStatus('saved');
      });

      const state = useSettingsStore.getState();
      expect(state.saveStatus).toBe('saved');
      expect(state.saveError).toBeNull();
    });
  });

  describe('Reset Functions', () => {
    it('resetPreferences resets only preferences', () => {
      act(() => {
        useSettingsStore.getState().setTheme('light');
        useSettingsStore.getState().addApiKey(mockApiKey);
        useSettingsStore.getState().resetPreferences();
      });

      const state = useSettingsStore.getState();
      expect(state.preferences.theme).toBe('dark'); // Reset
      expect(state.apiKeys).toHaveLength(1); // Not reset
    });

    it('resetAll resets all state', () => {
      act(() => {
        useSettingsStore.getState().setTheme('light');
        useSettingsStore.getState().addApiKey(mockApiKey);
        useSettingsStore.getState().toggleFeature('calibration');
        useSettingsStore.getState().setSaveStatus('error', 'Error');
        useSettingsStore.getState().resetAll();
      });

      const state = useSettingsStore.getState();
      expect(state.preferences.theme).toBe('dark');
      expect(state.apiKeys).toHaveLength(0);
      expect(state.featureConfig.calibration).toBe(false);
      expect(state.saveStatus).toBe('idle');
      expect(state.saveError).toBeNull();
    });
  });

  describe('Selectors', () => {
    beforeEach(() => {
      act(() => {
        useSettingsStore.getState().setTheme('light');
        useSettingsStore.getState().updateNotifications({ debateComplete: false });
        useSettingsStore.getState().updateDisplay({ compactMode: true });
        useSettingsStore.getState().updateIntegrations({ slackWebhook: 'https://slack.webhook' });
        useSettingsStore.getState().toggleFeature('calibration');
        useSettingsStore.getState().addApiKey(mockApiKey);
        useSettingsStore.getState().setSaveStatus('saved');
      });
    });

    it('selectTheme returns theme', () => {
      expect(selectTheme(useSettingsStore.getState())).toBe('light');
    });

    it('selectNotifications returns notifications', () => {
      const notifications = selectNotifications(useSettingsStore.getState());
      expect(notifications.debateComplete).toBe(false);
    });

    it('selectDisplay returns display settings', () => {
      const display = selectDisplay(useSettingsStore.getState());
      expect(display.compactMode).toBe(true);
    });

    it('selectIntegrations returns integrations', () => {
      const integrations = selectIntegrations(useSettingsStore.getState());
      expect(integrations.slackWebhook).toBe('https://slack.webhook');
    });

    it('selectFeatureConfig returns feature config', () => {
      const features = selectFeatureConfig(useSettingsStore.getState());
      expect(features.calibration).toBe(true);
    });

    it('selectApiKeys returns API keys', () => {
      const keys = selectApiKeys(useSettingsStore.getState());
      expect(keys).toHaveLength(1);
    });

    it('selectBackend returns backend config', () => {
      const backend = selectBackend(useSettingsStore.getState());
      expect(backend.defaultRounds).toBe(9);
    });

    it('selectSaveStatus returns status and error', () => {
      const { status, error } = selectSaveStatus(useSettingsStore.getState());
      expect(status).toBe('saved');
      expect(error).toBeNull();
    });
  });
});
