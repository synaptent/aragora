'use client';

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { API_BASE_URL } from '@/config';

// ============================================================================
// Types - Maps to aragora/sandbox/executor.py and policies.py
// ============================================================================

export type ExecutionMode = 'docker' | 'subprocess' | 'mock';
export type ExecutionStatus =
  'pending' | 'running' | 'completed' | 'failed' | 'timeout' | 'policy_denied';
export type Language = 'python' | 'javascript' | 'bash';

export interface ExecutionResult {
  execution_id: string;
  status: ExecutionStatus;
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_seconds: number;
  memory_used_mb: number;
  files_created: string[];
  policy_violations: string[];
  error_message: string | null;
}

export interface ResourceLimits {
  max_memory_mb: number;
  max_cpu_percent: number;
  max_execution_seconds: number;
  max_processes: number;
  max_file_size_mb: number;
}

export interface SandboxConfig {
  mode: ExecutionMode;
  docker_image: string;
  cleanup_on_complete: boolean;
  capture_output: boolean;
  network_enabled: boolean;
  resource_limits: ResourceLimits;
}

export interface PoolStatus {
  available: number;
  in_use: number;
  total: number;
  healthy: boolean;
}

// Status styling
export const STATUS_STYLES: Record<
  ExecutionStatus,
  { color: string; bgColor: string; label: string }
> = {
  pending: { color: 'text-gray-400', bgColor: 'bg-gray-500/10', label: 'PENDING' },
  running: { color: 'text-blue-400', bgColor: 'bg-blue-500/10', label: 'RUNNING' },
  completed: { color: 'text-green-400', bgColor: 'bg-green-500/10', label: 'COMPLETED' },
  failed: { color: 'text-red-400', bgColor: 'bg-red-500/10', label: 'FAILED' },
  timeout: { color: 'text-yellow-400', bgColor: 'bg-yellow-500/10', label: 'TIMEOUT' },
  policy_denied: { color: 'text-orange-400', bgColor: 'bg-orange-500/10', label: 'POLICY DENIED' },
};

// Language config
export const LANGUAGE_CONFIG: Record<
  Language,
  { label: string; extension: string; placeholder: string }
> = {
  python: {
    label: 'Python',
    extension: '.py',
    placeholder: '# Write Python code here\nprint("Hello, Sandbox!")',
  },
  javascript: {
    label: 'JavaScript',
    extension: '.js',
    placeholder: '// Write JavaScript code here\nconsole.log("Hello, Sandbox!");',
  },
  bash: {
    label: 'Bash',
    extension: '.sh',
    placeholder: '#!/bin/bash\n# Write shell commands here\necho "Hello, Sandbox!"',
  },
};

// ============================================================================
// Store State
// ============================================================================

interface SandboxState {
  // Code editor
  code: string;
  language: Language;

  // Execution
  currentExecution: ExecutionResult | null;
  executionHistory: ExecutionResult[];
  isExecuting: boolean;
  executionError: string | null;

  // Config
  config: SandboxConfig | null;
  configLoading: boolean;

  // Pool status
  poolStatus: PoolStatus | null;
}

interface SandboxActions {
  // Code actions
  setCode: (code: string) => void;
  setLanguage: (language: Language) => void;

  // Execution actions
  execute: () => Promise<void>;
  cancelExecution: (executionId: string) => Promise<void>;
  clearResult: () => void;
  clearHistory: () => void;

  // Config actions
  fetchConfig: () => Promise<void>;
  updateConfig: (config: Partial<SandboxConfig>) => Promise<void>;

  // Pool actions
  fetchPoolStatus: () => Promise<void>;

  // Reset
  reset: () => void;
}

// ============================================================================
// Initial State
// ============================================================================

const initialState: SandboxState = {
  code: LANGUAGE_CONFIG.python.placeholder,
  language: 'python',
  currentExecution: null,
  executionHistory: [],
  isExecuting: false,
  executionError: null,
  config: null,
  configLoading: false,
  poolStatus: null,
};

// ============================================================================
// API Helpers
// ============================================================================

const API_URL = API_BASE_URL;

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `API error: ${response.status}`);
  }

  return response.json();
}

// ============================================================================
// Store
// ============================================================================

export const useSandboxStore = create<SandboxState & SandboxActions>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // Code actions
      setCode: (code: string) => {
        set({ code });
      },

      setLanguage: (language: Language) => {
        const currentCode = get().code;
        const currentLang = get().language;
        // If code is still the placeholder, update it for the new language
        if (currentCode === LANGUAGE_CONFIG[currentLang].placeholder) {
          set({ language, code: LANGUAGE_CONFIG[language].placeholder });
        } else {
          set({ language });
        }
      },

      // Execution actions
      execute: async () => {
        const { code, language } = get();
        if (!code.trim()) {
          set({ executionError: 'No code to execute' });
          return;
        }

        set({ isExecuting: true, executionError: null, currentExecution: null });

        try {
          const result = await fetchApi<ExecutionResult>('/api/sandbox/execute', {
            method: 'POST',
            body: JSON.stringify({ code, language }),
          });

          set((state) => ({
            currentExecution: result,
            executionHistory: [result, ...state.executionHistory].slice(0, 20), // Keep last 20
            isExecuting: false,
          }));
        } catch (error) {
          set({
            executionError: error instanceof Error ? error.message : 'Execution failed',
            isExecuting: false,
          });
        }
      },

      cancelExecution: async (executionId: string) => {
        try {
          await fetchApi(`/api/sandbox/executions/${executionId}`, { method: 'DELETE' });
          set({ isExecuting: false });
        } catch (error) {
          set({ executionError: error instanceof Error ? error.message : 'Failed to cancel' });
        }
      },

      clearResult: () => {
        set({ currentExecution: null, executionError: null });
      },

      clearHistory: () => {
        set({ executionHistory: [] });
      },

      // Config actions
      fetchConfig: async () => {
        set({ configLoading: true });
        try {
          const config = await fetchApi<SandboxConfig>('/api/sandbox/config');
          set({ config, configLoading: false });
        } catch {
          set({ configLoading: false });
        }
      },

      updateConfig: async (updates: Partial<SandboxConfig>) => {
        try {
          const config = await fetchApi<SandboxConfig>('/api/sandbox/config', {
            method: 'PUT',
            body: JSON.stringify(updates),
          });
          set({ config });
        } catch (error) {
          set({
            executionError: error instanceof Error ? error.message : 'Failed to update config',
          });
        }
      },

      // Pool actions
      fetchPoolStatus: async () => {
        try {
          const poolStatus = await fetchApi<PoolStatus>('/api/sandbox/pool/status');
          set({ poolStatus });
        } catch {
          // Pool status is non-critical
        }
      },

      // Reset
      reset: () => {
        set(initialState);
      },
    }),
    { name: 'sandbox-store' },
  ),
);
