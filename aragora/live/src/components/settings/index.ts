/**
 * Settings Panel components and utilities.
 *
 * This module provides modular settings components for the Aragora dashboard.
 */

// Types
export type { FeatureConfig, UserPreferences, SlackNotifications, SettingsTab } from './types';

export {
  DEFAULT_FEATURE_CONFIG,
  DEFAULT_USER_PREFERENCES,
  DEFAULT_SLACK_NOTIFICATIONS,
  SETTINGS_TABS,
  PREFERENCES_KEY,
  getStoredPreferences,
  storePreferences,
} from './types';

// Components
export { ToggleSwitch } from './ToggleSwitch';
export { FeaturesTab } from './FeaturesTab';
export { ProviderPreferencesTab } from './ProviderPreferencesTab';
