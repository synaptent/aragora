'use client';

import { useState, useEffect, useCallback } from 'react';
import { getRuntimeBackendConfig } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';

interface ProviderStatus {
  id: string;
  name: string;
  icon: string;
  category: 'ai' | 'channel' | 'data';
  connected: boolean;
  required: boolean;
}

interface IntegrationSelectorProps {
  onComplete: (connectedProviders: string[]) => void;
  onSkip?: () => void;
  onBack?: () => void;
}

const DEFAULT_PROVIDERS: ProviderStatus[] = [
  {
    id: 'anthropic',
    name: 'Anthropic (Claude)',
    icon: 'A',
    category: 'ai',
    connected: false,
    required: true,
  },
  {
    id: 'openai',
    name: 'OpenAI (GPT)',
    icon: 'O',
    category: 'ai',
    connected: false,
    required: false,
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    icon: 'R',
    category: 'ai',
    connected: false,
    required: false,
  },
  {
    id: 'mistral',
    name: 'Mistral AI',
    icon: 'M',
    category: 'ai',
    connected: false,
    required: false,
  },
  { id: 'slack', name: 'Slack', icon: 'S', category: 'channel', connected: false, required: false },
  {
    id: 'github',
    name: 'GitHub',
    icon: 'G',
    category: 'channel',
    connected: false,
    required: false,
  },
  {
    id: 'email',
    name: 'Email (SMTP)',
    icon: 'E',
    category: 'channel',
    connected: false,
    required: false,
  },
  {
    id: 'supabase',
    name: 'Supabase',
    icon: 'D',
    category: 'data',
    connected: false,
    required: false,
  },
];

const CATEGORY_LABELS: Record<string, string> = {
  ai: 'AI PROVIDERS',
  channel: 'CHANNELS',
  data: 'DATA & STORAGE',
};

/**
 * IntegrationSelector component for onboarding.
 * Shows provider connection status and allows users to configure integrations.
 */
export function IntegrationSelector({ onComplete, onSkip, onBack }: IntegrationSelectorProps) {
  const apiBase = getRuntimeBackendConfig().config.api;
  const [providers, setProviders] = useState<ProviderStatus[]>(DEFAULT_PROVIDERS);
  const [loading, setLoading] = useState(true);

  // Fetch current integration status
  useEffect(() => {
    async function checkStatus() {
      try {
        const res = await fetch(`${apiBase}/api/v1/integrations/status`);
        if (res.ok) {
          const data = await res.json();
          const statusMap: Record<string, boolean> = data.integrations ?? {};
          setProviders((prev) =>
            prev.map((p) => ({ ...p, connected: statusMap[p.id] ?? p.connected })),
          );
        }
      } catch (err) {
        logger.debug('Could not fetch integration status:', err);
      } finally {
        setLoading(false);
      }
    }

    checkStatus();
  }, [apiBase]);

  const connectedCount = providers.filter((p) => p.connected).length;
  const hasRequiredProvider = providers.some((p) => p.required && p.connected);

  const handleComplete = useCallback(() => {
    const connected = providers.filter((p) => p.connected).map((p) => p.id);
    onComplete(connected);
  }, [providers, onComplete]);

  const categories = ['ai', 'channel', 'data'] as const;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-theme-data text-[var(--acid-green)] mb-2">
          Connect Your Tools
        </h2>
        <p className="font-theme-data text-[var(--text-muted)] text-sm">
          Aragora works best with multiple AI providers for diverse debate perspectives. At least
          one AI provider is required.
        </p>
      </div>

      {loading ? (
        <div className="space-y-4 animate-pulse">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-[var(--border)] rounded" />
          ))}
        </div>
      ) : (
        <div className="space-y-5">
          {categories.map((cat) => {
            const catProviders = providers.filter((p) => p.category === cat);
            return (
              <div key={cat}>
                <h3 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-2 flex items-center gap-2">
                  <span>{cat === 'ai' ? '>' : cat === 'channel' ? '#' : '$'}</span>
                  {CATEGORY_LABELS[cat]}
                </h3>
                <div className="space-y-1">
                  {catProviders.map((provider) => (
                    <div
                      key={provider.id}
                      className={`flex items-center justify-between p-3 border transition-colors ${
                        provider.connected
                          ? 'border-green-500/30 bg-green-500/5'
                          : 'border-[var(--border)] bg-[var(--surface)]'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className={`w-6 h-6 flex items-center justify-center text-xs font-theme-data font-bold ${
                            provider.connected
                              ? 'bg-green-500/20 text-green-400'
                              : 'bg-[var(--border)] text-[var(--text-muted)]'
                          }`}
                        >
                          {provider.icon}
                        </span>
                        <div>
                          <span className="text-sm font-theme-data text-[var(--text)]">
                            {provider.name}
                          </span>
                          {provider.required && (
                            <span className="ml-2 text-[10px] font-theme-data text-yellow-400">
                              REQUIRED
                            </span>
                          )}
                        </div>
                      </div>
                      <span
                        className={`text-xs font-theme-data px-2 py-0.5 ${
                          provider.connected
                            ? 'bg-green-500/20 text-green-400'
                            : 'bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)]'
                        }`}
                      >
                        {provider.connected ? 'CONNECTED' : 'NOT SET'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Status summary */}
      <div
        className={`p-3 border text-xs font-theme-data ${
          hasRequiredProvider
            ? 'border-green-500/30 bg-green-500/5 text-green-400'
            : 'border-yellow-500/30 bg-yellow-500/5 text-yellow-400'
        }`}
      >
        {hasRequiredProvider
          ? `> ${connectedCount} provider${connectedCount > 1 ? 's' : ''} connected. You're ready to start debates.`
          : '! At least one AI provider is required. Configure API keys in Settings.'}
      </div>

      {/* Actions */}
      <div className="flex gap-3 pt-2">
        {onBack && (
          <button
            onClick={onBack}
            className="px-4 py-2 font-theme-data text-sm border border-[var(--acid-green)]/30 text-[var(--text-muted)] hover:border-[var(--acid-green)] hover:text-[var(--acid-green)] transition-colors"
          >
            Back
          </button>
        )}
        <div className="flex-1" />
        {onSkip && (
          <button
            onClick={onSkip}
            className="px-4 py-2 font-theme-data text-sm text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
          >
            Skip for now
          </button>
        )}
        <button
          onClick={handleComplete}
          className="px-6 py-2 font-theme-data text-sm bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors"
        >
          Continue
        </button>
      </div>
    </div>
  );
}

export default IntegrationSelector;
