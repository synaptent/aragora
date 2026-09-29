'use client';

import { useMemo } from 'react';

export type WorkflowCategory =
  'general' | 'legal' | 'healthcare' | 'finance' | 'code' | 'academic' | 'compliance';

export interface WorkflowStep {
  id: string;
  name: string;
  step_type:
    'agent' | 'debate' | 'decision' | 'human_checkpoint' | 'task' | 'memory_write' | 'memory_read';
  description?: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  version: string;
  category: WorkflowCategory;
  tags: string[];
  icon?: string;
  steps: WorkflowStep[];
  inputs?: Record<string, string>;
  outputs?: Record<string, string>;
  estimated_duration?: string;
  complexity?: 'simple' | 'moderate' | 'complex';
}

export interface TemplateCardProps {
  template: WorkflowTemplate;
  selected?: boolean;
  onSelect?: (template: WorkflowTemplate) => void;
  onPreview?: (template: WorkflowTemplate) => void;
  onInstantiate?: (template: WorkflowTemplate) => void;
  compact?: boolean;
}

const CATEGORY_COLORS: Record<WorkflowCategory, string> = {
  general: '#6B7280',
  legal: '#3B82F6',
  healthcare: '#EF4444',
  finance: '#10B981',
  code: '#8B5CF6',
  academic: '#F59E0B',
  compliance: '#EC4899',
};

const CATEGORY_ICONS: Record<WorkflowCategory, string> = {
  general: '  ',
  legal: '  ',
  healthcare: '  ',
  finance: '  ',
  code: '  ',
  academic: '  ',
  compliance: '  ',
};

const STEP_TYPE_ICONS: Record<string, string> = {
  agent: '  ',
  debate: '  ',
  decision: '  ',
  human_checkpoint: '  ',
  task: '  ',
  memory_write: '  ',
  memory_read: '  ',
};

const COMPLEXITY_COLORS: Record<string, string> = {
  simple: 'text-success',
  moderate: 'text-[var(--acid-yellow)]',
  complex: 'text-[var(--crimson)]',
};

/**
 * Card component for displaying workflow templates.
 */
export function TemplateCard({
  template,
  selected = false,
  onSelect,
  onPreview,
  onInstantiate,
  compact = false,
}: TemplateCardProps) {
  const categoryColor = CATEGORY_COLORS[template.category] || CATEGORY_COLORS.general;
  const categoryIcon = CATEGORY_ICONS[template.category] || CATEGORY_ICONS.general;

  // Count step types
  const stepTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    template.steps.forEach((step) => {
      counts[step.step_type] = (counts[step.step_type] || 0) + 1;
    });
    return counts;
  }, [template.steps]);

  // Calculate complexity if not provided
  const complexity = useMemo(() => {
    if (template.complexity) return template.complexity;
    const stepCount = template.steps.length;
    if (stepCount <= 3) return 'simple';
    if (stepCount <= 6) return 'moderate';
    return 'complex';
  }, [template]);

  if (compact) {
    return (
      <div
        onClick={() => onSelect?.(template)}
        className={`p-3 rounded border cursor-pointer transition-all ${
          selected
            ? 'border-[var(--accent)] bg-[var(--accent)]/10'
            : 'border-border bg-surface hover:border-[var(--accent)]/50'
        }`}
      >
        <div className="flex items-center gap-3">
          <span className="text-lg">{categoryIcon}</span>
          <div className="flex-1 min-w-0">
            <div className="font-theme-data text-sm truncate">{template.name}</div>
            <div className="text-xs text-text-muted capitalize">{template.category}</div>
          </div>
          <div className="text-xs text-text-muted">{template.steps.length} steps</div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`card p-4 transition-all ${
        selected ? 'border-[var(--accent)] ring-1 ring-acid-green/30' : ''
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center text-xl"
            style={{ backgroundColor: `${categoryColor}20` }}
          >
            {categoryIcon}
          </div>
          <div>
            <h3 className="font-theme-data font-medium">{template.name}</h3>
            <div className="flex items-center gap-2 mt-0.5">
              <span
                className="text-xs font-theme-data px-2 py-0.5 rounded"
                style={{ backgroundColor: `${categoryColor}20`, color: categoryColor }}
              >
                {template.category}
              </span>
              <span className="text-xs text-text-muted">v{template.version}</span>
            </div>
          </div>
        </div>
        <div className={`text-xs font-theme-data capitalize ${COMPLEXITY_COLORS[complexity]}`}>
          {complexity}
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-text-muted mb-3 line-clamp-2">{template.description}</p>

      {/* Step Types Summary */}
      <div className="flex flex-wrap gap-2 mb-3">
        {Object.entries(stepTypeCounts).map(([type, count]) => (
          <div key={type} className="flex items-center gap-1 px-2 py-1 bg-surface rounded text-xs">
            <span>{STEP_TYPE_ICONS[type] || '  '}</span>
            <span className="text-text-muted">{count}</span>
          </div>
        ))}
      </div>

      {/* Tags */}
      <div className="flex flex-wrap gap-1 mb-3">
        {template.tags.slice(0, 4).map((tag) => (
          <span
            key={tag}
            className="px-2 py-0.5 text-xs font-theme-data bg-bg border border-border rounded text-text-muted"
          >
            {tag}
          </span>
        ))}
        {template.tags.length > 4 && (
          <span className="px-2 py-0.5 text-xs font-theme-data text-text-muted">
            +{template.tags.length - 4}
          </span>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-2 mb-3 text-center">
        <div className="bg-surface p-2 rounded">
          <div className="text-lg font-theme-data">{template.steps.length}</div>
          <div className="text-xs text-text-muted">Steps</div>
        </div>
        <div className="bg-surface p-2 rounded">
          <div className="text-lg font-theme-data">{Object.keys(template.inputs || {}).length}</div>
          <div className="text-xs text-text-muted">Inputs</div>
        </div>
        <div className="bg-surface p-2 rounded">
          <div className="text-lg font-theme-data">
            {Object.keys(template.outputs || {}).length}
          </div>
          <div className="text-xs text-text-muted">Outputs</div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => onPreview?.(template)}
          className="flex-1 px-3 py-1.5 text-xs font-theme-data border border-border rounded hover:border-[var(--accent)] transition-colors"
        >
          Preview
        </button>
        <button
          onClick={() => onInstantiate?.(template)}
          className="flex-1 px-3 py-1.5 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30 rounded hover:bg-[var(--accent)]/30 transition-colors"
        >
          Use Template
        </button>
      </div>
    </div>
  );
}

export default TemplateCard;
