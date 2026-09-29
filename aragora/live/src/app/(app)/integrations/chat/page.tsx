'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useBackend } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';

interface IntegrationStatus {
  name: string;
  id: string;
  icon: string;
  description: string;
  configured: boolean;
  enabled: boolean;
  status: 'connected' | 'disconnected' | 'error' | 'unknown';
  lastMessage?: string;
  configFields: ConfigField[];
}

interface ConfigField {
  key: string;
  label: string;
  type: 'text' | 'password' | 'textarea';
  required: boolean;
  placeholder?: string;
  envVar?: string;
}

const INTEGRATIONS: Omit<IntegrationStatus, 'configured' | 'enabled' | 'status' | 'lastMessage'>[] =
  [
    {
      id: 'slack',
      name: 'Slack',
      icon: '#',
      description: 'Post debate updates to Slack channels via webhooks or bot',
      configFields: [
        {
          key: 'webhook_url',
          label: 'Webhook URL',
          type: 'password',
          required: true,
          placeholder: 'https://hooks.slack.com/services/...',
          envVar: 'SLACK_WEBHOOK_URL',
        },
        {
          key: 'channel',
          label: 'Channel',
          type: 'text',
          required: false,
          placeholder: '#aragora-debates',
        },
      ],
    },
    {
      id: 'discord',
      name: 'Discord',
      icon: '@',
      description: 'Send notifications to Discord servers via webhooks',
      configFields: [
        {
          key: 'webhook_url',
          label: 'Webhook URL',
          type: 'password',
          required: true,
          placeholder: 'https://discord.com/api/webhooks/...',
          envVar: 'DISCORD_WEBHOOK_URL',
        },
      ],
    },
    {
      id: 'teams',
      name: 'Microsoft Teams',
      icon: '{}',
      description: 'Post Adaptive Cards to Teams channels',
      configFields: [
        {
          key: 'webhook_url',
          label: 'Incoming Webhook URL',
          type: 'password',
          required: true,
          placeholder: 'https://xxx.webhook.office.com/...',
          envVar: 'TEAMS_WEBHOOK_URL',
        },
      ],
    },
    {
      id: 'telegram',
      name: 'Telegram',
      icon: '>',
      description: 'Send messages via Telegram bot',
      configFields: [
        {
          key: 'bot_token',
          label: 'Bot Token',
          type: 'password',
          required: true,
          placeholder: '123456:ABC-DEF1234...',
          envVar: 'TELEGRAM_BOT_TOKEN',
        },
        {
          key: 'chat_id',
          label: 'Chat ID',
          type: 'text',
          required: true,
          placeholder: '-1001234567890',
          envVar: 'TELEGRAM_CHAT_ID',
        },
      ],
    },
    {
      id: 'matrix',
      name: 'Matrix / Element',
      icon: '[]',
      description: 'Send messages to Matrix rooms (Element, etc.)',
      configFields: [
        {
          key: 'homeserver',
          label: 'Homeserver URL',
          type: 'text',
          required: true,
          placeholder: 'https://matrix.org',
          envVar: 'MATRIX_HOMESERVER_URL',
        },
        {
          key: 'access_token',
          label: 'Access Token',
          type: 'password',
          required: true,
          placeholder: 'syt_xxxxx',
          envVar: 'MATRIX_ACCESS_TOKEN',
        },
        {
          key: 'room_id',
          label: 'Room ID',
          type: 'text',
          required: true,
          placeholder: '!abc123:matrix.org',
          envVar: 'MATRIX_ROOM_ID',
        },
      ],
    },
  ];

interface IntegrationCardProps {
  integration: IntegrationStatus;
  onTest: () => void;
  onToggle: () => void;
  isLoading: boolean;
}

