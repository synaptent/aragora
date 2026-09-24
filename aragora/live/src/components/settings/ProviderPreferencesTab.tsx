'use client';

import { useMemo } from 'react';
import { useSWRFetch } from '@/hooks/useSWRFetch';

interface RawProviderStatus {
  provider?: string;
  name?: string;
  display_name?: string;
  available?: boolean;
  configured?: boolean;
  status?: string | null;
  model?: string | null;
  default_model?: string | null;
  reason?: string | null;
  env_vars?: string[];
  required_env_vars?: string[];
  optional_env_vars?: string[];
  required?: boolean;
  is_required?: boolean;
}

interface ProviderStatusResponse {
  providers?: Record<string, RawProviderStatus> | RawProviderStatus[];
  missing_required?: string[];
  missing_optional?: string[];
  ready_to_debate?: boolean;
  timestamp?: string;
}

interface ProviderCard {
  id: string;
  displayName: string;
  configured: boolean;
  available: boolean;
  required: boolean;
  configurationLabel: string;
  availabilityLabel: string;
  model: string | null;
  reason: string | null;
  envVars: string[];
  missingEnvVars: string[];
}

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
  gemini: 'Google Gemini',
  mistral: 'Mistral',
  xai: 'xAI',
  grok: 'Grok',
};

const PROVIDER_ORDER = ['anthropic', 'openai', 'openrouter', 'gemini', 'xai', 'mistral'];
const REQUIRED_PROVIDERS = new Set(['anthropic', 'openai', 'openrouter']);
const ONLINE_STATUSES = new Set(['available', 'online', 'ready', 'healthy', 'connected']);
const CONFIGURED_STATUSES = new Set([
  'configured',
  'available',
  'online',
  'ready',
  'healthy',
  'connected',
]);

