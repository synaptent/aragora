/**
 * Selectors for Workflow Builder Store
 */

import type { WorkflowBuilderStore } from './types';

export const selectCurrentWorkflow = (state: WorkflowBuilderStore) => state.currentWorkflow;
export const selectCanvas = (state: WorkflowBuilderStore) => state.canvas;
export const selectConfigPanel = (state: WorkflowBuilderStore) => state.configPanel;
export const selectNodePalette = (state: WorkflowBuilderStore) => state.nodePalette;
export const selectIsDirty = (state: WorkflowBuilderStore) => state.isDirty;
export const selectIsSaving = (state: WorkflowBuilderStore) => state.isSaving;
export const selectIsLoading = (state: WorkflowBuilderStore) => state.isLoading;
export const selectValidationErrors = (state: WorkflowBuilderStore) => state.validationErrors;
export const selectWorkflows = (state: WorkflowBuilderStore) => state.workflows;
export const selectTemplates = (state: WorkflowBuilderStore) => state.templates;
export const selectExecutionPreview = (state: WorkflowBuilderStore) => state.executionPreview;
export const selectCanUndo = (state: WorkflowBuilderStore) => state._historyIndex > 0;
export const selectCanRedo = (state: WorkflowBuilderStore) =>
  state._historyIndex < state._history.length - 1;
