/**
 * Constants for Workflow Builder Store
 */

import type {
  CanvasState,
  NodePaletteState,
  ConfigPanelState,
  ExecutionPreviewState,
} from './types';

export const MAX_HISTORY = 50;

export const initialCanvasState: CanvasState = {
  zoom: 1,
  panX: 0,
  panY: 0,
  selectedNodeIds: new Set<string>(),
  selectedEdgeIds: new Set<string>(),
  isDragging: false,
  draggedNodeId: null,
};

export const initialPaletteState: NodePaletteState = {
  searchQuery: '',
  selectedCategory: null,
  expandedCategories: new Set<string>(['agents', 'control']),
};

export const initialConfigPanelState: ConfigPanelState = {
  isOpen: false,
  selectedNodeId: null,
  pendingChanges: null,
};

export const initialPreviewState: ExecutionPreviewState = {
  isOpen: false,
  isRunning: false,
  result: null,
};
