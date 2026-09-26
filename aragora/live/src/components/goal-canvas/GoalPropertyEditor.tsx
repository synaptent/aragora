'use client';

import {
  GOAL_NODE_CONFIGS,
  type GoalNodeData,
  type GoalNodeType,
  type GoalPriority,
} from './types';

interface GoalPropertyEditorProps {
  data: GoalNodeData | null;
  onChange: (updates: Partial<GoalNodeData>) => void;
  onAdvance?: () => void;
  onDelete?: () => void;
}

const goalTypeOptions: GoalNodeType[] = [
  'goal',
  'principle',
  'strategy',
  'milestone',
  'metric',
  'risk',
];
const priorityOptions: GoalPriority[] = ['critical', 'high', 'medium', 'low'];

/**
 * Right sidebar for editing selected goal node properties.
 */
export function GoalPropertyEditor({
  data,
  onChange,
  onAdvance,
  onDelete,
}: GoalPropertyEditorProps) {
  if (!data) {
    return (
      <div className="w-64 border-l border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-sm text-text-muted text-center mt-8">
          Select a goal node to edit its properties.
        </p>
      </div>
    );
  }

  return (
    <div className="w-64 border-l border-[var(--border)] bg-[var(--surface)] p-4 overflow-y-auto space-y-4">
      <h3 className="text-xs font-theme-data uppercase text-text-muted tracking-wider">
        Goal Properties
      </h3>

      {/* Goal Type */}
      <div>
        <label className="block text-xs text-text-muted mb-1">Type</label>
        <select
          value={data.goalType}
          onChange={(e) => onChange({ goalType: e.target.value as GoalNodeType })}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        >
          {goalTypeOptions.map((t) => (
            <option key={t} value={t}>
              {GOAL_NODE_CONFIGS[t].label}
            </option>
          ))}
        </select>
      </div>

      {/* Priority */}
      <div>
        <label className="block text-xs text-text-muted mb-1">Priority</label>
        <select
          value={data.priority}
          onChange={(e) => onChange({ priority: e.target.value as GoalPriority })}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        >
          {priorityOptions.map((p) => (
            <option key={p} value={p}>
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </option>
          ))}
        </select>
      </div>

      {/* Label */}
      <div>
        <label className="block text-xs text-text-muted mb-1">Title</label>
        <input
          type="text"
          value={data.label}
          onChange={(e) => onChange({ label: e.target.value })}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        />
      </div>

      {/* Description */}
      <div>
        <label className="block text-xs text-text-muted mb-1">Description</label>
        <textarea
          value={data.description}
          onChange={(e) => onChange({ description: e.target.value })}
          rows={3}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text resize-none"
        />
      </div>

      {/* Measurable */}
      <div>
        <label className="block text-xs text-text-muted mb-1">Success Criteria</label>
        <input
          type="text"
          value={data.measurable}
          onChange={(e) => onChange({ measurable: e.target.value })}
          placeholder="How to measure success..."
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm text-text"
        />
      </div>

      {/* Confidence */}
      <div>
        <label className="block text-xs text-text-muted mb-1">
          Confidence: {Math.round(data.confidence * 100)}%
        </label>
        <input
          type="range"
          min={0}
          max={100}
          value={Math.round(data.confidence * 100)}
          onChange={(e) => onChange({ confidence: parseInt(e.target.value) / 100 })}
          className="w-full accent-emerald-500"
        />
      </div>

      {/* Tags */}
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

      {/* Source ideas info */}
      {data.sourceIdeaIds && data.sourceIdeaIds.length > 0 && (
        <div className="text-xs text-text-muted">
          Derived from {data.sourceIdeaIds.length} idea(s)
        </div>
      )}

      {/* Actions */}
      <div className="pt-2 space-y-2 border-t border-[var(--border)]">
        {onAdvance && (
          <button
            onClick={onAdvance}
            className="w-full px-3 py-1.5 text-xs font-theme-data rounded bg-amber-500/20 border border-amber-500 text-amber-200 hover:bg-amber-500/30 transition-colors"
          >
            Advance to Actions
          </button>
        )}
        {onDelete && (
          <button
            onClick={onDelete}
            className="w-full px-3 py-1.5 text-xs font-theme-data rounded bg-red-500/20 border border-red-500 text-red-200 hover:bg-red-500/30 transition-colors"
          >
            Delete Goal
          </button>
        )}
      </div>
    </div>
  );
}

export default GoalPropertyEditor;
