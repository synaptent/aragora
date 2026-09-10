'use client';

import { useState, useEffect, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';
import {
  IntegrationType,
  INTEGRATION_CONFIGS,
  MASKED_SECRET_FIELD_VALUE,
} from './IntegrationSetupWizard';

interface IntegrationStatus {
  type: IntegrationType;
  enabled: boolean;
  lastActivity?: string;
  messagesSent: number;
  errors: number;
  status: 'connected' | 'degraded' | 'disconnected' | 'not_configured';
}

interface IntegrationStatusDashboardProps {
  onConfigure: (type: IntegrationType) => void;
  onEdit: (type: IntegrationType, config: Record<string, unknown>) => void;
}

const MASKED_SECRET_DISPLAY_VALUE = '••••••••';

async function readResponseMessage(response: Response, fallback: string) {
  const text = await response.text().catch(() => '');
  if (!text) {
    return fallback;
  }

  try {
    const data = JSON.parse(text) as { error?: unknown; message?: unknown };
    if (typeof data.error === 'string' && data.error) {
      return data.error;
    }
    if (typeof data.message === 'string' && data.message) {
      return data.message;
    }
  } catch {
    return text;
  }

  return text;
}

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  const message = await readResponseMessage(response, fallback);
  if (response.status === 401) {
    return 'Sign in to view and manage live integrations.';
  }
  if (response.status === 403) {
    return message || 'You do not have permission to manage integrations.';
  }
  return message;
}

function buildEditConfig(
  type: IntegrationType,
  integration: Record<string, unknown>,
): Record<string, unknown> {
  const settings = (
    integration.settings && typeof integration.settings === 'object' ? integration.settings : {}
  ) as Record<string, unknown>;
  const config = INTEGRATION_CONFIGS[type];
  const nextConfig: Record<string, unknown> = { enabled: integration.enabled !== false };

  for (const field of config.fields) {
    const rawValue = settings[field.key];
    if (rawValue === undefined) {
      continue;
    }
    nextConfig[field.key] =
      field.type === 'password' && rawValue === MASKED_SECRET_DISPLAY_VALUE
        ? MASKED_SECRET_FIELD_VALUE
        : rawValue;
  }

  for (const option of config.notificationOptions) {
    if (integration[option.key] !== undefined) {
      nextConfig[option.key] = integration[option.key];
      continue;
    }
    if (settings[option.key] !== undefined) {
      nextConfig[option.key] = settings[option.key];
      continue;
    }
    nextConfig[option.key] = option.default;
  }

  return nextConfig;
}

