'use client';

import { useState, useMemo, useCallback } from 'react';
import type { ConnectorType, ConnectorInfo } from './ConnectorCard';

export interface ConnectorConfigField {
  key: string;
  label: string;
  type: 'text' | 'password' | 'select' | 'checkbox' | 'number' | 'textarea';
  required?: boolean;
  placeholder?: string;
  options?: Array<{ value: string; label: string }>;
  helperText?: string;
  defaultValue?: string | number | boolean;
}

export interface ConnectorConfigModalProps {
  connector: ConnectorInfo | null;
  isOpen: boolean;
  onClose: () => void;
  onSave: (connectorId: string, config: Record<string, unknown>) => Promise<void>;
  onTest?: (connectorId: string, config: Record<string, unknown>) => Promise<boolean>;
}

// Configuration schemas for each connector type
const CONNECTOR_CONFIGS: Record<ConnectorType, ConnectorConfigField[]> = {
  github: [
    {
      key: 'org',
      label: 'Organization/User',
      type: 'text',
      required: true,
      placeholder: 'your-org',
    },
    {
      key: 'repos',
      label: 'Repositories',
      type: 'textarea',
      placeholder: 'repo1, repo2 (leave empty for all)',
      helperText: 'Comma-separated list of repositories to sync',
    },
    {
      key: 'token',
      label: 'Personal Access Token',
      type: 'password',
      required: true,
      placeholder: 'ghp_xxxxx',
      helperText: 'Requires repo scope for private repos',
    },
    { key: 'include_issues', label: 'Include Issues', type: 'checkbox', defaultValue: true },
    { key: 'include_prs', label: 'Include Pull Requests', type: 'checkbox', defaultValue: true },
    {
      key: 'include_discussions',
      label: 'Include Discussions',
      type: 'checkbox',
      defaultValue: false,
    },
  ],
  s3: [
    { key: 'bucket', label: 'Bucket Name', type: 'text', required: true, placeholder: 'my-bucket' },
    {
      key: 'region',
      label: 'AWS Region',
      type: 'select',
      required: true,
      options: [
        { value: 'us-east-1', label: 'US East (N. Virginia)' },
        { value: 'us-west-2', label: 'US West (Oregon)' },
        { value: 'eu-west-1', label: 'EU (Ireland)' },
        { value: 'ap-southeast-1', label: 'Asia Pacific (Singapore)' },
      ],
    },
    {
      key: 'prefix',
      label: 'Key Prefix',
      type: 'text',
      placeholder: 'documents/',
      helperText: 'Optional path prefix to sync',
    },
    { key: 'access_key_id', label: 'Access Key ID', type: 'password', required: true },
    { key: 'secret_access_key', label: 'Secret Access Key', type: 'password', required: true },
  ],
  sharepoint: [
    {
      key: 'tenant_id',
      label: 'Tenant ID',
      type: 'text',
      required: true,
      placeholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
    },
    {
      key: 'site_url',
      label: 'Site URL',
      type: 'text',
      required: true,
      placeholder: 'https://company.sharepoint.com/sites/MySite',
    },
    {
      key: 'client_id',
      label: 'Client ID',
      type: 'text',
      required: true,
      placeholder: 'Azure AD App Client ID',
    },
    { key: 'client_secret', label: 'Client Secret', type: 'password', required: true },
    {
      key: 'drive_id',
      label: 'Drive ID',
      type: 'text',
      placeholder: 'Leave empty for default document library',
    },
  ],
  postgresql: [
    { key: 'host', label: 'Host', type: 'text', required: true, placeholder: 'localhost' },
    { key: 'port', label: 'Port', type: 'number', required: true, defaultValue: 5432 },
    { key: 'database', label: 'Database', type: 'text', required: true, placeholder: 'mydb' },
    { key: 'username', label: 'Username', type: 'text', required: true },
    { key: 'password', label: 'Password', type: 'password', required: true },
    {
      key: 'tables',
      label: 'Tables',
      type: 'textarea',
      placeholder: 'table1, table2 (leave empty for all)',
      helperText: 'Comma-separated list of tables to sync',
    },
    { key: 'ssl', label: 'Use SSL', type: 'checkbox', defaultValue: true },
  ],
  mongodb: [
    {
      key: 'connection_string',
      label: 'Connection String',
      type: 'password',
      required: true,
      placeholder: 'mongodb+srv://user:pass@cluster.mongodb.net/db',
    },
    { key: 'database', label: 'Database', type: 'text', required: true },
    {
      key: 'collections',
      label: 'Collections',
      type: 'textarea',
      placeholder: 'collection1, collection2 (leave empty for all)',
    },
  ],
  confluence: [
    {
      key: 'base_url',
      label: 'Base URL',
      type: 'text',
      required: true,
      placeholder: 'https://your-domain.atlassian.net/wiki',
    },
    {
      key: 'email',
      label: 'Email',
      type: 'text',
      required: true,
      placeholder: 'user@company.com',
      helperText: 'For Cloud instances',
    },
    {
      key: 'api_token',
      label: 'API Token',
      type: 'password',
      required: true,
      helperText: 'Generate at id.atlassian.com/manage-profile/security/api-tokens',
    },
    {
      key: 'spaces',
      label: 'Space Keys',
      type: 'textarea',
      placeholder: 'ENG, DOCS, HR (leave empty for all)',
      helperText: 'Comma-separated space keys to sync',
    },
    {
      key: 'include_attachments',
      label: 'Include Attachments',
      type: 'checkbox',
      defaultValue: true,
    },
    { key: 'include_comments', label: 'Include Comments', type: 'checkbox', defaultValue: true },
  ],
  notion: [
    {
      key: 'api_key',
      label: 'Integration Token',
      type: 'password',
      required: true,
      placeholder: 'secret_xxxxx',
      helperText: 'Create at notion.so/my-integrations',
    },
    {
      key: 'root_page_ids',
      label: 'Root Page IDs',
      type: 'textarea',
      placeholder: 'Page IDs to sync (leave empty for all shared pages)',
      helperText: 'Comma-separated page IDs',
    },
    { key: 'include_databases', label: 'Include Databases', type: 'checkbox', defaultValue: true },
    {
      key: 'include_child_pages',
      label: 'Include Child Pages',
      type: 'checkbox',
      defaultValue: true,
    },
  ],
  slack: [
    {
      key: 'bot_token',
      label: 'Bot Token',
      type: 'password',
      required: true,
      placeholder: 'xoxb-xxxxx',
      helperText: 'OAuth Bot Token with channels:read, channels:history scopes',
    },
    {
      key: 'channels',
      label: 'Channels',
      type: 'textarea',
      placeholder: '#general, #engineering (leave empty for all public channels)',
      helperText: 'Comma-separated channel names or IDs',
    },
    { key: 'include_threads', label: 'Include Threads', type: 'checkbox', defaultValue: true },
    {
      key: 'include_private',
      label: 'Include Private Channels',
      type: 'checkbox',
      defaultValue: false,
      helperText: 'Requires groups:read, groups:history scopes',
    },
    { key: 'max_messages', label: 'Max Messages per Channel', type: 'number', defaultValue: 1000 },
  ],
  fhir: [
    {
      key: 'base_url',
      label: 'FHIR Server URL',
      type: 'text',
      required: true,
      placeholder: 'https://fhir.example.com/r4',
    },
    {
      key: 'auth_type',
      label: 'Authentication',
      type: 'select',
      required: true,
      options: [
        { value: 'none', label: 'None' },
        { value: 'basic', label: 'Basic Auth' },
        { value: 'bearer', label: 'Bearer Token' },
        { value: 'smart', label: 'SMART on FHIR' },
      ],
    },
    { key: 'username', label: 'Username', type: 'text' },
    { key: 'password', label: 'Password/Token', type: 'password' },
    {
      key: 'resource_types',
      label: 'Resource Types',
      type: 'textarea',
      placeholder: 'Patient, Observation, Condition',
      helperText: 'FHIR resource types to sync',
    },
    {
      key: 'redact_phi',
      label: 'Redact PHI',
      type: 'checkbox',
      defaultValue: true,
      helperText: 'Automatically redact protected health information',
    },
  ],
  gdrive: [
    { key: 'client_id', label: 'OAuth Client ID', type: 'text', required: true },
    { key: 'client_secret', label: 'OAuth Client Secret', type: 'password', required: true },
    {
      key: 'refresh_token',
      label: 'Refresh Token',
      type: 'password',
      helperText: 'Leave empty to initiate OAuth flow',
    },
    {
      key: 'folder_ids',
      label: 'Folder IDs',
      type: 'textarea',
      placeholder: 'Folder IDs to sync (leave empty for entire drive)',
    },
    { key: 'include_shared', label: 'Include Shared Drives', type: 'checkbox', defaultValue: true },
    {
      key: 'export_docs',
      label: 'Export Google Docs as Text',
      type: 'checkbox',
      defaultValue: true,
    },
  ],
};

