'use client';

import { IDEA_NODE_CONFIGS, type IdeaNodeType, type IdeaNodeData } from './types';

interface IdeaPropertyEditorProps {
  data: IdeaNodeData | null;
  onChange: (updates: Partial<IdeaNodeData>) => void;
  onPromote: () => void;
  onDelete: () => void;
}

/**
 * Right sidebar for editing the selected idea node's properties.
 */
export function IdeaPropertyEditor({
  data,
  onChange,
  onPromote,
  onDelete,
}: IdeaPropertyEditorProps) {
  if (!data) {
    return (
      <div className="w-72 flex-shrink-0 border-l border-[var(--border)] bg-[var(--bg)] p-4">
        <p className="text-xs text-[var(--text-muted)] font-theme-data">
          Select a node to edit its properties
        </p>
      </div>
    );
  }

  const config = IDEA_NODE_CONFIGS[data.ideaType] || IDEA_NODE_CONFIGS.concept;

  return (
    <div className="w-72 flex-shrink-0 border-l border-[var(--border)] bg-[var(--bg)] p-4 overflow-y-auto font-theme-data">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <span className={`text-sm ${config.borderColor.replace('border-', 'text-')}`}>
          {config.icon}
        </span>
        <h3 className="text-sm font-bold text-[var(--text)]">{config.label}</h3>
      </div>

      {/* Label */}
      <div className="mb-3">
        <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
          Label
        </label>
        <input
          type="text"
          value={data.label}
          onChange={(e) => onChange({ label: e.target.value })}
          className="w-full mt-1 px-2 py-1 text-xs bg-[var(--surface)] border border-[var(--border)] rounded text-[var(--text)]"
        />
      </div>

      {/* Body */}
      <div className="mb-3">
        <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
          Body
        </label>
        <textarea
          value={data.body}
          onChange={(e) => onChange({ body: e.target.value })}
          rows={4}
          className="w-full mt-1 px-2 py-1 text-xs bg-[var(--surface)] border border-[var(--border)] rounded text-[var(--text)] resize-y"
        />
      </div>

      {/* Idea Type */}
      <div className="mb-3">
        <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
          Type
        </label>
        <select
          value={data.ideaType}
          onChange={(e) => onChange({ ideaType: e.target.value as IdeaNodeType })}
          className="w-full mt-1 px-2 py-1 text-xs bg-[var(--surface)] border border-[var(--border)] rounded text-[var(--text)]"
        >
          {Object.entries(IDEA_NODE_CONFIGS).map(([type, cfg]) => (
            <option key={type} value={type}>
              {cfg.icon} {cfg.label}
            </option>
          ))}
        </select>
      </div>

      {/* Confidence */}
      <div className="mb-3">
        <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
          Confidence: {Math.round(data.confidence * 100)}%
        </label>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={data.confidence}
          onChange={(e) => onChange({ confidence: parseFloat(e.target.value) })}
          className="w-full mt-1"
        />
      </div>

      {/* Tags */}
      <div className="mb-3">
        <label className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
          Tags (comma-separated)
        </label>
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
          className="w-full mt-1 px-2 py-1 text-xs bg-[var(--surface)] border border-[var(--border)] rounded text-[var(--text)]"
        />
      </div>

      {/* KM link */}
      {data.kmNodeId && (
        <div className="mb-3 text-[10px] text-[var(--text-muted)]">KM: {data.kmNodeId}</div>
      )}

      {/* Actions */}
      <div className="space-y-2 mt-4 pt-4 border-t border-[var(--border)]">
        {!data.promotedToGoalId && (
          <button
            onClick={onPromote}
            className="w-full px-3 py-1.5 text-xs rounded bg-emerald-500/20 border border-emerald-500 text-emerald-400 hover:bg-emerald-500/30 transition-colors"
          >
            Promote to Goal
          </button>
        )}
        {data.promotedToGoalId && (
          <div className="text-[10px] text-emerald-400">Promoted to goal</div>
        )}
        <button
          onClick={onDelete}
          className="w-full px-3 py-1.5 text-xs rounded bg-red-500/20 border border-red-500 text-red-400 hover:bg-red-500/30 transition-colors"
        >
          Delete Node
        </button>
      </div>
    </div>
  );
}

export default IdeaPropertyEditor;