function StatusIndicator({ status }: { status: IntegrationStatus['status'] }) {
  const styles: Record<string, { bg: string; text: string; label: string }> = {
    connected: { bg: 'bg-[var(--accent)]/20', text: 'text-[var(--accent)]', label: 'CONNECTED' },
    degraded: { bg: 'bg-warning/20', text: 'text-warning', label: 'DEGRADED' },
    disconnected: {
      bg: 'bg-[var(--crimson)]/20',
      text: 'text-[var(--crimson)]',
      label: 'DISCONNECTED',
    },
    not_configured: { bg: 'bg-text-muted/20', text: 'text-text-muted', label: 'NOT CONFIGURED' },
  };

  const style = styles[status] || styles.not_configured;

  return (
    <span className={`px-2 py-0.5 text-xs font-theme-data rounded ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

export function IntegrationStatusDashboard({
  onConfigure,
  onEdit,
}: IntegrationStatusDashboardProps) {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const [integrations, setIntegrations] = useState<IntegrationStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadingConfigType, setLoadingConfigType] = useState<IntegrationType | null>(null);

  const buildAuthHeaders = useCallback(
    (options: { contentType?: string; requireAuth?: boolean } = {}) => {
      const headers: HeadersInit = {};

      if (options.contentType) {
        headers['Content-Type'] = options.contentType;
      }

      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
        return headers;
      }

      if (options.requireAuth) {
        setError('Sign in to view and manage live integrations.');
        return null;
      }

      return headers;
    },
    [tokens?.access_token],
  );

  const fetchStatus = useCallback(async () => {
    const headers = buildAuthHeaders({ requireAuth: true });
    if (!headers) {
      setIntegrations([]);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${backendConfig.api}/api/integrations/status`, { headers });

      if (res.ok) {
        const data = await res.json();
        setIntegrations(data.integrations || []);
      } else {
        setIntegrations([]);
        setError(
          await readErrorMessage(res, 'Live integration status is unavailable from this backend.'),
        );
      }
    } catch (err) {
      setIntegrations([]);
      setError(err instanceof Error ? err.message : 'Failed to load integration status');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, buildAuthHeaders]);

  useEffect(() => {
    void fetchStatus();
    // Refresh every 30 seconds
    const interval = setInterval(() => {
      void fetchStatus();
    }, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const handleDisable = async (type: IntegrationType) => {
    if (!confirm(`Disable ${INTEGRATION_CONFIGS[type].title} integration?`)) return;

    const headers = buildAuthHeaders({ contentType: 'application/json', requireAuth: true });
    if (!headers) return;

    try {
      const res = await fetch(`${backendConfig.api}/api/integrations/${type}`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify({ enabled: false }),
      });

      if (res.ok) {
        void fetchStatus();
      } else {
        setError(
          await readErrorMessage(res, `Failed to disable ${INTEGRATION_CONFIGS[type].title}.`),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to disable integration');
    }
  };

  const handleDelete = async (type: IntegrationType) => {
    if (!confirm(`Delete ${INTEGRATION_CONFIGS[type].title} configuration? This cannot be undone.`))
      return;

    const headers = buildAuthHeaders({ requireAuth: true });
    if (!headers) return;

    try {
      const res = await fetch(`${backendConfig.api}/api/integrations/${type}`, {
        method: 'DELETE',
        headers,
      });

      if (res.ok) {
        void fetchStatus();
      } else {
        setError(
          await readErrorMessage(res, `Failed to delete ${INTEGRATION_CONFIGS[type].title}.`),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete integration');
    }
  };

  const handleTestConnection = async (type: IntegrationType) => {
    const headers = buildAuthHeaders({ requireAuth: true });
    if (!headers) return;

    try {
      const res = await fetch(`${backendConfig.api}/api/integrations/${type}/test`, {
        method: 'POST',
        headers,
      });

      if (res.ok) {
        const data = await res.json();
        alert(data.success ? 'Connection test successful!' : `Test failed: ${data.error}`);
      } else {
        setError(await readErrorMessage(res, `Failed to test ${INTEGRATION_CONFIGS[type].title}.`));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection test failed');
    }
  };

  const handleEditClick = async (type: IntegrationType) => {
    const headers = buildAuthHeaders({ requireAuth: true });
    if (!headers) return;

    setLoadingConfigType(type);
    setError(null);

    try {
      const res = await fetch(`${backendConfig.api}/api/integrations/${type}`, { headers });

      if (!res.ok) {
        setError(
          await readErrorMessage(
            res,
            `${INTEGRATION_CONFIGS[type].title} configuration is unavailable from this backend.`,
          ),
        );
        if (res.status === 404) {
          void fetchStatus();
        }
        return;
      }

      const data = await res.json();
      onEdit(type, buildEditConfig(type, data.integration || {}));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load integration configuration');
    } finally {
      setLoadingConfigType(null);
    }
  };

  // Calculate stats
  const connectedCount = integrations.filter((i) => i.status === 'connected').length;
  const totalMessages = integrations.reduce((sum, i) => sum + i.messagesSent, 0);
  const totalErrors = integrations.reduce((sum, i) => sum + i.errors, 0);

  if (loading) {
    return (
      <div className="p-6 border border-[var(--accent)]/20 rounded bg-surface/30">
        <p className="font-theme-data text-text-muted text-center">Loading integration status...</p>
      </div>
    );
  }

  if (integrations.length === 0) {
    return (
      <div className="space-y-4">
        {error && (
          <div className="p-3 border border-warning/30 bg-warning/10 rounded">
            <p className="text-warning font-theme-data text-sm">{error}</p>
          </div>
        )}

        <div className="p-6 border border-warning/30 rounded bg-surface/30">
          <p className="font-theme-data text-text text-center">
            No live integration status is available.
          </p>
          <p className="mt-2 font-theme-data text-xs text-text-muted text-center">
            Sign in and connect to a backend that exposes the integrations API to view real status
            data.
          </p>
        </div>

        <div className="text-center">
          <button
            onClick={() => void fetchStatus()}
            className="text-xs font-theme-data text-text-muted hover:text-text transition-colors"
          >
            [REFRESH STATUS]
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {integrations.length > 0 && (
        <div className="grid grid-cols-3 gap-4">
          <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30 text-center">
            <div className="font-theme-data text-2xl text-[var(--accent)]">{connectedCount}</div>
            <div className="font-theme-data text-xs text-text-muted">Connected</div>
          </div>
          <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30 text-center">
            <div className="font-theme-data text-2xl text-[var(--acid-cyan)]">
              {totalMessages.toLocaleString()}
            </div>
            <div className="font-theme-data text-xs text-text-muted">Messages Sent</div>
          </div>
          <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30 text-center">
            <div className="font-theme-data text-2xl text-warning">{totalErrors}</div>
            <div className="font-theme-data text-xs text-text-muted">Errors (24h)</div>
          </div>
        </div>
      )}

      {error && (
        <div className="p-3 border border-warning/30 bg-warning/10 rounded">
          <p className="text-warning font-theme-data text-sm">{error}</p>
        </div>
      )}

      {/* Integration List */}
      <div className="space-y-3">
        {integrations.map((integration) => {
          const config = INTEGRATION_CONFIGS[integration.type];
          const isConfigured = integration.status !== 'not_configured';

          return (
            <div
              key={integration.type}
              className={`p-4 border rounded transition-colors ${
                isConfigured
                  ? 'border-[var(--accent)]/30 bg-surface/40'
                  : 'border-[var(--accent)]/10 bg-surface/20'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span className="font-theme-data text-lg text-[var(--acid-cyan)]">
                    {config.icon}
                  </span>
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="font-theme-data text-text">{config.title}</h4>
                      <StatusIndicator status={integration.status} />
                    </div>
                    <p className="font-theme-data text-xs text-text-muted mt-0.5">
                      {config.description}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {isConfigured ? (
                    <>
                      <button
                        onClick={() => handleTestConnection(integration.type)}
                        className="px-2 py-1 text-xs font-theme-data border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                      >
                        [TEST]
                      </button>
                      <button
                        onClick={() => handleEditClick(integration.type)}
                        disabled={loadingConfigType === integration.type}
                        className="px-2 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-text transition-colors"
                      >
                        {loadingConfigType === integration.type ? '[LOADING...]' : '[EDIT]'}
                      </button>
                      <button
                        onClick={() => handleDisable(integration.type)}
                        className="px-2 py-1 text-xs font-theme-data border border-warning/30 text-warning hover:bg-warning/10 transition-colors"
                      >
                        [DISABLE]
                      </button>
                      <button
                        onClick={() => handleDelete(integration.type)}
                        className="px-2 py-1 text-xs font-theme-data border border-[var(--crimson)]/30 text-[var(--crimson)] hover:bg-[var(--crimson)]/10 transition-colors"
                      >
                        [DELETE]
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => onConfigure(integration.type)}
                      className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                    >
                      [CONFIGURE]
                    </button>
                  )}
                </div>
              </div>

              {isConfigured && (
                <div className="mt-3 pt-3 border-t border-[var(--accent)]/10 flex gap-4 text-xs font-theme-data">
                  <span className="text-text-muted">
                    Messages:{' '}
                    <span className="text-[var(--acid-cyan)]">{integration.messagesSent}</span>
                  </span>
                  {integration.errors > 0 && (
                    <span className="text-text-muted">
                      Errors: <span className="text-warning">{integration.errors}</span>
                    </span>
                  )}
                  {integration.lastActivity && (
                    <span className="text-text-muted">
                      Last activity: {new Date(integration.lastActivity).toLocaleString()}
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Refresh Button */}
      <div className="text-center">
        <button
          onClick={() => void fetchStatus()}
          className="text-xs font-theme-data text-text-muted hover:text-text transition-colors"
        >
          [REFRESH STATUS]
        </button>
      </div>
    </div>
  );
}

export default IntegrationStatusDashboard;
