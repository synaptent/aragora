'use client';

/**
 * useFractalNavigation - Drill-down navigation hook for fractal DAG canvas.
 *
 * Enables zooming into an idea to see its child goals, zooming into a goal
 * to see its actions, etc. Maintains a navigation stack so users can
 * drill down and back up through provenance chains.
 *
 * Keyboard: Enter to drill down on selected, Escape to drill up.
 */

import { useCallback, useEffect, useReducer, useMemo } from 'react';
import type { PipelineStageType, ProvenanceLink } from '../components/pipeline-canvas/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NavigationLevel {
  /** Stage being viewed at this level. */
  stage: PipelineStageType;
  /** If drilled into a specific node, its ID. Null for stage-level view. */
  nodeId: string | null;
  /** Human label for breadcrumb display. */
  label: string;
}

export interface FractalNavigationState {
  /** Stack of navigation levels. Top of stack is current view. */
  stack: NavigationLevel[];
  /** Currently selected node ID (for keyboard drill-down). */
  selectedNodeId: string | null;
}

interface FractalNavigationActions {
  /** Drill down into a node to see its children in the next stage. */
  drillDown: (nodeId: string, nodeLabel: string) => void;
  /** Go back up one level. */
  drillUp: () => void;
  /** Jump directly to a specific level in the stack. */
  jumpTo: (index: number) => void;
  /** Set the currently selected node (for keyboard navigation). */
  setSelected: (nodeId: string | null) => void;
  /** Reset to stage-level view. */
  reset: (stage?: PipelineStageType) => void;
}

export interface FractalNavigationResult extends FractalNavigationActions {
  /** Current navigation level (top of stack). */
  current: NavigationLevel;
  /** Full navigation stack for breadcrumb display. */
  breadcrumbs: NavigationLevel[];
  /** Whether we can drill up (stack depth > 1). */
  canDrillUp: boolean;
  /** Currently selected node ID. */
  selectedNodeId: string | null;
  /** Depth of current navigation (0 = root). */
  depth: number;
  /** Get child node IDs for a given node from provenance links. */
  getChildNodeIds: (nodeId: string) => string[];
}

// ---------------------------------------------------------------------------
// Stage order
// ---------------------------------------------------------------------------

const STAGE_ORDER: PipelineStageType[] = ['ideas', 'goals', 'actions', 'orchestration'];

function nextStage(stage: PipelineStageType): PipelineStageType | null {
  const idx = STAGE_ORDER.indexOf(stage);
  return idx >= 0 && idx < STAGE_ORDER.length - 1 ? STAGE_ORDER[idx + 1] : null;
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

type Action =
  | { type: 'DRILL_DOWN'; nodeId: string; label: string }
  | { type: 'DRILL_UP' }
  | { type: 'JUMP_TO'; index: number }
  | { type: 'SET_SELECTED'; nodeId: string | null }
  | { type: 'RESET'; stage: PipelineStageType };

function reducer(state: FractalNavigationState, action: Action): FractalNavigationState {
  switch (action.type) {
    case 'DRILL_DOWN': {
      const current = state.stack[state.stack.length - 1];
      const next = nextStage(current.stage);
      if (!next) return state; // Can't drill deeper than orchestration

      return {
        ...state,
        stack: [...state.stack, { stage: next, nodeId: action.nodeId, label: action.label }],
        selectedNodeId: null,
      };
    }

    case 'DRILL_UP': {
      if (state.stack.length <= 1) return state;
      return { ...state, stack: state.stack.slice(0, -1), selectedNodeId: null };
    }

    case 'JUMP_TO': {
      if (action.index < 0 || action.index >= state.stack.length) return state;
      return { ...state, stack: state.stack.slice(0, action.index + 1), selectedNodeId: null };
    }

    case 'SET_SELECTED': {
      return { ...state, selectedNodeId: action.nodeId };
    }

    case 'RESET': {
      return {
        stack: [
          {
            stage: action.stage,
            nodeId: null,
            label: action.stage.charAt(0).toUpperCase() + action.stage.slice(1),
          },
        ],
        selectedNodeId: null,
      };
    }

    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useFractalNavigation(
  initialStage: PipelineStageType = 'ideas',
  provenance: ProvenanceLink[] = [],
): FractalNavigationResult {
  const [state, dispatch] = useReducer(reducer, {
    stack: [
      {
        stage: initialStage,
        nodeId: null,
        label: initialStage.charAt(0).toUpperCase() + initialStage.slice(1),
      },
    ],
    selectedNodeId: null,
  });

  // Build parent->children lookup from provenance links
  const childrenMap = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const link of provenance) {
      const existing = map.get(link.source_node_id) ?? [];
      existing.push(link.target_node_id);
      map.set(link.source_node_id, existing);
    }
    return map;
  }, [provenance]);

  const getChildNodeIds = useCallback(
    (nodeId: string) => childrenMap.get(nodeId) ?? [],
    [childrenMap],
  );

  const drillDown = useCallback(
    (nodeId: string, nodeLabel: string) =>
      dispatch({ type: 'DRILL_DOWN', nodeId, label: nodeLabel }),
    [],
  );

  const drillUp = useCallback(() => dispatch({ type: 'DRILL_UP' }), []);
  const jumpTo = useCallback((index: number) => dispatch({ type: 'JUMP_TO', index }), []);
  const setSelected = useCallback(
    (nodeId: string | null) => dispatch({ type: 'SET_SELECTED', nodeId }),
    [],
  );
  const reset = useCallback(
    (stage?: PipelineStageType) => dispatch({ type: 'RESET', stage: stage ?? initialStage }),
    [initialStage],
  );

  // Keyboard shortcuts: Enter to drill down, Escape to drill up
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      if (e.key === 'Enter' && state.selectedNodeId) {
        e.preventDefault();
        // Find the label for the selected node — use ID as fallback
        drillDown(state.selectedNodeId, state.selectedNodeId);
      } else if (e.key === 'Escape' && state.stack.length > 1) {
        e.preventDefault();
        drillUp();
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [state.selectedNodeId, state.stack.length, drillDown, drillUp]);

  const current = state.stack[state.stack.length - 1];

  return {
    current,
    breadcrumbs: state.stack,
    canDrillUp: state.stack.length > 1,
    selectedNodeId: state.selectedNodeId,
    depth: state.stack.length - 1,
    getChildNodeIds,
    drillDown,
    drillUp,
    jumpTo,
    setSelected,
    reset,
  };
}
