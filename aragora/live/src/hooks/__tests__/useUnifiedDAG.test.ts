import type { Edge, Node } from '@xyflow/react';

import { mapServerGraphToReactFlow, validateDagGraph, type DAGNodeData } from '../useUnifiedDAG';

function makeDagNode(id: string, stage: DAGNodeData['stage']): Node<DAGNodeData> {
  return {
    id,
    type: `${stage}Node`,
    position: { x: 0, y: 0 },
    data: {
      label: id,
      description: '',
      stage,
      subtype: '',
      status: 'ready',
      priority: 0,
      metadata: {},
    },
  };
}

describe('useUnifiedDAG helpers', () => {
  it('maps persisted positions, data payloads, and cross-stage edges from graph snapshots', () => {
    const { nodes, edges } = mapServerGraphToReactFlow({
      nodes: [
        {
          id: 'idea-1',
          stage: 'ideas',
          node_subtype: 'concept',
          label: 'Capture latency budget',
          description: 'Clarify the guardrail',
          position_x: 48,
          position_y: 120,
          status: 'active',
          execution_status: 'in_progress',
          metadata: { agents: ['codex'] },
          data: { assignedAgent: 'codex' },
        },
        {
          id: 'goal-1',
          stage: 'goals',
          node_subtype: 'goal',
          label: 'Protect API latency',
          position_x: 640,
          position_y: 120,
          status: 'approved',
        },
      ],
      edges: [
        {
          id: 'edge-1',
          source_id: 'idea-1',
          target_id: 'goal-1',
          edge_type: 'derives',
          cross_stage: true,
          data: { weight: 0.8 },
        },
      ],
    });

    expect(nodes[0]).toMatchObject({
      id: 'idea-1',
      position: { x: 48, y: 120 },
      data: { stage: 'ideas', subtype: 'concept', status: 'running', assignedAgent: 'codex' },
    });

    expect(edges[0]).toMatchObject({
      id: 'edge-1',
      source: 'idea-1',
      target: 'goal-1',
      type: 'crossStage',
      data: expect.objectContaining({ edgeType: 'derives', crossStage: true, weight: 0.8 }),
    });
  });

  it('auto-layouts principles between ideas and goals using upstream ordering', () => {
    const { nodes } = mapServerGraphToReactFlow({
      nodes: [
        { id: 'idea-1', stage: 'ideas', node_subtype: 'concept', label: 'Idea A', position_y: 120 },
        { id: 'idea-2', stage: 'ideas', node_subtype: 'concept', label: 'Idea B', position_y: 320 },
        {
          id: 'principle-1',
          stage: 'principles',
          node_subtype: 'principle',
          label: 'Principle A',
          parent_ids: ['idea-1'],
        },
        {
          id: 'principle-2',
          stage: 'principles',
          node_subtype: 'principle',
          label: 'Principle B',
          parent_ids: ['idea-2'],
        },
        {
          id: 'goal-1',
          stage: 'goals',
          node_subtype: 'goal',
          label: 'Goal A',
          parent_ids: ['principle-1'],
        },
      ],
      edges: [],
    });

    const ideaOne = nodes.find((node) => node.id === 'idea-1');
    const principleOne = nodes.find((node) => node.id === 'principle-1');
    const principleTwo = nodes.find((node) => node.id === 'principle-2');
    const goalOne = nodes.find((node) => node.id === 'goal-1');

    expect(ideaOne?.position.x).toBeLessThan(principleOne?.position.x ?? 0);
    expect(principleOne?.position.x).toBeLessThan(goalOne?.position.x ?? 0);
    expect(principleOne?.position.y).toBeLessThan(principleTwo?.position.y ?? 0);
  });

  it('validates goals connected directly from ideas when principles are absent', () => {
    const nodes = [makeDagNode('idea-1', 'ideas'), makeDagNode('goal-1', 'goals')];
    const edges: Edge[] = [{ id: 'edge-1', source: 'idea-1', target: 'goal-1' }];

    expect(validateDagGraph(nodes, edges)).toEqual([]);
  });
});
