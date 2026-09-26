'use client';

import { useCallback, useState, useRef, useMemo } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type NodeTypes,
  type OnConnect,
  Panel,
  BackgroundVariant,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import {
  DebateNode,
  TaskNode,
  DecisionNode,
  HumanCheckpointNode,
  MemoryReadNode,
  MemoryWriteNode,
  ParallelNode,
  LoopNode,
} from './nodes';
import { NodePalette } from './NodePalette';
import { PropertyEditor } from './PropertyEditor';
import type {
  WorkflowNode,
  WorkflowEdge,
  WorkflowStepType,
  WorkflowNodeData,
  DebateNodeData,
  TaskNodeData,
  DecisionNodeData,
  HumanCheckpointNodeData,
  MemoryReadNodeData,
  MemoryWriteNodeData,
  ParallelNodeData,
  LoopNodeData,
} from './types';

// Custom node types mapping
const nodeTypes: NodeTypes = {
  debate: DebateNode,
  task: TaskNode,
  decision: DecisionNode,
  human_checkpoint: HumanCheckpointNode,
  memory_read: MemoryReadNode,
  memory_write: MemoryWriteNode,
  parallel: ParallelNode,
  loop: LoopNode,
};

// Default data for each node type
function getDefaultNodeData(type: WorkflowStepType): WorkflowNodeData {
  const base = { stepId: `step-${Date.now()}` };

  switch (type) {
    case 'debate':
      return {
        ...base,
        type: 'debate',
        label: 'New Debate',
        agents: ['claude', 'gpt4'],
        rounds: 2,
      } as DebateNodeData;
    case 'task':
      return { ...base, type: 'task', label: 'New Task', taskType: 'transform' } as TaskNodeData;
    case 'decision':
      return {
        ...base,
        type: 'decision',
        label: 'Decision Point',
        condition: 'condition_met',
      } as DecisionNodeData;
    case 'human_checkpoint':
      return {
        ...base,
        type: 'human_checkpoint',
        label: 'Human Review',
        approvalType: 'review',
      } as HumanCheckpointNodeData;
    case 'memory_read':
      return {
        ...base,
        type: 'memory_read',
        label: 'Read Memory',
        queryTemplate: '',
        domains: [],
      } as MemoryReadNodeData;
    case 'memory_write':
      return {
        ...base,
        type: 'memory_write',
        label: 'Write Memory',
        domain: '',
      } as MemoryWriteNodeData;
    case 'parallel':
      return {
        ...base,
        type: 'parallel',
        label: 'Parallel Execution',
        branches: [],
      } as ParallelNodeData;
    case 'loop':
      return {
        ...base,
        type: 'loop',
        label: 'Loop',
        maxIterations: 10,
        condition: 'continue',
      } as LoopNodeData;
    default:
      return { ...base, type: 'task', label: 'New Node', taskType: 'transform' } as TaskNodeData;
  }
}

interface WorkflowCanvasProps {
  initialNodes?: WorkflowNode[];
  initialEdges?: WorkflowEdge[];
  onSave?: (nodes: WorkflowNode[], edges: WorkflowEdge[]) => void;
  onExecute?: (nodes: WorkflowNode[], edges: WorkflowEdge[]) => void;
  isExecuting?: boolean;
  readOnly?: boolean;
}

