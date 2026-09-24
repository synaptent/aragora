'use client';

import type { UserPreferences } from './types';
import { ToggleSwitch } from './ToggleSwitch';

export interface AppearanceTabProps {
  preferences: UserPreferences;
  updateTheme: (theme: 'dark' | 'light' | 'system') => void;
  updateDisplay: (key: keyof UserPreferences['display'], value: boolean) => void;
}

export function AppearanceTab({ preferences, updateTheme, updateDisplay }: AppearanceTabProps) {
  return (
    <div
      className="space-y-6"
      role="tabpanel"
      id="panel-appearance"
      aria-labelledby="tab-appearance"
    >
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Theme</h3>
        <div className="space-y-3">
          {(['dark', 'light', 'system'] as const).map((theme) => (
            <label
              key={theme}
              className={`flex items-center gap-3 p-3 rounded border cursor-pointer transition-colors ${
                preferences.theme === theme
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                  : 'border-[var(--accent)]/30 hover:border-[var(--accent)]/60'
              }`}
            >
              <input
                type="radio"
                name="theme"
                value={theme}
                checked={preferences.theme === theme}
                onChange={() => updateTheme(theme)}
                className="sr-only"
              />
              <div
                className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                  preferences.theme === theme ? 'border-[var(--accent)]' : 'border-text-muted'
                }`}
              >
                {preferences.theme === theme && (
                  <div className="w-2 h-2 rounded-full bg-[var(--accent)]" />
                )}
              </div>
              <div>
                <div className="font-theme-data text-sm text-text capitalize">{theme}</div>
                <div className="font-theme-data text-xs text-text-muted">
                  {theme === 'dark' && 'Default dark theme with acid green accents'}
                  {theme === 'light' && 'Light theme for bright environments'}
                  {theme === 'system' && 'Match your system preference'}
                </div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Display Options</h3>
        <div className="space-y-4">
          <ToggleSwitch
            label="Compact Mode"
            description="Reduce spacing in lists and panels"
            checked={preferences.display.compact_mode}
            onChange={() => updateDisplay('compact_mode', !preferences.display.compact_mode)}
          />
          <ToggleSwitch
            label="Show Agent Icons"
            description="Display model icons next to agent names"
            checked={preferences.display.show_agent_icons}
            onChange={() =>
              updateDisplay('show_agent_icons', !preferences.display.show_agent_icons)
            }
          />
          <ToggleSwitch
            label="Auto-scroll Messages"
            description="Automatically scroll to new messages in debates"
            checked={preferences.display.auto_scroll_messages}
            onChange={() =>
              updateDisplay('auto_scroll_messages', !preferences.display.auto_scroll_messages)
            }
          />
        </div>
      </div>
    </div>
  );
}

export default AppearanceTab;
