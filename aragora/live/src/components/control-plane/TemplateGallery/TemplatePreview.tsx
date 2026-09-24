'use client';

import { useMemo } from 'react';
import type { WorkflowTemplate, WorkflowStep } from './TemplateCard';

export interface TemplatePreviewProps {
  template: WorkflowTemplate | null;
  isOpen: boolean;
  onClose: () => void;
  onInstantiate?: (template: WorkflowTemplate) => void;
}

const STEP_TYPE_COLORS: Record<string, string> = {
  agent: '#4299e1',
  debate: '#38b2ac',
  decision: '#ed8936',
  human_checkpoint: '#f56565',
  task: '#48bb78',
  memory_write: '#9f7aea',
  memory_read: '#667eea',
};

const STEP_TYPE_LABELS: Record<string, string> = {
  agent: 'AI Agent',
  debate: 'Multi-Agent Debate',
  decision: 'Decision Point',
  human_checkpoint: 'Human Review',
  task: 'Task',
  memory_write: 'Store to Knowledge',
  memory_read: 'Read from Knowledge',
};

/**
 * Modal for previewing workflow template details.
 */
export function TemplatePreview({
  template,
  isOpen,
  onClose,
  onInstantiate,
}: TemplatePreviewProps) {
  // Group steps by type for visualization
  const stepsByType = useMemo(() => {
    if (!template) return {};
    const groups: Record<string, WorkflowStep[]> = {};
    template.steps.forEach((step) => {
      if (!groups[step.step_type]) {
        groups[step.step_type] = [];
      }
      groups[step.step_type].push(step);
    });
    return groups;
  }, [template]);

  if (!isOpen || !template) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-surface border border-border rounded-lg w-full max-w-4xl max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div>
            <h2 className="font-theme-data font-medium text-lg">{template.name}</h2>
            <p className="text-xs text-text-muted mt-1">
              {template.category} | v{template.version} | {template.steps.length} steps
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text transition-colors p-1"
          >
            <span className="text-xl">x</span>
          </button>
        </div>

        {/* Content */}
        <div className="p-4 overflow-y-auto max-h-[calc(90vh-140px)]">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left Column - Details */}
            <div className="space-y-4">
              {/* Description */}
              <div>
                <h3 className="text-sm font-theme-data text-[var(--accent)] mb-2">Description</h3>
                <p className="text-sm text-text-muted">{template.description}</p>
              </div>

              {/* Tags */}
              <div>
                <h3 className="text-sm font-theme-data text-[var(--accent)] mb-2">Tags</h3>
                <div className="flex flex-wrap gap-1">
                  {template.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-2 py-1 text-xs font-theme-data bg-bg border border-border rounded"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>

              {/* Inputs */}
              {template.inputs && Object.keys(template.inputs).length > 0 && (
                <div>
                  <h3 className="text-sm font-theme-data text-[var(--accent)] mb-2">
                    Required Inputs
                  </h3>
                  <div className="space-y-2">
                    {Object.entries(template.inputs).map(([key, description]) => (
                      <div key={key} className="p-2 bg-bg rounded border border-border">
                        <div className="font-theme-data text-sm text-[var(--acid-cyan)]">{key}</div>
                        <div className="text-xs text-text-muted">{description}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Outputs */}
              {template.outputs && Object.keys(template.outputs).length > 0 && (
                <div>
                  <h3 className="text-sm font-theme-data text-[var(--accent)] mb-2">Outputs</h3>
                  <div className="space-y-2">
                    {Object.entries(template.outputs).map(([key, description]) => (
                      <div key={key} className="p-2 bg-bg rounded border border-border">
                        <div className="font-theme-data text-sm text-success">{key}</div>
                        <div className="text-xs text-text-muted">{description}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Right Column - Workflow Steps */}
            <div>
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">Workflow Steps</h3>

              {/* Step Type Summary */}
              <div className="flex flex-wrap gap-2 mb-4">
                {Object.entries(stepsByType).map(([type, steps]) => (
                  <div
                    key={type}
                    className="px-2 py-1 rounded text-xs font-theme-data flex items-center gap-1"
                    style={{ backgroundColor: `${STEP_TYPE_COLORS[type]}20` }}
                  >
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: STEP_TYPE_COLORS[type] }}
                    />
                    <span>{STEP_TYPE_LABELS[type] || type}</span>
                    <span className="text-text-muted">({steps.length})</span>
                  </div>
                ))}
              </div>

              {/* Step Flow */}
              <div className="space-y-3">
                {template.steps.map((step, index) => (
                  <div key={step.id} className="relative">
                    {/* Connection line */}
                    {index < template.steps.length - 1 && (
                      <div className="absolute left-4 top-full w-0.5 h-3 bg-border" />
                    )}

                    {/* Step card */}
                    <div
                      className="p-3 rounded border-l-4"
                      style={{
                        borderLeftColor: STEP_TYPE_COLORS[step.step_type] || '#666',
                        backgroundColor: `${STEP_TYPE_COLORS[step.step_type]}10`,
                      }}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-theme-data text-text-muted">
                            {String(index + 1).padStart(2, '0')}
                          </span>
                          <div>
                            <div className="font-theme-data text-sm">{step.name}</div>
                            <div
                              className="text-xs"
                              style={{ color: STEP_TYPE_COLORS[step.step_type] }}
                            >
                              {STEP_TYPE_LABELS[step.step_type] || step.step_type}
                            </div>
                          </div>
                        </div>
                      </div>
                      {step.description && (
                        <p className="text-xs text-text-muted mt-2 ml-6">{step.description}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              {/* Flow Legend */}
              <div className="mt-4 p-3 bg-bg rounded border border-border">
                <div className="text-xs font-theme-data text-text-muted mb-2">Step Types</div>
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(STEP_TYPE_LABELS).map(([type, label]) => (
                    <div key={type} className="flex items-center gap-2 text-xs">
                      <span
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: STEP_TYPE_COLORS[type] }}
                      />
                      <span className="text-text-muted">{label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end p-4 border-t border-border bg-bg/50">
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-theme-data border border-border rounded hover:border-text-muted transition-colors"
            >
              Close
            </button>
            <button
              onClick={() => {
                onInstantiate?.(template);
                onClose();
              }}
              className="px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors"
            >
              Use This Template
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default TemplatePreview;
