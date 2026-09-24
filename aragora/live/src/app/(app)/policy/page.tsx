'use client';

import { useState, useCallback, useMemo } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { ErrorWithRetry } from '@/components/ErrorWithRetry';
import { useToastContext } from '@/context/ToastContext';
import { useSWRFetch } from '@/hooks/useSWRFetch';
import { usePolicies, type Policy, type Violation } from '@/hooks/usePolicies';
import { logger } from '@/utils/logger';

// ============================================================================
// Types for conflict detection and sync status
// ============================================================================

interface PolicyConflict {
  id: string;
  policy_a_id: string;
  policy_a_name: string;
  policy_b_id: string;
  policy_b_name: string;
  conflict_type: 'contradictory' | 'overlapping' | 'redundant' | 'escalation';
  description: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  resolution_suggestion?: string;
  detected_at: string;
  resolved: boolean;
}

interface PolicySyncStatus {
  scheduler_running: boolean;
  last_sync: string | null;
  next_sync: string | null;
  sync_interval_seconds: number;
  policies_synced: number;
  sync_errors: number;
  status: 'synced' | 'syncing' | 'error' | 'stale' | 'disabled';
}

// ============================================================================
// Local Policy types (page-specific, extends hook types for display)
// ============================================================================

interface PolicyRule {
  id: string;
  pattern?: string;
  action: 'warn' | 'block' | 'flag' | 'redact';
  message: string;
}

interface LocalPolicy extends Omit<Policy, 'rules'> {
  type?: 'content' | 'output' | 'behavior' | 'custom';
  severity?: 'low' | 'medium' | 'high' | 'critical';
  rules: PolicyRule[];
  violation_count?: number;
}

// ============================================================================
// Constants
// ============================================================================

const severityColors: Record<string, string> = {
  low: 'text-text-muted border-text-muted/30',
  medium: 'text-[var(--acid-yellow)] border-acid-yellow/30',
  high: 'text-warning border-warning/30',
  critical: 'text-[var(--crimson)] border-[var(--crimson)]/30',
};

const severityBgColors: Record<string, string> = {
  low: 'bg-text-muted/10',
  medium: 'bg-acid-yellow/10',
  high: 'bg-warning/10',
  critical: 'bg-[var(--crimson)]/10',
};

const statusColors: Record<string, string> = {
  open: 'text-[var(--crimson)] bg-[var(--crimson)]/10 border-[var(--crimson)]/30',
  investigating: 'text-[var(--acid-yellow)] bg-acid-yellow/10 border-acid-yellow/30',
  resolved: 'text-[var(--accent)] bg-[var(--accent)]/10 border-[var(--accent)]/30',
  false_positive: 'text-text-muted bg-text-muted/10 border-text-muted/30',
  ignored: 'text-text-muted bg-text-muted/10 border-text-muted/30',
};

const typeIcons: Record<string, string> = { content: '#', output: '>', behavior: '!', custom: '*' };

const actionColors: Record<string, string> = {
  warn: 'text-[var(--acid-yellow)]',
  block: 'text-[var(--crimson)]',
  flag: 'text-[var(--acid-cyan)]',
  redact: 'text-warning',
};

const conflictTypeColors: Record<string, string> = {
  contradictory: 'text-[var(--crimson)] border-[var(--crimson)]/30 bg-[var(--crimson)]/10',
  overlapping: 'text-[var(--acid-yellow)] border-acid-yellow/30 bg-acid-yellow/10',
  redundant: 'text-text-muted border-text-muted/30 bg-text-muted/10',
  escalation: 'text-warning border-warning/30 bg-warning/10',
};

const syncStatusColors: Record<string, string> = {
  synced: 'text-[var(--accent)]',
  syncing: 'text-[var(--acid-cyan)]',
  error: 'text-[var(--crimson)]',
  stale: 'text-[var(--acid-yellow)]',
  disabled: 'text-text-muted',
};

const syncStatusBg: Record<string, string> = {
  synced: 'bg-[var(--accent)]/10 border-[var(--accent)]/30',
  syncing: 'bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/30',
  error: 'bg-[var(--crimson)]/10 border-[var(--crimson)]/30',
  stale: 'bg-acid-yellow/10 border-acid-yellow/30',
  disabled: 'bg-text-muted/10 border-text-muted/30',
};

function timeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// ============================================================================
// Create/Edit Policy Modal
// ============================================================================

