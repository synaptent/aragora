'use client';

import { ORCH_NODE_CONFIGS, type OrchNodeData, type OrchNodeType, type OrchStatus } from './types';

interface OrchPropertyEditorProps {
  data: OrchNodeData | null;
  onChange: (updates: Partial<OrchNodeData>) => void;
  onExecute?: () => void;
  onDelete?: () => void;
}

const orchTypeOptions: OrchNodeType[] = [
  'agent_task',
  'debate',
  'human_gate',
  'parallel_fan',
  'merge',
  'verification',
];
const statusOptions: OrchStatus[] = ['pending', 'running', 'completed', 'failed', 'awaiting_human'];

export function OrchPropertyEditor({
  data,
  onChange,
  onExecute,
  onDelete,
}: OrchPropertyEditorProps) {
  if (!data) {
    return (
      <div className="w-64 border-l border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-sm text-text-muted text-center mt-8">
          Select an orchestration node to edit its properties.
        </p>
      </div>
    );
  }

  return (
    <div className="w-64 border-l border-[var(--border)] bg-[var(--surface)] p-4 overflow-y-auto space-y-4">
      <h3 className="text-xs font-theme-data uppercase text-text-muted tracking-wider">
        Orchestration Properties
      </h3>

      <div>
        <label className="block text-xs text-text-muted mb-1">Type</label>
        <select
          value={data.orchType}
          onChange={(e) => onChange({ orchType: e.target.value as OrchNodeType })}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        >
          {orchTypeOptions.map((t) => (
            <option key={t} value={t}>
              {ORCH_NODE_CONFIGS[t].label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs text-text-muted mb-1">Status</label>
        <select
          value={data.status}
          onChange={(e) => onChange({ status: e.target.value as OrchStatus })}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        >
          {statusOptions.map((s) => (
            <option key={s} value={s}>
              {s.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs text-text-muted mb-1">Title</label>
        <input
          type="text"
          value={data.label}
          onChange={(e) => onChange({ label: e.target.value })}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        />
      </div>

      <div>
        <label className="block text-xs text-text-muted mb-1">Description</label>
        <textarea
          value={data.description}
          onChange={(e) => onChange({ description: e.target.value })}
          rows={3}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text resize-none"
        />
      </div>

      <div>
        <label className="block text-xs text-text-muted mb-1">Assigned Agent</label>
        <input
          type="text"
          value={data.assignedAgent}
          onChange={(e) => onChange({ assignedAgent: e.target.value })}
          placeholder="e.g. claude, gpt-4, gemini..."
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        />
      </div>

      <div>
        <label className="block text-xs text-text-muted mb-1">Agent Type</label>
        <input
          type="text"
          value={data.agentType}
          onChange={(e) => onChange({ agentType: e.target.value })}
          placeholder="e.g. analyst, coder, reviewer..."
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        />
      </div>

      <div>
        <label className="block text-xs text-text-muted mb-1">Capabilities</label>
        <input
          type="text"
          value={(data.capabilities || []).join(', ')}
          onChange={(e) =>
            onChange({
              capabilities: e.target.value
                .split(',')
                .map((t) => t.trim())
                .filter(Boolean),
            })
          }
          placeholder="reasoning, code, analysis..."
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        />
      </div>

      {data.sourceActionIds && data.sourceActionIds.length > 0 && (
        <div className="text-xs text-text-muted">
          Derived from {data.sourceActionIds.length} action(s)
        </div>
      )}

      <div className="pt-2 space-y-2 border-t border-[var(--border)]">
        {onExecute && (
          <button
            onClick={onExecute}
            className="w-full px-3 py-1.5 text-xs font-theme-data rounded bg-pink-500/20 border border-pink-500 text-pink-200 hover:bg-pink-500/30 transition-colors"
          >
            Execute Pipeline
          </button>
        )}
        {onDelete && (
          <button
            onClick={onDelete}
            className="w-full px-3 py-1.5 text-xs font-theme-data rounded bg-red-500/20 border border-red-500 text-red-200 hover:bg-red-500/30 transition-colors"
          >
            Delete Node
          </button>
        )}
      </div>
    </div>
  );
}

export default OrchPropertyEditor;
