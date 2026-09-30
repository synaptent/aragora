'use client';

import { memo, useCallback } from 'react';
import {
  type WorkflowNodeData,
  type DebateNodeData,
  type TaskNodeData,
  type DecisionNodeData,
  type HumanCheckpointNodeData,
  type MemoryReadNodeData,
  type MemoryWriteNodeData,
  AVAILABLE_PERSONAS,
  NODE_TYPE_CONFIGS,
} from './types';

interface PropertyEditorProps {
  node: WorkflowNodeData | null;
  onUpdate: (updates: Partial<WorkflowNodeData>) => void;
  onDelete: () => void;
}

interface InputFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: 'text' | 'number' | 'textarea';
}

const InputField = memo(function InputField({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
}: InputFieldProps) {
  return (
    <div className="mb-3">
      <label className="block text-xs font-theme-data text-text-muted uppercase tracking-wide mb-1">
        {label}
      </label>
      {type === 'textarea' ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none resize-none"
          rows={3}
        />
      ) : (
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
        />
      )}
    </div>
  );
});

interface SelectFieldProps {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}

const SelectField = memo(function SelectField({
  label,
  value,
  options,
  onChange,
}: SelectFieldProps) {
  return (
    <div className="mb-3">
      <label className="block text-xs font-theme-data text-text-muted uppercase tracking-wide mb-1">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
});

interface MultiSelectProps {
  label: string;
  selected: string[];
  options: string[];
  onChange: (selected: string[]) => void;
}

const MultiSelect = memo(function MultiSelect({
  label,
  selected,
  options,
  onChange,
}: MultiSelectProps) {
  const toggleOption = useCallback(
    (option: string) => {
      if (selected.includes(option)) {
        onChange(selected.filter((s) => s !== option));
      } else {
        onChange([...selected, option]);
      }
    },
    [selected, onChange],
  );

  return (
    <div className="mb-3">
      <label className="block text-xs font-theme-data text-text-muted uppercase tracking-wide mb-1">
        {label}
      </label>
      <div className="flex flex-wrap gap-1 p-2 bg-bg border border-border rounded max-h-32 overflow-y-auto">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => toggleOption(opt)}
            className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
              selected.includes(opt)
                ? 'bg-[var(--accent)] text-bg'
                : 'bg-surface text-text-muted hover:text-text'
            }`}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
});

function DebateNodeEditor({
  data,
  onUpdate,
}: {
  data: DebateNodeData;
  onUpdate: (updates: Partial<DebateNodeData>) => void;
}) {
  const allPersonas = [
    ...AVAILABLE_PERSONAS.general,
    ...AVAILABLE_PERSONAS.legal,
    ...AVAILABLE_PERSONAS.healthcare,
    ...AVAILABLE_PERSONAS.accounting,
    ...AVAILABLE_PERSONAS.code,
    ...AVAILABLE_PERSONAS.academic,
  ];

  return (
    <>
      <MultiSelect
        label="Agents"
        selected={data.agents}
        options={allPersonas}
        onChange={(agents) => onUpdate({ agents })}
      />
      <InputField
        label="Rounds"
        value={String(data.rounds)}
        onChange={(v) => onUpdate({ rounds: parseInt(v) || 1 })}
        type="number"
      />
      <InputField
        label="Topic Template"
        value={data.topicTemplate || ''}
        onChange={(topicTemplate) => onUpdate({ topicTemplate })}
        placeholder="e.g., Review contract: {document}"
        type="textarea"
      />
    </>
  );
}

function TaskNodeEditor({
  data,
  onUpdate,
}: {
  data: TaskNodeData;
  onUpdate: (updates: Partial<TaskNodeData>) => void;
}) {
  return (
    <>
      <SelectField
        label="Task Type"
        value={data.taskType}
        options={[
          { value: 'validate', label: 'Validate' },
          { value: 'transform', label: 'Transform' },
          { value: 'aggregate', label: 'Aggregate' },
          { value: 'function', label: 'Function Call' },
          { value: 'http', label: 'HTTP Request' },
        ]}
        onChange={(taskType) => onUpdate({ taskType: taskType as TaskNodeData['taskType'] })}
      />
      {data.taskType === 'function' && (
        <InputField
          label="Function Name"
          value={data.functionName || ''}
          onChange={(functionName) => onUpdate({ functionName })}
          placeholder="e.g., run_security_scan"
        />
      )}
      {data.taskType === 'transform' && (
        <InputField
          label="Template"
          value={data.template || ''}
          onChange={(template) => onUpdate({ template })}
          placeholder="e.g., audit_report_template"
        />
      )}
    </>
  );
}

function DecisionNodeEditor({
  data,
  onUpdate,
}: {
  data: DecisionNodeData;
  onUpdate: (updates: Partial<DecisionNodeData>) => void;
}) {
  return (
    <>
      <InputField
        label="Condition"
        value={data.condition}
        onChange={(condition) => onUpdate({ condition })}
        placeholder="e.g., critical_count > 0"
      />
    </>
  );
}

function HumanCheckpointEditor({
  data,
  onUpdate,
}: {
  data: HumanCheckpointNodeData;
  onUpdate: (updates: Partial<HumanCheckpointNodeData>) => void;
}) {
  return (
    <>
      <SelectField
        label="Approval Type"
        value={data.approvalType}
        options={[
          { value: 'review', label: 'Review' },
          { value: 'sign_off', label: 'Sign-Off' },
          { value: 'revision', label: 'Revision Request' },
          { value: 'presentation', label: 'Presentation' },
        ]}
        onChange={(approvalType) =>
          onUpdate({ approvalType: approvalType as HumanCheckpointNodeData['approvalType'] })
        }
      />
      <InputField
        label="Required Role"
        value={data.requiredRole || ''}
        onChange={(requiredRole) => onUpdate({ requiredRole })}
        placeholder="e.g., senior_partner"
      />
    </>
  );
}

function MemoryReadEditor({
  data,
  onUpdate,
}: {
  data: MemoryReadNodeData;
  onUpdate: (updates: Partial<MemoryReadNodeData>) => void;
}) {
  return (
    <>
      <InputField
        label="Query Template"
        value={data.queryTemplate}
        onChange={(queryTemplate) => onUpdate({ queryTemplate })}
        placeholder="e.g., Find precedents for {case_type}"
        type="textarea"
      />
      <InputField
        label="Domains (comma-separated)"
        value={data.domains.join(', ')}
        onChange={(v) =>
          onUpdate({
            domains: v
              .split(',')
              .map((d) => d.trim())
              .filter(Boolean),
          })
        }
        placeholder="e.g., legal/contracts, legal/precedents"
      />
    </>
  );
}

function MemoryWriteEditor({
  data,
  onUpdate,
}: {
  data: MemoryWriteNodeData;
  onUpdate: (updates: Partial<MemoryWriteNodeData>) => void;
}) {
  return (
    <>
      <InputField
        label="Domain"
        value={data.domain}
        onChange={(domain) => onUpdate({ domain })}
        placeholder="e.g., legal/contracts"
      />
      <InputField
        label="Retention (years)"
        value={String(data.retentionYears || '')}
        onChange={(v) => onUpdate({ retentionYears: parseInt(v) || undefined })}
        type="number"
      />
    </>
  );
}

export function PropertyEditor({ node, onUpdate, onDelete }: PropertyEditorProps) {
  if (!node) {
    return (
      <div className="h-full p-4 bg-surface border-l border-border">
        <div className="text-center text-text-muted py-8">
          <p className="text-sm font-theme-data">Select a node to edit its properties</p>
        </div>
      </div>
    );
  }

  const config = NODE_TYPE_CONFIGS[node.type];

  return (
    <div className="h-full overflow-y-auto p-4 bg-surface border-l border-border">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4 pb-3 border-b border-border">
        <span className="text-lg">{config.icon}</span>
        <div>
          <h3 className="text-sm font-theme-data font-bold text-text">{config.label}</h3>
          <p className="text-xs text-text-muted">{config.description}</p>
        </div>
      </div>

      {/* Common fields */}
      <InputField
        label="Label"
        value={node.label}
        onChange={(label) => onUpdate({ label })}
        placeholder="Step name"
      />
      <InputField
        label="Description"
        value={node.description || ''}
        onChange={(description) => onUpdate({ description })}
        placeholder="What this step does"
        type="textarea"
      />

      {/* Type-specific fields */}
      <div className="mt-4 pt-4 border-t border-border">
        {node.type === 'debate' && (
          <DebateNodeEditor
            data={node as DebateNodeData}
            onUpdate={onUpdate as (u: Partial<DebateNodeData>) => void}
          />
        )}
        {node.type === 'task' && (
          <TaskNodeEditor
            data={node as TaskNodeData}
            onUpdate={onUpdate as (u: Partial<TaskNodeData>) => void}
          />
        )}
        {node.type === 'decision' && (
          <DecisionNodeEditor
            data={node as DecisionNodeData}
            onUpdate={onUpdate as (u: Partial<DecisionNodeData>) => void}
          />
        )}
        {node.type === 'human_checkpoint' && (
          <HumanCheckpointEditor
            data={node as HumanCheckpointNodeData}
            onUpdate={onUpdate as (u: Partial<HumanCheckpointNodeData>) => void}
          />
        )}
        {node.type === 'memory_read' && (
          <MemoryReadEditor
            data={node as MemoryReadNodeData}
            onUpdate={onUpdate as (u: Partial<MemoryReadNodeData>) => void}
          />
        )}
        {node.type === 'memory_write' && (
          <MemoryWriteEditor
            data={node as MemoryWriteNodeData}
            onUpdate={onUpdate as (u: Partial<MemoryWriteNodeData>) => void}
          />
        )}
      </div>

      {/* Delete button */}
      <div className="mt-6 pt-4 border-t border-border">
        <button
          onClick={onDelete}
          className="w-full px-4 py-2 bg-red-500/20 border border-red-500/50 text-red-400 font-theme-data text-sm hover:bg-red-500/30 transition-colors rounded"
        >
          Delete Node
        </button>
      </div>
    </div>
  );
}

export default PropertyEditor;
