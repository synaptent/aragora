'use client';

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { API_BASE_URL } from '@/config';

// ============================================================================
// Types - Maps to aragora/connectors/enterprise/streaming/*.py
// ============================================================================

export type ConnectorType = 'kafka' | 'rabbitmq' | 'snssqs';
export type ConnectorStatus = 'connected' | 'disconnected' | 'connecting' | 'error';
export type SecurityProtocol = 'PLAINTEXT' | 'SSL' | 'SASL_PLAINTEXT' | 'SASL_SSL';
export type SaslMechanism = 'PLAIN' | 'GSSAPI' | 'SCRAM-SHA-256' | 'SCRAM-SHA-512';

export interface KafkaConfig {
  // Connection
  bootstrap_servers: string;
  topics: string[];
  group_id: string;

  // Authentication
  security_protocol: SecurityProtocol;
  sasl_mechanism: SaslMechanism | null;
  sasl_username: string | null;
  sasl_password: string | null;
  ssl_cafile: string | null;
  ssl_certfile: string | null;
  ssl_keyfile: string | null;

  // Consumer settings
  auto_offset_reset: 'earliest' | 'latest' | 'none';
  enable_auto_commit: boolean;
  auto_commit_interval_ms: number;
  max_poll_records: number;
  session_timeout_ms: number;
  heartbeat_interval_ms: number;

  // Schema registry (optional)
  schema_registry_url: string | null;

  // Processing
  batch_size: number;
  poll_timeout_seconds: number;

  // Resilience
  enable_circuit_breaker: boolean;
  enable_dlq: boolean;
  enable_graceful_shutdown: boolean;
}

export interface RabbitMQConfig {
  // Connection
  url: string;
  queue: string;
  exchange: string;
  exchange_type: 'direct' | 'fanout' | 'topic' | 'headers';
  routing_key: string;

  // Queue settings
  durable: boolean;
  auto_delete: boolean;
  exclusive: boolean;
  prefetch_count: number;

  // Dead letter queue
  dead_letter_exchange: string | null;
  dead_letter_routing_key: string | null;
  message_ttl: number | null;

  // SSL/TLS
  ssl: boolean;
  ssl_cafile: string | null;
  ssl_certfile: string | null;
  ssl_keyfile: string | null;

  // Processing
  batch_size: number;
  auto_ack: boolean;
  requeue_on_error: boolean;

  // Resilience
  enable_circuit_breaker: boolean;
  enable_dlq: boolean;
  enable_graceful_shutdown: boolean;
}

export interface SNSSQSConfig {
  region: string;
  queue_url: string;
  topic_arn: string | null;
  max_messages: number;
  wait_time_seconds: number;
  visibility_timeout_seconds: number;
  dead_letter_queue_url: string | null;
  enable_circuit_breaker: boolean;
  enable_idempotency: boolean;
}

export interface HealthStatus {
  healthy: boolean;
  latency_ms: number;
  messages_processed: number;
  messages_failed: number;
  last_message_at: string | null;
  circuit_breaker_state: 'closed' | 'open' | 'half_open';
  error: string | null;
}

export interface ConnectorInfo {
  type: ConnectorType;
  status: ConnectorStatus;
  health: HealthStatus | null;
  config: KafkaConfig | RabbitMQConfig | SNSSQSConfig;
  created_at: string;
  updated_at: string;
}

// Default configs
export const DEFAULT_KAFKA_CONFIG: KafkaConfig = {
  bootstrap_servers: '',
  topics: ['aragora-events'],
  group_id: 'aragora-consumer',
  security_protocol: 'PLAINTEXT',
  sasl_mechanism: null,
  sasl_username: null,
  sasl_password: null,
  ssl_cafile: null,
  ssl_certfile: null,
  ssl_keyfile: null,
  auto_offset_reset: 'earliest',
  enable_auto_commit: true,
  auto_commit_interval_ms: 5000,
  max_poll_records: 500,
  session_timeout_ms: 30000,
  heartbeat_interval_ms: 10000,
  schema_registry_url: null,
  batch_size: 100,
  poll_timeout_seconds: 1.0,
  enable_circuit_breaker: true,
  enable_dlq: true,
  enable_graceful_shutdown: true,
};