function dedupe(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function startCase(value: string): string {
  return value
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');
}

function formatStatusLabel(value: string): string {
  return value.replace(/[_-]+/g, ' ').toUpperCase();
}

function getProviderId(raw: RawProviderStatus, fallbackId?: string): string {
  if (fallbackId) return fallbackId;
  if (raw.provider) return raw.provider;
  if (raw.name) return raw.name;
  if (raw.display_name) return raw.display_name.toLowerCase().replace(/\s+/g, '_');
  return 'unknown';
}

function getEnvVars(raw: RawProviderStatus): string[] {
  return dedupe([
    ...(raw.env_vars || []),
    ...(raw.required_env_vars || []),
    ...(raw.optional_env_vars || []),
  ]);
}

// The endpoint contract may vary slightly across deployments, so normalize both
// object and array payloads into a stable UI shape.
function normalizeProviders(data: ProviderStatusResponse | null): ProviderCard[] {
  const missingRequired = new Set(data?.missing_required || []);
  const missingOptional = new Set(data?.missing_optional || []);
  const rawProviders = Array.isArray(data?.providers)
    ? data.providers.map((provider) => [getProviderId(provider), provider] as const)
    : Object.entries(data?.providers || {});

  return rawProviders
    .map(([providerId, rawProvider]) => {
      const id = getProviderId(rawProvider, providerId);
      const normalizedStatus = (rawProvider.status || '').trim().toLowerCase().replace(/\s+/g, '_');
      const envVars = getEnvVars(rawProvider);
      const missingEnvVars = envVars.filter(
        (envVar) => missingRequired.has(envVar) || missingOptional.has(envVar),
      );

      const available =
        typeof rawProvider.available === 'boolean'
          ? rawProvider.available
          : ONLINE_STATUSES.has(normalizedStatus);
      const configured =
        typeof rawProvider.configured === 'boolean'
          ? rawProvider.configured
          : envVars.length > 0
            ? missingEnvVars.length < envVars.length
            : typeof rawProvider.available === 'boolean'
              ? rawProvider.available
              : CONFIGURED_STATUSES.has(normalizedStatus);
      const required =
        typeof rawProvider.required === 'boolean'
          ? rawProvider.required
          : typeof rawProvider.is_required === 'boolean'
            ? rawProvider.is_required
            : REQUIRED_PROVIDERS.has(id) || envVars.some((envVar) => missingRequired.has(envVar));

      return {
        id,
        displayName: rawProvider.display_name || PROVIDER_LABELS[id] || startCase(id),
        configured,
        available,
        required,
        configurationLabel: configured ? 'CONFIGURED' : 'MISSING CONFIG',
        availabilityLabel:
          rawProvider.status && !CONFIGURED_STATUSES.has(normalizedStatus)
            ? formatStatusLabel(rawProvider.status)
            : available
              ? 'ONLINE'
              : 'OFFLINE',
        model: rawProvider.model || rawProvider.default_model || null,
        reason:
          rawProvider.reason ||
          (!configured && missingEnvVars.length > 0
            ? `Missing ${missingEnvVars.join(', ')}`
            : null),
        envVars,
        missingEnvVars,
      };
    })
    .sort((left, right) => {
      const leftOrder = PROVIDER_ORDER.indexOf(left.id);
      const rightOrder = PROVIDER_ORDER.indexOf(right.id);

      if (left.required !== right.required) return left.required ? -1 : 1;
      if (leftOrder !== -1 || rightOrder !== -1) {
        const safeLeftOrder = leftOrder === -1 ? Number.MAX_SAFE_INTEGER : leftOrder;
        const safeRightOrder = rightOrder === -1 ? Number.MAX_SAFE_INTEGER : rightOrder;
        if (safeLeftOrder !== safeRightOrder) return safeLeftOrder - safeRightOrder;
      }
      return left.displayName.localeCompare(right.displayName);
    });
}

export function ProviderPreferencesTab() {
  const { data, error, isLoading, isValidating, mutate } = useSWRFetch<ProviderStatusResponse>(
    '/api/v1/routing/providers/status',
    { refreshInterval: 120000 },
  );

  const providers = useMemo(() => normalizeProviders(data), [data]);
  const configuredProviders = providers.filter((provider) => provider.configured).length;
  const onlineProviders = providers.filter((provider) => provider.available).length;
  const missingRequiredCount = data?.missing_required?.length || 0;
  const missingOptionalCount = data?.missing_optional?.length || 0;
  const lastChecked = data?.timestamp ? new Date(data.timestamp).toLocaleString() : null;

  if (isLoading && providers.length === 0) {
    return (
      <div className="space-y-4">
        <div className="animate-pulse grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {[...Array(4)].map((_, index) => (
            <div key={index} className="h-24 bg-[var(--surface)] border border-[var(--border)]" />
          ))}
        </div>
        <div className="animate-pulse grid gap-4 lg:grid-cols-2">
          {[...Array(4)].map((_, index) => (
            <div key={index} className="h-48 bg-[var(--surface)] border border-[var(--border)]" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-sm font-theme-data text-[var(--acid-green)]">
            {'>'} PROVIDER PREFERENCES
          </h2>
          <p className="mt-1 text-xs font-theme-data text-[var(--text-muted)]">
            Inspect which routing providers are configured and whether they are currently reachable.
          </p>
          {lastChecked && (
            <p className="mt-2 text-[10px] font-theme-data text-[var(--text-muted)]">
              Last checked: {lastChecked}
            </p>
          )}
        </div>
        <button
          onClick={() => void mutate()}
          disabled={isValidating}
          className="px-4 py-2 font-theme-data text-xs border border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--acid-green)] hover:text-[var(--acid-green)] disabled:opacity-50"
        >
          {isValidating ? 'REFRESHING...' : 'REFRESH'}
        </button>
      </div>

      {typeof data?.ready_to_debate === 'boolean' && (
        <div
          className={`p-3 border font-theme-data text-xs ${
            data.ready_to_debate
              ? 'bg-[var(--acid-green)]/10 border-[var(--acid-green)]/30 text-[var(--acid-green)]'
              : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
          }`}
        >
          {data.ready_to_debate
            ? 'At least one core provider is configured for routing.'
            : 'No core routing provider is configured yet.'}
        </div>
      )}

      {error && providers.length === 0 ? (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
          Failed to load provider status from /api/v1/routing/providers/status.
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-[var(--acid-green)]">
                {configuredProviders}
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                Configured Providers
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                {onlineProviders}
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                Online Providers
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-amber-300">{missingRequiredCount}</div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                Missing Required Env Vars
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-[var(--text)]">
                {missingOptionalCount}
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                Missing Optional Env Vars
              </div>
            </div>
          </div>

          {providers.length === 0 ? (
            <div className="p-8 bg-[var(--surface)] border border-[var(--border)] text-center font-theme-data text-sm text-[var(--text-muted)]">
              No provider status was returned by the routing API.
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {providers.map((provider) => (
                <div
                  key={provider.id}
                  className={`p-4 bg-[var(--surface)] border ${
                    provider.available
                      ? 'border-[var(--acid-green)]/40'
                      : provider.configured
                        ? 'border-[var(--acid-cyan)]/30'
                        : 'border-[var(--border)]'
                  }`}
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <h3 className="text-sm font-theme-data text-[var(--text)]">
                        {provider.displayName}
                      </h3>
                      <p className="mt-1 text-[10px] font-theme-data uppercase tracking-wider text-[var(--text-muted)]">
                        {provider.id}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {provider.required && (
                        <span className="px-2 py-0.5 text-[10px] font-theme-data bg-amber-500/10 border border-amber-500/30 text-amber-300">
                          CORE
                        </span>
                      )}
                      <span
                        className={`px-2 py-0.5 text-[10px] font-theme-data border ${
                          provider.configured
                            ? 'bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)]'
                            : 'bg-[var(--bg)] border-[var(--border)] text-[var(--text-muted)]'
                        }`}
                      >
                        {provider.configurationLabel}
                      </span>
                      <span
                        className={`px-2 py-0.5 text-[10px] font-theme-data border ${
                          provider.available
                            ? 'bg-[var(--acid-green)]/10 border-[var(--acid-green)]/30 text-[var(--acid-green)]'
                            : 'bg-[var(--bg)] border-[var(--border)] text-[var(--text-muted)]'
                        }`}
                      >
                        {provider.availabilityLabel}
                      </span>
                    </div>
                  </div>

                  <div className="mt-4 space-y-3 font-theme-data text-xs">
                    <div className="text-[var(--text-muted)]">
                      Model:{' '}
                      <span className="text-[var(--text)]">{provider.model || 'Not reported'}</span>
                    </div>

                    {provider.envVars.length > 0 && (
                      <div>
                        <div className="mb-1 text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                          Environment Variables
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {provider.envVars.map((envVar) => (
                            <span
                              key={envVar}
                              className={`px-2 py-0.5 border text-[10px] ${
                                provider.missingEnvVars.includes(envVar)
                                  ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                                  : 'bg-[var(--bg)] border-[var(--border)] text-[var(--text)]'
                              }`}
                            >
                              {envVar}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {provider.reason && (
                      <div className="p-3 bg-[var(--bg)] border border-[var(--border)] text-[var(--text-muted)]">
                        {provider.reason}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
