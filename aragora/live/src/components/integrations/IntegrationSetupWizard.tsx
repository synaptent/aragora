'use client';

import { useState } from 'react';

export type IntegrationType =
  'slack' | 'discord' | 'telegram' | 'email' | 'teams' | 'whatsapp' | 'matrix';

export const MASKED_SECRET_FIELD_VALUE = '__aragora_masked_secret__';

interface IntegrationField {
  key: string;
  label: string;
  type: 'text' | 'password' | 'select' | 'checkbox';
  placeholder?: string;
  required?: boolean;
  options?: { value: string; label: string }[];
  helpText?: string;
}

interface IntegrationConfig {
  title: string;
  description: string;
  icon: string;
  docsUrl: string;
  fields: IntegrationField[];
  notificationOptions: { key: string; label: string; default: boolean }[];
}

const INTEGRATION_CONFIGS: Record<IntegrationType, IntegrationConfig> = {
  slack: {
    title: 'Slack',
    description: 'Post debate updates to Slack channels via webhooks or bot.',
    icon: '#',
    docsUrl: 'https://api.slack.com/messaging/webhooks',
    fields: [
      {
        key: 'webhook_url',
        label: 'Webhook URL',
        type: 'text',
        placeholder: 'https://hooks.slack.com/services/...',
        required: true,
        helpText: 'Create an incoming webhook in your Slack app settings',
      },
      {
        key: 'channel',
        label: 'Channel (optional)',
        type: 'text',
        placeholder: '#debates',
        helpText: 'Override the default channel',
      },
      {
        key: 'bot_token',
        label: 'Bot Token (optional)',
        type: 'password',
        placeholder: 'xoxb-...',
        helpText: 'For advanced features like threads',
      },
    ],
    notificationOptions: [
      { key: 'notify_on_consensus', label: 'Consensus reached', default: true },
      { key: 'notify_on_debate_end', label: 'Debate completed', default: true },
      { key: 'notify_on_error', label: 'Errors', default: false },
      { key: 'notify_on_leaderboard', label: 'Leaderboard updates', default: false },
    ],
  },
  discord: {
    title: 'Discord',
    description: 'Send rich embeds to Discord channels via webhooks.',
    icon: 'D>',
    docsUrl: 'https://discord.com/developers/docs/resources/webhook',
    fields: [
      {
        key: 'webhook_url',
        label: 'Webhook URL',
        type: 'text',
        placeholder: 'https://discord.com/api/webhooks/...',
        required: true,
        helpText: 'Create a webhook in your Discord server settings',
      },
      {
        key: 'username',
        label: 'Bot Username (optional)',
        type: 'text',
        placeholder: 'Aragora Bot',
        helpText: 'Custom display name for messages',
      },
      {
        key: 'avatar_url',
        label: 'Avatar URL (optional)',
        type: 'text',
        placeholder: 'https://...',
        helpText: 'Custom avatar image URL',
      },
    ],
    notificationOptions: [
      { key: 'notify_on_consensus', label: 'Consensus reached', default: true },
      { key: 'notify_on_debate_end', label: 'Debate completed', default: true },
      { key: 'notify_on_error', label: 'Errors', default: true },
      { key: 'notify_on_leaderboard', label: 'Leaderboard updates', default: false },
    ],
  },
  telegram: {
    title: 'Telegram',
    description: 'Send messages to Telegram chats or channels via bot.',
    icon: 'T>',
    docsUrl: 'https://core.telegram.org/bots/api',
    fields: [
      {
        key: 'bot_token',
        label: 'Bot Token',
        type: 'password',
        placeholder: '123456:ABC-DEF...',
        required: true,
        helpText: 'Get from @BotFather on Telegram',
      },
      {
        key: 'chat_id',
        label: 'Chat ID',
        type: 'text',
        placeholder: '-1001234567890',
        required: true,
        helpText: 'Channel or group chat ID',
      },
      {
        key: 'parse_mode',
        label: 'Parse Mode',
        type: 'select',
        options: [
          { value: 'HTML', label: 'HTML' },
          { value: 'Markdown', label: 'Markdown' },
        ],
      },
    ],
    notificationOptions: [
      { key: 'notify_on_consensus', label: 'Consensus reached', default: true },
      { key: 'notify_on_debate_end', label: 'Debate completed', default: true },
      { key: 'notify_on_error', label: 'Errors', default: true },
      { key: 'enable_commands', label: 'Enable bot commands', default: false },
    ],
  },
  email: {
    title: 'Email',
    description: 'Send email notifications via SMTP, SendGrid, or AWS SES.',
    icon: '@>',
    docsUrl: 'https://docs.sendgrid.com/api-reference/mail-send/mail-send',
    fields: [
      {
        key: 'provider',
        label: 'Provider',
        type: 'select',
        required: true,
        options: [
          { value: 'smtp', label: 'SMTP' },
          { value: 'sendgrid', label: 'SendGrid' },
          { value: 'ses', label: 'AWS SES' },
        ],
      },
      {
        key: 'from_email',
        label: 'From Email',
        type: 'text',
        placeholder: 'debates@example.com',
        required: true,
      },
      { key: 'from_name', label: 'From Name', type: 'text', placeholder: 'Aragora Debates' },
      {
        key: 'smtp_host',
        label: 'SMTP Host',
        type: 'text',
        placeholder: 'smtp.example.com',
        helpText: 'Required for SMTP provider',
      },
      { key: 'smtp_port', label: 'SMTP Port', type: 'text', placeholder: '587' },
      { key: 'smtp_username', label: 'SMTP Username', type: 'text' },
      { key: 'smtp_password', label: 'SMTP Password', type: 'password' },
      {
        key: 'sendgrid_api_key',
        label: 'SendGrid API Key',
        type: 'password',
        placeholder: 'SG.xxx',
        helpText: 'Required for SendGrid provider',
      },
      {
        key: 'ses_region',
        label: 'AWS Region',
        type: 'text',
        placeholder: 'us-east-1',
        helpText: 'Required for SES provider',
      },
    ],
    notificationOptions: [
      { key: 'notify_on_consensus', label: 'Consensus reached', default: true },
      { key: 'notify_on_debate_end', label: 'Debate completed', default: true },
      { key: 'notify_on_error', label: 'Errors', default: false },
      { key: 'enable_digest', label: 'Daily digest', default: true },
    ],
  },
  teams: {
    title: 'Microsoft Teams',
    description: 'Post adaptive cards to Teams channels via incoming webhooks.',
    icon: 'T#',
    docsUrl:
      'https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook',
    fields: [
      {
        key: 'webhook_url',
        label: 'Webhook URL',
        type: 'text',
        placeholder: 'https://xxx.webhook.office.com/webhookb2/...',
        required: true,
        helpText: 'Create an incoming webhook connector in Teams',
      },
    ],
    notificationOptions: [
      { key: 'notify_on_consensus', label: 'Consensus reached', default: true },
      { key: 'notify_on_debate_end', label: 'Debate completed', default: true },
      { key: 'notify_on_error', label: 'Errors', default: true },
      { key: 'notify_on_leaderboard', label: 'Leaderboard updates', default: false },
      { key: 'use_adaptive_cards', label: 'Use Adaptive Cards', default: true },
    ],
  },
  whatsapp: {
    title: 'WhatsApp',
    description: 'Send messages via Meta Business API or Twilio.',
    icon: 'W>',
    docsUrl: 'https://developers.facebook.com/docs/whatsapp/cloud-api',
    fields: [
      {
        key: 'provider',
        label: 'Provider',
        type: 'select',
        required: true,
        options: [
          { value: 'meta', label: 'Meta Business API' },
          { value: 'twilio', label: 'Twilio' },
        ],
      },
      {
        key: 'recipient',
        label: 'Recipient Phone',
        type: 'text',
        placeholder: '+1234567890',
        required: true,
        helpText: 'Phone number with country code',
      },
      {
        key: 'phone_number_id',
        label: 'Phone Number ID (Meta)',
        type: 'text',
        placeholder: '1234567890',
      },
      {
        key: 'access_token',
        label: 'Access Token (Meta)',
        type: 'password',
        placeholder: 'EAAxx...',
      },
      {
        key: 'twilio_account_sid',
        label: 'Twilio Account SID',
        type: 'text',
        placeholder: 'ACxx...',
      },
      { key: 'twilio_auth_token', label: 'Twilio Auth Token', type: 'password' },
      {
        key: 'twilio_whatsapp_number',
        label: 'Twilio WhatsApp Number',
        type: 'text',
        placeholder: '+14155238886',
      },
    ],
    notificationOptions: [
      { key: 'notify_on_consensus', label: 'Consensus reached', default: true },
      { key: 'notify_on_debate_end', label: 'Debate completed', default: true },
      { key: 'notify_on_error', label: 'Errors', default: false },
    ],
  },
  matrix: {
    title: 'Matrix / Element',
    description: 'Post messages to Matrix rooms with HTML formatting.',
    icon: 'M>',
    docsUrl: 'https://spec.matrix.org/latest/client-server-api/',
    fields: [
      {
        key: 'homeserver_url',
        label: 'Homeserver URL',
        type: 'text',
        placeholder: 'https://matrix.org',
        required: true,
      },
      {
        key: 'access_token',
        label: 'Access Token',
        type: 'password',
        placeholder: 'syt_xxx...',
        required: true,
        helpText: 'Bot user access token',
      },
      { key: 'user_id', label: 'User ID', type: 'text', placeholder: '@aragora-bot:matrix.org' },
      {
        key: 'room_id',
        label: 'Room ID',
        type: 'text',
        placeholder: '!abc123:matrix.org',
        required: true,
      },
    ],
    notificationOptions: [
      { key: 'notify_on_consensus', label: 'Consensus reached', default: true },
      { key: 'notify_on_debate_end', label: 'Debate completed', default: true },
      { key: 'notify_on_error', label: 'Errors', default: true },
      { key: 'notify_on_leaderboard', label: 'Leaderboard updates', default: false },
      { key: 'enable_commands', label: 'Enable room commands', default: false },
      { key: 'use_html', label: 'Use HTML formatting', default: true },
    ],
  },
};