export const DEFAULT_RABBITMQ_CONFIG: RabbitMQConfig = {
  url: '',
  queue: 'aragora-events',
  exchange: '',
  exchange_type: 'direct',
  routing_key: '',
  durable: true,
  auto_delete: false,
  exclusive: false,
  prefetch_count: 10,
  dead_letter_exchange: null,
  dead_letter_routing_key: null,
  message_ttl: null,
  ssl: false,
  ssl_cafile: null,
  ssl_certfile: null,
  ssl_keyfile: null,
  batch_size: 100,
  auto_ack: false,
  requeue_on_error: true,
  enable_circuit_breaker: true,
  enable_dlq: true,
  enable_graceful_shutdown: true,
};

export const DEFAULT_SNSSQS_CONFIG: SNSSQSConfig = {
  region: 'us-east-1',
  queue_url: '',
  topic_arn: null,
  max_messages: 10,
  wait_time_seconds: 20,
  visibility_timeout_seconds: 300,
  dead_letter_queue_url: null,
  enable_circuit_breaker: true,
  enable_idempotency: true,
};

// Status styling
export const STATUS_STYLES: Record<
  ConnectorStatus,
  { color: string; bgColor: string; label: string }
> = {
  connected: { color: 'text-green-400', bgColor: 'bg-green-500/10', label: 'CONNECTED' },
  disconnected: { color: 'text-gray-400', bgColor: 'bg-gray-500/10', label: 'DISCONNECTED' },
  connecting: { color: 'text-yellow-400', bgColor: 'bg-yellow-500/10', label: 'CONNECTING' },
  error: { color: 'text-red-400', bgColor: 'bg-red-500/10', label: 'ERROR' },
};

// ============================================================================
// Store State
// ============================================================================

interface StreamingState {
  // Connectors
  connectors: ConnectorInfo[];
  activeConnector: ConnectorType | null;

  // Forms
  kafkaConfig: KafkaConfig;
  rabbitMQConfig: RabbitMQConfig;
  snssqsConfig: SNSSQSConfig;

  // UI
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;
  successMessage: string | null;
}

interface StreamingActions {
  // Fetch actions
  fetchConnectors: () => Promise<void>;
  fetchHealth: (type: ConnectorType) => Promise<HealthStatus | null>;

  // Config actions
  setKafkaConfig: (config: Partial<KafkaConfig>) => void;
  setRabbitMQConfig: (config: Partial<RabbitMQConfig>) => void;
  setSNSSQSConfig: (config: Partial<SNSSQSConfig>) => void;
  saveConfig: (type: ConnectorType) => Promise<void>;

  // Connector actions
  connect: (type: ConnectorType) => Promise<void>;
  disconnect: (type: ConnectorType) => Promise<void>;
  testConnection: (type: ConnectorType) => Promise<boolean>;

  // UI actions
  setActiveConnector: (type: ConnectorType | null) => void;
  clearMessages: () => void;

  // Reset
  reset: () => void;
}

// ============================================================================
// Initial State
// ============================================================================

