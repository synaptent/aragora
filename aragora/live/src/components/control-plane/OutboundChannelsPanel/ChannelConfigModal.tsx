'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import type { OutboundChannel, OutboundChannelType } from './ChannelCard';

export interface ChannelConfigField {
  key: string;
  label: string;
  type: 'text' | 'password' | 'url' | 'select' | 'toggle';
  required?: boolean;
  placeholder?: string;
  helpText?: string;
  options?: { value: string; label: string }[];
}

export interface ChannelConfigModalProps {
  channel: OutboundChannel | null;
  isOpen: boolean;
  onClose: () => void;
  onSave: (channelId: string, config: Record<string, unknown>) => Promise<void>;
  onTest: (channelId: string, config: Record<string, unknown>) => Promise<boolean>;
}

const CHANNEL_CONFIG_FIELDS: Record<OutboundChannelType, ChannelConfigField[]> = {
  slack: [
    {
      key: 'webhook_url',
      label: 'Webhook URL',
      type: 'url',
      required: true,
      placeholder: 'https://hooks.slack.com/...',
    },
    { key: 'default_channel', label: 'Default Channel', type: 'text', placeholder: '#general' },
    { key: 'bot_name', label: 'Bot Name', type: 'text', placeholder: 'Aragora Bot' },
    { key: 'include_metadata', label: 'Include Debate Metadata', type: 'toggle' },
  ],
  teams: [
    {
      key: 'webhook_url',
      label: 'Incoming Webhook URL',
      type: 'url',
      required: true,
      placeholder: 'https://outlook.office.com/webhook/...',
    },
    { key: 'default_channel', label: 'Default Channel', type: 'text', placeholder: 'General' },
    { key: 'adaptive_cards', label: 'Use Adaptive Cards', type: 'toggle' },
  ],
  discord: [
    {
      key: 'webhook_url',
      label: 'Webhook URL',
      type: 'url',
      required: true,
      placeholder: 'https://discord.com/api/webhooks/...',
    },
    { key: 'default_channel', label: 'Default Channel ID', type: 'text', placeholder: '123456789' },
    { key: 'embed_color', label: 'Embed Color', type: 'text', placeholder: '#00ff88' },
  ],
  telegram: [
    {
      key: 'bot_token',
      label: 'Bot Token',
      type: 'password',
      required: true,
      placeholder: '123456:ABC-DEF...',
    },
    {
      key: 'chat_id',
      label: 'Default Chat ID',
      type: 'text',
      required: true,
      placeholder: '-1001234567890',
    },
    {
      key: 'parse_mode',
      label: 'Parse Mode',
      type: 'select',
      options: [
        { value: 'HTML', label: 'HTML' },
        { value: 'Markdown', label: 'Markdown' },
        { value: 'MarkdownV2', label: 'Markdown V2' },
      ],
    },
  ],
  whatsapp: [
    { key: 'api_key', label: 'API Key', type: 'password', required: true },
    { key: 'phone_number_id', label: 'Phone Number ID', type: 'text', required: true },
    {
      key: 'default_recipient',
      label: 'Default Recipient',
      type: 'text',
      placeholder: '+1234567890',
    },
  ],
  voice: [
    {
      key: 'provider',
      label: 'Provider',
      type: 'select',
      required: true,
      options: [
        { value: 'twilio', label: 'Twilio' },
        { value: 'vonage', label: 'Vonage' },
        { value: 'aws_connect', label: 'AWS Connect' },
      ],
    },
    { key: 'api_key', label: 'API Key', type: 'password', required: true },
    { key: 'api_secret', label: 'API Secret', type: 'password', required: true },
    {
      key: 'from_number',
      label: 'From Number',
      type: 'text',
      required: true,
      placeholder: '+1234567890',
    },
    {
      key: 'voice',
      label: 'Voice',
      type: 'select',
      options: [
        { value: 'alloy', label: 'Alloy' },
        { value: 'echo', label: 'Echo' },
        { value: 'fable', label: 'Fable' },
        { value: 'onyx', label: 'Onyx' },
        { value: 'nova', label: 'Nova' },
      ],
    },
  ],
  email: [
    {
      key: 'smtp_host',
      label: 'SMTP Host',
      type: 'text',
      required: true,
      placeholder: 'smtp.gmail.com',
    },
    { key: 'smtp_port', label: 'SMTP Port', type: 'text', required: true, placeholder: '587' },
    { key: 'username', label: 'Username', type: 'text', required: true },
    { key: 'password', label: 'Password', type: 'password', required: true },
    {
      key: 'from_email',
      label: 'From Email',
      type: 'text',
      required: true,
      placeholder: 'decisions@company.com',
    },
    { key: 'use_tls', label: 'Use TLS', type: 'toggle' },
  ],
  webhook: [
    {
      key: 'url',
      label: 'Webhook URL',
      type: 'url',
      required: true,
      placeholder: 'https://api.example.com/webhook',
    },
    {
      key: 'method',
      label: 'HTTP Method',
      type: 'select',
      options: [
        { value: 'POST', label: 'POST' },
        { value: 'PUT', label: 'PUT' },
      ],
    },
    {
      key: 'auth_header',
      label: 'Authorization Header',
      type: 'password',
      placeholder: 'Bearer token...',
    },
    {
      key: 'custom_headers',
      label: 'Custom Headers (JSON)',
      type: 'text',
      placeholder: '{"X-Custom": "value"}',
    },
    { key: 'include_full_response', label: 'Include Full Debate Response', type: 'toggle' },
  ],
};

