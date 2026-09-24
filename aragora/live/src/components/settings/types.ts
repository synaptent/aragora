/**
 * Type definitions for Settings Panel.
 */

export interface FeatureConfig {
  // Feature toggles
  calibration: boolean;
  trickster: boolean;
  rhetorical: boolean;
  insights: boolean;
  moments: boolean;
  crux: boolean;
  evolution: boolean;
  continuum_memory: boolean;
  consensus_memory: boolean;
  supermemory: boolean;
  laboratory: boolean;
  // Display
  show_advanced_metrics: boolean;
  compact_mode: boolean;
  theme: string;
  // Debate defaults
  default_mode: string;
  default_rounds: number;
  default_agents: string;
  // Notifications
  telegram_enabled: boolean;
  email_digest: string;
  consensus_alert_threshold: number;
}

export const DEFAULT_FEATURE_CONFIG: FeatureConfig = {
  calibration: true,
  trickster: false,
  rhetorical: true,
  insights: true,
  moments: true,
  crux: true,
  evolution: true,
  continuum_memory: true,
  consensus_memory: true,
  supermemory: false,
  laboratory: true,
  show_advanced_metrics: false,
  compact_mode: false,
  theme: 'system',
  default_mode: 'standard',
  default_rounds: 9,
  default_agents: 'grok,anthropic-api,openai-api,deepseek,mistral,gemini,qwen,kimi',
  telegram_enabled: false,
  email_digest: 'none',
  consensus_alert_threshold: 0.7,
};

export interface UserPreferences {
  theme: 'dark' | 'light' | 'system';
  notifications: { email_digest: boolean; debate_completed: boolean; weekly_summary: boolean };
  display: { compact_mode: boolean; show_agent_icons: boolean; auto_scroll_messages: boolean };
  api_keys: { name: string; prefix: string; created_at: string; last_used: string | null }[];
  integrations: { slack_webhook: string | null; discord_webhook: string | null };
}

export const DEFAULT_USER_PREFERENCES: UserPreferences = {
  theme: 'dark',
  notifications: { email_digest: true, debate_completed: true, weekly_summary: false },
  display: { compact_mode: false, show_agent_icons: true, auto_scroll_messages: true },
  api_keys: [],
  integrations: { slack_webhook: null, discord_webhook: null },
};

export interface SlackNotifications {
  notify_on_consensus: boolean;
  notify_on_debate_end: boolean;
  notify_on_error: boolean;
  notify_on_leaderboard: boolean;
}

export const DEFAULT_SLACK_NOTIFICATIONS: SlackNotifications = {
  notify_on_consensus: true,
  notify_on_debate_end: true,
  notify_on_error: true,
  notify_on_leaderboard: false,
};

export type SettingsTab =
  'features' | 'debate' | 'appearance' | 'notifications' | 'api' | 'integrations' | 'account';

export const SETTINGS_TABS: { id: SettingsTab; label: string }[] = [
  { id: 'features', label: 'FEATURES' },
  { id: 'debate', label: 'DEBATE' },
  { id: 'appearance', label: 'APPEARANCE' },
  { id: 'notifications', label: 'NOTIFICATIONS' },
  { id: 'api', label: 'API KEYS' },
  { id: 'integrations', label: 'INTEGRATIONS' },
  { id: 'account', label: 'ACCOUNT' },
];

// Local storage key
export const PREFERENCES_KEY = 'aragora_preferences';

// Storage helpers
export function getStoredPreferences(): Partial<UserPreferences> {
  if (typeof window === 'undefined') return {};
  const stored = localStorage.getItem(PREFERENCES_KEY);
  if (!stored) return {};
  try {
    return JSON.parse(stored);
  } catch {
    return {};
  }
}

export function storePreferences(prefs: Partial<UserPreferences>): void {
  const current = getStoredPreferences();
  const merged = { ...current, ...prefs };
  localStorage.setItem(PREFERENCES_KEY, JSON.stringify(merged));
}