const initialState: StreamingState = {
  connectors: [],
  activeConnector: null,
  kafkaConfig: DEFAULT_KAFKA_CONFIG,
  rabbitMQConfig: DEFAULT_RABBITMQ_CONFIG,
  snssqsConfig: DEFAULT_SNSSQS_CONFIG,
  isLoading: false,
  isSaving: false,
  error: null,
  successMessage: null,
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

export const useStreamingStore = create<StreamingState & StreamingActions>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // Fetch actions
      fetchConnectors: async () => {
        set({ isLoading: true, error: null });
        try {
          const connectors = await fetchApi<ConnectorInfo[]>('/api/streaming/connectors');
          set({ connectors, isLoading: false });

          // Load configs from connectors
          for (const connector of connectors) {
            if (connector.type === 'kafka') {
              set({ kafkaConfig: connector.config as KafkaConfig });
            } else if (connector.type === 'rabbitmq') {
              set({ rabbitMQConfig: connector.config as RabbitMQConfig });
            } else if (connector.type === 'snssqs') {
              set({ snssqsConfig: connector.config as SNSSQSConfig });
            }
          }
        } catch (error) {
          set({
            error: error instanceof Error ? error.message : 'Failed to fetch connectors',
            isLoading: false,
          });
        }
      },

      fetchHealth: async (type: ConnectorType) => {
        try {
          const health = await fetchApi<HealthStatus>(`/api/streaming/connectors/${type}/health`);
          // Update the connector's health status
          set((state) => ({
            connectors: state.connectors.map((c) => (c.type === type ? { ...c, health } : c)),
          }));
          return health;
        } catch {
          return null;
        }
      },

      // Config actions
      setKafkaConfig: (config: Partial<KafkaConfig>) => {
        set((state) => ({ kafkaConfig: { ...state.kafkaConfig, ...config } }));
      },

      setRabbitMQConfig: (config: Partial<RabbitMQConfig>) => {
        set((state) => ({ rabbitMQConfig: { ...state.rabbitMQConfig, ...config } }));
      },

      setSNSSQSConfig: (config: Partial<SNSSQSConfig>) => {
        set((state) => ({ snssqsConfig: { ...state.snssqsConfig, ...config } }));
      },

      saveConfig: async (type: ConnectorType) => {
        const state = get();
        const config =
          type === 'kafka'
            ? state.kafkaConfig
            : type === 'rabbitmq'
              ? state.rabbitMQConfig
              : state.snssqsConfig;

        set({ isSaving: true, error: null, successMessage: null });
        try {
          await fetchApi(`/api/streaming/connectors/${type}/config`, {
            method: 'PUT',
            body: JSON.stringify(config),
          });
          set({
            isSaving: false,
            successMessage: `${type.toUpperCase()} configuration saved successfully`,
          });
        } catch (error) {
          set({
            error: error instanceof Error ? error.message : 'Failed to save configuration',
            isSaving: false,
          });
        }
      },

      // Connector actions
      connect: async (type: ConnectorType) => {
        set({ isLoading: true, error: null });
        try {
          await fetchApi(`/api/streaming/connectors/${type}/connect`, { method: 'POST' });
          // Update connector status
          set((state) => ({
            connectors: state.connectors.map((c) =>
              c.type === type ? { ...c, status: 'connected' as ConnectorStatus } : c,
            ),
            isLoading: false,
            successMessage: `${type.toUpperCase()} connected successfully`,
          }));
        } catch (error) {
          set({
            error: error instanceof Error ? error.message : 'Failed to connect',
            isLoading: false,
          });
        }
      },

      disconnect: async (type: ConnectorType) => {
        set({ isLoading: true, error: null });
        try {
          await fetchApi(`/api/streaming/connectors/${type}/disconnect`, { method: 'POST' });
          // Update connector status
          set((state) => ({
            connectors: state.connectors.map((c) =>
              c.type === type ? { ...c, status: 'disconnected' as ConnectorStatus } : c,
            ),
            isLoading: false,
            successMessage: `${type.toUpperCase()} disconnected`,
          }));
        } catch (error) {
          set({
            error: error instanceof Error ? error.message : 'Failed to disconnect',
            isLoading: false,
          });
        }
      },

      testConnection: async (type: ConnectorType) => {
        set({ isLoading: true, error: null });
        try {
          const result = await fetchApi<{ success: boolean; message: string }>(
            `/api/streaming/connectors/${type}/test`,
            { method: 'POST' },
          );
          set({
            isLoading: false,
            successMessage: result.success ? 'Connection test successful' : result.message,
            error: result.success ? null : result.message,
          });
          return result.success;
        } catch (error) {
          set({
            error: error instanceof Error ? error.message : 'Connection test failed',
            isLoading: false,
          });
          return false;
        }
      },

      // UI actions
      setActiveConnector: (activeConnector: ConnectorType | null) => {
        set({ activeConnector, error: null, successMessage: null });
      },

      clearMessages: () => {
        set({ error: null, successMessage: null });
      },

      // Reset
      reset: () => {
        set(initialState);
      },
    }),
    { name: 'streaming-store' },
  ),
);
