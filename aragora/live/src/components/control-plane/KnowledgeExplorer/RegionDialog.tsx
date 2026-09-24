/**
 * RegionDialog Component
 *
 * Modal dialog for adding or editing federated regions.
 * Supports all federation configuration options.
 */

import React, { useState, useCallback, useEffect } from 'react';
import type { FederatedRegion, SyncMode, SyncScope } from './FederationStatus';

export interface RegionFormData {
  name: string;
  regionId: string;
  endpointUrl: string;
  apiKey: string;
  mode: SyncMode;
  scope: SyncScope;
  enabled: boolean;
}

export interface RegionDialogProps {
  /** Whether the dialog is open */
  isOpen: boolean;
  /** Existing region data for editing (undefined for new region) */
  region?: FederatedRegion;
  /** Close handler */
  onClose: () => void;
  /** Save handler */
  onSave: (data: RegionFormData) => Promise<void>;
  /** Delete handler (only for editing) */
  onDelete?: (regionId: string) => Promise<void>;
  /** Whether save is in progress */
  isSaving?: boolean;
}

const syncModeOptions: { value: SyncMode; label: string; description: string }[] = [
  { value: 'bidirectional', label: 'Bidirectional', description: 'Push and pull data' },
  { value: 'push', label: 'Push Only', description: 'Only push data to this region' },
  { value: 'pull', label: 'Pull Only', description: 'Only pull data from this region' },
  { value: 'none', label: 'Disabled', description: 'No automatic sync' },
];

const syncScopeOptions: { value: SyncScope; label: string; description: string }[] = [
  { value: 'full', label: 'Full', description: 'Sync complete content and metadata' },
  { value: 'summary', label: 'Summary', description: 'Sync summarized content (recommended)' },
  { value: 'metadata', label: 'Metadata Only', description: 'Only sync metadata, no content' },
];

