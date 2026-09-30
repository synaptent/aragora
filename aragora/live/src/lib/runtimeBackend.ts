export type BackendType = 'production' | 'development';

export interface BackendConfig {
  api: string;
  ws: string;
  controlPlaneWs?: string;
  label: string;
  description: string;
  fallbackApi?: string;
  fallbackWs?: string;
  fallbackControlPlaneWs?: string;
}

export const BACKENDS: Record<BackendType, BackendConfig> = {
  production: {
    api: 'https://api.aragora.ai',
    ws: 'wss://api.aragora.ai/ws',
    controlPlaneWs: 'wss://api.aragora.ai/api/control-plane/stream',
    label: 'PROD',
    description: 'AWS Lightsail (always-on)',
  },
  development: {
    api: 'https://api-dev.aragora.ai',
    ws: 'wss://api-dev.aragora.ai/ws',
    controlPlaneWs: 'wss://api-dev.aragora.ai/api/control-plane/stream',
    label: 'DEV',
    description: 'Local Mac (via tunnel or localhost)',
    fallbackApi: '',
    fallbackWs: 'ws://localhost:8765/ws',
    fallbackControlPlaneWs: 'ws://localhost:8766/api/control-plane/stream',
  },
};

export const BACKEND_STORAGE_KEY = 'aragora-backend';

export function buildHealthCheckUrl(apiBase: string): string {
  const normalizedBase = apiBase.trim().replace(/\/$/, '');
  if (!normalizedBase) {
    // In local same-origin dev, Next rewrites `/api/*` and `trailingSlash: true`
    // turns `/api/health` into a redirect chain. Use the stable path directly.
    return '/api/health/';
  }
  return `${normalizedBase}/api/health`;
}

export function isLocalHost(hostname: string | undefined): boolean {
  if (!hostname) return false;
  return (
    hostname === 'localhost' ||
    hostname === '127.0.0.1' ||
    hostname.startsWith('192.168.') ||
    hostname.startsWith('10.') ||
    hostname.endsWith('.local')
  );
}

export function getSavedBackend(): BackendType | null {
  if (typeof window === 'undefined') return null;
  const saved = localStorage.getItem(BACKEND_STORAGE_KEY) as BackendType | null;
  return saved && BACKENDS[saved] ? saved : null;
}

export function getDefaultBackend(): BackendType {
  const saved = getSavedBackend();
  if (saved) return saved;
  if (typeof window !== 'undefined' && isLocalHost(window.location.hostname)) {
    return 'development';
  }
  return 'production';
}

export function resolveBackendConfig(
  backend: BackendType,
  devSource: 'tunnel' | 'localhost' | null,
): BackendConfig {
  const config = BACKENDS[backend];
  if (
    backend === 'development' &&
    devSource === 'localhost' &&
    config.fallbackApi !== undefined &&
    config.fallbackWs
  ) {
    return {
      ...config,
      api: config.fallbackApi,
      ws: config.fallbackWs,
      ...(config.fallbackControlPlaneWs ? { controlPlaneWs: config.fallbackControlPlaneWs } : {}),
    };
  }
  return config;
}

export function getRuntimeBackendConfig(): { backend: BackendType; config: BackendConfig } {
  const localHost = typeof window !== 'undefined' && isLocalHost(window.location.hostname);
  const backend = getDefaultBackend();
  return { backend, config: resolveBackendConfig(backend, localHost ? 'localhost' : null) };
}
