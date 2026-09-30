'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { PanelTemplate } from '@/components/shared/PanelTemplate';
import { useApi } from '@/hooks/useApi';
import { useBackend } from '@/components/BackendSelector';
import { ConditionListBuilder } from './ConditionBuilder';
import { ActionListBuilder } from './ActionBuilder';
import { type RoutingRule, type Condition, type Action, type EvaluateResponse } from './types';
import { logger } from '@/utils/logger';

export type RulesTab = 'rules' | 'editor' | 'test';

export interface RoutingRulesBuilderProps {
  /** Enable real-time updates */
  enableRealtime?: boolean;
  /** Custom CSS classes */
  className?: string;
}

const DEFAULT_CONDITION: Condition = { field: 'confidence', operator: 'lt', value: 0.7 };

const DEFAULT_ACTION: Action = { type: 'route_to_channel', target: '' };

/**
 * Visual builder for routing rules with IF/THEN logic.
 */
export function RoutingRulesBuilder({
  enableRealtime: _enableRealtime = true,
  className = '',
}: RoutingRulesBuilderProps) {
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  // State
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [templates, setTemplates] = useState<RoutingRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<RulesTab>('rules');
  const [selectedRule, setSelectedRule] = useState<RoutingRule | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Editor state
  const [editorRule, setEditorRule] = useState<Partial<RoutingRule>>({
    name: '',
    description: '',
    conditions: [DEFAULT_CONDITION],
    actions: [DEFAULT_ACTION],
    priority: 0,
    enabled: true,
    match_mode: 'all',
    stop_processing: false,
    tags: [],
  });
  const [saving, setSaving] = useState(false);

  // Test state
  const [testContext, setTestContext] = useState<string>(
    JSON.stringify(
      { confidence: 0.65, topic: 'security review', status: 'completed', agent_count: 3 },
      null,
      2,
    ),
  );
  const [testResults, setTestResults] = useState<EvaluateResponse | null>(null);
  const [testing, setTesting] = useState(false);

  // Load data
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [rulesRes, templatesRes] = await Promise.all([
        api.get('/api/v1/routing-rules').catch(() => ({ rules: [] })) as Promise<{
          rules: RoutingRule[];
        }>,
        api.get('/api/v1/routing-rules/templates').catch(() => ({ templates: [] })) as Promise<{
          templates: RoutingRule[];
        }>,
      ]);

      setRules(rulesRes.rules || []);
      setTemplates(templatesRes.templates || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load rules');

      // Mock data for demo
      setRules([
        {
          id: 'rule-1',
          name: 'Escalate Low Confidence',
          description: 'Escalate decisions with confidence below 70%',
          conditions: [{ field: 'confidence', operator: 'lt', value: 0.7 }],
          actions: [
            { type: 'require_approval', target: 'default' },
            {
              type: 'notify',
              target: 'admin',
              params: { message: 'Low confidence review needed' },
            },
          ],
          priority: 100,
          enabled: true,
          match_mode: 'all',
          tags: ['confidence', 'escalation'],
        },
        {
          id: 'rule-2',
          name: 'Security Topic Routing',
          description: 'Route security-related decisions to security team',
          conditions: [{ field: 'topic', operator: 'contains', value: 'security' }],
          actions: [
            { type: 'route_to_channel', target: 'security-team' },
            { type: 'tag', target: 'security' },
          ],
          priority: 90,
          enabled: true,
          match_mode: 'all',
          tags: ['security', 'routing'],
        },
        {
          id: 'rule-3',
          name: 'High Dissent Alert',
          description: 'Alert when agents have significant disagreement',
          conditions: [{ field: 'dissent_ratio', operator: 'gt', value: 0.3 }],
          actions: [
            { type: 'escalate_to', target: 'team-lead' },
            { type: 'log', params: { level: 'warning', message: 'High dissent detected' } },
          ],
          priority: 80,
          enabled: false,
          match_mode: 'all',
          tags: ['dissent'],
        },
      ]);

      setTemplates([
        {
          id: 'template-1',
          name: 'Low Confidence Escalation',
          description: 'Escalate decisions with confidence below threshold',
          conditions: [{ field: 'confidence', operator: 'lt', value: 0.7 }],
          actions: [{ type: 'require_approval', target: 'default' }],
          priority: 100,
          enabled: true,
          match_mode: 'all',
          tags: ['template', 'confidence'],
        },
        {
          id: 'template-2',
          name: 'Topic-Based Routing',
          description: 'Route decisions based on topic keywords',
          conditions: [{ field: 'topic', operator: 'contains', value: '' }],
          actions: [{ type: 'route_to_channel', target: '' }],
          priority: 50,
          enabled: true,
          match_mode: 'all',
          tags: ['template', 'routing'],
        },
      ]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  // Load on mount
  useEffect(() => {
    loadData();
  }, [loadData]);

  // Filter rules
  const filteredRules = useMemo(() => {
    if (!searchQuery.trim()) return rules;
    const query = searchQuery.toLowerCase();
    return rules.filter(
      (r) =>
        r.name.toLowerCase().includes(query) ||
        r.description?.toLowerCase().includes(query) ||
        r.tags?.some((t) => t.toLowerCase().includes(query)),
    );
  }, [rules, searchQuery]);

  // Handlers
  const handleCreateRule = useCallback(() => {
    setSelectedRule(null);
    setEditorRule({
      name: 'New Rule',
      description: '',
      conditions: [DEFAULT_CONDITION],
      actions: [DEFAULT_ACTION],
      priority: 0,
      enabled: true,
      match_mode: 'all',
      stop_processing: false,
      tags: [],
    });
    setActiveTab('editor');
  }, []);

  const handleEditRule = useCallback((rule: RoutingRule) => {
    setSelectedRule(rule);
    setEditorRule({ ...rule });
    setActiveTab('editor');
  }, []);

  const handleUseTemplate = useCallback((template: RoutingRule) => {
    setSelectedRule(null);
    setEditorRule({ ...template, id: undefined, name: `${template.name} (Copy)` });
    setActiveTab('editor');
  }, []);

  const handleSaveRule = useCallback(async () => {
    if (!editorRule.name) {
      setError('Rule name is required');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      if (selectedRule) {
        await api.put(`/api/v1/routing-rules/${selectedRule.id}`, editorRule);
      } else {
        await api.post('/api/v1/routing-rules', editorRule);
      }
      await loadData();
      setActiveTab('rules');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save rule');
    } finally {
      setSaving(false);
    }
  }, [api, editorRule, loadData, selectedRule]);

  const handleDeleteRule = useCallback(
    async (ruleId: string) => {
      if (!confirm('Delete this rule?')) return;

      try {
        await api.delete(`/api/v1/routing-rules/${ruleId}`);
        await loadData();
      } catch (err) {
        logger.error('Failed to delete rule:', err);
      }
    },
    [api, loadData],
  );

  const handleToggleRule = useCallback(
    async (rule: RoutingRule) => {
      try {
        await api.post(`/api/v1/routing-rules/${rule.id}/toggle`, { enabled: !rule.enabled });
        await loadData();
      } catch (err) {
        logger.error('Failed to toggle rule:', err);
      }
    },
    [api, loadData],
  );

  const handleTestRules = useCallback(async () => {
    setTesting(true);
    setTestResults(null);

    try {
      const context = JSON.parse(testContext);
      const result = (await api.post('/api/v1/routing-rules/evaluate', {
        context,
      })) as EvaluateResponse;
      setTestResults(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to evaluate rules');
    } finally {
      setTesting(false);
    }
  }, [api, testContext]);

  const tabs = [
    { id: 'rules' as RulesTab, label: 'Rules' },
    { id: 'editor' as RulesTab, label: 'Editor' },
    { id: 'test' as RulesTab, label: 'Test' },
  ];

  return (
    <PanelTemplate
      title="Routing Rules"
      icon="🔀"
      loading={loading}
      error={error}
      onRefresh={loadData}
      className={className}
    >
      {/* Tabs */}
      <div className="flex gap-1 mb-4 p-1 bg-surface rounded">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 px-4 py-2 text-sm font-theme-data rounded transition-colors ${
              activeTab === tab.id
                ? 'bg-[var(--accent)] text-bg'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Rules Tab */}
      {activeTab === 'rules' && (
        <>
          {/* Search and Create */}
          <div className="flex items-center gap-3 mb-4">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search rules..."
              className="flex-1 px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
            />
            <button
              onClick={handleCreateRule}
              className="px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors"
            >
              + New Rule
            </button>
          </div>

          {/* Rules List */}
          <div className="space-y-3">
            {filteredRules.length === 0 ? (
              <div className="card p-8 text-center">
                <div className="text-4xl mb-2">📋</div>
                <p className="text-text-muted">No routing rules yet</p>
                <button
                  onClick={handleCreateRule}
                  className="mt-4 px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors"
                >
                  Create Your First Rule
                </button>
              </div>
            ) : (
              filteredRules.map((rule) => (
                <div
                  key={rule.id}
                  className={`card p-4 cursor-pointer hover:border-[var(--accent)]/50 transition-colors ${
                    !rule.enabled ? 'opacity-60' : ''
                  }`}
                  onClick={() => handleEditRule(rule)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-theme-data font-bold">{rule.name}</h3>
                        <span
                          className={`px-2 py-0.5 text-xs rounded ${
                            rule.enabled
                              ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                              : 'bg-surface text-text-muted'
                          }`}
                        >
                          {rule.enabled ? 'Active' : 'Disabled'}
                        </span>
                        <span className="px-2 py-0.5 text-xs bg-surface text-text-muted rounded">
                          Priority: {rule.priority}
                        </span>
                      </div>
                      <p className="text-sm text-text-muted mb-2">{rule.description}</p>
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-cyan-400">
                          {rule.conditions.length} condition
                          {rule.conditions.length !== 1 ? 's' : ''}
                        </span>
                        <span className="text-text-muted">→</span>
                        <span className="text-[var(--accent)]">
                          {rule.actions.length} action{rule.actions.length !== 1 ? 's' : ''}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleToggleRule(rule);
                        }}
                        className={`p-2 rounded transition-colors ${
                          rule.enabled
                            ? 'bg-[var(--accent)]/20 text-[var(--accent)] hover:bg-[var(--accent)]/30'
                            : 'bg-surface text-text-muted hover:bg-surface-alt'
                        }`}
                        title={rule.enabled ? 'Disable rule' : 'Enable rule'}
                      >
                        {rule.enabled ? '✓' : '○'}
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteRule(rule.id);
                        }}
                        className="p-2 text-red-400 hover:bg-red-400/20 rounded transition-colors"
                        title="Delete rule"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Templates Section */}
          {templates.length > 0 && (
            <div className="mt-6">
              <h3 className="font-theme-data text-sm mb-3 text-text-muted">Templates</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {templates.map((template) => (
                  <button
                    key={template.id}
                    onClick={() => handleUseTemplate(template)}
                    className="card p-3 text-left hover:border-[var(--accent)]/50 transition-colors"
                  >
                    <div className="font-theme-data text-sm font-bold mb-1">{template.name}</div>
                    <p className="text-xs text-text-muted">{template.description}</p>
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Editor Tab */}
      {activeTab === 'editor' && (
        <div className="space-y-6">
          {/* Rule Metadata */}
          <div className="card p-4 space-y-4">
            <div>
              <label className="block text-sm font-theme-data mb-1">Rule Name</label>
              <input
                type="text"
                value={editorRule.name || ''}
                onChange={(e) => setEditorRule({ ...editorRule, name: e.target.value })}
                placeholder="Enter rule name..."
                className="w-full px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-theme-data mb-1">Description</label>
              <textarea
                value={editorRule.description || ''}
                onChange={(e) => setEditorRule({ ...editorRule, description: e.target.value })}
                placeholder="What does this rule do?"
                rows={2}
                className="w-full px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none resize-none"
              />
            </div>
            <div className="flex items-center gap-4">
              <div className="flex-1">
                <label className="block text-sm font-theme-data mb-1">Priority</label>
                <input
                  type="number"
                  value={editorRule.priority || 0}
                  onChange={(e) =>
                    setEditorRule({ ...editorRule, priority: parseInt(e.target.value) || 0 })
                  }
                  className="w-full px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm font-theme-data">Enabled</label>
                <button
                  onClick={() => setEditorRule({ ...editorRule, enabled: !editorRule.enabled })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${
                    editorRule.enabled ? 'bg-[var(--accent)]' : 'bg-surface-alt'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                      editorRule.enabled ? 'left-5' : 'left-0.5'
                    }`}
                  />
                </button>
              </div>
            </div>
          </div>

          {/* Conditions */}
          <div className="card p-4">
            <ConditionListBuilder
              conditions={editorRule.conditions || [DEFAULT_CONDITION]}
              matchMode={editorRule.match_mode || 'all'}
              onChange={(conditions) => setEditorRule({ ...editorRule, conditions })}
              onMatchModeChange={(match_mode) => setEditorRule({ ...editorRule, match_mode })}
            />
          </div>

          {/* Actions */}
          <div className="card p-4">
            <ActionListBuilder
              actions={editorRule.actions || [DEFAULT_ACTION]}
              onChange={(actions) => setEditorRule({ ...editorRule, actions })}
            />
          </div>

          {/* Save/Cancel */}
          <div className="flex items-center justify-end gap-3">
            <button
              onClick={() => setActiveTab('rules')}
              className="px-4 py-2 text-sm font-theme-data text-text-muted hover:text-text transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSaveRule}
              disabled={saving}
              className="px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
            >
              {saving ? 'Saving...' : selectedRule ? 'Update Rule' : 'Create Rule'}
            </button>
          </div>
        </div>
      )}

      {/* Test Tab */}
      {activeTab === 'test' && (
        <div className="space-y-4">
          <div className="card p-4">
            <label className="block text-sm font-theme-data mb-2">Test Context (JSON)</label>
            <textarea
              value={testContext}
              onChange={(e) => setTestContext(e.target.value)}
              rows={8}
              className="w-full px-3 py-2 text-sm font-theme-data bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none resize-none"
              placeholder='{"confidence": 0.65, "topic": "security"}'
            />
            <button
              onClick={handleTestRules}
              disabled={testing}
              className="mt-3 px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
            >
              {testing ? 'Evaluating...' : 'Evaluate Rules'}
            </button>
          </div>

          {testResults && (
            <div className="card p-4">
              <h3 className="font-theme-data text-sm mb-3">Results</h3>
              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="bg-surface rounded p-3 text-center">
                  <div className="text-xl font-theme-data font-bold text-text">
                    {testResults.rules_evaluated}
                  </div>
                  <div className="text-xs text-text-muted">Evaluated</div>
                </div>
                <div className="bg-surface rounded p-3 text-center">
                  <div className="text-xl font-theme-data font-bold text-[var(--accent)]">
                    {testResults.rules_matched}
                  </div>
                  <div className="text-xs text-text-muted">Matched</div>
                </div>
                <div className="bg-surface rounded p-3 text-center">
                  <div className="text-xl font-theme-data font-bold text-cyan-400">
                    {testResults.matching_actions.length}
                  </div>
                  <div className="text-xs text-text-muted">Actions</div>
                </div>
              </div>

              <div className="space-y-2">
                {testResults.results.map((result) => (
                  <div
                    key={result.rule_id}
                    className={`p-3 rounded ${
                      result.matched
                        ? 'bg-[var(--accent)]/10 border border-[var(--accent)]/30'
                        : 'bg-surface'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-theme-data text-sm">{result.rule_name}</span>
                      <span
                        className={`px-2 py-0.5 text-xs rounded ${
                          result.matched
                            ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                            : 'bg-surface-alt text-text-muted'
                        }`}
                      >
                        {result.matched ? 'MATCHED' : 'No Match'}
                      </span>
                    </div>
                    {result.matched && result.actions.length > 0 && (
                      <div className="mt-2 text-xs text-text-muted">
                        Actions: {result.actions.map((a) => a.type).join(', ')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </PanelTemplate>
  );
}

export default RoutingRulesBuilder;
