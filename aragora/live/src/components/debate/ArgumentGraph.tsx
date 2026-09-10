'use client';

import { useMemo, useCallback } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { ArgumentNode, type ArgumentType } from './ArgumentNode';
import type { StreamEvent } from '@/types/events';

interface ArgumentGraphProps {
  events: StreamEvent[];
  className?: string;
}

const nodeTypes = { argumentNode: ArgumentNode };

/** Map event type to argument type for node coloring */
function eventToArgumentType(
  eventType: string,
  data: Record<string, unknown>,
): ArgumentType | null {
  switch (eventType) {
    case 'proposal':
      return 'proposal';
    case 'agent_message': {
      const role = (data.role as string) || '';
      if (role === 'critique' || role === 'critic') return 'critique';
      if (role === 'evidence') return 'evidence';
      if (data.is_proposal || data.proposal) return 'proposal';
      return 'proposal';
    }
    case 'critique':
      return 'critique';
    case 'evidence':
      return 'evidence';
    case 'concession':
      return 'concession';
    case 'vote':
      return 'vote';
    case 'consensus':
    case 'grounded_verdict':
      return 'consensus';
    default:
      return null;
  }
}

/** Edge color based on relationship type */
function edgeColor(sourceType: ArgumentType, targetType: ArgumentType): string {
  if (targetType === 'critique') return '#FF073A'; // refutes
  if (targetType === 'evidence') return '#39FF14'; // supports
  return '#00F0FF'; // responds_to
}

const X_SPACING = 320;
const Y_SPACING = 160;

export function ArgumentGraph({ events, className }: ArgumentGraphProps) {
  const { initialNodes, initialEdges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    const nodeIdMap = new Map<string, string>(); // event id -> node id
    const roundAgents = new Map<number, string[]>(); // round -> agents seen
    const prevByRound = new Map<number, string>(); // round -> last node id in that round

    let nodeIndex = 0;

    for (const event of events) {
      const d = event.data as Record<string, unknown>;
      const argType = eventToArgumentType(event.type, d);
      if (!argType) continue;

      const eventId = (d.id as string) || (d.message_id as string) || `node-${nodeIndex}`;
      const nodeId = `arg-${nodeIndex}`;
      const agent = (d.agent as string) || (d.agent_name as string) || event.agent || 'unknown';
      const round = (d.round as number) ?? event.round ?? 0;
      const content = (d.content as string) || (d.message as string) || (d.text as string) || '';

      // Track agent positions within rounds
      if (!roundAgents.has(round)) {
        roundAgents.set(round, []);
      }
      const agents = roundAgents.get(round)!;
      let agentIdx = agents.indexOf(agent);
      if (agentIdx === -1) {
        agentIdx = agents.length;
        agents.push(agent);
      }

      // Compute position: Y by round, X by agent index within round
      const x = agentIdx * X_SPACING;
      const y = round * Y_SPACING;

      nodes.push({
        id: nodeId,
        type: 'argumentNode',
        position: { x, y },
        data: {
          label: content.slice(0, 80) || argType,
          content,
          agent,
          round,
          argumentType: argType,
          timestamp: String(event.timestamp || ''),
        },
      });

      nodeIdMap.set(eventId, nodeId);

      // Build edges
      const responseTarget = (d.in_response_to as string) || (d.target_id as string);
      if (responseTarget && nodeIdMap.has(responseTarget)) {
        const sourceId = nodeIdMap.get(responseTarget)!;
        const sourceNode = nodes.find((n) => n.id === sourceId);
        const sourceArgType =
          (sourceNode?.data as { argumentType?: ArgumentType })?.argumentType || 'proposal';
        edges.push({
          id: `edge-${sourceId}-${nodeId}`,
          source: sourceId,
          target: nodeId,
          style: { stroke: edgeColor(sourceArgType, argType), strokeWidth: 2 },
          animated: argType === 'critique',
        });
      } else {
        // Connect sequentially within the same round
        const prevId = prevByRound.get(round);
        if (prevId) {
          const prevNode = nodes.find((n) => n.id === prevId);
          const prevArgType =
            (prevNode?.data as { argumentType?: ArgumentType })?.argumentType || 'proposal';
          edges.push({
            id: `edge-${prevId}-${nodeId}`,
            source: prevId,
            target: nodeId,
            style: { stroke: edgeColor(prevArgType, argType), strokeWidth: 1.5, opacity: 0.6 },
          });
        }
      }

      prevByRound.set(round, nodeId);
      nodeIndex++;
    }

    return { initialNodes: nodes, initialEdges: edges };
  }, [events]);

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [graphEdges, , onEdgesChange] = useEdgesState(initialEdges);

  const defaultViewport = useMemo(() => ({ x: 50, y: 50, zoom: 0.8 }), []);

  const minimapNodeColor = useCallback((node: Node) => {
    const argType = (node.data as { argumentType?: string })?.argumentType;
    const colors: Record<string, string> = {
      proposal: '#39FF14',
      critique: '#FF073A',
      evidence: '#00F0FF',
      concession: '#FFD700',
      vote: '#BF40BF',
      consensus: '#FFFFFF',
    };
    return colors[argType || ''] || '#00F0FF';
  }, []);

  const hasNodes = initialNodes.length > 0;

  return (
    <div
      className={`${className || 'h-[500px]'} w-full rounded border border-[var(--border)] bg-[var(--bg)]`}
    >
      {!hasNodes ? (
        <div className="flex items-center justify-center h-full">
          <p className="font-theme-data text-sm text-[var(--text-muted)]">
            Start a debate to see the argument graph
          </p>
        </div>
      ) : (
        <ReactFlow
          nodes={nodes}
          edges={graphEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          defaultViewport={defaultViewport}
          fitView
          minZoom={0.2}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="var(--border)" gap={24} size={1} />
          <Controls className="!bg-[var(--surface)] !border-[var(--border)] !shadow-none [&_button]:!bg-[var(--surface)] [&_button]:!border-[var(--border)] [&_button]:!fill-[var(--text-muted)] [&_button:hover]:!fill-[var(--acid-green)]" />
          <MiniMap
            nodeColor={minimapNodeColor}
            maskColor="rgba(0, 0, 0, 0.7)"
            className="!bg-[var(--surface)] !border-[var(--border)]"
          />
        </ReactFlow>
      )}
    </div>
  );
}
