'use client';

import { useState, useEffect, useCallback } from 'react';

// Rule condition types
type ConditionField = 'from' | 'to' | 'subject' | 'body' | 'labels' | 'priority' | 'sender_domain';
type ConditionOperator = 'contains' | 'equals' | 'starts_with' | 'ends_with' | 'matches' | 'greater_than' | 'less_than';

interface RuleCondition {
  field: ConditionField;
  operator: ConditionOperator;
  value: string;
}

// Rule action types
type ActionType = 'assign' | 'label' | 'escalate' | 'archive' | 'notify' | 'forward';

interface RuleAction {
  type: ActionType;
  target?: string; // Team ID, label name, user email, etc.
  params?: Record<string, string>;
}

interface TriageRule {
  id: string;
  name: string;
  description?: string;
  conditions: RuleCondition[];
  condition_logic: 'AND' | 'OR';
  actions: RuleAction[];
  priority: number; // Order of rule evaluation
  enabled: boolean;
  created_at: string;
  updated_at: string;
  stats?: {
    total_matches: number;
    last_matched?: string;
  };
}

interface TriageRulesPanelProps {
  apiBase?: string;
  workspaceId?: string;
  authToken?: string;
  onRuleApplied?: (ruleId: string, emailCount: number) => void;
  onRuleChange?: () => void;
}

const FIELD_OPTIONS: { value: ConditionField; label: string }[] = [
  { value: 'from', label: 'From Address' },
  { value: 'to', label: 'To Address' },
  { value: 'subject', label: 'Subject' },
  { value: 'body', label: 'Body' },
  { value: 'labels', label: 'Labels' },
  { value: 'priority', label: 'AI Priority' },
  { value: 'sender_domain', label: 'Sender Domain' },
];

const OPERATOR_OPTIONS: { value: ConditionOperator; label: string }[] = [
  { value: 'contains', label: 'Contains' },
  { value: 'equals', label: 'Equals' },
  { value: 'starts_with', label: 'Starts with' },
  { value: 'ends_with', label: 'Ends with' },
  { value: 'matches', label: 'Matches (regex)' },
  { value: 'greater_than', label: 'Greater than' },
  { value: 'less_than', label: 'Less than' },
];

const ACTION_OPTIONS: { value: ActionType; label: string; icon: string; needsTarget: boolean }[] = [
  { value: 'assign', label: 'Assign to Team', icon: '👥', needsTarget: true },
  { value: 'label', label: 'Add Label', icon: '🏷️', needsTarget: true },
  { value: 'escalate', label: 'Escalate', icon: '⚡', needsTarget: true },
  { value: 'archive', label: 'Archive', icon: '📦', needsTarget: false },
  { value: 'notify', label: 'Send Notification', icon: '🔔', needsTarget: true },
  { value: 'forward', label: 'Forward To', icon: '➡️', needsTarget: true },
];