/**
 * Modal for configuring outbound channel settings.
 */
export function ChannelConfigModal({
  channel,
  isOpen,
  onClose,
  onSave,
  onTest,
}: ChannelConfigModalProps) {
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<'success' | 'failure' | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reset state when modal opens/closes or channel changes
  useEffect(() => {
    if (isOpen && channel) {
      setConfig({});
      setTestResult(null);
      setError(null);
    }
  }, [isOpen, channel]);

  const fields = useMemo(
    () => (channel ? CHANNEL_CONFIG_FIELDS[channel.type] || [] : []),
    [channel],
  );

  const handleChange = useCallback((key: string, value: unknown) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
    setTestResult(null);
    setError(null);
  }, []);

  const handleTest = useCallback(async () => {
    if (!channel) return;

    setTesting(true);
    setTestResult(null);
    setError(null);

    try {
      const success = await onTest(channel.id, config);
      setTestResult(success ? 'success' : 'failure');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Test failed');
      setTestResult('failure');
    } finally {
      setTesting(false);
    }
  }, [channel, config, onTest]);

  const handleSave = useCallback(async () => {
    if (!channel) return;

    // Validate required fields
    const missingFields = fields.filter((f) => f.required && !config[f.key]).map((f) => f.label);

    if (missingFields.length > 0) {
      setError(`Missing required fields: ${missingFields.join(', ')}`);
      return;
    }

    setSaving(true);
    setError(null);

    try {
      await onSave(channel.id, config);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }, [channel, config, fields, onSave, onClose]);

  if (!isOpen || !channel) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80">
      <div className="bg-bg border border-border rounded-lg w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-bg border-b border-border p-4 flex items-center justify-between">
          <h2 className="font-theme-data font-bold text-lg">Configure {channel.name}</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text transition-colors">
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="p-4 space-y-4">
          {error && (
            <div className="p-3 bg-red-400/10 border border-red-400/30 rounded text-sm text-red-400">
              {error}
            </div>
          )}

          {testResult === 'success' && (
            <div className="p-3 bg-[var(--accent)]/10 border border-[var(--accent)]/30 rounded text-sm text-[var(--accent)]">
              Connection test successful!
            </div>
          )}

          {testResult === 'failure' && !error && (
            <div className="p-3 bg-red-400/10 border border-red-400/30 rounded text-sm text-red-400">
              Connection test failed. Please check your configuration.
            </div>
          )}

          {fields.map((field) => (
            <div key={field.key}>
              <label className="block text-sm font-theme-data mb-1">
                {field.label}
                {field.required && <span className="text-red-400 ml-1">*</span>}
              </label>

              {field.type === 'toggle' ? (
                <button
                  onClick={() => handleChange(field.key, !config[field.key])}
                  className={`relative w-10 h-5 rounded-full transition-colors ${
                    config[field.key] ? 'bg-[var(--accent)]' : 'bg-surface-alt'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                      config[field.key] ? 'left-5' : 'left-0.5'
                    }`}
                  />
                </button>
              ) : field.type === 'select' ? (
                <select
                  value={(config[field.key] as string) || ''}
                  onChange={(e) => handleChange(field.key, e.target.value)}
                  className="w-full px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
                >
                  <option value="">Select...</option>
                  {field.options?.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.type === 'password' ? 'password' : 'text'}
                  value={(config[field.key] as string) || ''}
                  onChange={(e) => handleChange(field.key, e.target.value)}
                  placeholder={field.placeholder}
                  className="w-full px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
                />
              )}

              {field.helpText && <p className="text-xs text-text-muted mt-1">{field.helpText}</p>}
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 bg-bg border-t border-border p-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-theme-data text-text-muted hover:text-text transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleTest}
            disabled={testing}
            className="px-4 py-2 text-sm font-theme-data bg-surface hover:bg-surface-alt rounded transition-colors disabled:opacity-50"
          >
            {testing ? 'Testing...' : 'Test Connection'}
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Configuration'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ChannelConfigModal;
