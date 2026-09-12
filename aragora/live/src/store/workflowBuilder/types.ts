/**
 * Types for Workflow Builder Store
 */

export type StepType =
  | 'agent'
  | 'debate'
  | 'quick_debate'
  | 'parallel'
  | 'conditional'
  | 'loop'
  | 'human_checkpoint'
  | 'memory_read'
  | 'memory_write'
  | 'task';

export type NodeCategory = 'agents' | 'control' | 'memory' | 'integration';

export interface Position {
  x: number;
  y: number;
}

export interface StepDefinition {
  id: string;
  name: string;
  step_type: StepType;
  config: Record<string, unknown>;
  next_steps: string[];
  position?: Position;
}

export interface TransitionRule {
  id: string;
  from_step: string;
  to_step: string;
  condition?: string;
  label?: string;
}

export interface WorkflowDefinition {
  id: string;
  name: string;
  description?: string;
  category?: string;
  steps: StepDefinition[];
  transitions: TransitionRule[];
  config?: { timeout_seconds?: number; max_tokens?: number; max_cost_usd?: number };
  version?: string;
  created_at?: string;
  updated_at?: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  workflow: WorkflowDefinition;
  preview_image?: string;
}

export interface WorkflowSimulationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  estimated_cost?: number;
  estimated_duration_ms?: number;
  step_order: string[];
}

// ============================================================================
// Store State
// ============================================================================

export interface CanvasState {
  zoom: number;
  panX: number;
  panY: number;
  selectedNodeIds: Set<string>;
  selectedEdgeIds: Set<string>;
  isDragging: boolean;
  draggedNodeId: string | null;
}

export interface NodePaletteState {
  searchQuery: string;
  selectedCategory: NodeCategory | null;
  expandedCategories: Set<string>;
}

export interface ConfigPanelState {
  isOpen: boolean;
  selectedNodeId: string | null;
  pendingChanges: Partial<StepDefinition> | null;
}

export interface ExecutionPreviewState {
  isOpen: boolean;
  isRunning: boolean;
  result: WorkflowSimulationResult | null;
}

export interface WorkflowBuilderState {
  // Current workflow being edited
  currentWorkflow: WorkflowDefinition | null;
  originalWorkflow: WorkflowDefinition | null;

  // Canvas state
  canvas: CanvasState;

  // Node palette
  nodePalette: NodePaletteState;

  // Configuration panel
  configPanel: ConfigPanelState;

  // Workflow list
  workflows: WorkflowDefinition[];
  templates: WorkflowTemplate[];

  // UI state
  isDirty: boolean;
  isSaving: boolean;
  isLoading: boolean;
  saveError: string | null;
  loadError: string | null;
  validationErrors: string[];

  // Execution preview
  executionPreview: ExecutionPreviewState;

  // Undo/redo history
  _history: WorkflowDefinition[];
  _historyIndex: number;
}

export interface WorkflowBuilderActions {
  // Workflow CRUD
  setCurrentWorkflow: (workflow: WorkflowDefinition | null) => void;
  createNewWorkflow: (name: string, description?: string) => WorkflowDefinition;
  updateWorkflowMetadata: (
    updates: Partial<Pick<WorkflowDefinition, 'name' | 'description' | 'category' | 'config'>>,
  ) => void;

  // Node operations
  addNode: (type: StepType, position: Position) => string;
  updateNode: (id: string, updates: Partial<StepDefinition>) => void;
  deleteNode: (id: string) => void;
  duplicateNode: (id: string) => string | null;

  // Edge operations
  addEdge: (fromId: string, toId: string, condition?: string) => string;
  updateEdge: (id: string, updates: Partial<TransitionRule>) => void;
  deleteEdge: (id: string) => void;

  // Canvas operations
  setZoom: (zoom: number) => void;
  setPan: (x: number, y: number) => void;
  selectNodes: (ids: string[]) => void;
  selectEdges: (ids: string[]) => void;
  clearSelection: () => void;
  setDragging: (isDragging: boolean, nodeId?: string | null) => void;

  // Node palette operations
  setSearchQuery: (query: string) => void;
  setSelectedCategory: (category: NodeCategory | null) => void;
  toggleCategory: (category: string) => void;

  // Config panel operations
  openConfigPanel: (nodeId: string) => void;
  closeConfigPanel: () => void;
  setPendingChanges: (changes: Partial<StepDefinition> | null) => void;
  applyPendingChanges: () => void;

  // Validation
  validate: () => string[];

  // Execution preview
  openExecutionPreview: () => void;
  closeExecutionPreview: () => void;
  setSimulationResult: (result: WorkflowSimulationResult | null) => void;
  setSimulationRunning: (running: boolean) => void;

  // Workflow list
  setWorkflows: (workflows: WorkflowDefinition[]) => void;
  setTemplates: (templates: WorkflowTemplate[]) => void;

  // Loading states
  setLoading: (loading: boolean) => void;
  setSaving: (saving: boolean) => void;
  setSaveError: (error: string | null) => void;
  setLoadError: (error: string | null) => void;

  // Undo/redo
  undo: () => void;
  redo: () => void;
  pushHistory: () => void;

  // Reset
  resetBuilder: () => void;
  markClean: () => void;
}

export type WorkflowBuilderStore = WorkflowBuilderState & WorkflowBuilderActions;