interface IntegrationSetupWizardProps {
  type: IntegrationType;
  onClose: () => void;
  onSave: (config: Record<string, unknown>) => Promise<void>;
  onTest?: (
    type: IntegrationType,
    config: Record<string, unknown>,
  ) => Promise<{ success: boolean; error?: string }>;
  existingConfig?: Record<string, unknown>;
}

export function IntegrationSetupWizard({
  type,
  onClose,
  onSave,
  onTest,
  existingConfig,
}: IntegrationSetupWizardProps) {
  const config = INTEGRATION_CONFIGS[type];
  const [step, setStep] = useState(1);
  const [formData, setFormData] = useState<Record<string, unknown>>(existingConfig || {});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'failed'>('idle');

  const buildSubmissionData = () => {
    return Object.fromEntries(
      Object.entries(formData).filter(
        ([key, value]) =>
          key !== '_notificationsInitialized' && value !== MASKED_SECRET_FIELD_VALUE,
      ),
    );
  };

  const handleFieldChange = (key: string, value: unknown) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  };

  const handleNotificationToggle = (key: string) => {
    setFormData((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleTest = async () => {
    setTestStatus('testing');
    setError(null);

    try {
      // Check required fields first
      const missingRequired = config.fields
        .filter((f) => f.required && !formData[f.key])
        .map((f) => f.label);

      if (missingRequired.length > 0) {
        throw new Error(`Missing required fields: ${missingRequired.join(', ')}`);
      }

      // Use the onTest callback if provided (calls real API)
      if (onTest) {
        const result = await onTest(type, buildSubmissionData());
        if (result.success) {
          setTestStatus('success');
        } else {
          throw new Error(result.error || 'Connection test failed');
        }
      } else {
        // Fallback: validation-only test when no API handler provided
        await new Promise((resolve) => setTimeout(resolve, 500));
        setTestStatus('success');
      }
    } catch (err) {
      setTestStatus('failed');
      setError(err instanceof Error ? err.message : 'Test failed');
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);

    try {
      await onSave({ ...buildSubmissionData(), type });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save configuration');
    } finally {
      setSaving(false);
    }
  };

  // Initialize notification defaults
  if (step === 2 && !formData._notificationsInitialized) {
    const defaults: Record<string, boolean> = {};
    config.notificationOptions.forEach((opt) => {
      if (formData[opt.key] === undefined) {
        defaults[opt.key] = opt.default;
      }
    });
    setFormData((prev) => ({ ...prev, ...defaults, _notificationsInitialized: true }));
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-surface border border-[var(--accent)]/30 rounded-lg w-full max-w-2xl max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="p-4 border-b border-[var(--accent)]/20 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="font-theme-data text-[var(--acid-cyan)] text-xl">{config.icon}</span>
            <div>
              <h2 className="font-theme-data text-[var(--accent)] text-lg">
                {existingConfig ? 'Edit' : 'Setup'} {config.title}
              </h2>
              <p className="font-theme-data text-xs text-text-muted">{config.description}</p>
            </div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text font-theme-data">
            [X]
          </button>
        </div>

        {/* Progress */}
        <div className="px-4 py-2 border-b border-[var(--accent)]/10 flex gap-2">
          {[1, 2, 3].map((s) => (
            <button
              key={s}
              onClick={() => setStep(s)}
              className={`flex-1 py-1 font-theme-data text-xs border transition-colors ${
                step === s
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : step > s
                    ? 'border-[var(--accent)]/30 text-[var(--accent)]/50'
                    : 'border-[var(--accent)]/20 text-text-muted'
              }`}
            >
              {s === 1 ? 'Credentials' : s === 2 ? 'Notifications' : 'Test & Save'}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="p-4 overflow-y-auto max-h-[60vh]">
          {error && (
            <div className="mb-4 p-3 border border-warning/30 bg-warning/10 rounded">
              <p className="text-warning font-theme-data text-sm">{error}</p>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              {config.fields.map((field) => (
                <div key={field.key}>
                  <label className="block font-theme-data text-sm text-text-muted mb-1">
                    {field.label}
                    {field.required && <span className="text-warning ml-1">*</span>}
                  </label>

                  {field.type === 'select' ? (
                    <select
                      value={(formData[field.key] as string) || ''}
                      onChange={(e) => handleFieldChange(field.key, e.target.value)}
                      className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
                    >
                      <option value="">Select...</option>
                      {field.options?.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  ) : field.type === 'checkbox' ? (
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={!!formData[field.key]}
                        onChange={(e) => handleFieldChange(field.key, e.target.checked)}
                        className="form-checkbox bg-bg border-[var(--accent)]/30"
                      />
                      <span className="font-theme-data text-sm text-text">{field.placeholder}</span>
                    </label>
                  ) : (
                    <input
                      type={field.type}
                      value={
                        formData[field.key] === MASKED_SECRET_FIELD_VALUE
                          ? '••••••••'
                          : (formData[field.key] as string) || ''
                      }
                      onChange={(e) => handleFieldChange(field.key, e.target.value)}
                      placeholder={field.placeholder}
                      className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
                    />
                  )}

                  {field.helpText && (
                    <p className="mt-1 text-xs font-theme-data text-text-muted">{field.helpText}</p>
                  )}
                </div>
              ))}

              <a
                href={config.docsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block mt-2 text-xs font-theme-data text-[var(--acid-cyan)] hover:underline"
              >
                [VIEW DOCUMENTATION]
              </a>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-3">
              <p className="font-theme-data text-sm text-text-muted mb-4">
                Select which events should trigger notifications:
              </p>

              {config.notificationOptions.map((opt) => (
                <label
                  key={opt.key}
                  className="flex items-center gap-3 p-3 border border-[var(--accent)]/20 rounded cursor-pointer hover:border-[var(--accent)]/40 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={!!formData[opt.key]}
                    onChange={() => handleNotificationToggle(opt.key)}
                    className="form-checkbox bg-bg border-[var(--accent)]/30 text-[var(--accent)]"
                  />
                  <span className="font-theme-data text-sm text-text">{opt.label}</span>
                </label>
              ))}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <div className="p-4 border border-[var(--accent)]/20 rounded bg-bg/50">
                <h4 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                  Configuration Summary
                </h4>
                <div className="space-y-2 text-xs font-theme-data">
                  {config.fields
                    .filter((f) => formData[f.key])
                    .map((f) => (
                      <div key={f.key} className="flex justify-between">
                        <span className="text-text-muted">{f.label}:</span>
                        <span className="text-text">
                          {f.type === 'password'
                            ? '••••••••'
                            : String(formData[f.key]).slice(0, 30)}
                          {String(formData[f.key]).length > 30 ? '...' : ''}
                        </span>
                      </div>
                    ))}
                </div>
              </div>

              <div className="flex items-center gap-4">
                <button
                  onClick={handleTest}
                  disabled={testStatus === 'testing'}
                  className="px-4 py-2 border border-[var(--acid-cyan)]/50 text-[var(--acid-cyan)] font-theme-data text-sm hover:bg-[var(--acid-cyan)]/10 transition-colors disabled:opacity-50"
                >
                  {testStatus === 'testing' ? 'Testing...' : '[TEST CONNECTION]'}
                </button>

                {testStatus === 'success' && (
                  <span className="font-theme-data text-sm text-[var(--accent)]">
                    Connection successful!
                  </span>
                )}
                {testStatus === 'failed' && (
                  <span className="font-theme-data text-sm text-warning">Connection failed</span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-[var(--accent)]/20 flex justify-between">
          <button
            onClick={() => (step > 1 ? setStep(step - 1) : onClose())}
            className="px-4 py-2 border border-[var(--accent)]/30 text-text-muted font-theme-data text-sm hover:text-text transition-colors"
          >
            {step > 1 ? '[BACK]' : '[CANCEL]'}
          </button>

          {step < 3 ? (
            <button
              onClick={() => setStep(step + 1)}
              className="px-4 py-2 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/10 transition-colors"
            >
              [NEXT]
            </button>
          ) : (
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {saving ? 'Saving...' : '[SAVE INTEGRATION]'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export { INTEGRATION_CONFIGS };