function IntegrationCard({ integration, onTest, onToggle, isLoading }: IntegrationCardProps) {
  const [showConfig, setShowConfig] = useState(false);

  const statusColors = {
    connected: 'text-[var(--accent)] bg-[var(--accent)]/10 border-[var(--accent)]/30',
    disconnected: 'text-text-muted bg-surface border-[var(--accent)]/20',
    error: 'text-warning bg-warning/10 border-warning/30',
    unknown: 'text-[var(--acid-yellow)] bg-acid-yellow/10 border-acid-yellow/30',
  };

  const statusLabels = {
    connected: 'CONNECTED',
    disconnected: 'NOT CONFIGURED',
    error: 'ERROR',
    unknown: 'UNKNOWN',
  };

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/30">
      {/* Header */}
      <div className="p-4 flex items-start justify-between">
        <div className="flex items-start gap-3">
          <span className="text-[var(--accent)] font-theme-data text-lg opacity-60">
            {integration.icon}
          </span>
          <div>
            <h3 className="text-[var(--accent)] font-theme-data text-sm font-bold">
              {integration.name}
            </h3>
            <p className="text-text-muted font-theme-data text-[10px] mt-1 max-w-xs">
              {integration.description}
            </p>
          </div>
        </div>
        <div
          className={`px-2 py-1 font-theme-data text-[10px] border ${statusColors[integration.status]}`}
        >
          {statusLabels[integration.status]}
        </div>
      </div>

      {/* Actions */}
      <div className="px-4 pb-4 flex items-center gap-2">
        <button
          onClick={onTest}
          disabled={!integration.configured || isLoading}
          className={`px-3 py-1.5 font-theme-data text-[10px] border transition-colors ${
            integration.configured && !isLoading
              ? 'border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10'
              : 'border-[var(--accent)]/20 text-text-muted cursor-not-allowed'
          }`}
        >
          {isLoading ? 'TESTING...' : 'TEST CONNECTION'}
        </button>
        <button
          onClick={() => setShowConfig(!showConfig)}
          className="px-3 py-1.5 font-theme-data text-[10px] border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors"
        >
          {showConfig ? 'HIDE CONFIG' : 'SHOW CONFIG'}
        </button>
        {integration.configured && (
          <button
            onClick={onToggle}
            className={`px-3 py-1.5 font-theme-data text-[10px] border transition-colors ${
              integration.enabled
                ? 'border-[var(--accent)]/50 text-[var(--accent)] bg-[var(--accent)]/10'
                : 'border-acid-yellow/50 text-[var(--acid-yellow)]'
            }`}
          >
            {integration.enabled ? 'ENABLED' : 'DISABLED'}
          </button>
        )}
      </div>

      {/* Config Panel */}
      {showConfig && (
        <div className="px-4 pb-4 border-t border-[var(--accent)]/20 pt-3">
          <p className="text-text-muted/50 font-theme-data text-[10px] mb-3">
            Configure via environment variables:
          </p>
          <div className="space-y-2">
            {integration.configFields.map((field) => (
              <div key={field.key} className="flex items-center gap-2">
                <code className="text-[var(--acid-cyan)] font-theme-data text-[10px] bg-bg px-2 py-1 border border-[var(--accent)]/20">
                  {field.envVar || field.key.toUpperCase()}
                </code>
                <span className="text-text-muted font-theme-data text-[10px]">
                  {field.label}
                  {field.required && <span className="text-warning ml-1">*</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Last Message */}
      {integration.lastMessage && (
        <div className="px-4 pb-3 border-t border-[var(--accent)]/10 pt-2">
          <p className="text-text-muted/40 font-theme-data text-[9px]">
            Last: {integration.lastMessage}
          </p>
        </div>
      )}
    </div>
  );
}

export default function ChatIntegrationsPage() {
  const { config: backendConfig } = useBackend();
  const [integrations, setIntegrations] = useState<IntegrationStatus[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{
    id: string;
    success: boolean;
    message: string;
  } | null>(null);

  // Fetch integration statuses
  const fetchStatuses = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/integrations/status`);
      if (response.ok) {
        const data = await response.json();

        // Merge API data with static config
        const merged = INTEGRATIONS.map((integration) => {
          const apiStatus = data.integrations?.[integration.id] || {};
          return {
            ...integration,
            configured: apiStatus.configured || false,
            enabled: apiStatus.enabled || false,
            status: apiStatus.status || 'unknown',
            lastMessage: apiStatus.lastMessage,
          };
        });

        setIntegrations(merged);
      } else {
        // API not available, show unconfigured state
        setIntegrations(
          INTEGRATIONS.map((i) => ({
            ...i,
            configured: false,
            enabled: false,
            status: 'unknown' as const,
          })),
        );
      }
    } catch {
      // Network error, show unconfigured state
      setIntegrations(
        INTEGRATIONS.map((i) => ({
          ...i,
          configured: false,
          enabled: false,
          status: 'unknown' as const,
        })),
      );
    } finally {
      setIsLoading(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchStatuses();
  }, [fetchStatuses]);

  const handleTest = async (integrationId: string) => {
    setTestingId(integrationId);
    setTestResult(null);

    try {
      const response = await fetch(`${backendConfig.api}/api/integrations/${integrationId}/test`, {
        method: 'POST',
      });
      const data = await response.json();

      setTestResult({
        id: integrationId,
        success: data.success || response.ok,
        message: data.message || (response.ok ? 'Connection successful' : 'Connection failed'),
      });

      // Refresh statuses after test
      await fetchStatuses();
    } catch (err) {
      setTestResult({
        id: integrationId,
        success: false,
        message: err instanceof Error ? err.message : 'Test failed',
      });
    } finally {
      setTestingId(null);
    }
  };

  const handleToggle = async (integrationId: string) => {
    const integration = integrations.find((i) => i.id === integrationId);
    if (!integration) return;

    try {
      await fetch(`${backendConfig.api}/api/integrations/${integrationId}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !integration.enabled }),
      });

      // Refresh statuses
      await fetchStatuses();
    } catch (err) {
      logger.error('Toggle failed:', err);
    }
  };

  return (
    <main className="min-h-screen bg-bg text-text">
      {/* Header */}
      <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-[var(--accent)] font-theme-data text-sm hover:opacity-80"
            >
              [ARAGORA]
            </Link>
            <span className="text-[var(--accent)]/30">/</span>
            <Link
              href="/integrations"
              className="text-[var(--acid-cyan)] font-theme-data text-sm hover:opacity-80"
            >
              INTEGRATIONS
            </Link>
            <span className="text-[var(--accent)]/30">/</span>
            <span className="text-[var(--acid-cyan)] font-theme-data text-sm">CHAT</span>
          </div>
        </div>
      </header>

      <div className="container mx-auto px-4 py-8 max-w-4xl">
        {/* Title */}
        <div className="text-center mb-8">
          <h1 className="text-[var(--accent)] font-theme-data text-xl mb-2">CHAT INTEGRATIONS</h1>
          <p className="text-text-muted font-theme-data text-xs">
            Connect Aragora to your team communication platforms
          </p>
        </div>

        {/* Test Result Banner */}
        {testResult && (
          <div
            className={`mb-6 p-3 border ${
              testResult.success
                ? 'border-[var(--accent)]/30 bg-[var(--accent)]/10'
                : 'border-warning/30 bg-warning/10'
            }`}
          >
            <div className="flex items-center justify-between">
              <span
                className={`font-theme-data text-sm ${
                  testResult.success ? 'text-[var(--accent)]' : 'text-warning'
                }`}
              >
                {testResult.success ? '✓' : '✗'} {testResult.message}
              </span>
              <button
                onClick={() => setTestResult(null)}
                className="text-text-muted hover:text-text"
              >
                ×
              </button>
            </div>
          </div>
        )}

        {/* Integrations Grid */}
        {isLoading ? (
          <div className="text-center py-12">
            <span className="text-[var(--accent)] font-theme-data animate-pulse">LOADING...</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {integrations.map((integration) => (
              <IntegrationCard
                key={integration.id}
                integration={integration}
                onTest={() => handleTest(integration.id)}
                onToggle={() => handleToggle(integration.id)}
                isLoading={testingId === integration.id}
              />
            ))}
          </div>
        )}

        {/* Info Section */}
        <div className="mt-12 border-t border-[var(--accent)]/20 pt-8">
          <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
            HOW IT WORKS
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 border border-[var(--accent)]/10 bg-surface/20">
              <div className="text-[var(--accent)] font-theme-data text-lg mb-2">1</div>
              <div className="text-text font-theme-data text-xs mb-1">Configure</div>
              <div className="text-text-muted/50 font-theme-data text-[10px]">
                Set environment variables for your chosen platforms
              </div>
            </div>
            <div className="p-4 border border-[var(--accent)]/10 bg-surface/20">
              <div className="text-[var(--accent)] font-theme-data text-lg mb-2">2</div>
              <div className="text-text font-theme-data text-xs mb-1">Test</div>
              <div className="text-text-muted/50 font-theme-data text-[10px]">
                Verify connections work with the test button
              </div>
            </div>
            <div className="p-4 border border-[var(--accent)]/10 bg-surface/20">
              <div className="text-[var(--accent)] font-theme-data text-lg mb-2">3</div>
              <div className="text-text font-theme-data text-xs mb-1">Receive Updates</div>
              <div className="text-text-muted/50 font-theme-data text-[10px]">
                Get debate results, consensus alerts, and errors
              </div>
            </div>
          </div>
        </div>

        {/* Event Types */}
        <div className="mt-8">
          <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
            NOTIFICATION EVENTS
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {[
              { name: 'Debate Started', desc: 'When a new debate begins' },
              { name: 'Consensus Reached', desc: 'When agents agree' },
              { name: 'Debate Complete', desc: 'Final results available' },
              { name: 'Errors', desc: 'When something goes wrong' },
            ].map((event) => (
              <div key={event.name} className="p-3 border border-[var(--accent)]/10 bg-surface/10">
                <div className="text-[var(--acid-cyan)] font-theme-data text-[10px]">
                  {event.name}
                </div>
                <div className="text-text-muted/40 font-theme-data text-[9px] mt-1">
                  {event.desc}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
