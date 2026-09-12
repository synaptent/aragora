/**
 * Shared provider key storage utilities.
 *
 * LLM provider API keys are stored in localStorage under `aragora_provider_keys`
 * and passed to the backend per-request via `X-Provider-Key-{id}` headers.
 * This keeps keys client-side, so XSS protections remain important.
 */

export const PROVIDER_KEYS_STORAGE_KEY = 'aragora_provider_keys';

export interface ProviderKeyConfig {
  id: string;
  label: string;
  envVar: string;
  placeholder: string;
  docsUrl?: string;
}

export const LLM_PROVIDERS: ProviderKeyConfig[] = [
  {
    id: 'anthropic',
    label: 'Anthropic (Claude)',
    envVar: 'ANTHROPIC_API_KEY',
    placeholder: 'sk-ant-...',
    docsUrl: 'https://console.anthropic.com/settings/keys',
  },
  {
    id: 'openai',
    label: 'OpenAI (GPT)',
    envVar: 'OPENAI_API_KEY',
    placeholder: 'sk-...',
    docsUrl: 'https://platform.openai.com/api-keys',
  },
  {
    id: 'openrouter',
    label: 'OpenRouter (Fallback)',
    envVar: 'OPENROUTER_API_KEY',
    placeholder: 'sk-or-...',
    docsUrl: 'https://openrouter.ai/keys',
  },
  {
    id: 'mistral',
    label: 'Mistral',
    envVar: 'MISTRAL_API_KEY',
    placeholder: '...',
    docsUrl: 'https://console.mistral.ai/api-keys/',
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    envVar: 'GEMINI_API_KEY',
    placeholder: 'AIza...',
    docsUrl: 'https://aistudio.google.com/app/apikey',
  },
  {
    id: 'xai',
    label: 'xAI (Grok)',
    envVar: 'XAI_API_KEY',
    placeholder: 'xai-...',
    docsUrl: 'https://console.x.ai/',
  },
];

export function getStoredProviderKeys(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  try {
    const stored = localStorage.getItem(PROVIDER_KEYS_STORAGE_KEY);
    return stored ? JSON.parse(stored) : {};
  } catch (error) {
    console.warn('Failed to parse stored provider keys from localStorage.', error);
    return {};
  }
}

export function storeProviderKeys(keys: Record<string, string>): void {
  localStorage.setItem(PROVIDER_KEYS_STORAGE_KEY, JSON.stringify(keys));
}

/** Build X-Provider-Key-{id} headers from stored provider keys. */
export function getProviderKeyHeaders(): Record<string, string> {
  const keys = getStoredProviderKeys();
  const headers: Record<string, string> = {};
  for (const [id, value] of Object.entries(keys)) {
    if (value) {
      const provider = LLM_PROVIDERS.find((p) => p.id === id);
      if (provider) {
        headers[`X-Provider-Key-${provider.id}`] = value;
      }
    }
  }
  return headers;
}
