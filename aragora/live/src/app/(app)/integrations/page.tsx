'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';
import {
  IntegrationSetupWizard,
  IntegrationStatusDashboard,
  IntegrationType,
  INTEGRATION_CONFIGS,
} from '@/components/integrations';

interface BotStatus {
  platform: string;
  label: string;
  icon: string;
  status: 'online' | 'offline' | 'error' | 'loading';
  endpoint: string;
  features: string[];
  lastPing?: string;
  errorMessage?: string;
}

interface SystemIntegrationConfig {
  title: string;
  description: string;
  href: string;
  icon: string;
  /** API endpoint to probe for availability (GET request, 2xx = available) */
  probeEndpoint: string;
  features: string[];
}

interface SystemIntegrationStatus extends SystemIntegrationConfig {
  status: 'available' | 'unavailable' | 'checking';
}

/** Health data for each connector from /api/v1/integrations/health */
interface ConnectorHealth {
  name: string;
  configured: boolean;
  module_available: boolean;
  healthy: boolean;
  last_check: string | null;
  circuit_breakers: { name: string; state: string; failures: number }[];
}

const SYSTEM_INTEGRATION_CONFIGS: SystemIntegrationConfig[] = [
  {
    title: 'Webhooks',
    description: 'Receive real-time HTTP callbacks for debate events. Integrate with any system.',
    href: '/webhooks',
    icon: '>>',
    probeEndpoint: '/api/v1/webhooks',
    features: ['Lifecycle events', 'Consensus alerts', 'HMAC signatures', 'Retry logic'],
  },
  {
    title: 'Plugin Marketplace',
    description: 'Extend Aragora with custom plugins for selection, scoring, and behaviors.',
    href: '/plugins',
    icon: '+>',
    probeEndpoint: '/api/v1/plugins',
    features: ['Agent scorers', 'Team selectors', 'Custom behaviors'],
  },
  {
    title: 'Training Export',
    description: 'Export debate data for fine-tuning language models.',
    href: '/training',
    icon: '[]',
    probeEndpoint: '/api/v1/training/export',
    features: ['SFT format', 'DPO pairs', 'JSONL export'],
  },
  {
    title: 'Evidence Connectors',
    description: 'Connect external knowledge sources for fact-grounded debates.',
    href: '/evidence',
    icon: '??',
    probeEndpoint: '/api/v1/evidence',
    features: ['Web search', 'Document upload', 'Citations'],
  },
  {
    title: 'API Explorer',
    description: 'Interactive documentation and testing for all API endpoints.',
    href: '/api-explorer',
    icon: '{}',
    probeEndpoint: '/api/v1/openapi.json',
    features: ['OpenAPI spec', 'Try requests', 'Authentication'],
  },
  {
    title: 'MCP Server',
    description: 'Model Context Protocol server for AI assistant integrations.',
    href: '/developer',
    icon: '<>',
    probeEndpoint: '/api/v1/mcp/tools',
    features: ['Claude integration', 'MCP tools', 'Context streaming'],
  },
];

// Chat platform integrations
const chatPlatforms: IntegrationType[] = [
  'slack',
  'discord',
  'telegram',
  'email',
  'teams',
  'whatsapp',
  'matrix',
];

// Bot integrations configuration
const BOT_CONFIGS: Omit<BotStatus, 'status' | 'lastPing' | 'errorMessage'>[] = [
  {
    platform: 'slack',
    label: 'Slack',
    icon: '#',
    endpoint: '/api/integrations/slack/status',
    features: ['Slash commands', 'Interactive components', 'Event subscriptions'],
  },
  {
    platform: 'discord',
    label: 'Discord',
    icon: '>',
    endpoint: '/api/bots/discord/status',
    features: ['Bot interactions', 'Slash commands', 'Message components'],
  },
  {
    platform: 'teams',
    label: 'Microsoft Teams',
    icon: 'T',
    endpoint: '/api/bots/teams/status',
    features: ['Bot messages', 'Adaptive cards', 'Activity handler'],
  },
  {
    platform: 'zoom',
    label: 'Zoom',
    icon: 'Z',
    endpoint: '/api/bots/zoom/status',
    features: ['Meeting events', 'Webhooks', 'Chat integration'],
  },
];

