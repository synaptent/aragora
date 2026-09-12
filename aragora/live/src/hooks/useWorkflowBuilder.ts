'use client';

/**
 * Workflow Builder hook for managing workflow editing and execution.
 *
 * Provides:
 * - Workflow CRUD operations
 * - Auto-save with debouncing
 * - Template loading
 * - Keyboard shortcuts
 * - Validation and simulation
 */

import { useEffect, useCallback, useRef } from 'react';
import { useApi } from './useApi';
import { useBackend } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';
import {
  useWorkflowBuilderStore,
  type WorkflowDefinition,
  type WorkflowTemplate,
  type WorkflowSimulationResult,
} from '@/store/workflowBuilderStore';

export interface UseWorkflowBuilderOptions {
  /** Workflow ID to load on mount */
  workflowId?: string;
  /** Enable auto-save (default: true) */
  autoSave?: boolean;
  /** Auto-save debounce delay in ms (default: 2000) */
  autoSaveDelay?: number;
  /** Enable keyboard shortcuts (default: true) */
  enableKeyboardShortcuts?: boolean;
  /** Callback when workflow is saved */
  onSave?: (workflow: WorkflowDefinition) => void;
  /** Callback when save fails */
  onSaveError?: (error: Error) => void;
}

export interface UseWorkflowBuilderReturn {
  // State from store
  currentWorkflow: WorkflowDefinition | null;
  workflows: WorkflowDefinition[];
  templates: WorkflowTemplate[];
  isDirty: boolean;
  isSaving: boolean;
  isLoading: boolean;
  saveError: string | null;
  loadError: string | null;
  validationErrors: string[];

  // CRUD operations
  loadWorkflow: (id: string) => Promise<void>;
  createWorkflow: (name: string, description?: string) => Promise<WorkflowDefinition>;
  saveWorkflow: () => Promise<void>;
  deleteWorkflow: (id: string) => Promise<void>;
  duplicateWorkflow: (id: string, newName: string) => Promise<WorkflowDefinition>;

  // Template operations
  loadTemplates: () => Promise<void>;
  createFromTemplate: (templateId: string, name: string) => Promise<WorkflowDefinition>;

  // Workflow list
  loadWorkflows: () => Promise<void>;

  // Validation and simulation
  validate: () => string[];
  runSimulation: () => Promise<WorkflowSimulationResult>;

  // Execution
  executeWorkflow: (inputs?: Record<string, unknown>) => Promise<string>;
}

/**
 * Hook for workflow builder functionality.
 *
 * @example
 * ```tsx
 * const {
 *   currentWorkflow,
 *   isDirty,
 *   saveWorkflow,
 *   loadTemplates,
 * } = useWorkflowBuilder({
 *   workflowId: 'wf_123',
 *   onSave: (wf) => toast('Saved!'),
 * });
 * ```
 */
