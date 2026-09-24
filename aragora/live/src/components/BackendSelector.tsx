'use client';

import { useState, useEffect } from 'react';
import {
  BACKEND_STORAGE_KEY,
  BACKENDS,
  buildHealthCheckUrl,
  getDefaultBackend,
  getRuntimeBackendConfig,
  getSavedBackend,
  isLocalHost,
  resolveBackendConfig,
  type BackendConfig,
  type BackendType,
} from '@/lib/runtimeBackend';

export { BACKENDS, buildHealthCheckUrl, getRuntimeBackendConfig };
export type { BackendConfig, BackendType };

export const BACKEND_CHANGE_EVENT = 'aragora-backend-change';

interface BackendSelectorProps {
  onChange?: (backend: BackendType, config: BackendConfig) => void;
  compact?: boolean;
}

export function BackendSelector({ onChange, compact = false }: BackendSelectorProps) {
  const localHost = typeof window !== 'undefined' && isLocalHost(window.location.hostname);
  const [selected, setSelected] = useState<BackendType>(getDefaultBackend);
  const [devAvailable, setDevAvailable] = useState<boolean | null>(localHost ? true : null);
  const [devSource, setDevSource] = useState<'tunnel' | 'localhost' | null>(
    localHost ? 'localhost' : null,
  );

  // Load saved preference
  useEffect(() => {
    const saved = getSavedBackend();
    if (saved) {
      setSelected(saved);
      onChange?.(saved, resolveBackendConfig(saved, devSource));
    } else if (localHost) {
      onChange?.('development', resolveBackendConfig('development', 'localhost'));
    }
  }, [devSource, localHost, onChange]);

  // Check if dev backend is available (try tunnel first, then localhost)
  useEffect(() => {
    const checkEndpoint = async (url: string): Promise<boolean> => {
      try {
        const res = await fetch(buildHealthCheckUrl(url), {
          method: 'GET',
          signal: AbortSignal.timeout(3000),
        });
        return res.ok || res.status === 405;
      } catch {
        return false;
      }
    };

    const checkDev = async () => {
      // Try tunnel first
      const tunnelOk = await checkEndpoint(BACKENDS.development.api);
      if (tunnelOk) {
        setDevAvailable(true);
        setDevSource('tunnel');
        return;
      }

      // Try localhost fallback
      if (BACKENDS.development.fallbackApi) {
        const localhostOk = await checkEndpoint(BACKENDS.development.fallbackApi);
        if (localhostOk) {
          setDevAvailable(true);
          setDevSource('localhost');
          return;
        }
      }

      setDevAvailable(false);
      setDevSource(null);
    };

    if (localHost) {
      setDevAvailable(true);
      setDevSource('localhost');
    }

    checkDev();
    const interval = setInterval(checkDev, 30000); // Check every 30s
    return () => clearInterval(interval);
  }, [localHost]);

  const handleSelect = (backend: BackendType) => {
    setSelected(backend);
    localStorage.setItem(BACKEND_STORAGE_KEY, backend);
    window.dispatchEvent(new CustomEvent<BackendType>(BACKEND_CHANGE_EVENT, { detail: backend }));
    onChange?.(backend, resolveBackendConfig(backend, devSource));
  };

  if (compact) {
    return (
      <div className="flex items-center gap-1 font-theme-data text-xs">
        <button
          onClick={() => handleSelect('production')}
          className={`px-2 py-1 border transition-colors ${
            selected === 'production'
              ? 'bg-[var(--accent)] text-bg border-[var(--accent)]'
              : 'text-text-muted border-border hover:text-[var(--accent)] hover:border-[var(--accent)]/50'
          }`}
          title={BACKENDS.production.description}
        >
          PROD
        </button>
        <button
          onClick={() => handleSelect('development')}
          disabled={devAvailable === false}
          className={`px-2 py-1 border transition-colors ${
            selected === 'development'
              ? 'bg-[var(--acid-cyan)] text-bg border-[var(--acid-cyan)]'
              : devAvailable === false
                ? 'text-text-muted/30 border-border/30 cursor-not-allowed'
                : 'text-text-muted border-border hover:text-[var(--acid-cyan)] hover:border-[var(--acid-cyan)]/50'
          }`}
          title={
            devAvailable === false
              ? 'Dev server offline'
              : devSource === 'localhost'
                ? 'Connected via localhost'
                : BACKENDS.development.description
          }
        >
          DEV
          {devAvailable === false && <span className="ml-1 text-warning">●</span>}
          {devSource === 'localhost' && <span className="ml-1 text-[10px]">L</span>}
        </button>
      </div>
    );
  }

  return (
    <div className="border border-[var(--accent)]/30 p-3 bg-surface/50">
      <div className="text-xs text-text-muted mb-2 font-theme-data">API BACKEND</div>
      <div className="flex gap-2">
        {(Object.entries(BACKENDS) as [BackendType, BackendConfig][]).map(([key, config]) => {
          const isSelected = selected === key;
          const isDisabled = key === 'development' && devAvailable === false;

          return (
            <button
              key={key}
              onClick={() => !isDisabled && handleSelect(key)}
              disabled={isDisabled}
              className={`flex-1 p-2 border font-theme-data text-left transition-colors ${
                isSelected
                  ? key === 'production'
                    ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                    : 'bg-[var(--acid-cyan)]/20 border-[var(--acid-cyan)] text-[var(--acid-cyan)]'
                  : isDisabled
                    ? 'border-border/30 text-text-muted/30 cursor-not-allowed'
                    : 'border-border text-text-muted hover:border-[var(--accent)]/50'
              }`}
            >
              <div className="text-sm font-bold flex items-center gap-2">
                {config.label}
                {isSelected && <span>✓</span>}
                {key === 'development' && devAvailable === false && (
                  <span className="text-warning text-xs">OFFLINE</span>
                )}
                {key === 'development' && devAvailable === true && (
                  <span className="text-success text-xs">●</span>
                )}
                {key === 'development' && devSource === 'localhost' && (
                  <span className="text-[var(--acid-cyan)] text-xs">LOCAL</span>
                )}
              </div>
              <div className="text-[10px] opacity-70">
                {key === 'development' && devSource === 'localhost'
                  ? 'Connected via localhost:8080'
                  : config.description}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function useBackend(): { backend: BackendType; config: BackendConfig } {
  const localHost = typeof window !== 'undefined' && isLocalHost(window.location.hostname);
  const [backend, setBackend] = useState<BackendType>(() => getRuntimeBackendConfig().backend);

  useEffect(() => {
    const saved = getSavedBackend();
    if (saved) {
      setBackend(saved);
    } else if (localHost) {
      setBackend('development');
    }

    // Listen for changes
    const handleStorage = (e: StorageEvent) => {
      if (e.key === BACKEND_STORAGE_KEY && e.newValue) {
        setBackend(e.newValue as BackendType);
      }
    };
    const handleBackendChange = (event: Event) => {
      const nextBackend = (event as CustomEvent<BackendType>).detail;
      if (nextBackend && BACKENDS[nextBackend]) {
        setBackend(nextBackend);
      }
    };
    window.addEventListener('storage', handleStorage);
    window.addEventListener(BACKEND_CHANGE_EVENT, handleBackendChange as EventListener);
    return () => {
      window.removeEventListener('storage', handleStorage);
      window.removeEventListener(BACKEND_CHANGE_EVENT, handleBackendChange as EventListener);
    };
  }, [localHost]);

  return { backend, config: resolveBackendConfig(backend, localHost ? 'localhost' : null) };
}