function SystemStatusBadge({ status }: { status: SystemIntegrationStatus['status'] }) {
  const styles: Record<SystemIntegrationStatus['status'], { classes: string; label: string }> = {
    available: {
      classes: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/30',
      label: 'AVAILABLE',
    },
    unavailable: {
      classes: 'bg-text-muted/20 text-text-muted border-text-muted/30',
      label: 'UNAVAILABLE',
    },
    checking: {
      classes:
        'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30 animate-pulse',
      label: 'CHECKING',
    },
  };
  const style = styles[status];
  return (
    <span className={`px-2 py-0.5 text-xs font-theme-data rounded border ${style.classes}`}>
      {style.label}
    </span>
  );
}

function HealthBadge({ configured, healthy }: { configured: boolean; healthy: boolean }) {
  if (!configured) {
    return (
      <span className="px-2 py-0.5 text-xs font-theme-data rounded bg-text-muted/20 text-text-muted">
        NOT CONFIGURED
      </span>
    );
  }
  if (healthy) {
    return (
      <span className="px-2 py-0.5 text-xs font-theme-data rounded bg-[var(--accent)]/20 text-[var(--accent)]">
        HEALTHY
      </span>
    );
  }
  return (
    <span className="px-2 py-0.5 text-xs font-theme-data rounded bg-warning/20 text-warning">
      UNHEALTHY
    </span>
  );
}

function BotStatusBadge({ status }: { status: BotStatus['status'] }) {
  const styles: Record<BotStatus['status'], string> = {
    online: 'bg-[var(--accent)]/20 text-[var(--accent)]',
    offline: 'bg-text-muted/20 text-text-muted',
    error: 'bg-warning/20 text-warning',
    loading: 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] animate-pulse',
  };
  return (
    <span className={`px-2 py-0.5 text-xs font-theme-data rounded ${styles[status]}`}>
      {status.toUpperCase()}
    </span>
  );
}

