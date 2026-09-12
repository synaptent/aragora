/**
 * Utility functions for Graph Debate visualization.
 */

import * as d3Force from 'd3-force';
import type { DebateNode, SimulationNode, SimulationLink, NodePosition, Branch } from './types';

/**
 * Calculate node depths using BFS from root.
 */
export function calculateNodeDepths(
  nodes: Record<string, DebateNode>,
  rootId: string | null,
): Map<string, number> {
  const depths = new Map<string, number>();
  if (!rootId || !nodes[rootId]) return depths;

  const visited = new Set<string>();
  const queue: Array<{ id: string; depth: number }> = [{ id: rootId, depth: 0 }];

  while (queue.length > 0) {
    const { id, depth } = queue.shift()!;
    if (visited.has(id)) continue;
    visited.add(id);
    depths.set(id, depth);

    const node = nodes[id];
    if (node) {
      for (const childId of node.child_ids) {
        if (!visited.has(childId)) {
          queue.push({ id: childId, depth: depth + 1 });
        }
      }
    }
  }

  return depths;
}

/**
 * Create D3 force simulation for graph layout.
 */
export function createForceSimulation(
  nodes: Record<string, DebateNode>,
  rootId: string | null,
  width: number,
  height: number,
): {
  nodes: SimulationNode[];
  links: SimulationLink[];
  simulation: d3Force.Simulation<SimulationNode, SimulationLink>;
} {
  const depths = calculateNodeDepths(nodes, rootId);
  const maxDepth = Math.max(...Array.from(depths.values()), 0);
  const levelHeight = height / (maxDepth + 2);

  // Create simulation nodes
  const simNodes: SimulationNode[] = Object.values(nodes).map((node) => ({
    id: node.id,
    node,
    depth: depths.get(node.id) || 0,
    x: width / 2 + (Math.random() - 0.5) * 100,
    y: (depths.get(node.id) || 0) * levelHeight + 60,
  }));

  // Create links from parent-child relationships
  const simLinks: SimulationLink[] = [];
  Object.values(nodes).forEach((node) => {
    node.parent_ids.forEach((parentId) => {
      if (nodes[parentId]) {
        simLinks.push({ source: parentId, target: node.id, branchId: node.branch_id || 'main' });
      }
    });
  });

  // Create D3 force simulation
  const simulation = d3Force
    .forceSimulation<SimulationNode, SimulationLink>(simNodes)
    .force(
      'link',
      d3Force
        .forceLink<SimulationNode, SimulationLink>(simLinks)
        .id((d) => d.id)
        .distance(100)
        .strength(0.8),
    )
    .force('charge', d3Force.forceManyBody<SimulationNode>().strength(-300).distanceMax(400))
    .force('collide', d3Force.forceCollide<SimulationNode>().radius(50).strength(0.7))
    .force('x', d3Force.forceX<SimulationNode>(width / 2).strength(0.05))
    .force('y', d3Force.forceY<SimulationNode>((d) => d.depth * levelHeight + 60).strength(0.3))
    .alphaDecay(0.02)
    .velocityDecay(0.4);

  // Run simulation for initial layout
  simulation.tick(150);
  simulation.stop();

  return { nodes: simNodes, links: simLinks, simulation };
}

/**
 * Legacy layout calculation (fallback).
 */
export function calculateLayout(
  nodes: Record<string, DebateNode>,
  rootId: string | null,
  _branches: Record<string, Branch>,
): NodePosition[] {
  if (!rootId || !nodes[rootId]) return [];

  const { nodes: simNodes } = createForceSimulation(nodes, rootId, 800, 600);

  return simNodes.map((simNode) => ({
    x: simNode.x || 400,
    y: simNode.y || 60,
    node: simNode.node,
  }));
}

// Branch color mapping
const BRANCH_COLORS: Record<string, string> = {
  main: 'text-acid-green',
  'Branch-1': 'text-acid-cyan',
  'Branch-2': 'text-gold',
  'Branch-3': 'text-purple',
  'Branch-4': 'text-crimson',
};

export function getBranchColor(branchId: string): string {
  return BRANCH_COLORS[branchId] || 'text-text-muted';
}

export function getBranchBgColor(branchId: string): string {
  const colorMap: Record<string, string> = {
    main: 'bg-acid-green/20',
    'Branch-1': 'bg-acid-cyan/20',
    'Branch-2': 'bg-gold/20',
    'Branch-3': 'bg-purple/20',
    'Branch-4': 'bg-crimson/20',
  };
  return colorMap[branchId] || 'bg-surface';
}

export function getEdgeColor(branchId: string): string {
  const colorMap: Record<string, string> = {
    main: '#00ff00',
    'Branch-1': '#00ffff',
    'Branch-2': '#ffd700',
    'Branch-3': '#9966ff',
    'Branch-4': '#ff3333',
  };
  return colorMap[branchId] || '#666666';
}

/**
 * Node type icon mapping.
 */
export function getNodeTypeIcon(type: string): string {
  const icons: Record<string, string> = {
    root: 'O',
    proposal: 'P',
    critique: 'C',
    synthesis: 'S',
    branch_point: '/',
    merge_point: 'M',
    counterfactual: '?',
    conclusion: 'X',
  };
  return icons[type] || '.';
}
