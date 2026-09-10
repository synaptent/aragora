'use client';

import { useOpenRouterConnection } from '@/hooks/useOpenRouterConnection';

function maskKey(key: string): string {
  if (key.length <= 8) return '*'.repeat(key.length);
  return key.slice(0, 6) + '****' + key.slice(-4);
}

function formatCredits(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

function OpenRouterIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 2L2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5" />
      <path d="M2 12l10 5 10-5" />
    </svg>
  );
}

interface ConnectOpenRouterButtonProps {
  compact?: boolean;
  className?: string;
}

export function ConnectOpenRouterButton({
  compact = false,
  className = '',
}: ConnectOpenRouterButtonProps) {
  const { isConnected, keyInfo, connect, disconnect } = useOpenRouterConnection();

  if (compact) {
    if (isConnected) {
      return (
        <span
          className={`inline-flex items-center gap-1.5 font-theme-data text-xs ${className}`}
          style={{ color: 'var(--accent)' }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              backgroundColor: 'var(--accent)',
              display: 'inline-block',
            }}
          />
          OpenRouter connected
          {keyInfo?.limitRemaining != null && (
            <span style={{ color: 'var(--text-muted)' }}>
              ({formatCredits(keyInfo.limitRemaining)} remaining)
            </span>
          )}
        </span>
      );
    }

    return (
      <button
        onClick={connect}
        className={`inline-flex items-center gap-1.5 font-theme-data text-xs cursor-pointer transition-opacity hover:opacity-80 ${className}`}
        style={{ color: 'var(--accent)', background: 'none', border: 'none', padding: 0 }}
      >
        <OpenRouterIcon />
        Connect OpenRouter for instant setup
      </button>
    );
  }

  // Full card mode (settings page)
  if (isConnected) {
    const storedKeys =
      typeof window !== 'undefined'
        ? JSON.parse(localStorage.getItem('aragora_provider_keys') || '{}')
        : {};
    const maskedKey = storedKeys.openrouter ? maskKey(storedKeys.openrouter) : '';

    return (
      <div
        className={`p-4 rounded border ${className}`}
        style={{
          backgroundColor: 'var(--surface)',
          borderColor: 'color-mix(in srgb, var(--accent) 30%, transparent)',
        }}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span
                className="font-theme-data text-sm font-medium"
                style={{ color: 'var(--text)' }}
              >
                OpenRouter
              </span>
              <span
                className="px-1.5 py-0.5 text-[10px] font-theme-data rounded"
                style={{
                  backgroundColor: 'color-mix(in srgb, var(--accent) 10%, transparent)',
                  color: 'var(--accent)',
                  border: '1px solid color-mix(in srgb, var(--accent) 30%, transparent)',
                }}
              >
                CONNECTED
              </span>
            </div>
            {maskedKey && (
              <code
                className="font-theme-data text-xs rounded px-1.5 py-0.5"
                style={{ color: 'var(--text-muted)', backgroundColor: 'var(--bg)' }}
              >
                {maskedKey}
              </code>
            )}
            {keyInfo?.limitRemaining != null && (
              <div className="mt-2 font-theme-data text-xs" style={{ color: 'var(--text-muted)' }}>
                {formatCredits(keyInfo.limitRemaining)} credit remaining
                {keyInfo.limit != null && <span> of {formatCredits(keyInfo.limit)} limit</span>}
              </div>
            )}
          </div>
          <button
            onClick={disconnect}
            className="px-2 py-1 text-[10px] font-theme-data rounded transition-colors cursor-pointer"
            style={{ color: 'var(--crimson, #ff0040)' }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.backgroundColor =
                'color-mix(in srgb, var(--crimson, #ff0040) 10%, transparent)')
            }
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            Disconnect
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`p-4 rounded border ${className}`}
      style={{
        backgroundColor: 'color-mix(in srgb, var(--accent) 5%, var(--surface))',
        borderColor: 'color-mix(in srgb, var(--accent) 20%, transparent)',
      }}
    >
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="font-theme-data text-sm font-medium" style={{ color: 'var(--text)' }}>
            One-click setup via OpenRouter
          </div>
          <div
            className="font-theme-data text-[10px] mt-0.5"
            style={{ color: 'var(--text-muted)' }}
          >
            Connect your account and set a budget — no key pasting needed.
          </div>
        </div>
        <button
          onClick={connect}
          className="inline-flex items-center gap-2 px-4 py-2 font-theme-data text-xs rounded transition-colors cursor-pointer shrink-0"
          style={{
            color: 'var(--accent)',
            border: '1px solid color-mix(in srgb, var(--accent) 40%, transparent)',
            backgroundColor: 'color-mix(in srgb, var(--accent) 10%, transparent)',
          }}
          onMouseEnter={(e) =>
            (e.currentTarget.style.backgroundColor =
              'color-mix(in srgb, var(--accent) 20%, transparent)')
          }
          onMouseLeave={(e) =>
            (e.currentTarget.style.backgroundColor =
              'color-mix(in srgb, var(--accent) 10%, transparent)')
          }
        >
          <OpenRouterIcon />
          Connect OpenRouter
        </button>
      </div>
    </div>
  );
}
