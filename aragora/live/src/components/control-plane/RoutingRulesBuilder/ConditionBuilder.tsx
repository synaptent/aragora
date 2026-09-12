'use client';

import { useCallback } from 'react';
import {
  type Condition,
  type ConditionOperator,
  CONDITION_FIELDS,
  OPERATORS_BY_TYPE,
} from './types';

export interface ConditionBuilderProps {
  condition: Condition;
  index: number;
  onChange: (index: number, condition: Condition) => void;
  onRemove: (index: number) => void;
  isOnly?: boolean;
}

/**
 * Builder component for a single condition.
 */
export function ConditionBuilder({
  condition,
  index,
  onChange,
  onRemove,
  isOnly = false,
}: ConditionBuilderProps) {
  const fieldConfig = CONDITION_FIELDS.find((f) => f.value === condition.field);
  const fieldType = fieldConfig?.type || 'string';
  const operators = OPERATORS_BY_TYPE[fieldType] || OPERATORS_BY_TYPE.string;

  const handleFieldChange = useCallback(
    (field: string) => {
      const newFieldConfig = CONDITION_FIELDS.find((f) => f.value === field);
      const newType = newFieldConfig?.type || 'string';
      const newOperators = OPERATORS_BY_TYPE[newType];
      const currentOpValid = newOperators.some((o) => o.value === condition.operator);

      onChange(index, {
        ...condition,
        field,
        operator: currentOpValid ? condition.operator : newOperators[0].value,
        value: newType === 'number' ? 0 : '',
      });
    },
    [condition, index, onChange],
  );

  const handleOperatorChange = useCallback(
    (operator: ConditionOperator) => {
      onChange(index, { ...condition, operator });
    },
    [condition, index, onChange],
  );

  const handleValueChange = useCallback(
    (value: string) => {
      const parsedValue = fieldType === 'number' ? parseFloat(value) || 0 : value;
      onChange(index, { ...condition, value: parsedValue });
    },
    [condition, fieldType, index, onChange],
  );

  const isValueRequired = condition.operator !== 'exists' && condition.operator !== 'not_exists';

  return (
    <div className="flex items-center gap-2 p-3 bg-surface rounded group">
      {/* Field Selector */}
      <select
        value={condition.field}
        onChange={(e) => handleFieldChange(e.target.value)}
        className="px-2 py-1.5 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none min-w-[140px]"
      >
        {CONDITION_FIELDS.map((field) => (
          <option key={field.value} value={field.value}>
            {field.label}
          </option>
        ))}
      </select>

      {/* Operator Selector */}
      <select
        value={condition.operator}
        onChange={(e) => handleOperatorChange(e.target.value as ConditionOperator)}
        className="px-2 py-1.5 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none min-w-[140px]"
      >
        {operators.map((op) => (
          <option key={op.value} value={op.value}>
            {op.label}
          </option>
        ))}
      </select>

      {/* Value Input */}
      {isValueRequired && (
        <input
          type={fieldType === 'number' ? 'number' : 'text'}
          value={condition.value as string | number}
          onChange={(e) => handleValueChange(e.target.value)}
          placeholder={fieldType === 'number' ? '0' : 'value'}
          step={fieldType === 'number' ? '0.01' : undefined}
          className="flex-1 px-2 py-1.5 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none min-w-[100px]"
        />
      )}

      {/* Remove Button */}
      <button
        onClick={() => onRemove(index)}
        disabled={isOnly}
        className={`p-1.5 text-sm rounded transition-colors ${
          isOnly
            ? 'text-text-muted cursor-not-allowed'
            : 'text-red-400 hover:bg-red-400/20 opacity-0 group-hover:opacity-100'
        }`}
        title={isOnly ? 'At least one condition required' : 'Remove condition'}
      >
        ✕
      </button>
    </div>
  );
}

export interface ConditionListBuilderProps {
  conditions: Condition[];
  matchMode: 'all' | 'any';
  onChange: (conditions: Condition[]) => void;
  onMatchModeChange: (mode: 'all' | 'any') => void;
}

/**
 * Builder for a list of conditions with match mode selector.
 */
export function ConditionListBuilder({
  conditions,
  matchMode,
  onChange,
  onMatchModeChange,
}: ConditionListBuilderProps) {
  const handleConditionChange = useCallback(
    (index: number, condition: Condition) => {
      const newConditions = [...conditions];
      newConditions[index] = condition;
      onChange(newConditions);
    },
    [conditions, onChange],
  );

  const handleConditionRemove = useCallback(
    (index: number) => {
      if (conditions.length <= 1) return;
      const newConditions = conditions.filter((_, i) => i !== index);
      onChange(newConditions);
    },
    [conditions, onChange],
  );

  const handleAddCondition = useCallback(() => {
    const newCondition: Condition = { field: 'confidence', operator: 'lt', value: 0.7 };
    onChange([...conditions, newCondition]);
  }, [conditions, onChange]);

  return (
    <div className="space-y-3">
      {/* Header with match mode */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-theme-data text-cyan-400">IF</span>
          <select
            value={matchMode}
            onChange={(e) => onMatchModeChange(e.target.value as 'all' | 'any')}
            className="px-2 py-1 text-xs bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
          >
            <option value="all">ALL conditions match</option>
            <option value="any">ANY condition matches</option>
          </select>
        </div>
        <button
          onClick={handleAddCondition}
          className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] rounded hover:bg-[var(--accent)]/30 transition-colors"
        >
          + Add Condition
        </button>
      </div>

      {/* Conditions List */}
      <div className="space-y-2">
        {conditions.map((condition, index) => (
          <div key={index}>
            {index > 0 && (
              <div className="text-xs text-text-muted text-center py-1">
                {matchMode === 'all' ? 'AND' : 'OR'}
              </div>
            )}
            <ConditionBuilder
              condition={condition}
              index={index}
              onChange={handleConditionChange}
              onRemove={handleConditionRemove}
              isOnly={conditions.length === 1}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

export default ConditionBuilder;
