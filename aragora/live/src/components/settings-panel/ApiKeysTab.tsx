'use client';

import { useState, useEffect, useCallback } from 'react';
import type { UserPreferences, ApiKey } from './types';
import {
  LLM_PROVIDERS,
  getStoredProviderKeys,
  storeProviderKeys,
  type ProviderKeyConfig,
} from '@/lib/provider-keys';
import { ConnectOpenRouterButton } from '@/components/openrouter/ConnectOpenRouterButton';
export { getProviderKeyHeaders } from '@/lib/provider-keys';

export interface ApiKeysTabProps {
  preferences: UserPreferences;
  onGenerateKey: () => Promise<string>;
  onRevokeKey: (prefix: string) => Promise<void>;
  apiBase?: string;
  loading?: boolean;
  error?: string | null;
  singleKeyMode?: boolean;
}

function formatExpirationTime(dateString: string | null | undefined): {
  text: string;
  isExpiringSoon: boolean;
  isExpired: boolean;
} {
  if (!dateString) return { text: 'Never expires', isExpiringSoon: false, isExpired: false };
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMs < 0) return { text: 'Expired', isExpiringSoon: false, isExpired: true };
  if (diffDays < 7)
    return { text: `Expires in ${diffDays}d`, isExpiringSoon: true, isExpired: false };
  if (diffDays < 30)
    return { text: `Expires in ${diffDays}d`, isExpiringSoon: false, isExpired: false };
  return { text: `Expires ${date.toLocaleDateString()}`, isExpiringSoon: false, isExpired: false };
}

