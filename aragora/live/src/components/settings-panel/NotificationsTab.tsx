'use client';

import { useState, useEffect, useCallback } from 'react';
import type { UserPreferences } from './types';
import { ToggleSwitch } from './ToggleSwitch';

export interface NotificationsTabProps {
  preferences: UserPreferences;
  updateNotification: (key: keyof UserPreferences['notifications'], value: boolean) => void;
}

// ---------------------------------------------------------------------------
// Template types
// ---------------------------------------------------------------------------

interface NotificationTemplate {
  id: string;
  name: string;
  description: string;
  channel: string;
  subject: string;
  body: string;
  variables: string[];
  sample_values: Record<string, string>;
  customized: boolean;
}

// ---------------------------------------------------------------------------
// Template editor row
// ---------------------------------------------------------------------------

function TemplateRow({
  template,
  onSave,
  onReset,
  onPreview,
}: {
  template: NotificationTemplate;
  onSave: (id: string, subject: string, body: string) => Promise<void>;
  onReset: (id: string) => Promise<void>;
  onPreview: (id: string) => Promise<{ rendered_subject: string; rendered_body: string } | null>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [editSubject, setEditSubject] = useState(template.subject);
  const [editBody, setEditBody] = useState(template.body);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [preview, setPreview] = useState<{
    rendered_subject: string;
    rendered_body: string;
  } | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Sync when template changes externally (after reset)
  useEffect(() => {
    setEditSubject(template.subject);
    setEditBody(template.body);
    setDirty(false);
    setPreview(null);
    setShowPreview(false);
  }, [template.subject, template.body]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(template.id, editSubject, editBody);
      setDirty(false);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    try {
      await onReset(template.id);
    } finally {
      setResetting(false);
    }
  };

  const handlePreview = async () => {
    const result = await onPreview(template.id);
    setPreview(result);
    setShowPreview(true);
  };

  return (
    <div className="border border-gray-700 rounded">
      {/* Header row */}
      <button
        type="button"
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-800/50 transition-colors"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-3">
          <span className="font-theme-data text-sm text-white">{template.name}</span>
          {template.customized && (
            <span className="text-xs px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 rounded font-theme-data">
              custom
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-gray-400">
          <span className="text-xs font-theme-data">{template.channel}</span>
          <svg
            className={`w-4 h-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-4 pb-4 space-y-4 border-t border-gray-700">
          <p className="text-xs text-gray-400 mt-3">{template.description}</p>

          {/* Variables hint */}
          <div className="flex flex-wrap gap-1.5">
            {template.variables.map((v) => (
              <span
                key={v}
                className="text-xs font-theme-data px-1.5 py-0.5 bg-gray-700/50 text-gray-400 rounded"
              >
                {`{{${v}}}`}
              </span>
            ))}
          </div>

          {/* Subject */}
          <div>
            <label
              className="block text-xs font-theme-data text-gray-400 mb-1"
              htmlFor={`subject-${template.id}`}
            >
              Subject
            </label>
            <input
              id={`subject-${template.id}`}
              type="text"
              className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-sm text-white font-theme-data focus:outline-none focus:border-[var(--accent)]"
              value={editSubject}
              onChange={(e) => {
                setEditSubject(e.target.value);
                setDirty(true);
              }}
            />
          </div>

          {/* Body */}
          <div>
            <label
              className="block text-xs font-theme-data text-gray-400 mb-1"
              htmlFor={`body-${template.id}`}
            >
              Body
            </label>
            <textarea
              id={`body-${template.id}`}
              rows={6}
              className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-sm text-white font-theme-data focus:outline-none focus:border-[var(--accent)] resize-y"
              value={editBody}
              onChange={(e) => {
                setEditBody(e.target.value);
                setDirty(true);
              }}
            />
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              disabled={!dirty || saving}
              onClick={handleSave}
              className="px-3 py-1.5 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/40 rounded hover:bg-[var(--accent)]/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={handlePreview}
              className="px-3 py-1.5 text-xs font-theme-data bg-gray-700/50 text-gray-300 border border-gray-600 rounded hover:bg-gray-700 transition-colors"
            >
              Preview
            </button>
            {template.customized && (
              <button
                type="button"
                disabled={resetting}
                onClick={handleReset}
                className="px-3 py-1.5 text-xs font-theme-data bg-red-500/10 text-red-400 border border-red-500/30 rounded hover:bg-red-500/20 disabled:opacity-40 transition-colors"
              >
                {resetting ? 'Resetting…' : 'Reset to default'}
              </button>
            )}
          </div>

          {/* Preview panel */}
          {showPreview && preview && (
            <div className="mt-2 p-3 bg-gray-900 border border-gray-600 rounded space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-theme-data text-gray-400">
                  Preview (sample values)
                </span>
                <button
                  type="button"
                  className="text-xs text-gray-500 hover:text-gray-300"
                  onClick={() => setShowPreview(false)}
                >
                  ✕
                </button>
              </div>
              <p className="text-sm font-semibold text-white">{preview.rendered_subject}</p>
              <pre className="text-xs text-gray-300 whitespace-pre-wrap font-theme-data">
                {preview.rendered_body}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export function NotificationsTab({ preferences, updateNotification }: NotificationsTabProps) {
  const [templates, setTemplates] = useState<NotificationTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);

  const fetchTemplates = useCallback(async () => {
    setLoadingTemplates(true);
    setTemplateError(null);
    try {
      const res = await fetch('/api/v1/notifications/templates');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setTemplates(data.templates ?? []);
    } catch {
      setTemplateError('Failed to load templates');
    } finally {
      setLoadingTemplates(false);
    }
  }, []);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const handleSave = async (id: string, subject: string, body: string) => {
    const res = await fetch(`/api/v1/notifications/templates/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject, body }),
    });
    if (!res.ok) throw new Error('Save failed');
    const data = await res.json();
    setTemplates((prev) => prev.map((t) => (t.id === id ? { ...t, ...data.template } : t)));
  };

  const handleReset = async (id: string) => {
    const res = await fetch(`/api/v1/notifications/templates/${id}/reset`, { method: 'POST' });
    if (!res.ok) throw new Error('Reset failed');
    const data = await res.json();
    setTemplates((prev) => prev.map((t) => (t.id === id ? { ...t, ...data.template } : t)));
  };

  const handlePreview = async (id: string) => {
    const res = await fetch(`/api/v1/notifications/templates/${id}/preview`, { method: 'POST' });
    if (!res.ok) return null;
    const data = await res.json();
    return { rendered_subject: data.rendered_subject, rendered_body: data.rendered_body };
  };

  return (
    <div
      className="space-y-8"
      role="tabpanel"
      id="panel-notifications"
      aria-labelledby="tab-notifications"
    >
      {/* Notification toggles */}
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Email Notifications</h3>
        <div className="space-y-4">
          <ToggleSwitch
            label="Debate Completed"
            description="Notify when a debate finishes"
            checked={preferences.notifications.debate_completed}
            onChange={() =>
              updateNotification('debate_completed', !preferences.notifications.debate_completed)
            }
          />
          <ToggleSwitch
            label="Daily Digest"
            description="Summary of your debate activity"
            checked={preferences.notifications.email_digest}
            onChange={() =>
              updateNotification('email_digest', !preferences.notifications.email_digest)
            }
          />
          <ToggleSwitch
            label="Weekly Summary"
            description="Weekly insights and trends"
            checked={preferences.notifications.weekly_summary}
            onChange={() =>
              updateNotification('weekly_summary', !preferences.notifications.weekly_summary)
            }
          />
        </div>
      </div>

      {/* Template editor */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-theme-data text-[var(--accent)]">Email Templates</h3>
            <p className="text-xs text-gray-400 mt-0.5">
              Customise subject lines and body text. Use{' '}
              <code className="font-theme-data bg-gray-700/50 px-1 rounded">{'{{variable}}'}</code>{' '}
              placeholders.
            </p>
          </div>
          <button
            type="button"
            onClick={fetchTemplates}
            disabled={loadingTemplates}
            className="text-xs font-theme-data text-gray-400 hover:text-white disabled:opacity-40"
            title="Refresh"
          >
            ↺
          </button>
        </div>

        {loadingTemplates && (
          <p className="text-sm text-gray-500 font-theme-data">Loading templates…</p>
        )}

        {templateError && <p className="text-sm text-red-400 font-theme-data">{templateError}</p>}

        {!loadingTemplates && !templateError && templates.length > 0 && (
          <div className="space-y-2">
            {templates.map((tpl) => (
              <TemplateRow
                key={tpl.id}
                template={tpl}
                onSave={handleSave}
                onReset={handleReset}
                onPreview={handlePreview}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default NotificationsTab;