export const RegionDialog: React.FC<RegionDialogProps> = ({
  isOpen,
  region,
  onClose,
  onSave,
  onDelete,
  isSaving = false,
}) => {
  const isEditing = !!region;

  const [formData, setFormData] = useState<RegionFormData>({
    name: '',
    regionId: '',
    endpointUrl: '',
    apiKey: '',
    mode: 'bidirectional',
    scope: 'summary',
    enabled: true,
  });

  const [errors, setErrors] = useState<Partial<Record<keyof RegionFormData, string>>>({});
  const [showApiKey, setShowApiKey] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Initialize form data when region changes
  useEffect(() => {
    if (region) {
      setFormData({
        name: region.name,
        regionId: region.id,
        endpointUrl: region.endpointUrl,
        apiKey: '', // API key is not returned from server
        mode: region.mode,
        scope: region.scope,
        enabled: region.enabled,
      });
    } else {
      setFormData({
        name: '',
        regionId: '',
        endpointUrl: '',
        apiKey: '',
        mode: 'bidirectional',
        scope: 'summary',
        enabled: true,
      });
    }
    setErrors({});
    setShowDeleteConfirm(false);
  }, [region, isOpen]);

  const validateForm = useCallback((): boolean => {
    const newErrors: Partial<Record<keyof RegionFormData, string>> = {};

    if (!formData.name.trim()) {
      newErrors.name = 'Name is required';
    }

    if (!formData.regionId.trim()) {
      newErrors.regionId = 'Region ID is required';
    } else if (!/^[a-z0-9-]+$/.test(formData.regionId)) {
      newErrors.regionId = 'Region ID must be lowercase alphanumeric with hyphens';
    }

    if (!formData.endpointUrl.trim()) {
      newErrors.endpointUrl = 'Endpoint URL is required';
    } else {
      try {
        new URL(formData.endpointUrl);
      } catch {
        newErrors.endpointUrl = 'Invalid URL format';
      }
    }

    if (!isEditing && !formData.apiKey.trim()) {
      newErrors.apiKey = 'API key is required for new regions';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [formData, isEditing]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      if (!validateForm()) {
        return;
      }

      await onSave(formData);
    },
    [formData, validateForm, onSave],
  );

  const handleDelete = useCallback(async () => {
    if (onDelete && region) {
      await onDelete(region.id);
    }
  }, [onDelete, region]);

  const handleChange = useCallback(
    (field: keyof RegionFormData, value: string | boolean) => {
      setFormData((prev) => ({ ...prev, [field]: value }));
      // Clear error when user starts typing
      if (errors[field]) {
        setErrors((prev) => ({ ...prev, [field]: undefined }));
      }
    },
    [errors],
  );

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Dialog */}
      <div className="relative bg-surface border border-[var(--accent)]/30 rounded-lg shadow-xl w-full max-w-lg mx-4 max-h-[90vh] overflow-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--accent)]/20">
          <h2 className="text-lg font-theme-data text-[var(--accent)]">
            {isEditing ? 'Edit Region' : 'Add Federated Region'}
          </h2>
          <button onClick={onClose} className="text-text-muted hover:text-text transition-colors">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Name */}
          <div>
            <label className="block font-theme-data text-xs text-text-muted mb-1">
              Display Name
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => handleChange('name', e.target.value)}
              placeholder="e.g., US West 2"
              className={`w-full p-3 bg-bg border rounded font-theme-data text-sm text-text focus:outline-none focus:border-[var(--accent)] ${
                errors.name ? 'border-acid-red' : 'border-[var(--accent)]/30'
              }`}
            />
            {errors.name && <p className="mt-1 text-xs text-acid-red">{errors.name}</p>}
          </div>

          {/* Region ID */}
          <div>
            <label className="block font-theme-data text-xs text-text-muted mb-1">Region ID</label>
            <input
              type="text"
              value={formData.regionId}
              onChange={(e) => handleChange('regionId', e.target.value.toLowerCase())}
              placeholder="e.g., us-west-2"
              disabled={isEditing}
              className={`w-full p-3 bg-bg border rounded font-theme-data text-sm text-text focus:outline-none focus:border-[var(--accent)] ${
                errors.regionId ? 'border-acid-red' : 'border-[var(--accent)]/30'
              } ${isEditing ? 'opacity-50 cursor-not-allowed' : ''}`}
            />
            {errors.regionId && <p className="mt-1 text-xs text-acid-red">{errors.regionId}</p>}
            {isEditing && (
              <p className="mt-1 text-xs text-text-muted">Region ID cannot be changed</p>
            )}
          </div>

          {/* Endpoint URL */}
          <div>
            <label className="block font-theme-data text-xs text-text-muted mb-1">
              Endpoint URL
            </label>
            <input
              type="url"
              value={formData.endpointUrl}
              onChange={(e) => handleChange('endpointUrl', e.target.value)}
              placeholder="https://us-west-2.aragora.example.com/api"
              className={`w-full p-3 bg-bg border rounded font-theme-data text-sm text-text focus:outline-none focus:border-[var(--accent)] ${
                errors.endpointUrl ? 'border-acid-red' : 'border-[var(--accent)]/30'
              }`}
            />
            {errors.endpointUrl && (
              <p className="mt-1 text-xs text-acid-red">{errors.endpointUrl}</p>
            )}
          </div>

          {/* API Key */}
          <div>
            <label className="block font-theme-data text-xs text-text-muted mb-1">
              API Key {isEditing && '(leave blank to keep existing)'}
            </label>
            <div className="relative">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={formData.apiKey}
                onChange={(e) => handleChange('apiKey', e.target.value)}
                placeholder={isEditing ? '********' : 'Enter API key'}
                className={`w-full p-3 pr-10 bg-bg border rounded font-theme-data text-sm text-text focus:outline-none focus:border-[var(--accent)] ${
                  errors.apiKey ? 'border-acid-red' : 'border-[var(--accent)]/30'
                }`}
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text"
              >
                {showApiKey ? (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                    />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                    />
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                    />
                  </svg>
                )}
              </button>
            </div>
            {errors.apiKey && <p className="mt-1 text-xs text-acid-red">{errors.apiKey}</p>}
          </div>

          {/* Sync Mode */}
          <div>
            <label className="block font-theme-data text-xs text-text-muted mb-2">Sync Mode</label>
            <div className="grid grid-cols-2 gap-2">
              {syncModeOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => handleChange('mode', option.value)}
                  className={`p-3 text-left border rounded transition-colors ${
                    formData.mode === option.value
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                      : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40'
                  }`}
                >
                  <div className="font-theme-data text-sm text-text">{option.label}</div>
                  <div className="font-theme-data text-xs text-text-muted">
                    {option.description}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Sync Scope */}
          <div>
            <label className="block font-theme-data text-xs text-text-muted mb-2">Sync Scope</label>
            <div className="grid grid-cols-3 gap-2">
              {syncScopeOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => handleChange('scope', option.value)}
                  className={`p-2 text-left border rounded transition-colors ${
                    formData.scope === option.value
                      ? 'border-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10'
                      : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40'
                  }`}
                >
                  <div className="font-theme-data text-xs text-text">{option.label}</div>
                </button>
              ))}
            </div>
            <p className="mt-1 text-xs text-text-muted">
              {syncScopeOptions.find((o) => o.value === formData.scope)?.description}
            </p>
          </div>

          {/* Enabled Toggle */}
          <div className="flex items-center justify-between p-3 bg-bg border border-[var(--accent)]/20 rounded">
            <div>
              <div className="font-theme-data text-sm text-text">Enable Region</div>
              <div className="font-theme-data text-xs text-text-muted">
                Start syncing immediately after save
              </div>
            </div>
            <button
              type="button"
              onClick={() => handleChange('enabled', !formData.enabled)}
              className={`relative w-12 h-6 rounded-full transition-colors ${
                formData.enabled ? 'bg-[var(--accent)]' : 'bg-text-muted/30'
              }`}
            >
              <span
                className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform ${
                  formData.enabled ? 'translate-x-6' : ''
                }`}
              />
            </button>
          </div>

          {/* Delete confirmation */}
          {isEditing && showDeleteConfirm && (
            <div className="p-4 bg-acid-red/10 border border-acid-red/30 rounded">
              <p className="font-theme-data text-sm text-acid-red mb-3">
                Are you sure you want to delete this region? This cannot be undone.
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={isSaving}
                  className="px-4 py-2 bg-acid-red text-white font-theme-data text-sm rounded hover:bg-acid-red/80 transition-colors disabled:opacity-50"
                >
                  Delete Region
                </button>
                <button
                  type="button"
                  onClick={() => setShowDeleteConfirm(false)}
                  className="px-4 py-2 border border-[var(--accent)]/30 text-text font-theme-data text-sm rounded hover:bg-surface transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-between pt-4 border-t border-[var(--accent)]/20">
            {isEditing && onDelete && !showDeleteConfirm ? (
              <button
                type="button"
                onClick={() => setShowDeleteConfirm(true)}
                className="px-4 py-2 text-acid-red font-theme-data text-sm hover:bg-acid-red/10 rounded transition-colors"
              >
                Delete Region
              </button>
            ) : (
              <div />
            )}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 border border-[var(--accent)]/30 text-text font-theme-data text-sm rounded hover:bg-surface transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSaving}
                className="px-4 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm rounded hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
              >
                {isSaving ? 'Saving...' : isEditing ? 'Save Changes' : 'Add Region'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};

export default RegionDialog;
