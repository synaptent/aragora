'use client';

import { useEffect, useRef } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useRightSidebar } from '@/context/RightSidebarContext';
import {
  useStreamingStore,
  STATUS_STYLES,
  DEFAULT_KAFKA_CONFIG,
  DEFAULT_RABBITMQ_CONFIG,
  DEFAULT_SNSSQS_CONFIG,
  type ConnectorType,
  type KafkaConfig,
  type RabbitMQConfig,
  type SNSSQSConfig,
} from '@/store/streamingStore';

const CONNECTORS: Array<{ type: ConnectorType; label: string; icon: string; description: string }> =
  [
    {
      type: 'kafka',
      label: 'Apache Kafka',
      icon: 'K',
      description: 'High-throughput distributed event streaming',
    },
    {
      type: 'rabbitmq',
      label: 'RabbitMQ',
      icon: 'R',
      description: 'Message broker with flexible routing',
    },
    {
      type: 'snssqs',
      label: 'AWS SNS/SQS',
      icon: 'A',
      description: 'AWS managed messaging services',
    },
  ];

export default function StreamingConfigPage() {
  const {
    connectors,
    activeConnector,
    kafkaConfig,
    rabbitMQConfig,
    snssqsConfig,
    isLoading,
    isSaving,
    error,
    successMessage,
    fetchConnectors,
    fetchHealth,
    setKafkaConfig,
    setRabbitMQConfig,
    setSNSSQSConfig,
    saveConfig,
    connect,
    disconnect,
    testConnection,
    setActiveConnector,
    clearMessages,
  } = useStreamingStore();

  const { setContext, clearContext } = useRightSidebar();
  const healthPollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Fetch connectors on mount
  useEffect(() => {
    fetchConnectors();
  }, [fetchConnectors]);

  // Poll health for active connector
  useEffect(() => {
    if (healthPollIntervalRef.current) {
      clearInterval(healthPollIntervalRef.current);
      healthPollIntervalRef.current = null;
    }

    if (activeConnector) {
      fetchHealth(activeConnector);
      healthPollIntervalRef.current = setInterval(() => fetchHealth(activeConnector), 10000);
    }

    return () => {
      if (healthPollIntervalRef.current) {
        clearInterval(healthPollIntervalRef.current);
        healthPollIntervalRef.current = null;
      }
    };
  }, [activeConnector, fetchHealth]);

  // Set up right sidebar
  useEffect(() => {
    const activeConn = connectors.find((c) => c.type === activeConnector);

    setContext({
      title: 'Streaming Config',
      subtitle: 'Enterprise connectors',
      statsContent: (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Connectors</span>
            <span className="text-sm font-theme-data text-[var(--acid-green)]">
              {connectors.length}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Connected</span>
            <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
              {connectors.filter((c) => c.status === 'connected').length}
            </span>
          </div>
          {activeConn?.health && (
            <>
              <div className="border-t border-[var(--border)] pt-3 mt-3">
                <div className="flex justify-between items-center">
                  <span className="text-xs text-[var(--text-muted)]">Latency</span>
                  <span className="text-sm font-theme-data text-[var(--text)]">
                    {activeConn.health.latency_ms}ms
                  </span>
                </div>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-[var(--text-muted)]">Processed</span>
                <span className="text-sm font-theme-data text-green-400">
                  {activeConn.health.messages_processed}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-[var(--text-muted)]">Failed</span>
                <span className="text-sm font-theme-data text-red-400">
                  {activeConn.health.messages_failed}
                </span>
              </div>
            </>
          )}
        </div>
      ),
      actionsContent: activeConnector ? (
        <div className="space-y-2">
          <button
            onClick={() => saveConfig(activeConnector)}
            disabled={isSaving}
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--acid-green)] text-[var(--bg)] font-bold hover:bg-[var(--acid-green)]/80 transition-colors disabled:opacity-50"
          >
            {isSaving ? 'SAVING...' : 'SAVE CONFIG'}
          </button>
          <button
            onClick={() => testConnection(activeConnector)}
            disabled={isLoading}
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 hover:border-[var(--acid-cyan)] transition-colors disabled:opacity-50"
          >
            TEST CONNECTION
          </button>
          {connectors.find((c) => c.type === activeConnector)?.status === 'connected' ? (
            <button
              onClick={() => disconnect(activeConnector)}
              disabled={isLoading}
              className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20 transition-colors disabled:opacity-50"
            >
              DISCONNECT
            </button>
          ) : (
            <button
              onClick={() => connect(activeConnector)}
              disabled={isLoading}
              className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-green-500/10 text-green-400 border border-green-500/30 hover:bg-green-500/20 transition-colors disabled:opacity-50"
            >
              CONNECT
            </button>
          )}
        </div>
      ) : null,
    });

    return () => clearContext();
  }, [
    connectors,
    activeConnector,
    isLoading,
    isSaving,
    setContext,
    clearContext,
    saveConfig,
    testConnection,
    connect,
    disconnect,
  ]);

  // Clear messages after 5 seconds
  useEffect(() => {
    if (error || successMessage) {
      const timeout = setTimeout(clearMessages, 5000);
      return () => clearTimeout(timeout);
    }
  }, [error, successMessage, clearMessages]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="max-w-6xl mx-auto px-4 py-8">
          {/* Header */}
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              STREAMING CONFIGURATION
            </h1>
            <p className="text-text-muted text-sm font-theme-data">
              Configure enterprise streaming connectors for event ingestion into Knowledge Mound.
            </p>
          </div>

          {/* Messages */}
          {error && (
            <div className="mb-4 border border-red-500/30 bg-red-500/10 p-3">
              <p className="text-red-400 text-sm font-theme-data">{error}</p>
            </div>
          )}
          {successMessage && (
            <div className="mb-4 border border-green-500/30 bg-green-500/10 p-3">
              <p className="text-green-400 text-sm font-theme-data">{successMessage}</p>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            {/* Connector Selector */}
            <div className="lg:col-span-1 space-y-2">
              <h2 className="text-xs font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider mb-3">
                Connectors
              </h2>
              {CONNECTORS.map((conn) => {
                const info = connectors.find((c) => c.type === conn.type);
                const status = info?.status || 'disconnected';
                const statusStyle = STATUS_STYLES[status];

                return (
                  <button
                    key={conn.type}
                    onClick={() => setActiveConnector(conn.type)}
                    className={`w-full text-left p-3 border transition-colors ${
                      activeConnector === conn.type
                        ? 'border-[var(--accent)]/50 bg-[var(--accent)]/10'
                        : 'border-[var(--accent)]/20 bg-surface/50 hover:bg-surface/80'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 flex items-center justify-center bg-surface border border-[var(--accent)]/30 text-[var(--accent)] font-theme-data font-bold">
                        {conn.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-theme-data text-text font-bold">
                          {conn.label}
                        </div>
                        <div className="text-xs font-theme-data text-text-muted truncate">
                          {conn.description}
                        </div>
                      </div>
                    </div>
                    <div className="mt-2 flex items-center justify-between">
                      <span
                        className={`px-2 py-0.5 text-xs font-theme-data ${statusStyle.color} ${statusStyle.bgColor}`}
                      >
                        {statusStyle.label}
                      </span>
                      {info?.health && (
                        <span
                          className={`w-2 h-2 rounded-full ${
                            info.health.healthy ? 'bg-green-400' : 'bg-red-400'
                          }`}
                        />
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Configuration Form */}
            <div className="lg:col-span-3">
              {!activeConnector ? (
                <div className="border border-[var(--accent)]/20 bg-surface/30 p-8 text-center">
                  <p className="text-text-muted text-sm font-theme-data">
                    Select a connector to configure
                  </p>
                </div>
              ) : activeConnector === 'kafka' ? (
                <KafkaConfigForm
                  config={kafkaConfig}
                  onChange={setKafkaConfig}
                  onReset={() => setKafkaConfig(DEFAULT_KAFKA_CONFIG)}
                />
              ) : activeConnector === 'rabbitmq' ? (
                <RabbitMQConfigForm
                  config={rabbitMQConfig}
                  onChange={setRabbitMQConfig}
                  onReset={() => setRabbitMQConfig(DEFAULT_RABBITMQ_CONFIG)}
                />
              ) : (
                <SNSSQSConfigForm
                  config={snssqsConfig}
                  onChange={setSNSSQSConfig}
                  onReset={() => setSNSSQSConfig(DEFAULT_SNSSQS_CONFIG)}
                />
              )}
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

// ============================================================================
// Kafka Config Form
// ============================================================================

interface KafkaConfigFormProps {
  config: KafkaConfig;
  onChange: (config: Partial<KafkaConfig>) => void;
  onReset: () => void;
}

function KafkaConfigForm({ config, onChange, onReset }: KafkaConfigFormProps) {
  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--accent)]/20 bg-surface/80">
        <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
          Apache Kafka Configuration
        </span>
        <button
          onClick={onReset}
          className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
        >
          Reset to Defaults
        </button>
      </div>

      <div className="p-4 space-y-6">
        {/* Connection */}
        <Section title="Connection">
          <FormField label="Bootstrap Servers">
            <input
              type="text"
              value={config.bootstrap_servers}
              onChange={(e) => onChange({ bootstrap_servers: e.target.value })}
              placeholder="localhost:9092"
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </FormField>
          <FormField label="Topics (comma-separated)">
            <input
              type="text"
              value={config.topics.join(', ')}
              onChange={(e) =>
                onChange({
                  topics: e.target.value
                    .split(',')
                    .map((t) => t.trim())
                    .filter(Boolean),
                })
              }
              placeholder="aragora-events, decisions"
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </FormField>
          <FormField label="Consumer Group ID">
            <input
              type="text"
              value={config.group_id}
              onChange={(e) => onChange({ group_id: e.target.value })}
              placeholder="aragora-consumer"
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </FormField>
        </Section>

        {/* Authentication */}
        <Section title="Authentication">
          <FormField label="Security Protocol">
            <select
              value={config.security_protocol}
              onChange={(e) =>
                onChange({ security_protocol: e.target.value as KafkaConfig['security_protocol'] })
              }
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none"
            >
              <option value="PLAINTEXT">PLAINTEXT</option>
              <option value="SSL">SSL</option>
              <option value="SASL_PLAINTEXT">SASL_PLAINTEXT</option>
              <option value="SASL_SSL">SASL_SSL</option>
            </select>
          </FormField>
          {config.security_protocol.includes('SASL') && (
            <>
              <FormField label="SASL Mechanism">
                <select
                  value={config.sasl_mechanism || ''}
                  onChange={(e) =>
                    onChange({
                      sasl_mechanism: (e.target.value as KafkaConfig['sasl_mechanism']) || null,
                    })
                  }
                  className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none"
                >
                  <option value="">Select mechanism</option>
                  <option value="PLAIN">PLAIN</option>
                  <option value="GSSAPI">GSSAPI (Kerberos)</option>
                  <option value="SCRAM-SHA-256">SCRAM-SHA-256</option>
                  <option value="SCRAM-SHA-512">SCRAM-SHA-512</option>
                </select>
              </FormField>
              <FormField label="SASL Username">
                <input
                  type="text"
                  value={config.sasl_username || ''}
                  onChange={(e) => onChange({ sasl_username: e.target.value || null })}
                  className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </FormField>
              <FormField label="SASL Password">
                <input
                  type="password"
                  value={config.sasl_password || ''}
                  onChange={(e) => onChange({ sasl_password: e.target.value || null })}
                  className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </FormField>
            </>
          )}
        </Section>

        {/* Consumer Settings */}
        <Section title="Consumer Settings">
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Auto Offset Reset">
              <select
                value={config.auto_offset_reset}
                onChange={(e) =>
                  onChange({
                    auto_offset_reset: e.target.value as KafkaConfig['auto_offset_reset'],
                  })
                }
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none"
              >
                <option value="earliest">Earliest</option>
                <option value="latest">Latest</option>
                <option value="none">None</option>
              </select>
            </FormField>
            <FormField label="Max Poll Records">
              <input
                type="number"
                value={config.max_poll_records}
                onChange={(e) => onChange({ max_poll_records: parseInt(e.target.value) || 500 })}
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
            <FormField label="Session Timeout (ms)">
              <input
                type="number"
                value={config.session_timeout_ms}
                onChange={(e) =>
                  onChange({ session_timeout_ms: parseInt(e.target.value) || 30000 })
                }
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
            <FormField label="Batch Size">
              <input
                type="number"
                value={config.batch_size}
                onChange={(e) => onChange({ batch_size: parseInt(e.target.value) || 100 })}
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
          </div>
          <Toggle
            label="Enable Auto Commit"
            checked={config.enable_auto_commit}
            onChange={(enable_auto_commit) => onChange({ enable_auto_commit })}
          />
        </Section>

        {/* Resilience */}
        <Section title="Resilience">
          <div className="space-y-2">
            <Toggle
              label="Circuit Breaker"
              checked={config.enable_circuit_breaker}
              onChange={(enable_circuit_breaker) => onChange({ enable_circuit_breaker })}
            />
            <Toggle
              label="Dead Letter Queue"
              checked={config.enable_dlq}
              onChange={(enable_dlq) => onChange({ enable_dlq })}
            />
            <Toggle
              label="Graceful Shutdown"
              checked={config.enable_graceful_shutdown}
              onChange={(enable_graceful_shutdown) => onChange({ enable_graceful_shutdown })}
            />
          </div>
        </Section>
      </div>
    </div>
  );
}

// ============================================================================
// RabbitMQ Config Form
// ============================================================================

interface RabbitMQConfigFormProps {
  config: RabbitMQConfig;
  onChange: (config: Partial<RabbitMQConfig>) => void;
  onReset: () => void;
}

function RabbitMQConfigForm({ config, onChange, onReset }: RabbitMQConfigFormProps) {
  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--accent)]/20 bg-surface/80">
        <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
          RabbitMQ Configuration
        </span>
        <button
          onClick={onReset}
          className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
        >
          Reset to Defaults
        </button>
      </div>

      <div className="p-4 space-y-6">
        {/* Connection */}
        <Section title="Connection">
          <FormField label="Connection URL">
            <input
              type="text"
              value={config.url}
              onChange={(e) => onChange({ url: e.target.value })}
              placeholder="amqp://user:password@host:5672/vhost"
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </FormField>
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Queue">
              <input
                type="text"
                value={config.queue}
                onChange={(e) => onChange({ queue: e.target.value })}
                placeholder="aragora-events"
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
            <FormField label="Exchange">
              <input
                type="text"
                value={config.exchange}
                onChange={(e) => onChange({ exchange: e.target.value })}
                placeholder="(default exchange)"
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Exchange Type">
              <select
                value={config.exchange_type}
                onChange={(e) =>
                  onChange({ exchange_type: e.target.value as RabbitMQConfig['exchange_type'] })
                }
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none"
              >
                <option value="direct">Direct</option>
                <option value="fanout">Fanout</option>
                <option value="topic">Topic</option>
                <option value="headers">Headers</option>
              </select>
            </FormField>
            <FormField label="Routing Key">
              <input
                type="text"
                value={config.routing_key}
                onChange={(e) => onChange({ routing_key: e.target.value })}
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
          </div>
        </Section>

        {/* Queue Settings */}
        <Section title="Queue Settings">
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Prefetch Count">
              <input
                type="number"
                value={config.prefetch_count}
                onChange={(e) => onChange({ prefetch_count: parseInt(e.target.value) || 10 })}
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
            <FormField label="Batch Size">
              <input
                type="number"
                value={config.batch_size}
                onChange={(e) => onChange({ batch_size: parseInt(e.target.value) || 100 })}
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
          </div>
          <div className="space-y-2">
            <Toggle
              label="Durable Queue"
              checked={config.durable}
              onChange={(durable) => onChange({ durable })}
            />
            <Toggle
              label="Auto Delete"
              checked={config.auto_delete}
              onChange={(auto_delete) => onChange({ auto_delete })}
            />
            <Toggle
              label="Exclusive"
              checked={config.exclusive}
              onChange={(exclusive) => onChange({ exclusive })}
            />
          </div>
        </Section>

        {/* Dead Letter */}
        <Section title="Dead Letter Queue">
          <div className="grid grid-cols-2 gap-4">
            <FormField label="DLQ Exchange">
              <input
                type="text"
                value={config.dead_letter_exchange || ''}
                onChange={(e) => onChange({ dead_letter_exchange: e.target.value || null })}
                placeholder="(none)"
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
            <FormField label="DLQ Routing Key">
              <input
                type="text"
                value={config.dead_letter_routing_key || ''}
                onChange={(e) => onChange({ dead_letter_routing_key: e.target.value || null })}
                placeholder="(none)"
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
          </div>
        </Section>

        {/* Processing */}
        <Section title="Processing">
          <div className="space-y-2">
            <Toggle
              label="Auto Acknowledge"
              checked={config.auto_ack}
              onChange={(auto_ack) => onChange({ auto_ack })}
            />
            <Toggle
              label="Requeue on Error"
              checked={config.requeue_on_error}
              onChange={(requeue_on_error) => onChange({ requeue_on_error })}
            />
          </div>
        </Section>

        {/* Resilience */}
        <Section title="Resilience">
          <div className="space-y-2">
            <Toggle
              label="Circuit Breaker"
              checked={config.enable_circuit_breaker}
              onChange={(enable_circuit_breaker) => onChange({ enable_circuit_breaker })}
            />
            <Toggle
              label="Dead Letter Queue Handler"
              checked={config.enable_dlq}
              onChange={(enable_dlq) => onChange({ enable_dlq })}
            />
            <Toggle
              label="Graceful Shutdown"
              checked={config.enable_graceful_shutdown}
              onChange={(enable_graceful_shutdown) => onChange({ enable_graceful_shutdown })}
            />
          </div>
        </Section>
      </div>
    </div>
  );
}

// ============================================================================
// SNS/SQS Config Form
// ============================================================================

interface SNSSQSConfigFormProps {
  config: SNSSQSConfig;
  onChange: (config: Partial<SNSSQSConfig>) => void;
  onReset: () => void;
}

function SNSSQSConfigForm({ config, onChange, onReset }: SNSSQSConfigFormProps) {
  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--accent)]/20 bg-surface/80">
        <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
          AWS SNS/SQS Configuration
        </span>
        <button
          onClick={onReset}
          className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
        >
          Reset to Defaults
        </button>
      </div>

      <div className="p-4 space-y-6">
        {/* Connection */}
        <Section title="Connection">
          <FormField label="AWS Region">
            <input
              type="text"
              value={config.region}
              onChange={(e) => onChange({ region: e.target.value })}
              placeholder="us-east-1"
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </FormField>
          <FormField label="SQS Queue URL">
            <input
              type="text"
              value={config.queue_url}
              onChange={(e) => onChange({ queue_url: e.target.value })}
              placeholder="https://sqs.us-east-1.amazonaws.com/123456789012/my-queue"
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </FormField>
          <FormField label="SNS Topic ARN (optional)">
            <input
              type="text"
              value={config.topic_arn || ''}
              onChange={(e) => onChange({ topic_arn: e.target.value || null })}
              placeholder="arn:aws:sns:us-east-1:123456789012:my-topic"
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </FormField>
        </Section>

        {/* Consumer Settings */}
        <Section title="Consumer Settings">
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Max Messages per Poll">
              <input
                type="number"
                value={config.max_messages}
                onChange={(e) => onChange({ max_messages: parseInt(e.target.value) || 10 })}
                min={1}
                max={10}
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
            <FormField label="Wait Time (seconds)">
              <input
                type="number"
                value={config.wait_time_seconds}
                onChange={(e) => onChange({ wait_time_seconds: parseInt(e.target.value) || 20 })}
                min={0}
                max={20}
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
            <FormField label="Visibility Timeout (seconds)">
              <input
                type="number"
                value={config.visibility_timeout_seconds}
                onChange={(e) =>
                  onChange({ visibility_timeout_seconds: parseInt(e.target.value) || 300 })
                }
                className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </FormField>
          </div>
        </Section>

        {/* Dead Letter Queue */}
        <Section title="Dead Letter Queue">
          <FormField label="DLQ URL (optional)">
            <input
              type="text"
              value={config.dead_letter_queue_url || ''}
              onChange={(e) => onChange({ dead_letter_queue_url: e.target.value || null })}
              placeholder="https://sqs.us-east-1.amazonaws.com/123456789012/my-dlq"
              className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </FormField>
        </Section>

        {/* Resilience */}
        <Section title="Resilience">
          <div className="space-y-2">
            <Toggle
              label="Circuit Breaker"
              checked={config.enable_circuit_breaker}
              onChange={(enable_circuit_breaker) => onChange({ enable_circuit_breaker })}
            />
            <Toggle
              label="Idempotency Tracking"
              checked={config.enable_idempotency}
              onChange={(enable_idempotency) => onChange({ enable_idempotency })}
            />
          </div>
        </Section>
      </div>
    </div>
  );
}

// ============================================================================
// Shared Components
// ============================================================================

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider mb-3">
        {title}
      </h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-xs font-theme-data text-text-muted block mb-1">{label}</label>
      {children}
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-3 cursor-pointer">
      <div
        onClick={() => onChange(!checked)}
        className={`w-10 h-5 rounded-full relative transition-colors ${
          checked ? 'bg-[var(--accent)]/30' : 'bg-surface'
        } border ${checked ? 'border-[var(--accent)]/50' : 'border-border'}`}
      >
        <div
          className={`absolute top-0.5 w-4 h-4 rounded-full transition-all ${
            checked ? 'left-5 bg-[var(--accent)]' : 'left-0.5 bg-text-muted'
          }`}
        />
      </div>
      <span className="text-sm font-theme-data text-text">{label}</span>
    </label>
  );
}