function ApiKeyCard({
  apiKey,
  onRevoke,
  apiBase,
}: {
  apiKey: ApiKey;
  onRevoke: () => Promise<void>;
  apiBase?: string;
}) {
  const [showCurl, setShowCurl] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [isRevoking, setIsRevoking] = useState(false);
  const expiration = formatExpirationTime(apiKey.expires_at);
  const createdAtLabel = apiKey.created_at
    ? new Date(apiKey.created_at).toLocaleDateString()
    : 'Unknown';

  const curlExample = `curl -X POST ${apiBase || 'https://api.aragora.ai'}/api/v1/debates \\
  -H "Authorization: Bearer ${apiKey.prefix}..." \\
  -H "Content-Type: application/json" \\
  -d '{"task": "Your debate topic here"}'`;

  const handleCopy = async (text: string, type: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(type);
    setTimeout(() => setCopied(null), 2000);
  };

  const handleRevoke = async () => {
    if (isRevoking) return;
    setIsRevoking(true);
    try {
      await onRevoke();
    } finally {
      setIsRevoking(false);
    }
  };

  return (
    <div
      className={`p-4 bg-surface rounded border ${
        expiration.isExpired
          ? 'border-[var(--crimson)]/40'
          : expiration.isExpiringSoon
            ? 'border-acid-yellow/40'
            : 'border-[var(--accent)]/20'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="font-theme-data text-sm text-text font-medium">
            {apiKey.name || 'Active key'}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <code className="font-theme-data text-xs text-text-muted bg-bg px-1.5 py-0.5 rounded">
              {apiKey.prefix}...
            </code>
            <span className="text-text-muted text-[10px]">Created {createdAtLabel}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCurl(!showCurl)}
            className="px-2 py-1 text-[10px] font-theme-data text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 rounded transition-colors"
            title="Show cURL example"
          >
            {showCurl ? 'Hide' : 'cURL'}
          </button>
          <button
            onClick={handleRevoke}
            disabled={isRevoking}
            className="px-2 py-1 text-[10px] font-theme-data text-[var(--crimson)] hover:bg-[var(--crimson)]/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRevoking ? 'Revoking...' : 'Revoke'}
          </button>
        </div>
      </div>

      <div className="grid gap-3 mb-3 sm:grid-cols-2">
        <div className="rounded border border-border bg-bg/60 p-3">
          <div className="text-[10px] font-theme-data text-text-muted uppercase tracking-wide">
            Status
          </div>
          <div
            className={`mt-1 font-theme-data text-sm ${
              expiration.isExpired ? 'text-[var(--crimson)]' : 'text-[var(--accent)]'
            }`}
          >
            {expiration.isExpired ? 'Expired' : 'Active'}
          </div>
        </div>
        <div className="rounded border border-border bg-bg/60 p-3">
          <div className="text-[10px] font-theme-data text-text-muted uppercase tracking-wide">
            Expiration
          </div>
          <div
            className={`mt-1 font-theme-data text-sm ${
              expiration.isExpired
                ? 'text-[var(--crimson)]'
                : expiration.isExpiringSoon
                  ? 'text-[var(--acid-yellow)]'
                  : 'text-text'
            }`}
          >
            {expiration.text}
          </div>
        </div>
      </div>

      {/* Expiration Warning */}
      {(expiration.isExpired || expiration.isExpiringSoon) && (
        <div
          className={`text-xs font-theme-data px-2 py-1 rounded mb-3 ${
            expiration.isExpired
              ? 'bg-[var(--crimson)]/10 text-[var(--crimson)]'
              : 'bg-acid-yellow/10 text-[var(--acid-yellow)]'
          }`}
        >
          {expiration.text}
        </div>
      )}

      {/* cURL Example */}
      {showCurl && (
        <div className="mt-3 pt-3 border-t border-border">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-theme-data text-text-muted">cURL Example</span>
            <button
              onClick={() => handleCopy(curlExample, 'curl')}
              className={`px-2 py-0.5 text-[10px] font-theme-data rounded transition-colors ${
                copied === 'curl'
                  ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                  : 'text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10'
              }`}
            >
              {copied === 'curl' ? 'Copied!' : 'Copy'}
            </button>
          </div>
          <pre className="bg-bg p-3 rounded font-theme-data text-[10px] text-text overflow-x-auto whitespace-pre-wrap">
            {curlExample}
          </pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Provider Keys — localStorage-backed LLM provider key management
// ---------------------------------------------------------------------------

function maskKey(key: string): string {
  if (key.length <= 8) return '*'.repeat(key.length);
  return key.slice(0, 4) + '*'.repeat(Math.min(key.length - 8, 20)) + key.slice(-4);
}

function ProviderKeyRow({
  provider,
  savedValue,
  onSave,
  onClear,
}: {
  provider: ProviderKeyConfig;
  savedValue: string;
  onSave: (value: string) => void;
  onClear: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const hasSaved = !!savedValue;

  const handleSave = () => {
    const trimmed = inputValue.trim();
    if (trimmed) {
      onSave(trimmed);
      setInputValue('');
      setEditing(false);
    }
  };

  const handleCancel = () => {
    setInputValue('');
    setEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSave();
    if (e.key === 'Escape') handleCancel();
  };

  return (
    <div className="p-4 bg-surface rounded border border-border hover:border-[var(--accent)]/20 transition-colors">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-theme-data text-sm text-text font-medium">{provider.label}</span>
            {hasSaved && (
              <span className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30 rounded">
                SET
              </span>
            )}
          </div>
          <code className="font-theme-data text-[10px] text-text-muted">{provider.envVar}</code>
          {hasSaved && !editing && (
            <div className="mt-2">
              <code className="font-theme-data text-xs text-text-muted bg-bg px-1.5 py-0.5 rounded">
                {maskKey(savedValue)}
              </code>
            </div>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {provider.docsUrl && (
            <a
              href={provider.docsUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="px-2 py-1 text-[10px] font-theme-data text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 rounded transition-colors"
              title={`Get ${provider.label} API key`}
            >
              Get key
            </a>
          )}
          {!editing && (
            <button
              onClick={() => setEditing(true)}
              className="px-2 py-1 text-[10px] font-theme-data text-[var(--accent)] hover:bg-[var(--accent)]/10 rounded transition-colors"
            >
              {hasSaved ? 'Update' : 'Set'}
            </button>
          )}
          {hasSaved && !editing && (
            <button
              onClick={onClear}
              className="px-2 py-1 text-[10px] font-theme-data text-[var(--crimson)] hover:bg-[var(--crimson)]/10 rounded transition-colors"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {editing && (
        <div className="mt-3 pt-3 border-t border-border">
          <div className="flex gap-2">
            <input
              type="password"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={provider.placeholder}
              autoFocus
              className="flex-1 bg-bg border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm text-text focus:outline-none focus:border-[var(--accent)] placeholder:text-text-muted/40"
              aria-label={`${provider.label} API key`}
            />
            <button
              onClick={handleSave}
              disabled={!inputValue.trim()}
              className="px-3 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-xs rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Save
            </button>
            <button
              onClick={handleCancel}
              className="px-3 py-2 bg-surface border border-border text-text-muted font-theme-data text-xs rounded hover:border-text-muted transition-colors"
            >
              Cancel
            </button>
          </div>
          <p className="mt-2 font-theme-data text-[10px] text-text-muted">
            Stored locally in your browser. Never sent to Aragora servers.
          </p>
        </div>
      )}
    </div>
  );
}

function ProviderKeysSection() {
  const [providerKeys, setProviderKeys] = useState<Record<string, string>>({});
  const [saveFlash, setSaveFlash] = useState<string | null>(null);

  useEffect(() => {
    setProviderKeys(getStoredProviderKeys());
  }, []);

  const handleSave = useCallback(
    (providerId: string, value: string) => {
      const updated = { ...providerKeys, [providerId]: value };
      setProviderKeys(updated);
      storeProviderKeys(updated);
      setSaveFlash(providerId);
      setTimeout(() => setSaveFlash(null), 1500);
    },
    [providerKeys],
  );

  const handleClear = useCallback(
    (providerId: string) => {
      const updated = { ...providerKeys };
      delete updated[providerId];
      setProviderKeys(updated);
      storeProviderKeys(updated);
    },
    [providerKeys],
  );

  const configuredCount = Object.values(providerKeys).filter(Boolean).length;

  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-theme-data text-[var(--accent)]">LLM Provider Keys</h3>
        {configuredCount > 0 && (
          <span className="font-theme-data text-xs text-text-muted">
            {configuredCount} / {LLM_PROVIDERS.length} configured
          </span>
        )}
      </div>
      <p className="mb-2 font-theme-data text-sm text-text-muted">
        Enter your own LLM provider API keys so Aragora can run debates using your accounts. Keys
        are stored in your browser only and passed to the backend per-request.
      </p>
      <div className="mb-4 p-3 bg-[var(--acid-cyan)]/5 border border-[var(--acid-cyan)]/20 rounded">
        <p className="font-theme-data text-[10px] text-[var(--acid-cyan)]">
          At least one key (Anthropic or OpenAI) is required. OpenRouter is recommended as an
          automatic fallback when primary providers hit rate limits.
        </p>
      </div>

      <ConnectOpenRouterButton className="mb-4" />

      <div className="space-y-3">
        {LLM_PROVIDERS.map((provider) => (
          <ProviderKeyRow
            key={provider.id}
            provider={provider}
            savedValue={providerKeys[provider.id] || ''}
            onSave={(value) => handleSave(provider.id, value)}
            onClear={() => handleClear(provider.id)}
          />
        ))}
      </div>

      {saveFlash && (
        <div className="mt-3 font-theme-data text-xs text-[var(--accent)]">
          Key saved successfully.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Tab
// ---------------------------------------------------------------------------

export function ApiKeysTab({
  preferences,
  onGenerateKey,
  onRevokeKey,
  apiBase,
  loading = false,
  error = null,
  singleKeyMode = false,
}: ApiKeysTabProps) {
  const [generatedKey, setGeneratedKey] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const handleGenerateKey = async () => {
    if (isGenerating) return;
    setIsGenerating(true);
    try {
      const key = await onGenerateKey();
      setGeneratedKey(key);
    } finally {
      setIsGenerating(false);
    }
  };

  const activeKeys = preferences.api_keys.filter(
    (key) => !key.expires_at || new Date(key.expires_at) > new Date(),
  ).length;
  const hasExistingKey = preferences.api_keys.length > 0;

  return (
    <div className="space-y-6" role="tabpanel" id="panel-api" aria-labelledby="tab-api">
      {error && (
        <div className="rounded border border-[var(--crimson)]/40 bg-[var(--crimson)]/10 px-4 py-3 font-theme-data text-sm text-[var(--crimson)]">
          {error}
        </div>
      )}

      {/* Generate Key */}
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-2">Personal API Key</h3>
        <p className="mb-4 font-theme-data text-sm text-text-muted">
          {singleKeyMode
            ? 'This backend currently supports one active personal API key per account. Generating a new key rotates the current key, and the full value is only shown once.'
            : 'Generate an API key for authenticated requests to the Aragora API.'}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={handleGenerateKey}
            disabled={isGenerating || loading}
            className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isGenerating ? 'Generating...' : hasExistingKey ? 'Rotate key' : 'Generate key'}
          </button>
          {singleKeyMode && (
            <span className="font-theme-data text-xs text-text-muted">
              Active keys: {activeKeys} / 1
            </span>
          )}
        </div>

        {generatedKey && (
          <div className="mt-4 p-4 bg-acid-yellow/10 border border-acid-yellow/30 rounded">
            <div className="font-theme-data text-xs text-[var(--acid-yellow)] mb-2">
              Copy this key now - it won&apos;t be shown again!
            </div>
            <div className="flex gap-2">
              <code className="flex-1 bg-surface p-2 rounded font-theme-data text-sm text-text break-all">
                {generatedKey}
              </code>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(generatedKey);
                  setGeneratedKey(null);
                }}
                className="px-3 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30"
              >
                Copy
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Keys List */}
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">
          {singleKeyMode ? 'Active API Key' : `Your API Keys (${preferences.api_keys.length})`}
        </h3>
        {loading ? (
          <p className="font-theme-data text-sm text-text-muted">Loading API keys...</p>
        ) : preferences.api_keys.length === 0 ? (
          <p className="font-theme-data text-sm text-text-muted">
            No API key generated yet. Create one to access the Aragora API programmatically.
          </p>
        ) : (
          <div className="space-y-4">
            {preferences.api_keys.map((key) => (
              <ApiKeyCard
                key={key.prefix}
                apiKey={key}
                onRevoke={() => onRevokeKey(key.prefix)}
                apiBase={apiBase}
              />
            ))}
          </div>
        )}
      </div>

      {/* Provider Keys */}
      <ProviderKeysSection />

      {/* Documentation */}
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-2">API Documentation</h3>
        <p className="font-theme-data text-sm text-text-muted mb-4">
          Use your API key to authenticate requests to the Aragora API.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <a
            href="/docs/api"
            className="flex items-center gap-2 p-3 bg-surface border border-[var(--accent)]/20 rounded hover:border-[var(--accent)]/40 transition-colors"
          >
            <span className="text-[var(--accent)]">{'>'}</span>
            <span className="font-theme-data text-sm text-text">Full API Reference</span>
          </a>
          <a
            href="/docs/api#rate-limits"
            className="flex items-center gap-2 p-3 bg-surface border border-[var(--accent)]/20 rounded hover:border-[var(--accent)]/40 transition-colors"
          >
            <span className="text-[var(--accent)]">{'>'}</span>
            <span className="font-theme-data text-sm text-text">Rate Limits & Quotas</span>
          </a>
        </div>
      </div>
    </div>
  );
}

export default ApiKeysTab;
