'use client';

import {
  ACTION_NODE_CONFIGS,
  type ActionNodeData,
  type ActionNodeType,
  type ActionStatus,
} from './types';

interface ActionPropertyEditorProps {
  data: ActionNodeData | null;
  onChange: (updates: Partial<ActionNodeData>) => void;
  onAdvance?: () => void;
  onDelete?: () => void;
  advancing?: boolean;
}

const actionTypeOptions: ActionNodeType[] = [
  'task',
  'epic',
  'checkpoint',
  'deliverable',
  'dependency',
];
const statusOptions: ActionStatus[] = ['pending', 'in_progress', 'completed', 'blocked'];

export function ActionPropertyEditor({
  data,
  onChange,
  onAdvance,
  onDelete,
  advancing,
}: ActionPropertyEditorProps) {
  if (!data) {
    return (
      <div className="w-64 border-l border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-sm text-text-muted text-center mt-8">
          Select an action node to edit its properties.
        </p>
      </div>
    );
  }

  return (
    <div className="w-64 border-l border-[var(--border)] bg-[var(--surface)] p-4 overflow-y-auto space-y-4">
      <h3 className="text-xs font-theme-data uppercase text-text-muted tracking-wider">
        Action Properties
      </h3>

      <div>
        <label className="block text-xs text-text-muted mb-1">Type</label>
        <select
          value={data.actionType}
          onChange={(e) => onChange({ actionType: e.target.value as ActionNodeType })}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        >
          {actionTypeOptions.map((t) => (
            <option key={t} value={t}>
              {ACTION_NODE_CONFIGS[t].label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs text-text-muted mb-1">Status</label>
        <select
          value={data.status}
          onChange={(e) => onChange({ status: e.target.value as ActionStatus })}
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
        <label className="block text-xs text-text-muted mb-1">Assignee</label>
        <input
          type="text"
          value={data.assignee}
          onChange={(e) => onChange({ assignee: e.target.value })}
          placeholder="Who is responsible..."
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        />
      </div>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={data.optional}
          onChange={(e) => onChange({ optional: e.target.checked })}
          className="accent-amber-500"
        />
        <label className="text-xs text-text-muted">Optional</label>
      </div>

      <div>
        <label className="block text-xs text-text-muted mb-1">
          Timeout: {data.timeoutSeconds || 0}s
        </label>
        <input
          type="number"
          min={0}
          value={data.timeoutSeconds || 0}
          onChange={(e) => onChange({ timeoutSeconds: parseInt(e.target.value) || 0 })}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        />
      </div>

      <div>
        <label className="block text-xs text-text-muted mb-1">Tags</label>
        <input
          type="text"
          value={(data.tags || []).join(', ')}
          onChange={(e) =>
            onChange({
              tags: e.target.value
                .split(',')
                .map((t) => t.trim())
                .filter(Boolean),
            })
          }
          placeholder="tag1, tag2, ..."
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        />
      </div>

      {data.sourceGoalIds && data.sourceGoalIds.length > 0 && (
        <div className="text-xs text-text-muted">
          Derived from {data.sourceGoalIds.length} goal(s)
        </div>
      )}

      <div className="pt-2 space-y-2 border-t border-[var(--border)]">
        {onAdvance && (
          <button
            onClick={onAdvance}
            disabled={advancing}
            className="w-full px-3 py-1.5 text-xs font-theme-data rounded bg-pink-500/20 border border-pink-500 text-pink-200 hover:bg-pink-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {advancing ? 'Advancing...' : 'Advance to Orchestration \u2192'}
          </button>
        )}
        {onDelete && (
          <button
            onClick={onDelete}
            className="w-full px-3 py-1.5 text-xs font-theme-data rounded bg-red-500/20 border border-red-500 text-red-200 hover:bg-red-500/30 transition-colors"
          >
            Delete Action
          </button>
        )}
      </div>
    </div>
  );
}

export default ActionPropertyEditor;
