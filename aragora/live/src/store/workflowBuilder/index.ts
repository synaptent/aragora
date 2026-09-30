/**
 * Workflow Builder Store - Main Export
 */

'use client';

import { create } from 'zustand';
import { devtools, subscribeWithSelector, persist } from 'zustand/middleware';

// Import types
import type {
  StepDefinition,
  TransitionRule,
  WorkflowDefinition,
  WorkflowBuilderStore,
} from './types';

// Import constants
import {
  MAX_HISTORY,
  initialCanvasState,
  initialPaletteState,
  initialConfigPanelState,
  initialPreviewState,
} from './constants';

// Import utilities
import { generateId, getDefaultStepConfig, getDefaultStepName } from './utils';

// ============================================================================
// Store Implementation
// ============================================================================

export const useWorkflowBuilderStore = create<WorkflowBuilderStore>()(
  devtools(
    subscribeWithSelector(
      persist(
        (set, get) => ({
          // Initial state
          currentWorkflow: null,
          originalWorkflow: null,
          canvas: { ...initialCanvasState },
          nodePalette: { ...initialPaletteState },
          configPanel: { ...initialConfigPanelState },
          workflows: [],
          templates: [],
          isDirty: false,
          isSaving: false,
          isLoading: false,
          saveError: null,
          loadError: null,
          validationErrors: [],
          executionPreview: { ...initialPreviewState },
          _history: [],
          _historyIndex: -1,

          // Workflow CRUD
          setCurrentWorkflow: (workflow) => {
            set(
              {
                currentWorkflow: workflow,
                originalWorkflow: workflow ? JSON.parse(JSON.stringify(workflow)) : null,
                isDirty: false,
                validationErrors: [],
                configPanel: { ...initialConfigPanelState },
                canvas: {
                  ...initialCanvasState,
                  selectedNodeIds: new Set(),
                  selectedEdgeIds: new Set(),
                },
                _history: workflow ? [JSON.parse(JSON.stringify(workflow))] : [],
                _historyIndex: 0,
              },
              false,
              'setCurrentWorkflow',
            );
          },

          createNewWorkflow: (name, description) => {
            const workflow: WorkflowDefinition = {
              id: generateId('wf'),
              name,
              description,
              steps: [],
              transitions: [],
              config: { timeout_seconds: 600, max_tokens: 100000, max_cost_usd: 10 },
              version: '1.0.0',
              created_at: new Date().toISOString(),
            };

            set(
              {
                currentWorkflow: workflow,
                originalWorkflow: JSON.parse(JSON.stringify(workflow)),
                isDirty: false,
                _history: [JSON.parse(JSON.stringify(workflow))],
                _historyIndex: 0,
              },
              false,
              'createNewWorkflow',
            );

            return workflow;
          },

          updateWorkflowMetadata: (updates) => {
            const state = get();
            if (!state.currentWorkflow) return;

            state.pushHistory();
            set(
              {
                currentWorkflow: {
                  ...state.currentWorkflow,
                  ...updates,
                  updated_at: new Date().toISOString(),
                },
                isDirty: true,
              },
              false,
              'updateWorkflowMetadata',
            );
          },

          // Node operations
          addNode: (type, position) => {
            const state = get();
            if (!state.currentWorkflow) return '';

            state.pushHistory();
            const id = generateId('step');
            const newStep: StepDefinition = {
              id,
              name: getDefaultStepName(type),
              step_type: type,
              config: getDefaultStepConfig(type),
              next_steps: [],
              position,
            };

            set(
              {
                currentWorkflow: {
                  ...state.currentWorkflow,
                  steps: [...state.currentWorkflow.steps, newStep],
                  updated_at: new Date().toISOString(),
                },
                isDirty: true,
              },
              false,
              'addNode',
            );

            return id;
          },

          updateNode: (id, updates) => {
            const state = get();
            if (!state.currentWorkflow) return;

            state.pushHistory();
            set(
              {
                currentWorkflow: {
                  ...state.currentWorkflow,
                  steps: state.currentWorkflow.steps.map((step) =>
                    step.id === id ? { ...step, ...updates } : step,
                  ),
                  updated_at: new Date().toISOString(),
                },
                isDirty: true,
              },
              false,
              'updateNode',
            );
          },

          deleteNode: (id) => {
            const state = get();
            if (!state.currentWorkflow) return;

            state.pushHistory();
            set(
              {
                currentWorkflow: {
                  ...state.currentWorkflow,
                  steps: state.currentWorkflow.steps.filter((step) => step.id !== id),
                  transitions: state.currentWorkflow.transitions.filter(
                    (t) => t.from_step !== id && t.to_step !== id,
                  ),
                  updated_at: new Date().toISOString(),
                },
                isDirty: true,
                configPanel:
                  state.configPanel.selectedNodeId === id
                    ? { ...initialConfigPanelState }
                    : state.configPanel,
                canvas: {
                  ...state.canvas,
                  selectedNodeIds: new Set(
                    Array.from(state.canvas.selectedNodeIds).filter((nodeId) => nodeId !== id),
                  ),
                },
              },
              false,
              'deleteNode',
            );
          },

          duplicateNode: (id) => {
            const state = get();
            if (!state.currentWorkflow) return null;

            const step = state.currentWorkflow.steps.find((s) => s.id === id);
            if (!step) return null;

            state.pushHistory();
            const newId = generateId('step');
            const newStep: StepDefinition = {
              ...JSON.parse(JSON.stringify(step)),
              id: newId,
              name: `${step.name} (copy)`,
              position: step.position
                ? { x: step.position.x + 50, y: step.position.y + 50 }
                : undefined,
              next_steps: [],
            };

            set(
              {
                currentWorkflow: {
                  ...state.currentWorkflow,
                  steps: [...state.currentWorkflow.steps, newStep],
                  updated_at: new Date().toISOString(),
                },
                isDirty: true,
              },
              false,
              'duplicateNode',
            );

            return newId;
          },

          // Edge operations
          addEdge: (fromId, toId, condition) => {
            const state = get();
            if (!state.currentWorkflow) return '';

            // Check if edge already exists
            const exists = state.currentWorkflow.transitions.some(
              (t) => t.from_step === fromId && t.to_step === toId,
            );
            if (exists) return '';

            state.pushHistory();
            const id = generateId('edge');
            const newTransition: TransitionRule = {
              id,
              from_step: fromId,
              to_step: toId,
              condition,
            };

            // Also update next_steps on the source node
            const updatedSteps = state.currentWorkflow.steps.map((step) => {
              if (step.id === fromId && !step.next_steps.includes(toId)) {
                return { ...step, next_steps: [...step.next_steps, toId] };
              }
              return step;
            });

            set(
              {
                currentWorkflow: {
                  ...state.currentWorkflow,
                  steps: updatedSteps,
                  transitions: [...state.currentWorkflow.transitions, newTransition],
                  updated_at: new Date().toISOString(),
                },
                isDirty: true,
              },
              false,
              'addEdge',
            );

            return id;
          },

          updateEdge: (id, updates) => {
            const state = get();
            if (!state.currentWorkflow) return;

            state.pushHistory();
            set(
              {
                currentWorkflow: {
                  ...state.currentWorkflow,
                  transitions: state.currentWorkflow.transitions.map((t) =>
                    t.id === id ? { ...t, ...updates } : t,
                  ),
                  updated_at: new Date().toISOString(),
                },
                isDirty: true,
              },
              false,
              'updateEdge',
            );
          },

          deleteEdge: (id) => {
            const state = get();
            if (!state.currentWorkflow) return;

            const edge = state.currentWorkflow.transitions.find((t) => t.id === id);
            if (!edge) return;

            state.pushHistory();
            // Also remove from next_steps
            const updatedSteps = state.currentWorkflow.steps.map((step) => {
              if (step.id === edge.from_step) {
                return { ...step, next_steps: step.next_steps.filter((s) => s !== edge.to_step) };
              }
              return step;
            });

            set(
              {
                currentWorkflow: {
                  ...state.currentWorkflow,
                  steps: updatedSteps,
                  transitions: state.currentWorkflow.transitions.filter((t) => t.id !== id),
                  updated_at: new Date().toISOString(),
                },
                isDirty: true,
                canvas: {
                  ...state.canvas,
                  selectedEdgeIds: new Set(
                    Array.from(state.canvas.selectedEdgeIds).filter((edgeId) => edgeId !== id),
                  ),
                },
              },
              false,
              'deleteEdge',
            );
          },

          // Canvas operations
          setZoom: (zoom) =>
            set(
              (state) => ({ canvas: { ...state.canvas, zoom: Math.max(0.25, Math.min(2, zoom)) } }),
              false,
              'setZoom',
            ),

          setPan: (x, y) =>
            set((state) => ({ canvas: { ...state.canvas, panX: x, panY: y } }), false, 'setPan'),

          selectNodes: (ids) =>
            set(
              (state) => ({
                canvas: {
                  ...state.canvas,
                  selectedNodeIds: new Set(ids),
                  selectedEdgeIds: new Set(),
                },
              }),
              false,
              'selectNodes',
            ),

          selectEdges: (ids) =>
            set(
              (state) => ({
                canvas: {
                  ...state.canvas,
                  selectedEdgeIds: new Set(ids),
                  selectedNodeIds: new Set(),
                },
              }),
              false,
              'selectEdges',
            ),

          clearSelection: () =>
            set(
              (state) => ({
                canvas: { ...state.canvas, selectedNodeIds: new Set(), selectedEdgeIds: new Set() },
              }),
              false,
              'clearSelection',
            ),

          setDragging: (isDragging, nodeId = null) =>
            set(
              (state) => ({ canvas: { ...state.canvas, isDragging, draggedNodeId: nodeId } }),
              false,
              'setDragging',
            ),

          // Node palette
          setSearchQuery: (query) =>
            set(
              (state) => ({ nodePalette: { ...state.nodePalette, searchQuery: query } }),
              false,
              'setSearchQuery',
            ),

          setSelectedCategory: (category) =>
            set(
              (state) => ({ nodePalette: { ...state.nodePalette, selectedCategory: category } }),
              false,
              'setSelectedCategory',
            ),

          toggleCategory: (category) =>
            set(
              (state) => {
                const expanded = new Set(state.nodePalette.expandedCategories);
                if (expanded.has(category)) {
                  expanded.delete(category);
                } else {
                  expanded.add(category);
                }
                return { nodePalette: { ...state.nodePalette, expandedCategories: expanded } };
              },
              false,
              'toggleCategory',
            ),

          // Config panel
          openConfigPanel: (nodeId) =>
            set(
              { configPanel: { isOpen: true, selectedNodeId: nodeId, pendingChanges: null } },
              false,
              'openConfigPanel',
            ),

          closeConfigPanel: () =>
            set({ configPanel: { ...initialConfigPanelState } }, false, 'closeConfigPanel'),

          setPendingChanges: (changes) =>
            set(
              (state) => ({ configPanel: { ...state.configPanel, pendingChanges: changes } }),
              false,
              'setPendingChanges',
            ),

          applyPendingChanges: () => {
            const state = get();
            if (!state.configPanel.selectedNodeId || !state.configPanel.pendingChanges) return;

            state.updateNode(state.configPanel.selectedNodeId, state.configPanel.pendingChanges);
            set(
              (s) => ({ configPanel: { ...s.configPanel, pendingChanges: null } }),
              false,
              'applyPendingChanges',
            );
          },

          // Validation
          validate: () => {
            const state = get();
            if (!state.currentWorkflow) return ['No workflow loaded'];

            const errors: string[] = [];
            const workflow = state.currentWorkflow;

            // Check for empty workflow
            if (workflow.steps.length === 0) {
              errors.push('Workflow has no steps');
            }

            // Check for cycles
            const visited = new Set<string>();
            const recursionStack = new Set<string>();

            function hasCycle(stepId: string): boolean {
              if (recursionStack.has(stepId)) return true;
              if (visited.has(stepId)) return false;

              visited.add(stepId);
              recursionStack.add(stepId);

              const step = workflow.steps.find((s) => s.id === stepId);
              if (step) {
                for (const nextId of step.next_steps) {
                  if (hasCycle(nextId)) return true;
                }
              }

              recursionStack.delete(stepId);
              return false;
            }

            for (const step of workflow.steps) {
              if (!visited.has(step.id) && hasCycle(step.id)) {
                errors.push('Workflow contains cycles');
                break;
              }
            }

            // Check for orphan steps (no incoming or outgoing edges)
            const hasIncoming = new Set<string>();
            const hasOutgoing = new Set<string>();

            for (const step of workflow.steps) {
              if (step.next_steps.length > 0) {
                hasOutgoing.add(step.id);
                step.next_steps.forEach((id) => hasIncoming.add(id));
              }
            }

            // First step shouldn't have incoming edges
            const potentialStarts = workflow.steps.filter((s) => !hasIncoming.has(s.id));
            if (potentialStarts.length === 0 && workflow.steps.length > 0) {
              errors.push('No start step found (all steps have incoming edges)');
            } else if (potentialStarts.length > 1) {
              errors.push(
                `Multiple potential start steps: ${potentialStarts.map((s) => s.name).join(', ')}`,
              );
            }

            // Check step configurations
            for (const step of workflow.steps) {
              if (!step.name || step.name.trim() === '') {
                errors.push(`Step ${step.id} has no name`);
              }

              // Type-specific validation
              if (step.step_type === 'agent' && !step.config.agent_type) {
                errors.push(`Agent step "${step.name}" has no agent type specified`);
              }

              if (
                step.step_type === 'debate' &&
                (!step.config.agents || (step.config.agents as string[]).length < 2)
              ) {
                errors.push(`Debate step "${step.name}" needs at least 2 agents`);
              }
            }

            set({ validationErrors: errors }, false, 'validate');
            return errors;
          },

          // Execution preview
          openExecutionPreview: () =>
            set(
              (state) => ({ executionPreview: { ...state.executionPreview, isOpen: true } }),
              false,
              'openExecutionPreview',
            ),

          closeExecutionPreview: () =>
            set({ executionPreview: { ...initialPreviewState } }, false, 'closeExecutionPreview'),

          setSimulationResult: (result) =>
            set(
              (state) => ({
                executionPreview: { ...state.executionPreview, result, isRunning: false },
              }),
              false,
              'setSimulationResult',
            ),

          setSimulationRunning: (running) =>
            set(
              (state) => ({ executionPreview: { ...state.executionPreview, isRunning: running } }),
              false,
              'setSimulationRunning',
            ),

          // Workflow list
          setWorkflows: (workflows) => set({ workflows }, false, 'setWorkflows'),
          setTemplates: (templates) => set({ templates }, false, 'setTemplates'),

          // Loading states
          setLoading: (loading) => set({ isLoading: loading }, false, 'setLoading'),
          setSaving: (saving) => set({ isSaving: saving }, false, 'setSaving'),
          setSaveError: (error) => set({ saveError: error }, false, 'setSaveError'),
          setLoadError: (error) => set({ loadError: error }, false, 'setLoadError'),

          // Undo/redo
          pushHistory: () => {
            const state = get();
            if (!state.currentWorkflow) return;

            const newHistory = state._history.slice(0, state._historyIndex + 1);
            newHistory.push(JSON.parse(JSON.stringify(state.currentWorkflow)));

            // Trim history if too long
            if (newHistory.length > MAX_HISTORY) {
              newHistory.shift();
            }

            set(
              { _history: newHistory, _historyIndex: newHistory.length - 1 },
              false,
              'pushHistory',
            );
          },

          undo: () => {
            const state = get();
            if (state._historyIndex <= 0) return;

            const newIndex = state._historyIndex - 1;
            const workflow = JSON.parse(JSON.stringify(state._history[newIndex]));

            set(
              { currentWorkflow: workflow, _historyIndex: newIndex, isDirty: true },
              false,
              'undo',
            );
          },

          redo: () => {
            const state = get();
            if (state._historyIndex >= state._history.length - 1) return;

            const newIndex = state._historyIndex + 1;
            const workflow = JSON.parse(JSON.stringify(state._history[newIndex]));

            set(
              { currentWorkflow: workflow, _historyIndex: newIndex, isDirty: true },
              false,
              'redo',
            );
          },

          // Reset
          resetBuilder: () =>
            set(
              {
                currentWorkflow: null,
                originalWorkflow: null,
                canvas: {
                  ...initialCanvasState,
                  selectedNodeIds: new Set(),
                  selectedEdgeIds: new Set(),
                },
                nodePalette: {
                  ...initialPaletteState,
                  expandedCategories: new Set(['agents', 'control']),
                },
                configPanel: { ...initialConfigPanelState },
                isDirty: false,
                isSaving: false,
                isLoading: false,
                saveError: null,
                loadError: null,
                validationErrors: [],
                executionPreview: { ...initialPreviewState },
                _history: [],
                _historyIndex: -1,
              },
              false,
              'resetBuilder',
            ),

          markClean: () => set({ isDirty: false }, false, 'markClean'),
        }),
        {
          name: 'workflow-builder-storage',
          partialize: (state) => ({
            // Only persist certain state
            nodePalette: { expandedCategories: Array.from(state.nodePalette.expandedCategories) },
          }),
        },
      ),
    ),
    { name: 'workflow-builder-store' },
  ),
);

// Re-export types and selectors
export * from './types';
export * from './selectors';
export * from './utils';
export * from './constants';
