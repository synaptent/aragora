'use client';

import { useCallback } from 'react';
import {
  useWorkflowBuilderStore,
  selectIsDirty,
  selectIsSaving,
  selectCanUndo,
  selectCanRedo,
  selectValidationErrors,
} from '@/store/workflowBuilderStore';

export interface WorkflowToolbarProps {
  /** Callback to save workflow */
  onSave?: () => void;
  /** Callback to execute workflow */
  onExecute?: () => void;
  /** Callback to validate workflow */
  onValidate?: () => void;
  /** Callback to run simulation */
  onSimulate?: () => void;
  /** Callback to create new workflow */
  onNew?: () => void;
  /** Callback to open template gallery */
  onOpenTemplates?: () => void;
  /** Whether execution is enabled */
  canExecute?: boolean;
}

/**
 * Toolbar for the workflow builder with save, execute, and validation actions.
 */
export function WorkflowToolbar({
  onSave,
  onExecute,
  onValidate,
  onSimulate,
  onNew,
  onOpenTemplates,
  canExecute = true,
}: WorkflowToolbarProps) {
  const isDirty = useWorkflowBuilderStore(selectIsDirty);
  const isSaving = useWorkflowBuilderStore(selectIsSaving);
  const canUndo = useWorkflowBuilderStore(selectCanUndo);
  const canRedo = useWorkflowBuilderStore(selectCanRedo);
  const validationErrors = useWorkflowBuilderStore(selectValidationErrors);
  const currentWorkflow = useWorkflowBuilderStore((s) => s.currentWorkflow);

  const { undo, redo, validate } = useWorkflowBuilderStore();

  const handleValidate = useCallback(() => {
    validate();
    onValidate?.();
  }, [validate, onValidate]);

  const hasErrors = validationErrors.length > 0;

  return (
    <div className="flex items-center justify-between p-3 bg-surface border-b border-border">
      {/* Left section: File actions */}
      <div className="flex items-center gap-2">
        {/* New */}
        <button
          onClick={onNew}
          className="px-3 py-1.5 text-sm bg-bg border border-border rounded hover:border-text-muted transition-colors"
          title="New workflow"
        >
          + New
        </button>

        {/* Templates */}
        <button
          onClick={onOpenTemplates}
          className="px-3 py-1.5 text-sm bg-bg border border-border rounded hover:border-text-muted transition-colors"
          title="Open templates"
        >
          📁 Templates
        </button>

        {/* Separator */}
        <div className="w-px h-6 bg-border" />

        {/* Undo/Redo */}
        <button
          onClick={undo}
          disabled={!canUndo}
          className="p-1.5 text-sm bg-bg border border-border rounded hover:border-text-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title="Undo (Ctrl+Z)"
        >
          ↶
        </button>
        <button
          onClick={redo}
          disabled={!canRedo}
          className="p-1.5 text-sm bg-bg border border-border rounded hover:border-text-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title="Redo (Ctrl+Shift+Z)"
        >
          ↷
        </button>
      </div>

      {/* Center section: Workflow info */}
      <div className="flex items-center gap-2">
        {currentWorkflow && (
          <>
            <span className="text-sm font-theme-data text-text">{currentWorkflow.name}</span>
            {isDirty && (
              <span className="text-xs text-yellow-400" title="Unsaved changes">
                ●
              </span>
            )}
            {hasErrors && (
              <span
                className="text-xs text-red-400 cursor-help"
                title={validationErrors.join('\n')}
              >
                ⚠ {validationErrors.length} errors
              </span>
            )}
          </>
        )}
      </div>

      {/* Right section: Actions */}
      <div className="flex items-center gap-2">
        {/* Validate */}
        <button
          onClick={handleValidate}
          disabled={!currentWorkflow}
          className={`px-3 py-1.5 text-sm border rounded transition-colors ${
            hasErrors
              ? 'border-red-700 bg-red-900/20 text-red-400'
              : 'border-border bg-bg hover:border-text-muted'
          } disabled:opacity-50`}
          title="Validate workflow"
        >
          ✓ Validate
        </button>

        {/* Simulate */}
        <button
          onClick={onSimulate}
          disabled={!currentWorkflow || hasErrors}
          className="px-3 py-1.5 text-sm bg-bg border border-border rounded hover:border-text-muted transition-colors disabled:opacity-50"
          title="Run simulation (dry-run)"
        >
          🔬 Simulate
        </button>

        {/* Separator */}
        <div className="w-px h-6 bg-border" />

        {/* Save */}
        <button
          onClick={onSave}
          disabled={!currentWorkflow || isSaving || !isDirty}
          className={`px-3 py-1.5 text-sm rounded transition-colors ${
            isDirty && !isSaving
              ? 'bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/90'
              : 'bg-bg border border-border hover:border-text-muted'
          } disabled:opacity-50`}
          title="Save workflow (Ctrl+S)"
        >
          {isSaving ? '...' : '💾 Save'}
        </button>

        {/* Execute */}
        <button
          onClick={onExecute}
          disabled={!currentWorkflow || !canExecute || hasErrors}
          className="px-3 py-1.5 text-sm bg-[var(--acid-cyan)] text-bg rounded hover:bg-[var(--acid-cyan)]/90 transition-colors disabled:opacity-50"
          title="Execute workflow"
        >
          ▶ Execute
        </button>
      </div>
    </div>
  );
}

export default WorkflowToolbar;