export default function IntegrationsPage() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const [activeTab, setActiveTab] = useState<'notifications' | 'bots' | 'system' | 'docs'>(
    'notifications',
  );
  const [wizardOpen, setWizardOpen] = useState<IntegrationType | null>(null);
  const [editingConfig, setEditingConfig] = useState<Record<string, unknown> | undefined>();
  const [botStatuses, setBotStatuses] = useState<BotStatus[]>(
    BOT_CONFIGS.map((cfg) => ({ ...cfg, status: 'loading' as const })),
  );
  const [botsLoading, setBotsLoading] = useState(false);
  const [systemStatuses, setSystemStatuses] = useState<SystemIntegrationStatus[]>(
    SYSTEM_INTEGRATION_CONFIGS.map((cfg) => ({ ...cfg, status: 'checking' as const })),
  );
  const [systemLoading, setSystemLoading] = useState(false);
  const [connectorHealth, setConnectorHealth] = useState<ConnectorHealth[]>([]);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  // Probe system integration endpoints for real availability
  const fetchSystemStatuses = useCallback(async () => {
    setSystemLoading(true);
    const results = await Promise.all(
      SYSTEM_INTEGRATION_CONFIGS.map(async (cfg) => {
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 5000);
          const res = await fetch(`${backendConfig.api}${cfg.probeEndpoint}`, {
            method: 'GET',
            signal: controller.signal,
          });
          clearTimeout(timeoutId);
          // 2xx or 401/403 means the endpoint exists (auth required = still available)
          const isAvailable = res.ok || res.status === 401 || res.status === 403;
          return {
            ...cfg,
            status: (isAvailable
              ? 'available'
              : 'unavailable') as SystemIntegrationStatus['status'],
          };
        } catch {
          return { ...cfg, status: 'unavailable' as const };
        }
      }),
    );
    setSystemStatuses(results);
    setSystemLoading(false);
  }, [backendConfig.api]);

  // Fetch connector health from /api/v1/integrations/health
  const fetchConnectorHealth = useCallback(async () => {
    setHealthLoading(true);
    setHealthError(null);
    try {
      const headers: HeadersInit = {};
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const res = await fetch(`${backendConfig.api}/api/v1/integrations/health`, { headers });
      if (res.ok) {
        const data = await res.json();
        setConnectorHealth(data.integrations || []);
      } else if (res.status === 401 || res.status === 403) {
        setConnectorHealth([]);
        setHealthError('Sign in to view connector health.');
      } else {
        setConnectorHealth([]);
        setHealthError('Could not load connector health from server.');
      }
    } catch {
      setConnectorHealth([]);
      setHealthError('Could not reach the backend to check connector health.');
    } finally {
      setHealthLoading(false);
    }
  }, [backendConfig.api, tokens?.access_token]);

  // Load system statuses and connector health when system tab is active
  useEffect(() => {
    if (activeTab === 'system') {
      fetchSystemStatuses();
      fetchConnectorHealth();
    }
  }, [activeTab, fetchSystemStatuses, fetchConnectorHealth]);

  // Fetch bot statuses
  const fetchBotStatuses = useCallback(async () => {
    setBotsLoading(true);
    const newStatuses = await Promise.all(
      BOT_CONFIGS.map(async (cfg) => {
        try {
          const res = await fetch(`${backendConfig.api}${cfg.endpoint}`);
          if (res.ok) {
            const data = await res.json();
            return {
              ...cfg,
              status:
                data.online || data.status === 'online' || data.configured ? 'online' : 'offline',
              lastPing: data.last_activity
                ? new Date(data.last_activity * 1000).toLocaleString()
                : undefined,
            } as BotStatus;
          }
          return { ...cfg, status: 'offline' as const };
        } catch (err) {
          return {
            ...cfg,
            status: 'error' as const,
            errorMessage: err instanceof Error ? err.message : 'Failed to connect',
          } as BotStatus;
        }
      }),
    );
    setBotStatuses(newStatuses);
    setBotsLoading(false);
  }, [backendConfig.api]);

  // Load bot statuses when tab is active
  useEffect(() => {
    if (activeTab === 'bots') {
      fetchBotStatuses();
    }
  }, [activeTab, fetchBotStatuses]);

  const handleConfigure = useCallback((type: IntegrationType) => {
    setEditingConfig(undefined);
    setWizardOpen(type);
  }, []);

  const handleEdit = useCallback((type: IntegrationType, config: Record<string, unknown>) => {
    setEditingConfig(config);
    setWizardOpen(type);
  }, []);

  const buildAuthHeaders = useCallback(
    (includeJson = false): HeadersInit => {
      if (!tokens?.access_token) {
        throw new Error('Sign in to manage integrations.');
      }

      return {
        ...(includeJson ? { 'Content-Type': 'application/json' } : {}),
        Authorization: `Bearer ${tokens.access_token}`,
      };
    },
    [tokens?.access_token],
  );

  const handleSaveIntegration = async (config: Record<string, unknown>) => {
    const res = await fetch(`${backendConfig.api}/api/integrations/${config.type}`, {
      method: 'PUT',
      headers: buildAuthHeaders(true),
      body: JSON.stringify(config),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || data.message || 'Failed to save integration');
    }
  };

  const handleTestIntegration = async (
    type: IntegrationType,
    config: Record<string, unknown>,
  ): Promise<{ success: boolean; error?: string }> => {
    try {
      const res = await fetch(`${backendConfig.api}/api/integrations/${type}/test`, {
        method: 'POST',
        headers: buildAuthHeaders(true),
        body: JSON.stringify(config),
      });

      if (res.ok) {
        const data = await res.json();
        return { success: data.success !== false, error: data.error };
      } else {
        const data = await res.json().catch(() => ({}));
        return { success: false, error: data.error || `Test failed with status ${res.status}` };
      }
    } catch (err) {
      return {
        success: false,
        error: err instanceof Error ? err.message : 'Connection test failed',
      };
    }
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} INTEGRATIONS
            </h1>
            <p className="text-text-muted font-theme-data text-sm max-w-2xl">
              Connect Aragora to chat platforms for notifications, export data for ML training, and
              extend functionality with plugins and webhooks.
            </p>
          </div>

          {/* SDK Installation */}
          <div className="mb-6 p-4 border border-[var(--acid-cyan)]/30 bg-surface/30 rounded">
            <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
              SDK Installation
            </h3>
            <div className="flex items-center gap-4">
              <code className="flex-1 bg-bg px-3 py-2 font-theme-data text-sm text-text border border-[var(--accent)]/20 rounded">
                npm install @aragora/sdk
              </code>
              <Link
                href="https://www.npmjs.com/package/@aragora/sdk"
                target="_blank"
                className="px-3 py-2 border border-[var(--accent)]/30 text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [NPM]
              </Link>
              <Link
                href="/api-explorer"
                className="px-3 py-2 border border-[var(--accent)]/30 text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [DOCS]
              </Link>
            </div>
          </div>

          {/* Tab Navigation */}
          <div className="flex gap-2 mb-6">
            <button
              onClick={() => setActiveTab('notifications')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'notifications'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [NOTIFICATIONS]
            </button>
            <button
              onClick={() => setActiveTab('bots')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'bots'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [BOTS]
            </button>
            <button
              onClick={() => setActiveTab('system')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'system'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [SYSTEM]
            </button>
            <button
              onClick={() => setActiveTab('docs')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'docs'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [DOCUMENTATION]
            </button>
          </div>

          {/* Tab Content */}
          {activeTab === 'notifications' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="font-theme-data text-text">Chat & Notification Platforms</h2>
                <div className="flex gap-2">
                  {chatPlatforms.slice(0, 3).map((type) => (
                    <button
                      key={type}
                      onClick={() => handleConfigure(type)}
                      className="px-3 py-1 text-xs font-theme-data border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                    >
                      [+ {INTEGRATION_CONFIGS[type].title.toUpperCase()}]
                    </button>
                  ))}
                </div>
              </div>

              <IntegrationStatusDashboard onConfigure={handleConfigure} onEdit={handleEdit} />
            </div>
          )}

          {activeTab === 'bots' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="font-theme-data text-text">Chat Platform Bots</h2>
                <button
                  onClick={fetchBotStatuses}
                  disabled={botsLoading}
                  className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                >
                  {botsLoading ? '[CHECKING...]' : '[REFRESH STATUS]'}
                </button>
              </div>

              <p className="text-text-muted font-theme-data text-sm">
                Bots allow Aragora to interact directly with chat platforms, handling commands and
                events in real-time.
              </p>

              {/* Bot Status Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {botStatuses.map((bot) => (
                  <div
                    key={bot.platform}
                    className={`p-4 border rounded bg-surface/30 ${
                      bot.status === 'online'
                        ? 'border-[var(--accent)]/40'
                        : bot.status === 'error'
                          ? 'border-warning/40'
                          : 'border-[var(--accent)]/20'
                    }`}
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <span className="w-10 h-10 flex items-center justify-center bg-surface rounded font-theme-data text-lg text-[var(--acid-cyan)]">
                          {bot.icon}
                        </span>
                        <div>
                          <h3 className="font-theme-data text-text">{bot.label}</h3>
                          <div className="text-xs font-theme-data text-text-muted">
                            {bot.endpoint}
                          </div>
                        </div>
                      </div>
                      <BotStatusBadge status={bot.status} />
                    </div>

                    {bot.errorMessage && (
                      <div className="mb-3 p-2 bg-warning/10 border border-warning/30 rounded text-xs font-theme-data text-warning">
                        {bot.errorMessage}
                      </div>
                    )}

                    <div className="flex flex-wrap gap-1 mb-3">
                      {bot.features.map((feature) => (
                        <span
                          key={feature}
                          className="px-2 py-0.5 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)]/70 rounded"
                        >
                          {feature}
                        </span>
                      ))}
                    </div>

                    {bot.lastPing && (
                      <div className="text-xs font-theme-data text-text-muted">
                        Last activity: {bot.lastPing}
                      </div>
                    )}

                    <div className="flex gap-2 mt-3">
                      {bot.platform !== 'zoom' && (
                        <button
                          onClick={() => handleConfigure(bot.platform as IntegrationType)}
                          className="px-3 py-1 text-xs font-theme-data border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                        >
                          [CONFIGURE]
                        </button>
                      )}
                      <Link
                        href={`/api-explorer?path=${encodeURIComponent(bot.endpoint)}`}
                        className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors"
                      >
                        [API DOCS]
                      </Link>
                    </div>
                  </div>
                ))}
              </div>

              {/* Bot Setup Guide */}
              <div className="p-4 border border-[var(--acid-cyan)]/30 rounded bg-surface/20">
                <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                  Bot Setup Guide
                </h3>
                <div className="space-y-2 text-xs font-theme-data text-text-muted">
                  <p>
                    1. Configure your platform credentials in the Notifications tab or environment
                    variables
                  </p>
                  <p>2. Set up webhook URLs to point to your Aragora server endpoints</p>
                  <p>3. The bot will automatically handle incoming events and commands</p>
                </div>
                <div className="mt-3 p-3 bg-bg/50 rounded border border-[var(--accent)]/20">
                  <div className="text-xs font-theme-data text-text-muted mb-1">
                    Example Slack command:
                  </div>
                  <code className="text-xs font-theme-data text-[var(--acid-cyan)]">
                    /aragora debate &quot;Should we use microservices?&quot;
                  </code>
                </div>
              </div>

              {/* Environment Variables */}
              <div className="p-4 border border-[var(--accent)]/20 rounded bg-bg/50">
                <h3 className="font-theme-data text-text text-sm mb-3">
                  Required Environment Variables
                </h3>
                <pre className="font-theme-data text-xs text-text-muted whitespace-pre overflow-x-auto">
                  {`# Slack Bot
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...

# Discord Bot
DISCORD_BOT_TOKEN=...
DISCORD_PUBLIC_KEY=...

# Microsoft Teams
TEAMS_APP_ID=...
TEAMS_APP_PASSWORD=...

# Zoom
ZOOM_CLIENT_ID=...
ZOOM_CLIENT_SECRET=...
ZOOM_WEBHOOK_SECRET=...`}
                </pre>
              </div>
            </div>
          )}

          {activeTab === 'system' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="font-theme-data text-text">System Integrations</h2>
                <button
                  onClick={() => {
                    fetchSystemStatuses();
                    fetchConnectorHealth();
                  }}
                  disabled={systemLoading || healthLoading}
                  className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                >
                  {systemLoading || healthLoading ? '[CHECKING...]' : '[REFRESH STATUS]'}
                </button>
              </div>

              {/* Connector Health from /api/v1/integrations/health */}
              <div>
                <h3 className="font-theme-data text-text text-sm mb-3">
                  Connector Health (Environment)
                </h3>
                {healthError && (
                  <div className="mb-3 p-3 border border-warning/30 bg-warning/10 rounded">
                    <p className="text-warning font-theme-data text-sm">{healthError}</p>
                  </div>
                )}
                {healthLoading && connectorHealth.length === 0 && !healthError && (
                  <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                    <p className="font-theme-data text-text-muted text-center text-sm">
                      Checking connector health...
                    </p>
                  </div>
                )}
                {connectorHealth.length > 0 && (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {connectorHealth.map((connector) => (
                      <div
                        key={connector.name}
                        className={`p-3 border rounded bg-surface/30 ${
                          connector.configured && connector.healthy
                            ? 'border-[var(--accent)]/40'
                            : connector.configured && !connector.healthy
                              ? 'border-warning/40'
                              : 'border-[var(--accent)]/15'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <h4 className="font-theme-data text-text text-sm capitalize">
                            {connector.name}
                          </h4>
                          <HealthBadge
                            configured={connector.configured}
                            healthy={connector.healthy}
                          />
                        </div>
                        <div className="space-y-1 text-xs font-theme-data text-text-muted">
                          <div>
                            Module:{' '}
                            <span
                              className={
                                connector.module_available
                                  ? 'text-[var(--accent)]'
                                  : 'text-text-muted'
                              }
                            >
                              {connector.module_available ? 'loaded' : 'not loaded'}
                            </span>
                          </div>
                          {connector.last_check && (
                            <div>Last check: {new Date(connector.last_check).toLocaleString()}</div>
                          )}
                          {connector.circuit_breakers.length > 0 && (
                            <div className="flex gap-2 mt-1">
                              {connector.circuit_breakers.map((cb) => (
                                <span
                                  key={cb.name}
                                  className={`px-1.5 py-0.5 rounded ${
                                    cb.state === 'closed'
                                      ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                                      : cb.state === 'half-open'
                                        ? 'bg-warning/10 text-warning'
                                        : 'bg-[var(--crimson)]/10 text-[var(--crimson)]'
                                  }`}
                                >
                                  {cb.name}: {cb.state}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {!healthLoading && connectorHealth.length === 0 && !healthError && (
                  <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/20 text-center">
                    <p className="font-theme-data text-sm text-text-muted">
                      No connector health data available.
                    </p>
                  </div>
                )}
              </div>

              {/* System Feature Endpoints */}
              <div>
                <h3 className="font-theme-data text-text text-sm mb-3">Feature Endpoints</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {systemStatuses.map((integration) => (
                    <Link
                      key={integration.href}
                      href={integration.href}
                      className={`group p-4 border rounded bg-surface/30 hover:bg-surface/50 transition-all ${
                        integration.status === 'available'
                          ? 'border-[var(--accent)]/30 hover:border-[var(--accent)]/50'
                          : integration.status === 'checking'
                            ? 'border-[var(--acid-cyan)]/20'
                            : 'border-[var(--accent)]/10 hover:border-[var(--accent)]/30'
                      }`}
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <span className="font-theme-data text-[var(--acid-cyan)] text-lg">
                            {integration.icon}
                          </span>
                          <h3 className="font-theme-data text-text group-hover:text-[var(--accent)] transition-colors">
                            {integration.title}
                          </h3>
                        </div>
                        <SystemStatusBadge status={integration.status} />
                      </div>
                      <p className="text-text-muted font-theme-data text-xs mb-2 line-clamp-2">
                        {integration.description}
                      </p>
                      <div className="text-xs font-theme-data text-text-muted mb-3">
                        Endpoint:{' '}
                        <code className="text-[var(--acid-cyan)]/70">
                          {integration.probeEndpoint}
                        </code>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {integration.features.map((feature) => (
                          <span
                            key={feature}
                            className="px-2 py-0.5 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)]/70 rounded"
                          >
                            {feature}
                          </span>
                        ))}
                      </div>
                    </Link>
                  ))}
                </div>
              </div>

              {/* Quick Links */}
              <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/20">
                <h3 className="font-theme-data text-text mb-3 text-sm">Quick Actions</h3>
                <div className="flex flex-wrap gap-2">
                  <Link
                    href="/webhooks"
                    className="px-3 py-2 border border-[var(--acid-cyan)]/30 text-xs font-theme-data text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                  >
                    [+ NEW WEBHOOK]
                  </Link>
                  <Link
                    href="/plugins"
                    className="px-3 py-2 border border-[var(--acid-cyan)]/30 text-xs font-theme-data text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                  >
                    [BROWSE PLUGINS]
                  </Link>
                  <Link
                    href="/training"
                    className="px-3 py-2 border border-[var(--acid-cyan)]/30 text-xs font-theme-data text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                  >
                    [EXPORT DATA]
                  </Link>
                  <Link
                    href="/developer"
                    className="px-3 py-2 border border-[var(--acid-cyan)]/30 text-xs font-theme-data text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                  >
                    [MCP SERVER]
                  </Link>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'docs' && (
            <div className="space-y-6">
              {/* Webhook Event Types */}
              <div>
                <h3 className="font-theme-data text-text mb-4 text-sm">Webhook Event Types</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                  {[
                    { event: 'debate_start', desc: 'Debate begins' },
                    { event: 'debate_end', desc: 'Debate completes' },
                    { event: 'consensus', desc: 'Consensus reached' },
                    { event: 'round_start', desc: 'Round begins' },
                    { event: 'agent_message', desc: 'Agent responds' },
                    { event: 'vote', desc: 'Vote cast' },
                    { event: 'insight_extracted', desc: 'Insight found' },
                    { event: 'claim_verification_result', desc: 'Claim verified' },
                    { event: 'gauntlet_complete', desc: 'Gauntlet done' },
                    { event: 'graph_branch_created', desc: 'Branch created' },
                    { event: 'breakpoint', desc: 'Human intervention' },
                    { event: 'genesis_evolution', desc: 'Population evolved' },
                  ].map(({ event, desc }) => (
                    <div
                      key={event}
                      className="p-2 border border-[var(--accent)]/10 rounded bg-surface/20 flex items-center justify-between"
                    >
                      <code className="font-theme-data text-xs text-[var(--acid-cyan)]">
                        {event}
                      </code>
                      <span className="font-theme-data text-xs text-text-muted">{desc}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Environment Variables */}
              <div>
                <h3 className="font-theme-data text-text mb-4 text-sm">Environment Variables</h3>
                <div className="p-4 border border-[var(--accent)]/20 rounded bg-bg/50 overflow-x-auto">
                  <pre className="font-theme-data text-xs text-text-muted whitespace-pre">
                    {`# Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_BOT_TOKEN=xoxb-...

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=-1001234567890

# Email
SENDGRID_API_KEY=SG.xxxxxxxxx
# or AWS SES credentials

# Microsoft Teams
TEAMS_WEBHOOK_URL=https://xxx.webhook.office.com/webhookb2/...

# WhatsApp (Meta)
WHATSAPP_PHONE_NUMBER_ID=1234567890
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxxx
# or Twilio credentials

# Matrix
MATRIX_HOMESERVER_URL=https://matrix.org
MATRIX_ACCESS_TOKEN=syt_xxxxx
MATRIX_ROOM_ID=!abc123:matrix.org`}
                  </pre>
                </div>
              </div>

              {/* API Example */}
              <div>
                <h3 className="font-theme-data text-text mb-4 text-sm">SDK Example</h3>
                <div className="p-4 border border-[var(--accent)]/20 rounded bg-bg/50 overflow-x-auto">
                  <pre className="font-theme-data text-xs text-[var(--acid-cyan)] whitespace-pre">
                    {`import { Aragora } from '@aragora/sdk';

const client = new Aragora({ apiKey: 'your-api-key' });

// Configure Slack integration
await client.integrations.configure('slack', {
  webhook_url: 'https://hooks.slack.com/...',
  notify_on_consensus: true,
  notify_on_debate_end: true,
});

// List configured integrations
const integrations = await client.integrations.list();

// Test connection
const result = await client.integrations.test('slack');
console.log(result.success); // true`}
                  </pre>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Setup Wizard Modal */}
      {wizardOpen && (
        <IntegrationSetupWizard
          type={wizardOpen}
          onClose={() => {
            setWizardOpen(null);
            setEditingConfig(undefined);
          }}
          onSave={handleSaveIntegration}
          onTest={handleTestIntegration}
          existingConfig={editingConfig}
        />
      )}
    </>
  );
}
