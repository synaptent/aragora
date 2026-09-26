'use client';

import { useState, useCallback, useEffect } from 'react';
import { useWorkflowBuilder } from '@/hooks/useWorkflowBuilder';
import { useWorkflowBuilderStore } from '@/store/workflowBuilderStore';
import { logger } from '@/utils/logger';
import { NodePalette } from './NodePalette';
import { WorkflowToolbar } from './WorkflowToolbar';
import { WorkflowCanvas } from './WorkflowCanvas';
import type { StepType, StepDefinition } from '@/store/workflowBuilderStore';

export interface WorkflowBuilderProps {
  /** Initial workflow ID to load */
  workflowId?: string;
  /** Callback when workflow is saved */
  onSave?: () => void;
  /** Callback when workflow execution starts */
  onExecute?: (executionId: string) => void;
  /** Custom CSS classes */
  className?: string;
}

/**
 * Main workflow builder component with drag-drop canvas and configuration panels.
 */
export function WorkflowBuilder({
  workflowId,
  onSave,
  onExecute,
  className = '',
}: WorkflowBuilderProps) {
  const [showTemplates, setShowTemplates] = useState(false);
  const [selectedNode, setSelectedNode] = useState<StepDefinition | null>(null);

  // Workflow builder hook
  const {
    currentWorkflow,
    templates,
    isDirty,
    isLoading,
    saveError,
    validationErrors,
    createWorkflow,
    saveWorkflow,
    loadTemplates,
    createFromTemplate,
    loadWorkflows,
    validate,
    runSimulation,
    executeWorkflow,
  } = useWorkflowBuilder({
    workflowId,
    autoSave: true,
    onSave: () => {
      onSave?.();
    },
  });

  // Store state
  const { configPanel, closeConfigPanel, addNode, openConfigPanel } = useWorkflowBuilderStore();

  // Load initial data
  useEffect(() => {
    loadWorkflows();
    loadTemplates();
  }, [loadWorkflows, loadTemplates]);

  // Track selected node from config panel
  useEffect(() => {
    if (configPanel.selectedNodeId && currentWorkflow) {
      const node = currentWorkflow.steps.find((s) => s.id === configPanel.selectedNodeId);
      setSelectedNode(node || null);
    } else {
      setSelectedNode(null);
    }
  }, [configPanel.selectedNodeId, currentWorkflow]);

  // Handle new workflow
  const handleNew = useCallback(async () => {
    const name = prompt('Enter workflow name:');
    if (name) {
      await createWorkflow(name);
    }
  }, [createWorkflow]);

  // Handle add node from palette
  const handleAddNode = useCallback(
    (type: StepType) => {
      // Add node at center of canvas
      const x = 400 + Math.random() * 100;
      const y = 200 + Math.random() * 100;
      const nodeId = addNode(type, { x, y });
      if (nodeId) {
        openConfigPanel(nodeId);
      }
    },
    [addNode, openConfigPanel],
  );

  // Handle execute
  const handleExecute = useCallback(async () => {
    try {
      const executionId = await executeWorkflow();
      onExecute?.(executionId);
    } catch (error) {
      logger.error('Failed to execute workflow:', error);
    }
  }, [executeWorkflow, onExecute]);

  // Handle template selection
  const handleSelectTemplate = useCallback(
    async (templateId: string) => {
      const name = prompt('Enter workflow name:');
      if (name) {
        await createFromTemplate(templateId, name);
        setShowTemplates(false);
      }
    },
    [createFromTemplate],
  );

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center h-96 ${className}`}>
        <div className="text-center">
          <div className="animate-spin text-4xl mb-2">⟳</div>
          <p className="text-text-muted">Loading workflow...</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex flex-col h-full bg-bg ${className}`}>
      {/* Toolbar */}
      <WorkflowToolbar
        onSave={saveWorkflow}
        onExecute={handleExecute}
        onValidate={validate}
        onSimulate={runSimulation}
        onNew={handleNew}
        onOpenTemplates={() => setShowTemplates(true)}
        canExecute={!isDirty && validationErrors.length === 0}
      />

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar: Node palette */}
        <div className="w-64 border-r border-border overflow-y-auto bg-surface/50">
          <div className="p-3">
            <h3 className="text-xs font-theme-data text-text-muted uppercase tracking-wide mb-3">
              Node Palette
            </h3>
            <NodePalette onAddNode={handleAddNode} />
          </div>
        </div>

        {/* Canvas */}
        <div className="flex-1 overflow-hidden">
          <WorkflowCanvas width={1200} height={800} />
        </div>

        {/* Right sidebar: Configuration */}
        {configPanel.isOpen && selectedNode && (
          <div className="w-80 border-l border-border overflow-y-auto bg-surface/50">
            <div className="p-4">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-theme-data text-text">Configure Step</h3>
                <button onClick={closeConfigPanel} className="text-text-muted hover:text-text">
                  ✕
                </button>
              </div>

              {/* Node info */}
              <div className="space-y-4">
                <div>
                  <label className="block text-xs text-text-muted mb-1">Name</label>
                  <input
                    type="text"
                    value={selectedNode.name}
                    onChange={(e) => {
                      useWorkflowBuilderStore
                        .getState()
                        .updateNode(selectedNode.id, { name: e.target.value });
                    }}
                    className="w-full px-3 py-2 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs text-text-muted mb-1">Type</label>
                  <div className="px-3 py-2 text-sm bg-bg border border-border rounded text-text-muted">
                    {selectedNode.step_type}
                  </div>
                </div>

                {/* Type-specific config */}
                <div>
                  <label className="block text-xs text-text-muted mb-1">Configuration</label>
                  <textarea
                    value={JSON.stringify(selectedNode.config, null, 2)}
                    onChange={(e) => {
                      try {
                        const config = JSON.parse(e.target.value);
                        useWorkflowBuilderStore.getState().updateNode(selectedNode.id, { config });
                      } catch {
                        // Invalid JSON, ignore
                      }
                    }}
                    className="w-full px-3 py-2 text-sm bg-bg border border-border rounded font-theme-data focus:border-[var(--accent)] focus:outline-none"
                    rows={8}
                  />
                </div>

                {/* Connected steps */}
                <div>
                  <label className="block text-xs text-text-muted mb-1">
                    Next Steps ({selectedNode.next_steps.length})
                  </label>
                  <div className="space-y-1">
                    {selectedNode.next_steps.length === 0 ? (
                      <p className="text-xs text-text-muted italic">No connections</p>
                    ) : (
                      selectedNode.next_steps.map((stepId) => {
                        const step = currentWorkflow?.steps.find((s) => s.id === stepId);
                        return (
                          <div
                            key={stepId}
                            className="flex items-center gap-2 text-xs text-text-muted"
                          >
                            <span>→</span>
                            <span>{step?.name || stepId}</span>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Templates modal */}
      {showTemplates && (
        <div className="fixed inset-0 bg-bg/80 flex items-center justify-center z-50">
          <div className="bg-surface border border-border rounded-lg w-[600px] max-h-[80vh] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-border">
              <h2 className="text-lg font-theme-data text-text">Workflow Templates</h2>
              <button
                onClick={() => setShowTemplates(false)}
                className="text-text-muted hover:text-text"
              >
                ✕
              </button>
            </div>

            <div className="p-4 overflow-y-auto max-h-[60vh]">
              {templates.length === 0 ? (
                <p className="text-text-muted text-center py-8">No templates available</p>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  {templates.map((template) => (
                    <button
                      key={template.id}
                      onClick={() => handleSelectTemplate(template.id)}
                      className="p-4 text-left border border-border rounded-lg hover:border-[var(--accent)] transition-colors"
                    >
                      <div className="text-sm font-theme-data text-text mb-1">{template.name}</div>
                      <div className="text-xs text-text-muted line-clamp-2">
                        {template.description}
                      </div>
                      <div className="mt-2 text-xs text-[var(--accent)]">{template.category}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Error display */}
      {saveError && (
        <div className="absolute bottom-4 left-4 right-4 p-3 bg-red-900/20 border border-red-800/30 rounded text-red-400 text-sm">
          {saveError}
        </div>
      )}
    </div>
  );
}

export default WorkflowBuilder;