/**
 * Modal for configuring enterprise connectors.
 */
export function ConnectorConfigModal({
  connector,
  isOpen,
  onClose,
  onSave,
  onTest,
}: ConnectorConfigModalProps) {
  const [formData, setFormData] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message?: string } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Get config fields for connector type
  const configFields = useMemo(() => {
    if (!connector) return [];
    return CONNECTOR_CONFIGS[connector.type] || [];
  }, [connector]);

  // Initialize form data when connector changes
  useMemo(() => {
    if (!connector) return;

    const initialData: Record<string, unknown> = {};
    configFields.forEach((field) => {
      if (connector.config?.[field.key] !== undefined) {
        initialData[field.key] = connector.config[field.key];
      } else if (field.defaultValue !== undefined) {
        initialData[field.key] = field.defaultValue;
      }
    });
    setFormData(initialData);
    setErrors({});
    setTestResult(null);
  }, [connector, configFields]);

  // Handle field change
  const handleChange = useCallback((key: string, value: unknown) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setTestResult(null);
  }, []);

  // Validate form
  const validate = useCallback(() => {
    const newErrors: Record<string, string> = {};

    configFields.forEach((field) => {
      if (field.required && !formData[field.key]) {
        newErrors[field.key] = `${field.label} is required`;
      }
    });

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [configFields, formData]);

  // Handle test connection
  const handleTest = useCallback(async () => {
    if (!connector || !onTest) return;
    if (!validate()) return;

    setTesting(true);
    setTestResult(null);

    try {
      const success = await onTest(connector.id, formData);
      setTestResult({ success, message: success ? 'Connection successful!' : 'Connection failed' });
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : 'Connection test failed',
      });
    } finally {
      setTesting(false);
    }
  }, [connector, formData, onTest, validate]);

  // Handle save
  const handleSave = useCallback(async () => {
    if (!connector) return;
    if (!validate()) return;

    setSaving(true);

    try {
      await onSave(connector.id, formData);
      onClose();
    } catch (err) {
      setErrors({ _form: err instanceof Error ? err.message : 'Failed to save configuration' });
    } finally {
      setSaving(false);
    }
  }, [connector, formData, onSave, onClose, validate]);

  if (!isOpen || !connector) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-surface border border-border rounded-lg w-full max-w-lg max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div>
            <h2 className="font-theme-data font-medium text-lg">Configure {connector.name}</h2>
            <p className="text-xs text-text-muted mt-1">{connector.description}</p>
          </div>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text transition-colors p-1"
          >
            <span className="text-xl">x</span>
          </button>
        </div>

        {/* Form */}
        <div className="p-4 overflow-y-auto max-h-[60vh]">
          <div className="space-y-4">
            {configFields.map((field) => (
              <div key={field.key}>
                <label className="block text-sm font-theme-data mb-1">
                  {field.label}
                  {field.required && <span className="text-[var(--crimson)] ml-1">*</span>}
                </label>

                {field.type === 'text' && (
                  <input
                    type="text"
                    value={(formData[field.key] as string) || ''}
                    onChange={(e) => handleChange(field.key, e.target.value)}
                    placeholder={field.placeholder}
                    className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data focus:border-[var(--accent)] focus:outline-none"
                  />
                )}

                {field.type === 'password' && (
                  <input
                    type="password"
                    value={(formData[field.key] as string) || ''}
                    onChange={(e) => handleChange(field.key, e.target.value)}
                    placeholder={field.placeholder}
                    className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data focus:border-[var(--accent)] focus:outline-none"
                  />
                )}

                {field.type === 'number' && (
                  <input
                    type="number"
                    value={(formData[field.key] as number) ?? ''}
                    onChange={(e) => handleChange(field.key, parseInt(e.target.value, 10))}
                    placeholder={field.placeholder}
                    className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data focus:border-[var(--accent)] focus:outline-none"
                  />
                )}

                {field.type === 'textarea' && (
                  <textarea
                    value={(formData[field.key] as string) || ''}
                    onChange={(e) => handleChange(field.key, e.target.value)}
                    placeholder={field.placeholder}
                    rows={3}
                    className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data focus:border-[var(--accent)] focus:outline-none resize-none"
                  />
                )}

                {field.type === 'select' && (
                  <select
                    value={(formData[field.key] as string) || ''}
                    onChange={(e) => handleChange(field.key, e.target.value)}
                    className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data focus:border-[var(--accent)] focus:outline-none"
                  >
                    <option value="">Select...</option>
                    {field.options?.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                )}

                {field.type === 'checkbox' && (
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={(formData[field.key] as boolean) ?? false}
                      onChange={(e) => handleChange(field.key, e.target.checked)}
                      className="w-4 h-4 rounded border-border bg-bg checked:bg-[var(--accent)] checked:border-[var(--accent)]"
                    />
                    <span className="text-sm text-text-muted">{field.helperText || 'Enable'}</span>
                  </label>
                )}

                {field.helperText && field.type !== 'checkbox' && (
                  <p className="text-xs text-text-muted mt-1">{field.helperText}</p>
                )}

                {errors[field.key] && (
                  <p className="text-xs text-[var(--crimson)] mt-1">{errors[field.key]}</p>
                )}
              </div>
            ))}
          </div>

          {/* Form-level error */}
          {errors._form && (
            <div className="mt-4 p-3 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded text-sm text-[var(--crimson)]">
              {errors._form}
            </div>
          )}

          {/* Test result */}
          {testResult && (
            <div
              className={`mt-4 p-3 rounded text-sm ${
                testResult.success
                  ? 'bg-success/10 border border-success/30 text-success'
                  : 'bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 text-[var(--crimson)]'
              }`}
            >
              {testResult.message}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-border bg-bg/50">
          <div>
            {onTest && (
              <button
                onClick={handleTest}
                disabled={testing}
                className="px-4 py-2 text-sm font-theme-data border border-border rounded hover:border-[var(--acid-cyan)] transition-colors disabled:opacity-50"
              >
                {testing ? 'Testing...' : 'Test Connection'}
              </button>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-theme-data border border-border rounded hover:border-text-muted transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ConnectorConfigModal;
