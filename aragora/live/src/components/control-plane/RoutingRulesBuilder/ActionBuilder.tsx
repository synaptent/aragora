'use client';

import { useCallback } from 'react';
import { type Action, type ActionType, ACTION_CONFIGS } from './types';

export interface ActionBuilderProps {
  action: Action;
  index: number;
  onChange: (index: number, action: Action) => void;
  onRemove: (index: number) => void;
  isOnly?: boolean;
}

/**
 * Builder component for a single action.
 */
export function ActionBuilder({
  action,
  index,
  onChange,
  onRemove,
  isOnly = false,
}: ActionBuilderProps) {
  const config = ACTION_CONFIGS[action.type];

  const handleTypeChange = useCallback(
    (type: ActionType) => {
      const newConfig = ACTION_CONFIGS[type];
      onChange(index, { type, target: newConfig.requiresTarget ? '' : undefined, params: {} });
    },
    [index, onChange],
  );

  const handleTargetChange = useCallback(
    (target: string) => {
      onChange(index, { ...action, target });
    },
    [action, index, onChange],
  );

  const handleParamChange = useCallback(
    (key: string, value: string | number) => {
      onChange(index, { ...action, params: { ...action.params, [key]: value } });
    },
    [action, index, onChange],
  );

  return (
    <div className="p-3 bg-surface rounded group">
      <div className="flex items-start gap-2">
        {/* Icon */}
        <span className="text-lg mt-1">{config.icon}</span>

        {/* Main content */}
        <div className="flex-1 space-y-2">
          {/* Action type selector */}
          <div className="flex items-center gap-2">
            <select
              value={action.type}
              onChange={(e) => handleTypeChange(e.target.value as ActionType)}
              className="px-2 py-1.5 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none min-w-[160px]"
            >
              {Object.entries(ACTION_CONFIGS).map(([type, cfg]) => (
                <option key={type} value={type}>
                  {cfg.label}
                </option>
              ))}
            </select>
            <span className="text-xs text-text-muted">{config.description}</span>
          </div>

          {/* Target field */}
          {config.requiresTarget && (
            <div>
              <label className="block text-xs text-text-muted mb-1">{config.targetLabel}</label>
              <input
                type="text"
                value={action.target || ''}
                onChange={(e) => handleTargetChange(e.target.value)}
                placeholder={config.targetPlaceholder}
                className="w-full px-2 py-1.5 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
          )}

          {/* Additional param fields */}
          {config.paramFields?.map((field) => (
            <div key={field.key}>
              <label className="block text-xs text-text-muted mb-1">{field.label}</label>
              {field.type === 'select' ? (
                <select
                  value={(action.params?.[field.key] as string) || ''}
                  onChange={(e) => handleParamChange(field.key, e.target.value)}
                  className="w-full px-2 py-1.5 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none"
                >
                  <option value="">Select...</option>
                  {field.options?.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.type}
                  value={(action.params?.[field.key] as string | number) || ''}
                  onChange={(e) =>
                    handleParamChange(
                      field.key,
                      field.type === 'number' ? parseFloat(e.target.value) || 0 : e.target.value,
                    )
                  }
                  className="w-full px-2 py-1.5 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none"
                />
              )}
            </div>
          ))}
        </div>

        {/* Remove Button */}
        <button
          onClick={() => onRemove(index)}
          disabled={isOnly}
          className={`p-1.5 text-sm rounded transition-colors ${
            isOnly
              ? 'text-text-muted cursor-not-allowed'
              : 'text-red-400 hover:bg-red-400/20 opacity-0 group-hover:opacity-100'
          }`}
          title={isOnly ? 'At least one action required' : 'Remove action'}
        >
          ✕
        </button>
      </div>
    </div>
  );
}

export interface ActionListBuilderProps {
  actions: Action[];
  onChange: (actions: Action[]) => void;
}

/**
 * Builder for a list of actions.
 */
export function ActionListBuilder({ actions, onChange }: ActionListBuilderProps) {
  const handleActionChange = useCallback(
    (index: number, action: Action) => {
      const newActions = [...actions];
      newActions[index] = action;
      onChange(newActions);
    },
    [actions, onChange],
  );

  const handleActionRemove = useCallback(
    (index: number) => {
      if (actions.length <= 1) return;
      const newActions = actions.filter((_, i) => i !== index);
      onChange(newActions);
    },
    [actions, onChange],
  );

  const handleAddAction = useCallback(() => {
    const newAction: Action = { type: 'route_to_channel', target: '' };
    onChange([...actions, newAction]);
  }, [actions, onChange]);

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-sm font-theme-data text-[var(--accent)]">THEN</span>
        <button
          onClick={handleAddAction}
          className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] rounded hover:bg-[var(--accent)]/30 transition-colors"
        >
          + Add Action
        </button>
      </div>

      {/* Actions List */}
      <div className="space-y-2">
        {actions.map((action, index) => (
          <div key={index}>
            {index > 0 && <div className="text-xs text-text-muted text-center py-1">ALSO</div>}
            <ActionBuilder
              action={action}
              index={index}
              onChange={handleActionChange}
              onRemove={handleActionRemove}
              isOnly={actions.length === 1}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

export default ActionBuilder;
