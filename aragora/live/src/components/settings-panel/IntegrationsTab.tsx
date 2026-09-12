'use client';

import { useState } from 'react';
import type { SlackNotifications } from './types';
import { ToggleSwitch } from './ToggleSwitch';

export interface IntegrationsTabProps {
  backendApi: string;
  slackWebhook: string;
  discordWebhook: string;
  onSlackWebhookChange: (value: string) => void;
  onDiscordWebhookChange: (value: string) => void;
  onSave: () => void;
  saveStatus: 'idle' | 'saving' | 'saved' | 'error';
}

export function IntegrationsTab({
  backendApi,
  slackWebhook,
  discordWebhook,
  onSlackWebhookChange,
  onDiscordWebhookChange,
  onSave,
  saveStatus,
}: IntegrationsTabProps) {
  const [slackTestStatus, setSlackTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>(
    'idle',
  );
  const [slackNotifications, setSlackNotifications] = useState<SlackNotifications>({
    notify_on_consensus: true,
    notify_on_debate_end: true,
    notify_on_error: true,
    notify_on_leaderboard: false,
  });

  const handleSlackTest = async () => {
    if (!slackWebhook) return;
    setSlackTestStatus('testing');
    try {
      const response = await fetch(`${backendApi}/api/integrations/slack/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ webhook_url: slackWebhook }),
      });
      setSlackTestStatus(response.ok ? 'success' : 'error');
    } catch {
      setSlackTestStatus('error');
    }
    setTimeout(() => setSlackTestStatus('idle'), 3000);
  };

  return (
    <div
      className="space-y-6"
      role="tabpanel"
      id="panel-integrations"
      aria-labelledby="tab-integrations"
    >
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Slack Integration</h3>
        <p className="font-theme-data text-xs text-text-muted mb-4">
          Receive debate notifications in your Slack workspace.
        </p>
        <div className="space-y-4">
          <div>
            <label className="font-theme-data text-xs text-text-muted block mb-2">
              Webhook URL
            </label>
            <div className="flex gap-2">
              <input
                type="url"
                value={slackWebhook}
                onChange={(e) => onSlackWebhookChange(e.target.value)}
                placeholder="https://hooks.slack.com/services/..."
                className="flex-1 bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                aria-label="Slack webhook URL"
              />
              <button
                onClick={handleSlackTest}
                disabled={!slackWebhook || slackTestStatus === 'testing'}
                className={`px-4 py-2 font-theme-data text-sm rounded transition-colors disabled:opacity-50 ${
                  slackTestStatus === 'success'
                    ? 'bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)]'
                    : slackTestStatus === 'error'
                      ? 'bg-acid-red/20 border border-acid-red/40 text-acid-red'
                      : 'bg-surface border border-[var(--accent)]/30 text-text hover:border-[var(--accent)]/50'
                }`}
              >
                {slackTestStatus === 'testing'
                  ? '...'
                  : slackTestStatus === 'success'
                    ? 'Sent!'
                    : slackTestStatus === 'error'
                      ? 'Failed'
                      : 'Test'}
              </button>
            </div>
          </div>

          {slackWebhook && (
            <div className="pt-4 border-t border-[var(--accent)]/20">
              <h4 className="font-theme-data text-xs text-[var(--acid-cyan)] mb-3">
                NOTIFICATION SETTINGS
              </h4>
              <div className="space-y-3">
                <ToggleSwitch
                  label="Consensus Reached"
                  description="Alert when debates reach consensus"
                  checked={slackNotifications.notify_on_consensus}
                  onChange={() =>
                    setSlackNotifications((prev) => ({
                      ...prev,
                      notify_on_consensus: !prev.notify_on_consensus,
                    }))
                  }
                />
                <ToggleSwitch
                  label="Debate Completed"
                  description="Post summaries when debates end"
                  checked={slackNotifications.notify_on_debate_end}
                  onChange={() =>
                    setSlackNotifications((prev) => ({
                      ...prev,
                      notify_on_debate_end: !prev.notify_on_debate_end,
                    }))
                  }
                />
                <ToggleSwitch
                  label="Error Alerts"
                  description="Notify on debate errors"
                  checked={slackNotifications.notify_on_error}
                  onChange={() =>
                    setSlackNotifications((prev) => ({
                      ...prev,
                      notify_on_error: !prev.notify_on_error,
                    }))
                  }
                />
                <ToggleSwitch
                  label="Leaderboard Updates"
                  description="Post agent ranking changes"
                  checked={slackNotifications.notify_on_leaderboard}
                  onChange={() =>
                    setSlackNotifications((prev) => ({
                      ...prev,
                      notify_on_leaderboard: !prev.notify_on_leaderboard,
                    }))
                  }
                />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Discord Integration</h3>
        <p className="font-theme-data text-xs text-text-muted mb-4">
          Post debate results to your Discord server.
        </p>
        <input
          type="url"
          value={discordWebhook}
          onChange={(e) => onDiscordWebhookChange(e.target.value)}
          placeholder="https://discord.com/api/webhooks/..."
          className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
          aria-label="Discord webhook URL"
        />
      </div>

      <button
        onClick={onSave}
        disabled={saveStatus === 'saving'}
        className="px-6 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
      >
        {saveStatus === 'saving'
          ? 'Saving...'
          : saveStatus === 'saved'
            ? 'Saved!'
            : 'Save Integrations'}
      </button>
    </div>
  );
}

export default IntegrationsTab;