export function WorkflowCanvas({
  initialNodes = [],
  initialEdges = [],
  onSave,
  onExecute,
  isExecuting = false,
  readOnly = false,
}: WorkflowCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [, setDraggedType] = useState<WorkflowStepType | null>(null);

  // Get selected node data
  const selectedNode = useMemo((): WorkflowNodeData | null => {
    if (!selectedNodeId) return null;
    const node = nodes.find((n) => n.id === selectedNodeId);
    return (node?.data as WorkflowNodeData) || null;
  }, [nodes, selectedNodeId]);

  // Handle connection between nodes
  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) =>
        addEdge(
          { ...connection, animated: true, style: { stroke: '#10b981', strokeWidth: 2 } },
          eds,
        ),
      );
    },
    [setEdges],
  );

  // Handle node selection
  const onNodeClick = useCallback((_: React.MouseEvent, node: WorkflowNode) => {
    setSelectedNodeId(node.id);
  }, []);

  // Handle canvas click (deselect)
  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  // Handle drag start from palette
  const onDragStart = useCallback((type: WorkflowStepType) => {
    setDraggedType(type);
  }, []);

  // Handle drag over canvas
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  // Handle drop on canvas
  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const type = event.dataTransfer.getData('application/reactflow') as WorkflowStepType;
      if (!type || !reactFlowWrapper.current) return;

      const rect = reactFlowWrapper.current.getBoundingClientRect();
      const position = {
        x: event.clientX - rect.left - 90, // Center node
        y: event.clientY - rect.top - 40,
      };

      const newNode: WorkflowNode = {
        id: `node-${Date.now()}`,
        type,
        position,
        data: getDefaultNodeData(type),
      };

      setNodes((nds) => [...nds, newNode]);
      setSelectedNodeId(newNode.id);
      setDraggedType(null);
    },
    [setNodes],
  );

  // Handle property updates
  const onPropertyUpdate = useCallback(
    (updates: Partial<WorkflowNodeData>) => {
      if (!selectedNodeId) return;

      setNodes((nds) =>
        nds.map((node) =>
          node.id === selectedNodeId
            ? ({ ...node, data: { ...node.data, ...updates } } as WorkflowNode)
            : node,
        ),
      );
    },
    [selectedNodeId, setNodes],
  );

  // Handle node deletion
  const onDeleteNode = useCallback(() => {
    if (!selectedNodeId) return;

    setNodes((nds) => nds.filter((n) => n.id !== selectedNodeId));
    setEdges((eds) =>
      eds.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId),
    );
    setSelectedNodeId(null);
  }, [selectedNodeId, setNodes, setEdges]);

  // Handle save
  const handleSave = useCallback(() => {
    onSave?.(nodes as WorkflowNode[], edges as WorkflowEdge[]);
  }, [nodes, edges, onSave]);

  // Handle execute
  const handleExecute = useCallback(() => {
    onExecute?.(nodes as WorkflowNode[], edges as WorkflowEdge[]);
  }, [nodes, edges, onExecute]);

  return (
    <div className="flex h-full bg-bg">
      {/* Node Palette (left sidebar) */}
      {!readOnly && (
        <div className="w-64 flex-shrink-0">
          <NodePalette onDragStart={onDragStart} />
        </div>
      )}

      {/* Canvas */}
      <div ref={reactFlowWrapper} className="flex-1 h-full" onDragOver={onDragOver} onDrop={onDrop}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={readOnly ? undefined : onNodesChange}
          onEdgesChange={readOnly ? undefined : onEdgesChange}
          onConnect={readOnly ? undefined : onConnect}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          nodeTypes={nodeTypes}
          fitView
          snapToGrid
          snapGrid={[16, 16]}
          defaultEdgeOptions={{ animated: true, style: { stroke: '#10b981', strokeWidth: 2 } }}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#333" />
          <Controls
            className="bg-surface border border-border rounded"
            showInteractive={!readOnly}
          />
          <MiniMap
            className="bg-surface border border-border rounded"
            nodeColor={(node) => {
              switch (node.type) {
                case 'debate':
                  return '#a855f7';
                case 'task':
                  return '#3b82f6';
                case 'decision':
                  return '#eab308';
                case 'human_checkpoint':
                  return '#22c55e';
                case 'memory_read':
                case 'memory_write':
                  return '#06b6d4';
                case 'parallel':
                  return '#f97316';
                case 'loop':
                  return '#ec4899';
                default:
                  return '#6b7280';
              }
            }}
          />

          {/* Top toolbar */}
          <Panel position="top-center" className="flex gap-2">
            {!readOnly && (
              <>
                <button
                  onClick={handleSave}
                  className="px-4 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm font-bold hover:bg-[var(--accent)]/80 transition-colors rounded"
                >
                  SAVE WORKFLOW
                </button>
                {onExecute && (
                  <button
                    onClick={handleExecute}
                    disabled={isExecuting || nodes.length === 0}
                    className={`px-4 py-2 font-theme-data text-sm font-bold transition-colors rounded flex items-center gap-2 ${
                      isExecuting || nodes.length === 0
                        ? 'bg-surface border border-border text-text-muted cursor-not-allowed'
                        : 'bg-blue-600 text-white hover:bg-blue-500'
                    }`}
                  >
                    {isExecuting ? (
                      <>
                        <span className="animate-spin">⚡</span>
                        <span>EXECUTING...</span>
                      </>
                    ) : (
                      <>
                        <span>▶</span>
                        <span>EXECUTE</span>
                      </>
                    )}
                  </button>
                )}
                <button
                  onClick={() => {
                    setNodes([]);
                    setEdges([]);
                    setSelectedNodeId(null);
                  }}
                  className="px-4 py-2 bg-surface border border-border text-text font-theme-data text-sm hover:border-text transition-colors rounded"
                >
                  CLEAR
                </button>
              </>
            )}
          </Panel>

          {/* Stats panel */}
          <Panel position="bottom-left" className="bg-surface/90 border border-border rounded p-2">
            <div className="text-xs font-theme-data text-text-muted">
              <span className="text-text">{nodes.length}</span> nodes |{' '}
              <span className="text-text">{edges.length}</span> connections
            </div>
          </Panel>
        </ReactFlow>
      </div>

      {/* Property Editor (right sidebar) */}
      {!readOnly && (
        <div className="w-72 flex-shrink-0">
          <PropertyEditor node={selectedNode} onUpdate={onPropertyUpdate} onDelete={onDeleteNode} />
        </div>
      )}
    </div>
  );
}

export default WorkflowCanvas;