function PolicyModal({
  policy,
  onClose,
  onSave,
}: {
  policy?: LocalPolicy | null;
  onClose: () => void;
  onSave: (data: Partial<LocalPolicy>) => Promise<void>;
}) {
  const [name, setName] = useState(policy?.name || '');
  const [description, setDescription] = useState(policy?.description || '');
  const [type, setType] = useState<string>(policy?.type || 'content');
  const [severity, setSeverity] = useState<string>(policy?.severity || 'medium');
  const [frameworkId, setFrameworkId] = useState(policy?.framework_id || 'default');
  const [verticalId, setVerticalId] = useState(policy?.vertical_id || 'general');
  const [rules, setRules] = useState<PolicyRule[]>(policy?.rules || []);
  const [saving, setSaving] = useState(false);

  const handleAddRule = () => {
    setRules([...rules, { id: `rule-${Date.now()}`, pattern: '', action: 'warn', message: '' }]);
  };

  const handleRemoveRule = (ruleId: string) => {
    setRules(rules.filter((r) => r.id !== ruleId));
  };

  const handleUpdateRule = (ruleId: string, updates: Partial<PolicyRule>) => {
    setRules(rules.map((r) => (r.id === ruleId ? { ...r, ...updates } : r)));
  };

  const handleSubmit = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await onSave({
        name,
        description,
        type: type as LocalPolicy['type'],
        severity: severity as LocalPolicy['severity'],
        framework_id: frameworkId,
        vertical_id: verticalId,
        rules,
      });
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 overflow-y-auto p-4">
      <div className="card p-6 w-full max-w-2xl my-4">
        <h2 className="text-lg font-theme-data font-bold text-[var(--accent)] mb-4">
          {policy ? '[EDIT POLICY]' : '[NEW POLICY]'}
        </h2>

        <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-2">
          {/* Name */}
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1">Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Policy name"
              className="w-full bg-bg border border-border px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe what this policy enforces..."
              rows={2}
              className="w-full bg-bg border border-border px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
            />
          </div>

          {/* Type & Severity */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">Type</label>
              <select
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full bg-bg border border-border px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
              >
                <option value="content">Content</option>
                <option value="output">Output</option>
                <option value="behavior">Behavior</option>
                <option value="custom">Custom</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">Severity</label>
              <select
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
                className="w-full bg-bg border border-border px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
          </div>

          {/* Framework & Vertical */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Framework ID
              </label>
              <input
                type="text"
                value={frameworkId}
                onChange={(e) => setFrameworkId(e.target.value)}
                placeholder="default"
                className="w-full bg-bg border border-border px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Vertical ID
              </label>
              <input
                type="text"
                value={verticalId}
                onChange={(e) => setVerticalId(e.target.value)}
                placeholder="general"
                className="w-full bg-bg border border-border px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          </div>

          {/* Rules */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-theme-data text-text-muted">Rules</label>
              <button
                type="button"
                onClick={handleAddRule}
                className="text-xs font-theme-data text-[var(--accent)] hover:text-[var(--accent)]/80"
              >
                [+ ADD RULE]
              </button>
            </div>
            <div className="space-y-2">
              {rules.map((rule, idx) => (
                <div key={rule.id} className="bg-bg border border-border p-3 rounded space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-theme-data text-text-muted">Rule {idx + 1}</span>
                    <button
                      type="button"
                      onClick={() => handleRemoveRule(rule.id)}
                      className="text-xs font-theme-data text-[var(--crimson)] hover:text-[var(--crimson)]/80"
                    >
                      [X]
                    </button>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <div>
                      <select
                        value={rule.action}
                        onChange={(e) =>
                          handleUpdateRule(rule.id, {
                            action: e.target.value as PolicyRule['action'],
                          })
                        }
                        className="w-full bg-surface border border-border px-2 py-1 text-xs font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
                      >
                        <option value="warn">Warn</option>
                        <option value="block">Block</option>
                        <option value="flag">Flag</option>
                        <option value="redact">Redact</option>
                      </select>
                    </div>
                    <div className="col-span-2">
                      <input
                        type="text"
                        value={rule.pattern || ''}
                        onChange={(e) => handleUpdateRule(rule.id, { pattern: e.target.value })}
                        placeholder="Regex pattern (optional)"
                        className="w-full bg-surface border border-border px-2 py-1 text-xs font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
                      />
                    </div>
                  </div>
                  <input
                    type="text"
                    value={rule.message}
                    onChange={(e) => handleUpdateRule(rule.id, { message: e.target.value })}
                    placeholder="Violation message"
                    className="w-full bg-surface border border-border px-2 py-1 text-xs font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
                  />
                </div>
              ))}
              {rules.length === 0 && (
                <div className="text-text-muted text-xs text-center py-2">
                  No rules defined. Add rules to define policy behavior.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2 mt-4 pt-4 border-t border-border">
          <button
            onClick={handleSubmit}
            disabled={saving || !name.trim()}
            className="flex-1 px-4 py-2 font-theme-data text-sm bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
          >
            {saving ? '[SAVING...]' : policy ? '[SAVE CHANGES]' : '[CREATE POLICY]'}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 font-theme-data text-sm border border-border text-text-muted hover:border-text-muted transition-colors"
          >
            [CANCEL]
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Violation Details Modal
// ============================================================================

function ViolationModal({
  violation,
  onClose,
  onUpdateStatus,
}: {
  violation: Violation;
  onClose: () => void;
  onUpdateStatus: (status: Violation['status'], notes?: string) => Promise<void>;
}) {
  const [notes, setNotes] = useState('');
  const [updating, setUpdating] = useState(false);

  const handleUpdate = async (status: Violation['status']) => {
    setUpdating(true);
    try {
      await onUpdateStatus(status, notes);
      onClose();
    } finally {
      setUpdating(false);
    }
  };

  const violationSeverity = violation.severity || 'medium';
  const violationDescription = violation.description || '';
  const violationSource = violation.source || '';

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="card p-6 w-full max-w-lg">
        <h2 className="text-lg font-theme-data font-bold text-[var(--accent)] mb-4">
          [VIOLATION DETAILS]
        </h2>

        <div className="space-y-3">
          <div>
            <span className="text-xs font-theme-data text-text-muted">Policy:</span>
            <p className="font-theme-data text-text">
              {violation.rule_name || violation.policy_id}
            </p>
          </div>
          <div>
            <span className="text-xs font-theme-data text-text-muted">Severity:</span>
            <span
              className={`ml-2 px-2 py-0.5 text-xs font-theme-data border ${severityColors[violationSeverity]}`}
            >
              {violationSeverity.toUpperCase()}
            </span>
          </div>
          <div>
            <span className="text-xs font-theme-data text-text-muted">Status:</span>
            <span
              className={`ml-2 px-2 py-0.5 text-xs font-theme-data border ${statusColors[violation.status]}`}
            >
              {violation.status.toUpperCase()}
            </span>
          </div>
          {violationDescription && (
            <div>
              <span className="text-xs font-theme-data text-text-muted">Description:</span>
              <p className="text-sm text-text">{violationDescription}</p>
            </div>
          )}
          {violationSource && (
            <div>
              <span className="text-xs font-theme-data text-text-muted">Source:</span>
              <p className="text-sm text-text">{violationSource}</p>
            </div>
          )}
          <div>
            <span className="text-xs font-theme-data text-text-muted">Detected:</span>
            <p className="text-sm text-text">{new Date(violation.detected_at).toLocaleString()}</p>
          </div>

          {violation.status === 'open' && (
            <div>
              <label className="text-xs font-theme-data text-text-muted block mb-1">
                Resolution Notes
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Add notes about the resolution..."
                rows={2}
                className="w-full bg-bg border border-border px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-border">
          {violation.status === 'open' && (
            <>
              <button
                onClick={() => handleUpdate('investigating')}
                disabled={updating}
                className="px-3 py-1.5 font-theme-data text-xs bg-acid-yellow/20 border border-acid-yellow text-[var(--acid-yellow)] hover:bg-acid-yellow/30 transition-colors disabled:opacity-50"
              >
                [INVESTIGATE]
              </button>
              <button
                onClick={() => handleUpdate('resolved')}
                disabled={updating}
                className="px-3 py-1.5 font-theme-data text-xs bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
              >
                [RESOLVE]
              </button>
              <button
                onClick={() => handleUpdate('false_positive')}
                disabled={updating}
                className="px-3 py-1.5 font-theme-data text-xs border border-text-muted text-text-muted hover:border-text transition-colors disabled:opacity-50"
              >
                [FALSE POSITIVE]
              </button>
            </>
          )}
          {violation.status === 'investigating' && (
            <button
              onClick={() => handleUpdate('resolved')}
              disabled={updating}
              className="px-3 py-1.5 font-theme-data text-xs bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              [RESOLVE]
            </button>
          )}
          <button
            onClick={onClose}
            className="ml-auto px-3 py-1.5 font-theme-data text-xs border border-border text-text-muted hover:border-text-muted transition-colors"
          >
            [CLOSE]
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Compliance Check Modal
// ============================================================================

function ComplianceCheckModal({
  onClose,
  onCheck,
}: {
  onClose: () => void;
  onCheck: (
    content: string,
  ) => Promise<{ compliant: boolean; score: number; issue_count: number; result: unknown } | null>;
}) {
  const [content, setContent] = useState('');
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<{
    compliant: boolean;
    score: number;
    issue_count: number;
  } | null>(null);

  const handleCheck = async () => {
    if (!content.trim()) return;
    setChecking(true);
    try {
      const data = await onCheck(content);
      if (data) {
        setResult(data);
      }
    } catch (error) {
      logger.error('Failed to check compliance:', error);
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="card p-6 w-full max-w-lg">
        <h2 className="text-lg font-theme-data font-bold text-[var(--accent)] mb-4">
          [COMPLIANCE CHECK]
        </h2>

        <div className="space-y-4">
          <div>
            <label className="text-xs font-theme-data text-text-muted block mb-1">
              Content to Check
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Enter content to check against compliance policies..."
              rows={5}
              className="w-full bg-bg border border-border px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
            />
          </div>

          {result && (
            <div
              className={`p-4 rounded border ${result.compliant ? 'border-[var(--accent)] bg-[var(--accent)]/10' : 'border-[var(--crimson)] bg-[var(--crimson)]/10'}`}
            >
              <div className="flex items-center justify-between mb-2">
                <span
                  className={`font-theme-data font-bold ${result.compliant ? 'text-[var(--accent)]' : 'text-[var(--crimson)]'}`}
                >
                  {result.compliant ? 'COMPLIANT' : 'NON-COMPLIANT'}
                </span>
                <span className="font-theme-data text-sm text-text-muted">
                  Score: {result.score.toFixed(0)}%
                </span>
              </div>
              {result.issue_count > 0 && (
                <p className="text-sm text-text-muted">
                  {result.issue_count} issue{result.issue_count !== 1 ? 's' : ''} found
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex gap-2 mt-4 pt-4 border-t border-border">
          <button
            onClick={handleCheck}
            disabled={checking || !content.trim()}
            className="flex-1 px-4 py-2 font-theme-data text-sm bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
          >
            {checking ? '[CHECKING...]' : '[CHECK]'}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 font-theme-data text-sm border border-border text-text-muted hover:border-text-muted transition-colors"
          >
            [CLOSE]
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Policy Conflict Panel
// ============================================================================

function ConflictPanel({ conflicts }: { conflicts: PolicyConflict[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const unresolvedConflicts = useMemo(() => conflicts.filter((c) => !c.resolved), [conflicts]);

  if (unresolvedConflicts.length === 0) {
    return (
      <div className="card p-6 text-center">
        <div className="text-[var(--accent)] font-theme-data text-lg mb-2">NO CONFLICTS</div>
        <div className="text-text-muted font-theme-data text-xs">
          PolicyConflictDetector found no contradictions between active policies.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-theme-data text-text-muted">
          {unresolvedConflicts.length} unresolved conflict
          {unresolvedConflicts.length !== 1 ? 's' : ''}
        </span>
      </div>

      {unresolvedConflicts.map((conflict) => (
        <div
          key={conflict.id}
          className={`card p-4 transition-colors ${expandedId === conflict.id ? 'border-acid-yellow/50' : ''}`}
        >
          <div
            className="flex items-start justify-between cursor-pointer"
            onClick={() => setExpandedId(expandedId === conflict.id ? null : conflict.id)}
          >
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <span
                  className={`text-xs font-theme-data uppercase px-2 py-0.5 border ${conflictTypeColors[conflict.conflict_type]}`}
                >
                  {conflict.conflict_type}
                </span>
                <span
                  className={`text-xs font-theme-data uppercase px-2 py-0.5 border ${severityColors[conflict.severity]} ${severityBgColors[conflict.severity]}`}
                >
                  {conflict.severity}
                </span>
              </div>
              <div className="text-sm font-theme-data text-text mt-1">
                <span className="text-[var(--acid-cyan)]">{conflict.policy_a_name}</span>
                <span className="text-text-muted mx-2">vs</span>
                <span className="text-[var(--acid-cyan)]">{conflict.policy_b_name}</span>
              </div>
              <p className="text-xs text-text-muted mt-1">{conflict.description}</p>
            </div>
            <span className="text-text-muted font-theme-data text-xs ml-2">
              {expandedId === conflict.id ? '[-]' : '[+]'}
            </span>
          </div>

          {expandedId === conflict.id && (
            <div className="mt-3 pt-3 border-t border-border space-y-2">
              <div className="text-xs font-theme-data">
                <span className="text-text-muted">Detected:</span>{' '}
                <span className="text-text">{new Date(conflict.detected_at).toLocaleString()}</span>
              </div>
              <div className="text-xs font-theme-data">
                <span className="text-text-muted">Policy A:</span>{' '}
                <span className="text-text">{conflict.policy_a_name}</span>{' '}
                <span className="text-text-muted">({conflict.policy_a_id})</span>
              </div>
              <div className="text-xs font-theme-data">
                <span className="text-text-muted">Policy B:</span>{' '}
                <span className="text-text">{conflict.policy_b_name}</span>{' '}
                <span className="text-text-muted">({conflict.policy_b_id})</span>
              </div>
              {conflict.resolution_suggestion && (
                <div className="bg-[var(--accent)]/5 border border-[var(--accent)]/20 rounded p-2 mt-2">
                  <div className="text-xs font-theme-data text-[var(--accent)] mb-1">
                    Suggested Resolution:
                  </div>
                  <div className="text-xs font-theme-data text-text">
                    {conflict.resolution_suggestion}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ============================================================================
// Policy Sync Status Panel
// ============================================================================

function SyncStatusPanel({ syncStatus }: { syncStatus: PolicySyncStatus | null }) {
  if (!syncStatus) {
    return (
      <div className="card p-4">
        <div className="text-xs font-theme-data text-text-muted text-center py-3">
          Policy sync status unavailable.
        </div>
      </div>
    );
  }

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data font-bold text-[var(--accent)] uppercase tracking-wide">
          {'>'} Policy Sync Scheduler
        </h3>
        <div
          className={`flex items-center gap-2 px-3 py-1 border rounded-full ${syncStatusBg[syncStatus.status]}`}
        >
          {syncStatus.status === 'syncing' && (
            <span className="inline-block w-2 h-2 border border-[var(--acid-cyan)] border-t-transparent rounded-full animate-spin" />
          )}
          {syncStatus.status === 'synced' && (
            <span className="w-2 h-2 bg-[var(--accent)] rounded-full" />
          )}
          {(syncStatus.status === 'error' || syncStatus.status === 'stale') && (
            <span
              className={`w-2 h-2 rounded-full ${syncStatus.status === 'error' ? 'bg-[var(--crimson)]' : 'bg-acid-yellow'}`}
            />
          )}
          <span className={`text-xs font-theme-data ${syncStatusColors[syncStatus.status]}`}>
            {syncStatus.status.toUpperCase()}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs font-theme-data text-text-muted mb-1">Scheduler</div>
          <div
            className={`text-sm font-theme-data ${syncStatus.scheduler_running ? 'text-[var(--accent)]' : 'text-text-muted'}`}
          >
            {syncStatus.scheduler_running ? 'RUNNING' : 'STOPPED'}
          </div>
        </div>
        <div>
          <div className="text-xs font-theme-data text-text-muted mb-1">Sync Interval</div>
          <div className="text-sm font-theme-data text-text">
            {syncStatus.sync_interval_seconds}s
          </div>
        </div>
        <div>
          <div className="text-xs font-theme-data text-text-muted mb-1">Last Sync</div>
          <div className="text-sm font-theme-data text-text">
            {syncStatus.last_sync ? timeAgo(syncStatus.last_sync) : 'Never'}
          </div>
        </div>
        <div>
          <div className="text-xs font-theme-data text-text-muted mb-1">Next Sync</div>
          <div className="text-sm font-theme-data text-text">
            {syncStatus.next_sync ? timeAgo(syncStatus.next_sync) : '--'}
          </div>
        </div>
        <div>
          <div className="text-xs font-theme-data text-text-muted mb-1">Policies Synced</div>
          <div className="text-sm font-theme-data text-[var(--acid-cyan)]">
            {syncStatus.policies_synced}
          </div>
        </div>
        <div>
          <div className="text-xs font-theme-data text-text-muted mb-1">Sync Errors</div>
          <div
            className={`text-sm font-theme-data ${syncStatus.sync_errors > 0 ? 'text-[var(--crimson)]' : 'text-[var(--accent)]'}`}
          >
            {syncStatus.sync_errors}
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Main Page Component
// ============================================================================

export default function PolicyPage() {
  const { showToast } = useToastContext();

  // Wire up the usePolicies hook for all CRUD operations
  const {
    policies: hookPolicies,
    violations: hookViolations,
    stats,
    loading,
    error,
    openViolations,
    criticalViolations,
    riskScore,
    createPolicy: hookCreatePolicy,
    updatePolicy: hookUpdatePolicy,
    deletePolicy: hookDeletePolicy,
    togglePolicy: hookTogglePolicy,
    updateViolationStatus: hookUpdateViolationStatus,
    checkCompliance: hookCheckCompliance,
    refetch,
  } = usePolicies({ autoLoad: true });

  // Cast to local types for display (hook types are compatible)
  const policies = hookPolicies as unknown as LocalPolicy[];
  const violations = hookViolations;

  // ---- Fetch conflict detection results ----
  const { data: conflictsData } = useSWRFetch<{ data: { conflicts: PolicyConflict[] } }>(
    '/api/policies/conflicts',
    { refreshInterval: 60000 },
  );
  const conflicts = useMemo(
    () => (conflictsData?.data?.conflicts ?? []) as PolicyConflict[],
    [conflictsData],
  );
  const unresolvedConflicts = useMemo(() => conflicts.filter((c) => !c.resolved), [conflicts]);

  // ---- Fetch sync status ----
  const { data: syncData } = useSWRFetch<{ data: PolicySyncStatus }>('/api/policies/sync/status', {
    refreshInterval: 30000,
  });
  const syncStatus = (syncData?.data ?? null) as PolicySyncStatus | null;

  // ---- UI state ----
  const [activeTab, setActiveTab] = useState<'policies' | 'violations' | 'conflicts' | 'sync'>(
    'policies',
  );
  const [selectedPolicy, setSelectedPolicy] = useState<LocalPolicy | null>(null);
  const [showPolicyModal, setShowPolicyModal] = useState(false);
  const [editingPolicy, setEditingPolicy] = useState<LocalPolicy | null>(null);
  const [selectedViolation, setSelectedViolation] = useState<Violation | null>(null);
  const [showComplianceCheck, setShowComplianceCheck] = useState(false);
  const [violationFilter, setViolationFilter] = useState<'all' | 'open' | 'resolved'>('all');
  const [severityFilter, setSeverityFilter] = useState<
    'all' | 'critical' | 'high' | 'medium' | 'low'
  >('all');

  // ---- Handlers (wire to hook) ----
  const handleCreatePolicy = useCallback(
    async (data: Partial<LocalPolicy>) => {
      const result = await hookCreatePolicy({
        name: data.name || '',
        framework_id: data.framework_id || 'default',
        vertical_id: data.vertical_id || 'general',
        description: data.description,
        level: 'recommended',
        enabled: true,
        rules: data.rules?.map((r) => ({
          rule_id: r.id,
          name: r.message,
          description: r.message,
          severity: (data.severity as 'critical' | 'high' | 'medium' | 'low') || 'medium',
          enabled: true,
        })),
      });
      if (result) {
        showToast('Policy created successfully', 'success');
      } else {
        showToast('Failed to create policy', 'error');
      }
    },
    [hookCreatePolicy, showToast],
  );

  const handleUpdatePolicy = useCallback(
    async (policyId: string, data: Partial<LocalPolicy>) => {
      const result = await hookUpdatePolicy(policyId, {
        name: data.name,
        description: data.description,
        level: data.level as 'mandatory' | 'recommended' | 'optional' | undefined,
        enabled: data.enabled,
        rules: data.rules?.map((r) => ({
          rule_id: r.id,
          name: r.message,
          description: r.message,
          severity: (data.severity as 'critical' | 'high' | 'medium' | 'low') || 'medium',
          enabled: true,
        })),
      });
      if (result) {
        showToast('Policy updated successfully', 'success');
      } else {
        showToast('Failed to update policy', 'error');
      }
    },
    [hookUpdatePolicy, showToast],
  );

  const handleDeletePolicy = useCallback(
    async (policyId: string) => {
      if (!confirm('Are you sure you want to delete this policy?')) return;
      const success = await hookDeletePolicy(policyId);
      if (success) {
        showToast('Policy deleted successfully', 'success');
      } else {
        showToast('Failed to delete policy', 'error');
      }
    },
    [hookDeletePolicy, showToast],
  );

  const handleTogglePolicy = useCallback(
    async (policyId: string) => {
      await hookTogglePolicy(policyId);
    },
    [hookTogglePolicy],
  );

  const handleUpdateViolation = useCallback(
    async (violationId: string, status: Violation['status'], notes?: string) => {
      const result = await hookUpdateViolationStatus(violationId, status, notes);
      if (result) {
        showToast('Violation updated successfully', 'success');
      } else {
        showToast('Failed to update violation', 'error');
      }
    },
    [hookUpdateViolationStatus, showToast],
  );

  const handleComplianceCheck = useCallback(
    async (content: string) => {
      return await hookCheckCompliance(content, { store_violations: true });
    },
    [hookCheckCompliance],
  );

  // ---- Filter violations ----
  const filteredViolations = useMemo(() => {
    return violations.filter((v) => {
      if (
        violationFilter !== 'all' &&
        v.status !== violationFilter &&
        (violationFilter !== 'resolved' || v.status !== 'false_positive')
      ) {
        return false;
      }
      if (severityFilter !== 'all' && v.severity !== severityFilter) {
        return false;
      }
      return true;
    });
  }, [violations, violationFilter, severityFilter]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-8">
          {/* Title */}
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-2xl font-theme-data font-bold text-[var(--accent)] mb-2">
                [POLICY_ADMIN]
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Compliance policies, conflict detection, and violation tracking
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setShowComplianceCheck(true)}
                className="px-4 py-2 font-theme-data text-sm border border-[var(--acid-cyan)] text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
              >
                [CHECK CONTENT]
              </button>
              <button
                onClick={() => {
                  setEditingPolicy(null);
                  setShowPolicyModal(true);
                }}
                className="px-4 py-2 font-theme-data text-sm bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors"
              >
                [+ NEW POLICY]
              </button>
            </div>
          </div>

          {error && <ErrorWithRetry error={error} onRetry={refetch} className="mb-6" />}

          {loading ? (
            <div className="text-center py-12">
              <div className="text-[var(--accent)] font-theme-data animate-pulse">
                Loading policy data...
              </div>
            </div>
          ) : (
            <>
              {/* Stats Cards */}
              {stats && (
                <div className="grid grid-cols-2 md:grid-cols-6 gap-4 mb-8">
                  <div className="card p-4 text-center">
                    <div
                      className={`text-3xl font-theme-data ${riskScore < 25 ? 'text-[var(--accent)]' : riskScore < 50 ? 'text-[var(--acid-yellow)]' : riskScore < 75 ? 'text-warning' : 'text-[var(--crimson)]'}`}
                    >
                      {100 - riskScore}%
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Compliance Score</div>
                  </div>
                  <div className="card p-4 text-center">
                    <div className="text-3xl font-theme-data text-accent">
                      {stats.policies.enabled}/{stats.policies.total}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Active Policies</div>
                  </div>
                  <div className="card p-4 text-center">
                    <div className="text-3xl font-theme-data text-[var(--crimson)]">
                      {openViolations.length}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Open Violations</div>
                  </div>
                  <div className="card p-4 text-center">
                    <div className="text-3xl font-theme-data text-warning">
                      {criticalViolations.length}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Critical</div>
                  </div>
                  <div className="card p-4 text-center">
                    <div
                      className={`text-3xl font-theme-data ${unresolvedConflicts.length > 0 ? 'text-[var(--acid-yellow)]' : 'text-[var(--accent)]'}`}
                    >
                      {unresolvedConflicts.length}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Conflicts</div>
                  </div>
                  <div className="card p-4 text-center">
                    <div
                      className={`text-3xl font-theme-data ${syncStatusColors[syncStatus?.status ?? 'disabled']}`}
                    >
                      {syncStatus?.status === 'synced'
                        ? 'OK'
                        : syncStatus?.status === 'syncing'
                          ? '...'
                          : (syncStatus?.status?.toUpperCase() ?? '--')}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">Sync Status</div>
                  </div>
                </div>
              )}

              {/* Tabs */}
              <div className="flex gap-4 mb-6 border-b border-border">
                <button
                  onClick={() => setActiveTab('policies')}
                  className={`px-4 py-2 font-theme-data text-sm border-b-2 transition-colors ${
                    activeTab === 'policies'
                      ? 'border-[var(--accent)] text-[var(--accent)]'
                      : 'border-transparent text-text-muted hover:text-text'
                  }`}
                >
                  POLICIES ({policies.length})
                </button>
                <button
                  onClick={() => setActiveTab('violations')}
                  className={`px-4 py-2 font-theme-data text-sm border-b-2 transition-colors ${
                    activeTab === 'violations'
                      ? 'border-[var(--accent)] text-[var(--accent)]'
                      : 'border-transparent text-text-muted hover:text-text'
                  }`}
                >
                  VIOLATIONS ({openViolations.length} open)
                </button>
                <button
                  onClick={() => setActiveTab('conflicts')}
                  className={`px-4 py-2 font-theme-data text-sm border-b-2 transition-colors ${
                    activeTab === 'conflicts'
                      ? 'border-acid-yellow text-[var(--acid-yellow)]'
                      : 'border-transparent text-text-muted hover:text-text'
                  }`}
                >
                  CONFLICTS ({unresolvedConflicts.length})
                </button>
                <button
                  onClick={() => setActiveTab('sync')}
                  className={`px-4 py-2 font-theme-data text-sm border-b-2 transition-colors ${
                    activeTab === 'sync'
                      ? 'border-[var(--acid-cyan)] text-[var(--acid-cyan)]'
                      : 'border-transparent text-text-muted hover:text-text'
                  }`}
                >
                  SYNC
                </button>
              </div>

              {/* Policies Tab */}
              {activeTab === 'policies' && (
                <div className="space-y-4">
                  {policies.length === 0 ? (
                    <div className="card p-8 text-center">
                      <div className="text-text-muted font-theme-data">
                        No policies defined. Create your first compliance policy.
                      </div>
                    </div>
                  ) : (
                    policies
                      .filter((policy): policy is LocalPolicy => Boolean(policy?.id))
                      .map((policy) => (
                        <div
                          key={policy.id}
                          className={`card p-4 transition-colors ${selectedPolicy?.id === policy.id ? 'border-[var(--accent)]/50' : 'hover:border-[var(--accent)]/30'}`}
                        >
                          <div className="flex items-start justify-between">
                            <div
                              className="flex items-start gap-3 flex-1 cursor-pointer"
                              onClick={() =>
                                setSelectedPolicy(selectedPolicy?.id === policy.id ? null : policy)
                              }
                            >
                              <span className="text-[var(--accent)] font-theme-data text-lg">
                                {typeIcons[policy.type || 'content'] || '#'}
                              </span>
                              <div className="flex-1">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <h3 className="font-theme-data font-bold text-text">
                                    {policy.name}
                                  </h3>
                                  {policy.level && (
                                    <span
                                      className={`text-xs font-theme-data uppercase px-2 py-0.5 border ${
                                        policy.level === 'mandatory'
                                          ? 'text-[var(--crimson)] border-[var(--crimson)]/30 bg-[var(--crimson)]/10'
                                          : policy.level === 'recommended'
                                            ? 'text-[var(--acid-yellow)] border-acid-yellow/30 bg-acid-yellow/10'
                                            : 'text-text-muted border-text-muted/30 bg-text-muted/10'
                                      }`}
                                    >
                                      {policy.level}
                                    </span>
                                  )}
                                  <span className="text-xs font-theme-data text-text-muted">
                                    [{policy.rules_count ?? policy.rules?.length ?? 0} rules]
                                  </span>
                                </div>
                                <p className="text-sm text-text-muted mt-1">{policy.description}</p>
                                <div className="flex items-center gap-3 mt-1">
                                  {policy.framework_id && (
                                    <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                                      {policy.framework_id}
                                    </span>
                                  )}
                                  {policy.updated_at && (
                                    <span className="text-xs font-theme-data text-text-muted">
                                      Updated {timeAgo(policy.updated_at)}
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>
                            <div
                              className="flex items-center gap-2"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <button
                                onClick={() => handleTogglePolicy(policy.id)}
                                className={`px-3 py-1 font-theme-data text-xs border transition-colors ${
                                  policy.enabled
                                    ? 'border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/10'
                                    : 'border-text-muted text-text-muted hover:border-text'
                                }`}
                              >
                                {policy.enabled ? '[ON]' : '[OFF]'}
                              </button>
                              <button
                                onClick={() => {
                                  setEditingPolicy(policy);
                                  setShowPolicyModal(true);
                                }}
                                className="px-3 py-1 font-theme-data text-xs border border-[var(--acid-cyan)] text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                              >
                                [EDIT]
                              </button>
                              <button
                                onClick={() => handleDeletePolicy(policy.id)}
                                className="px-3 py-1 font-theme-data text-xs border border-[var(--crimson)] text-[var(--crimson)] hover:bg-[var(--crimson)]/10 transition-colors"
                              >
                                [DEL]
                              </button>
                            </div>
                          </div>

                          {/* Expanded details */}
                          {selectedPolicy?.id === policy.id && (
                            <div className="mt-4 pt-4 border-t border-border">
                              <h4 className="font-theme-data text-sm text-[var(--accent)] mb-2">
                                Rules ({policy.rules?.length || 0}):
                              </h4>
                              {policy.rules && policy.rules.length > 0 ? (
                                <div className="space-y-2">
                                  {policy.rules.map((rule) => (
                                    <div
                                      key={rule.id}
                                      className="bg-bg p-2 rounded text-sm font-theme-data"
                                    >
                                      <span
                                        className={`${actionColors[rule.action] || 'text-text-muted'}`}
                                      >
                                        [{rule.action?.toUpperCase?.() || 'RULE'}]
                                      </span>{' '}
                                      {rule.message}
                                      {rule.pattern && (
                                        <span className="text-text-muted ml-2">
                                          /{rule.pattern}/
                                        </span>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <div className="text-text-muted text-sm">No rules defined</div>
                              )}
                              <div className="mt-3 text-xs text-text-muted font-theme-data">
                                Framework: {policy.framework_id || 'default'} | Vertical:{' '}
                                {policy.vertical_id || 'general'}
                                {policy.workspace_id && ` | Workspace: ${policy.workspace_id}`}
                              </div>
                            </div>
                          )}
                        </div>
                      ))
                  )}
                </div>
              )}

              {/* Violations Tab */}
              {activeTab === 'violations' && (
                <div className="space-y-4">
                  {/* Filters */}
                  <div className="flex gap-4 flex-wrap">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-theme-data text-text-muted">Status:</span>
                      {(['all', 'open', 'resolved'] as const).map((f) => (
                        <button
                          key={f}
                          onClick={() => setViolationFilter(f)}
                          className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                            violationFilter === f
                              ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10'
                              : 'border-border text-text-muted hover:border-text-muted'
                          }`}
                        >
                          {f.toUpperCase()}
                        </button>
                      ))}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-theme-data text-text-muted">Severity:</span>
                      {(['all', 'critical', 'high', 'medium', 'low'] as const).map((f) => (
                        <button
                          key={f}
                          onClick={() => setSeverityFilter(f)}
                          className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                            severityFilter === f
                              ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10'
                              : 'border-border text-text-muted hover:border-text-muted'
                          }`}
                        >
                          {f.toUpperCase()}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="card">
                    {filteredViolations.length === 0 ? (
                      <div className="p-8 text-center">
                        <div className="text-text-muted font-theme-data">
                          {violations.length === 0
                            ? 'No violations recorded. Your content is compliant.'
                            : 'No violations match the current filters.'}
                        </div>
                      </div>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full font-theme-data text-sm">
                          <thead>
                            <tr className="border-b border-border">
                              <th className="text-left py-3 px-4 text-text-muted">Policy</th>
                              <th className="text-left py-3 px-4 text-text-muted">Description</th>
                              <th className="text-left py-3 px-4 text-text-muted">Severity</th>
                              <th className="text-left py-3 px-4 text-text-muted">Status</th>
                              <th className="text-left py-3 px-4 text-text-muted">Date</th>
                              <th className="text-left py-3 px-4 text-text-muted">Actions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {filteredViolations.map((violation) => (
                              <tr
                                key={violation.id}
                                className="border-b border-border/50 hover:bg-surface/50"
                              >
                                <td className="py-3 px-4">
                                  {violation.rule_name || violation.policy_id}
                                </td>
                                <td className="py-3 px-4 text-text-muted max-w-[200px] truncate">
                                  {violation.description}
                                </td>
                                <td className="py-3 px-4">
                                  <span
                                    className={`text-xs font-theme-data px-2 py-0.5 border ${severityColors[violation.severity]}`}
                                  >
                                    {violation.severity.toUpperCase()}
                                  </span>
                                </td>
                                <td className="py-3 px-4">
                                  <span
                                    className={`text-xs font-theme-data px-2 py-0.5 border ${statusColors[violation.status]}`}
                                  >
                                    {violation.status.toUpperCase()}
                                  </span>
                                </td>
                                <td className="py-3 px-4 text-text-muted">
                                  {new Date(violation.detected_at).toLocaleDateString()}
                                </td>
                                <td className="py-3 px-4">
                                  <button
                                    onClick={() => setSelectedViolation(violation)}
                                    className="text-[var(--acid-cyan)] hover:text-[var(--accent)] text-xs"
                                  >
                                    [VIEW]
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Conflicts Tab */}
              {activeTab === 'conflicts' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-theme-data text-text-muted">
                      PolicyConflictDetector analyzes active policies for contradictions, overlaps,
                      and redundancies.
                    </p>
                  </div>
                  <ConflictPanel conflicts={conflicts} />
                </div>
              )}

              {/* Sync Tab */}
              {activeTab === 'sync' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-theme-data text-text-muted">
                      PolicySyncScheduler continuously synchronizes policies across distributed
                      nodes.
                    </p>
                  </div>
                  <SyncStatusPanel syncStatus={syncStatus} />
                </div>
              )}
            </>
          )}
        </div>

        {/* Modals */}
        {showPolicyModal && (
          <PolicyModal
            policy={editingPolicy}
            onClose={() => {
              setShowPolicyModal(false);
              setEditingPolicy(null);
            }}
            onSave={async (data) => {
              if (editingPolicy) {
                await handleUpdatePolicy(editingPolicy.id, data);
              } else {
                await handleCreatePolicy(data);
              }
            }}
          />
        )}

        {selectedViolation && (
          <ViolationModal
            violation={selectedViolation}
            onClose={() => setSelectedViolation(null)}
            onUpdateStatus={(status, notes) =>
              handleUpdateViolation(selectedViolation.id, status, notes)
            }
          />
        )}

        {showComplianceCheck && (
          <ComplianceCheckModal
            onClose={() => setShowComplianceCheck(false)}
            onCheck={handleComplianceCheck}
          />
        )}
      </main>
    </>
  );
}
