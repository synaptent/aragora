/**
 * Graph Debate visualization components.
 *
 * This module provides the visualization layer for graph-based debates
 * with D3 force-directed layouts, branch visualization, and node interaction.
 */

// Types
export type {
  DebateNode,
  Branch,
  MergeResult,
  GraphDebate,
  SimulationNode,
  SimulationLink,
  NodePosition,
} from './types';

export { BRANCH_COLORS, getBranchColor, getBranchBgColor, getEdgeColor } from './types';

// Components
export { GraphVisualization, NodeDetailPanel } from './GraphVisualization';
export type { GraphVisualizationProps, NodeDetailPanelProps } from './GraphVisualization';