export function useWorkflowBuilder({
  workflowId,
  autoSave = true,
  autoSaveDelay = 2000,
  enableKeyboardShortcuts = true,
  onSave,
  onSaveError,
}: UseWorkflowBuilderOptions = {}): UseWorkflowBuilderReturn {
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  // Get store state and actions
  const store = useWorkflowBuilderStore();
  const {
    currentWorkflow,
    workflows,
    templates,
    isDirty,
    isSaving,
    isLoading,
    saveError,
    loadError,
    validationErrors,
    setCurrentWorkflow,
    createNewWorkflow,
    setWorkflows,
    setTemplates,
    setLoading,
    setSaving,
    setSaveError,
    setLoadError,
    setSimulationResult,
    setSimulationRunning,
    validate,
    markClean,
    undo,
    redo,
  } = store;

  // Auto-save timer ref
  const saveTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Load workflow on mount if ID provided
  useEffect(() => {
    if (workflowId) {
      loadWorkflow(workflowId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadWorkflow defined later, mount-only
  }, [workflowId]);

  // Auto-save when dirty
  useEffect(() => {
    if (!autoSave || !isDirty || !currentWorkflow) return;

    // Clear existing timer
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
    }

    // Set new timer
    saveTimerRef.current = setTimeout(() => {
      saveWorkflow();
    }, autoSaveDelay);

    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- saveWorkflow defined later
  }, [autoSave, isDirty, currentWorkflow, autoSaveDelay]);

  // Keyboard shortcuts
  useEffect(() => {
    if (!enableKeyboardShortcuts) return;

    const handleKeyboard = (e: KeyboardEvent) => {
      // Cmd/Ctrl + S - Save
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        saveWorkflow();
        return;
      }

      // Cmd/Ctrl + Z - Undo
      if ((e.metaKey || e.ctrlKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        undo();
        return;
      }

      // Cmd/Ctrl + Shift + Z or Cmd/Ctrl + Y - Redo
      if (
        ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'z') ||
        ((e.metaKey || e.ctrlKey) && e.key === 'y')
      ) {
        e.preventDefault();
        redo();
        return;
      }
    };

    window.addEventListener('keydown', handleKeyboard);
    return () => window.removeEventListener('keydown', handleKeyboard);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- saveWorkflow defined later
  }, [enableKeyboardShortcuts, undo, redo]);

  // Load a specific workflow
  const loadWorkflow = useCallback(
    async (id: string): Promise<void> => {
      setLoading(true);
      setLoadError(null);

      try {
        const data = (await api.get(`/api/workflows/${id}`)) as WorkflowDefinition;
        setCurrentWorkflow(data);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to load workflow';
        setLoadError(message);
        throw error;
      } finally {
        setLoading(false);
      }
    },
    [api, setCurrentWorkflow, setLoading, setLoadError],
  );

  // Create a new workflow
  const createWorkflow = useCallback(
    async (name: string, description?: string): Promise<WorkflowDefinition> => {
      setLoading(true);
      setSaveError(null);

      try {
        const workflow = createNewWorkflow(name, description);

        // Save to backend
        const saved = (await api.post('/api/workflows', workflow)) as WorkflowDefinition;
        setCurrentWorkflow(saved);
        onSave?.(saved);

        return saved;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to create workflow';
        setSaveError(message);
        onSaveError?.(error instanceof Error ? error : new Error(message));
        throw error;
      } finally {
        setLoading(false);
      }
    },
    [api, createNewWorkflow, setCurrentWorkflow, setLoading, setSaveError, onSave, onSaveError],
  );

  // Save current workflow
  const saveWorkflow = useCallback(async (): Promise<void> => {
    if (!currentWorkflow || isSaving) return;

    setSaving(true);
    setSaveError(null);

    try {
      const saved = (await api.put(
        `/api/workflows/${currentWorkflow.id}`,
        currentWorkflow,
      )) as WorkflowDefinition;
      setCurrentWorkflow(saved);
      markClean();
      onSave?.(saved);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to save workflow';
      setSaveError(message);
      onSaveError?.(error instanceof Error ? error : new Error(message));
      throw error;
    } finally {
      setSaving(false);
    }
  }, [
    api,
    currentWorkflow,
    isSaving,
    setCurrentWorkflow,
    setSaving,
    setSaveError,
    markClean,
    onSave,
    onSaveError,
  ]);

  // Delete a workflow
  const deleteWorkflow = useCallback(
    async (id: string): Promise<void> => {
      await api.delete(`/api/workflows/${id}`);

      // Refresh list
      await loadWorkflows();

      // If current workflow was deleted, clear it
      if (currentWorkflow?.id === id) {
        setCurrentWorkflow(null);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadWorkflows defined later
    [api, currentWorkflow, setCurrentWorkflow],
  );

  // Duplicate a workflow
  const duplicateWorkflow = useCallback(
    async (id: string, newName: string): Promise<WorkflowDefinition> => {
      const original = workflows.find((w) => w.id === id);
      if (!original) {
        throw new Error(`Workflow ${id} not found`);
      }

      const duplicate: WorkflowDefinition = {
        ...JSON.parse(JSON.stringify(original)),
        id: `wf_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
        name: newName,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };

      const saved = (await api.post('/api/workflows', duplicate)) as WorkflowDefinition;
      await loadWorkflows();

      return saved;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadWorkflows defined later
    [api, workflows],
  );

  // Load workflow templates
  const loadTemplates = useCallback(async (): Promise<void> => {
    try {
      const data = (await api.get('/api/workflow-templates')) as { templates: WorkflowTemplate[] };
      setTemplates(data.templates || []);
    } catch (error) {
      logger.error('Failed to load templates:', error);
    }
  }, [api, setTemplates]);

  // Create workflow from template
  const createFromTemplate = useCallback(
    async (templateId: string, name: string): Promise<WorkflowDefinition> => {
      const template = templates.find((t) => t.id === templateId);
      if (!template) {
        throw new Error(`Template ${templateId} not found`);
      }

      const workflow: WorkflowDefinition = {
        ...JSON.parse(JSON.stringify(template.workflow)),
        id: `wf_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
        name,
        created_at: new Date().toISOString(),
      };

      const saved = (await api.post('/api/workflows', workflow)) as WorkflowDefinition;
      setCurrentWorkflow(saved);
      await loadWorkflows();

      return saved;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadWorkflows defined later
    [api, templates, setCurrentWorkflow],
  );

  // Load all workflows
  const loadWorkflows = useCallback(async (): Promise<void> => {
    try {
      const data = (await api.get('/api/workflows')) as { workflows: WorkflowDefinition[] };
      setWorkflows(data.workflows || []);
    } catch (error) {
      logger.error('Failed to load workflows:', error);
    }
  }, [api, setWorkflows]);

  // Run workflow simulation (dry-run)
  const runSimulation = useCallback(async (): Promise<WorkflowSimulationResult> => {
    if (!currentWorkflow) {
      throw new Error('No workflow loaded');
    }

    // First validate locally
    const errors = validate();
    if (errors.length > 0) {
      const result: WorkflowSimulationResult = {
        valid: false,
        errors,
        warnings: [],
        step_order: [],
      };
      setSimulationResult(result);
      return result;
    }

    setSimulationRunning(true);

    try {
      const result = (await api.post(`/api/workflows/${currentWorkflow.id}/simulate`, {
        workflow: currentWorkflow,
      })) as WorkflowSimulationResult;
      setSimulationResult(result);
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Simulation failed';
      const result: WorkflowSimulationResult = {
        valid: false,
        errors: [message],
        warnings: [],
        step_order: [],
      };
      setSimulationResult(result);
      return result;
    }
  }, [api, currentWorkflow, validate, setSimulationResult, setSimulationRunning]);

  // Execute workflow
  const executeWorkflow = useCallback(
    async (inputs?: Record<string, unknown>): Promise<string> => {
      if (!currentWorkflow) {
        throw new Error('No workflow loaded');
      }

      const result = (await api.post(`/api/workflows/${currentWorkflow.id}/execute`, {
        inputs,
      })) as { execution_id: string };

      return result.execution_id;
    },
    [api, currentWorkflow],
  );

  return {
    // State
    currentWorkflow,
    workflows,
    templates,
    isDirty,
    isSaving,
    isLoading,
    saveError,
    loadError,
    validationErrors,

    // Operations
    loadWorkflow,
    createWorkflow,
    saveWorkflow,
    deleteWorkflow,
    duplicateWorkflow,
    loadTemplates,
    createFromTemplate,
    loadWorkflows,
    validate,
    runSimulation,
    executeWorkflow,
  };
}

export default useWorkflowBuilder;