export function TriageRulesPanel({
  apiBase,
  workspaceId,
  authToken,
  onRuleApplied,
}: TriageRulesPanelProps) {
  const [rules, setRules] = useState<TriageRule[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [_editingRule, setEditingRule] = useState<TriageRule | null>(null);
  const [expandedRuleId, setExpandedRuleId] = useState<string | null>(null);

  // New rule form state
  const [newRule, setNewRule] = useState<Partial<TriageRule>>({
    name: '',
    description: '',
    conditions: [{ field: 'from', operator: 'contains', value: '' }],
    condition_logic: 'AND',
    actions: [{ type: 'label', target: '' }],
    priority: 5,
    enabled: true,
  });

  const fetchRules = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${apiBase}/api/v1/inbox/routing/rules?workspace_id=${workspaceId}`,
        {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        }
      );

      if (!response.ok) {
        setError(`Failed to load rules: ${response.status}`);
        setRules([]);
        return;
      }

      const data = await response.json();
      setRules(data.rules || []);
      setError(null);
    } catch (err) {
      setError(`Failed to fetch rules: ${err instanceof Error ? err.message : 'Unknown error'}`);
      setRules([]);
    } finally {
      setIsLoading(false);
    }
  }, [apiBase, workspaceId, authToken]);

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  const handleCreateRule = async () => {
    if (!newRule.name || !newRule.conditions?.length || !newRule.actions?.length) {
      setError('Please fill in all required fields');
      return;
    }

    try {
      const response = await fetch(`${apiBase}/api/v1/inbox/routing/rules`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          workspace_id: workspaceId,
          ...newRule,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        setError(`Failed to create rule: ${response.status} ${errorText || response.statusText}`);
        return;
      }

      const data = await response.json();
      setRules([...rules, data.rule]);
      setIsCreating(false);
      resetNewRule();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create rule');
    }
  };

  const handleToggleRule = async (ruleId: string, enabled: boolean) => {
    try {
      const response = await fetch(`${apiBase}/api/v1/inbox/routing/rules/${ruleId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ enabled }),
      });

      if (!response.ok) {
        setError(`Failed to toggle rule: ${response.status} ${response.statusText}`);
        return;
      }

      // Update locally only after successful API call
      setRules(rules.map(r => r.id === ruleId ? { ...r, enabled } : r));
    } catch (error) {
      console.error('Toggle rule failed:', error);
      setError(`Failed to toggle rule: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    if (!confirm('Are you sure you want to delete this rule?')) return;

    try {
      const response = await fetch(`${apiBase}/api/v1/inbox/routing/rules/${ruleId}`, {
        method: 'DELETE',
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });

      if (!response.ok) {
        setError(`Failed to delete rule: ${response.status} ${response.statusText}`);
        return;
      }

      // Update locally only after successful API call
      setRules(rules.filter(r => r.id !== ruleId));
    } catch (error) {
      console.error('Delete rule failed:', error);
      setError(`Failed to delete rule: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  };

  const handleTestRule = async (rule: TriageRule) => {
    try {
      const response = await fetch(`${apiBase}/api/v1/inbox/routing/rules/${rule.id}/test`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ workspace_id: workspaceId }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        setError(`Failed to test rule: ${response.status} ${errorText || response.statusText}`);
        return;
      }

      const data = await response.json();
      alert(`Rule "${rule.name}" matches ${data.match_count} emails`);
      onRuleApplied?.(rule.id, data.match_count);
    } catch (err) {
      alert(`Failed to test rule: ${err instanceof Error ? err.message : 'Unable to connect to server'}`);
    }
  };

  const resetNewRule = () => {
    setNewRule({
      name: '',
      description: '',
      conditions: [{ field: 'from', operator: 'contains', value: '' }],
      condition_logic: 'AND',
      actions: [{ type: 'label', target: '' }],
      priority: 5,
      enabled: true,
    });
  };

  const addCondition = () => {
    setNewRule({
      ...newRule,
      conditions: [
        ...(newRule.conditions || []),
        { field: 'from', operator: 'contains', value: '' },
      ],
    });
  };

  const removeCondition = (index: number) => {
    setNewRule({
      ...newRule,
      conditions: newRule.conditions?.filter((_, i) => i !== index),
    });
  };

  const updateCondition = (index: number, updates: Partial<RuleCondition>) => {
    setNewRule({
      ...newRule,
      conditions: newRule.conditions?.map((c, i) =>
        i === index ? { ...c, ...updates } : c
      ),
    });
  };

  const addAction = () => {
    setNewRule({
      ...newRule,
      actions: [
        ...(newRule.actions || []),
        { type: 'label', target: '' },
      ],
    });
  };

  const removeAction = (index: number) => {
    setNewRule({
      ...newRule,
      actions: newRule.actions?.filter((_, i) => i !== index),
    });
  };

  const updateAction = (index: number, updates: Partial<RuleAction>) => {
    setNewRule({
      ...newRule,
      actions: newRule.actions?.map((a, i) =>
        i === index ? { ...a, ...updates } : a
      ),
    });
  };

  if (isLoading) {
    return (
      <div className="border border-acid-green/30 bg-surface/50 p-4 rounded">
        <h3 className="text-acid-green font-mono text-sm mb-4">Triage Rules</h3>
        <div className="text-center py-8 text-text-muted font-mono text-sm animate-pulse">
          Loading rules...
        </div>
      </div>
    );
  }

  return (
    <div className="border border-acid-green/30 bg-surface/50 p-4 rounded">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-acid-green font-mono text-sm">Triage Rules</h3>
        <button
          onClick={() => setIsCreating(true)}
          className="px-3 py-1 text-xs font-mono bg-acid-green/10 border border-acid-green/40 text-acid-green hover:bg-acid-green/20 rounded"
        >
          + New Rule
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 p-2 bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-mono rounded">
          {error}
        </div>
      )}

      {/* Rule Creation Form */}
      {isCreating && (
        <div className="mb-4 p-4 bg-bg/50 border border-acid-green/20 rounded">
          <div className="flex justify-between items-center mb-4">
            <span className="text-acid-green font-mono text-sm">Create New Rule</span>
            <button
              onClick={() => {
                setIsCreating(false);
                resetNewRule();
              }}
              className="text-text-muted hover:text-white text-sm"
            >
              x
            </button>
          </div>

          {/* Name & Description */}
          <div className="space-y-3 mb-4">
            <input
              type="text"
              placeholder="Rule name..."
              value={newRule.name || ''}
              onChange={(e) => setNewRule({ ...newRule, name: e.target.value })}
              className="w-full px-3 py-2 text-sm bg-bg border border-acid-green/30 rounded font-mono focus:border-acid-green focus:outline-none"
            />
            <input
              type="text"
              placeholder="Description (optional)..."
              value={newRule.description || ''}
              onChange={(e) => setNewRule({ ...newRule, description: e.target.value })}
              className="w-full px-3 py-2 text-sm bg-bg border border-acid-green/30 rounded font-mono focus:border-acid-green focus:outline-none"
            />
          </div>

          {/* Conditions */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-text-muted text-xs font-mono">CONDITIONS</span>
              <select
                value={newRule.condition_logic || 'AND'}
                onChange={(e) => setNewRule({ ...newRule, condition_logic: e.target.value as 'AND' | 'OR' })}
                className="px-2 py-1 text-xs bg-bg border border-acid-green/30 rounded font-mono"
              >
                <option value="AND">Match ALL</option>
                <option value="OR">Match ANY</option>
              </select>
            </div>
            <div className="space-y-2">
              {newRule.conditions?.map((condition, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <select
                    value={condition.field}
                    onChange={(e) => updateCondition(idx, { field: e.target.value as ConditionField })}
                    className="px-2 py-1 text-xs bg-bg border border-acid-green/30 rounded font-mono"
                  >
                    {FIELD_OPTIONS.map((f) => (
                      <option key={f.value} value={f.value}>{f.label}</option>
                    ))}
                  </select>
                  <select
                    value={condition.operator}
                    onChange={(e) => updateCondition(idx, { operator: e.target.value as ConditionOperator })}
                    className="px-2 py-1 text-xs bg-bg border border-acid-green/30 rounded font-mono"
                  >
                    {OPERATOR_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  <input
                    type="text"
                    value={condition.value}
                    onChange={(e) => updateCondition(idx, { value: e.target.value })}
                    placeholder="Value..."
                    className="flex-1 px-2 py-1 text-xs bg-bg border border-acid-green/30 rounded font-mono"
                  />
                  {(newRule.conditions?.length || 0) > 1 && (
                    <button
                      onClick={() => removeCondition(idx)}
                      className="text-red-400 hover:text-red-300 text-sm"
                    >
                      x
                    </button>
                  )}
                </div>
              ))}
            </div>
            <button
              onClick={addCondition}
              className="mt-2 text-xs text-acid-green hover:text-acid-green/80 font-mono"
            >
              + Add condition
            </button>
          </div>

          {/* Actions */}
          <div className="mb-4">
            <span className="text-text-muted text-xs font-mono block mb-2">ACTIONS</span>
            <div className="space-y-2">
              {newRule.actions?.map((action, idx) => {
                const actionConfig = ACTION_OPTIONS.find(a => a.value === action.type);
                return (
                  <div key={idx} className="flex items-center gap-2">
                    <select
                      value={action.type}
                      onChange={(e) => updateAction(idx, { type: e.target.value as ActionType })}
                      className="px-2 py-1 text-xs bg-bg border border-acid-green/30 rounded font-mono"
                    >
                      {ACTION_OPTIONS.map((a) => (
                        <option key={a.value} value={a.value}>{a.icon} {a.label}</option>
                      ))}
                    </select>
                    {actionConfig?.needsTarget && (
                      <input
                        type="text"
                        value={action.target || ''}
                        onChange={(e) => updateAction(idx, { target: e.target.value })}
                        placeholder="Target..."
                        className="flex-1 px-2 py-1 text-xs bg-bg border border-acid-green/30 rounded font-mono"
                      />
                    )}
                    {(newRule.actions?.length || 0) > 1 && (
                      <button
                        onClick={() => removeAction(idx)}
                        className="text-red-400 hover:text-red-300 text-sm"
                      >
                        x
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            <button
              onClick={addAction}
              className="mt-2 text-xs text-acid-green hover:text-acid-green/80 font-mono"
            >
              + Add action
            </button>
          </div>

          {/* Priority */}
          <div className="mb-4">
            <label className="text-text-muted text-xs font-mono block mb-1">
              PRIORITY (lower = higher priority)
            </label>
            <input
              type="number"
              min="0"
              max="100"
              value={newRule.priority || 5}
              onChange={(e) => setNewRule({ ...newRule, priority: parseInt(e.target.value) || 5 })}
              className="w-20 px-2 py-1 text-xs bg-bg border border-acid-green/30 rounded font-mono"
            />
          </div>

          {/* Submit */}
          <div className="flex gap-2">
            <button
              onClick={handleCreateRule}
              className="px-4 py-2 text-xs font-mono bg-acid-green text-bg hover:bg-acid-green/80 rounded"
            >
              Create Rule
            </button>
            <button
              onClick={() => {
                setIsCreating(false);
                resetNewRule();
              }}
              className="px-4 py-2 text-xs font-mono border border-acid-green/30 text-text-muted hover:text-white rounded"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Rules List */}
      {rules.length === 0 ? (
        <div className="text-center py-8 text-text-muted font-mono text-sm">
          No triage rules configured. Create one to get started.
        </div>
      ) : (
        <div className="space-y-2">
          {rules.sort((a, b) => a.priority - b.priority).map((rule) => (
            <div
              key={rule.id}
              className={`border rounded transition-all ${
                rule.enabled
                  ? 'border-acid-green/30 bg-bg/30'
                  : 'border-gray-600/30 bg-bg/20 opacity-60'
              }`}
            >
              <div
                className="p-3 cursor-pointer"
                onClick={() => setExpandedRuleId(expandedRuleId === rule.id ? null : rule.id)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleToggleRule(rule.id, !rule.enabled);
                      }}
                      className={`w-8 h-4 rounded-full relative transition-colors ${
                        rule.enabled ? 'bg-acid-green' : 'bg-gray-600'
                      }`}
                    >
                      <div
                        className={`absolute w-3 h-3 bg-white rounded-full top-0.5 transition-all ${
                          rule.enabled ? 'left-4' : 'left-0.5'
                        }`}
                      />
                    </button>
                    <div>
                      <div className="text-sm font-mono text-text">{rule.name}</div>
                      {rule.description && (
                        <div className="text-xs text-text-muted">{rule.description}</div>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {rule.stats && (
                      <span className="text-xs text-text-muted font-mono">
                        {rule.stats.total_matches} matches
                      </span>
                    )}
                    <span className="text-xs text-acid-green/60 font-mono">
                      P{rule.priority}
                    </span>
                    <span className="text-text-muted">
                      {expandedRuleId === rule.id ? '▼' : '▶'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Expanded View */}
              {expandedRuleId === rule.id && (
                <div className="border-t border-acid-green/20 p-3 bg-surface/30">
                  {/* Conditions */}
                  <div className="mb-3">
                    <span className="text-text-muted text-xs font-mono block mb-1">
                      CONDITIONS ({rule.condition_logic})
                    </span>
                    <div className="space-y-1">
                      {rule.conditions.map((c, idx) => (
                        <div key={idx} className="text-xs font-mono text-text-muted flex items-center gap-1">
                          <span className="text-acid-green">{c.field}</span>
                          <span>{c.operator}</span>
                          <span className="text-acid-cyan">"{c.value}"</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="mb-3">
                    <span className="text-text-muted text-xs font-mono block mb-1">ACTIONS</span>
                    <div className="flex flex-wrap gap-2">
                      {rule.actions.map((a, idx) => {
                        const config = ACTION_OPTIONS.find(opt => opt.value === a.type);
                        return (
                          <span
                            key={idx}
                            className="px-2 py-1 text-xs bg-acid-green/10 border border-acid-green/30 rounded font-mono"
                          >
                            {config?.icon} {config?.label}
                            {a.target && `: ${a.target}`}
                          </span>
                        );
                      })}
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleTestRule(rule)}
                      className="px-3 py-1 text-xs font-mono bg-acid-cyan/10 border border-acid-cyan/30 text-acid-cyan hover:bg-acid-cyan/20 rounded"
                    >
                      Test Rule
                    </button>
                    <button
                      onClick={() => setEditingRule(rule)}
                      className="px-3 py-1 text-xs font-mono border border-acid-green/30 text-text-muted hover:text-acid-green rounded"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDeleteRule(rule.id)}
                      className="px-3 py-1 text-xs font-mono bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 rounded"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default TriageRulesPanel;
