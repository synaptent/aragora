'use client';

/**
 * UnifiedDAGCanvas - Main React Flow canvas for the unified DAG view.
 *
 * Renders nodes across swim-lane stages (Ideas → Goals → Actions → Orchestration)
 * with right-click AI operations, brain dump, and auto-flow.
 */

import { useCallback, useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type OnConnect,
  type Connection,
  type NodeMouseHandler,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import {
  useUnifiedDAG,
  STAGE_COLORS,
  type DAGNodeData,
  type DAGOperationResult,
  type DAGStage,
} from '@/hooks/useUnifiedDAG';
import { DAGStageLanes } from './DAGStageLanes';
import { NodeContextMenu } from './NodeContextMenu';
import { AIOperationPanel } from './AIOperationPanel';
import { ExecutionSidebar } from './ExecutionSidebar';
import { DAGToolbar } from './DAGToolbar';
import { ValueNode } from './nodes/ValueNode';
import { AgentAssignmentNode } from './nodes/AgentAssignmentNode';
import { ExecutionDAGNode } from './nodes/ExecutionDAGNode';
import { CrossStageEdge } from './edges/CrossStageEdge';

// ---------------------------------------------------------------------------
// Custom node/edge types
// ---------------------------------------------------------------------------

const nodeTypes = {
  ideasNode: ExecutionDAGNode,
  principlesNode: ExecutionDAGNode,
  goalsNode: ExecutionDAGNode,
  actionsNode: ExecutionDAGNode,
  orchestrationNode: ExecutionDAGNode,
  valueNode: ValueNode,
  agentAssignmentNode: AgentAssignmentNode,
  executionNode: ExecutionDAGNode,
};

const edgeTypes = { crossStage: CrossStageEdge };

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface UnifiedDAGCanvasProps {
  graphId: string;
}

export function UnifiedDAGCanvas({ graphId }: UnifiedDAGCanvasProps) {
  const dag = useUnifiedDAG(graphId);

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    nodeId: string;
    stage: DAGStage;
    x: number;
    y: number;
  } | null>(null);

  // AI operation result
  const [lastResult, setLastResult] = useState<DAGOperationResult | null>(null);
  const [showPanel, setShowPanel] = useState(false);

  // Execution sidebar state
  const [showExecution, setShowExecution] = useState(false);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  // Stage filter
  const [stageFilter, setStageFilter] = useState<string | null>(null);

  // Filter nodes by stage
  const filteredNodes = useMemo(() => {
    if (!stageFilter) return dag.nodes;
    return dag.nodes.filter((n) => (n.data as DAGNodeData).stage === stageFilter);
  }, [dag.nodes, stageFilter]);

  const filteredEdges = useMemo(() => {
    if (!stageFilter) return dag.edges;
    const visibleNodeIds = new Set(filteredNodes.map((node) => node.id));
    return dag.edges.filter(
      (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target),
    );
  }, [dag.edges, filteredNodes, stageFilter]);

  // Right-click handler
  const handleNodeContextMenu: NodeMouseHandler = useCallback((event, node) => {
    event.preventDefault();
    const nodeData = node.data as DAGNodeData;
    setContextMenu({ nodeId: node.id, stage: nodeData.stage, x: event.clientX, y: event.clientY });
  }, []);

  // Connect handler
  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      const edge = {
        ...connection,
        id: `${connection.source}-${connection.target}`,
        type: 'crossStage',
      };
      dag.addEdge(edge as Parameters<typeof dag.addEdge>[0]);
    },
    [dag],
  );

  // AI operation wrappers
  const withResult = useCallback(async (fn: () => Promise<DAGOperationResult | null>) => {
    setShowPanel(true);
    const result = await fn();
    if (result) setLastResult(result);
  }, []);

  const handleDebate = useCallback(
    (nodeId: string) => withResult(() => dag.debateNode(nodeId)),
    [dag, withResult],
  );
  const handleDecompose = useCallback(
    (nodeId: string) => withResult(() => dag.decomposeNode(nodeId)),
    [dag, withResult],
  );
  const handlePrioritize = useCallback(
    (nodeId: string) => withResult(() => dag.prioritizeChildren(nodeId)),
    [dag, withResult],
  );
  const handleAssignAgents = useCallback(
    (nodeId: string) => withResult(() => dag.assignAgents(nodeId)),
    [dag, withResult],
  );
  const handleExecute = useCallback(
    (nodeId: string) => withResult(() => dag.executeNode(nodeId)),
    [dag, withResult],
  );
  const handleFindPrecedents = useCallback(
    (nodeId: string) => withResult(() => dag.findPrecedents(nodeId)),
    [dag, withResult],
  );

  const handleBrainDump = useCallback((_text: string) => {
    // Brain dump text is handled by the toolbar's auto-flow
  }, []);

  const handleAutoFlow = useCallback(
    (ideas: string[]) => withResult(() => dag.autoFlow(ideas)),
    [dag, withResult],
  );

  // Execution handlers
  const handleValidate = useCallback(() => {
    const errors = dag.validateGraph();
    setValidationErrors(errors);
  }, [dag]);

  const handleExecuteAll = useCallback(async () => {
    const errors = dag.validateGraph();
    setValidationErrors(errors);
    if (errors.length > 0) return;
    await dag.executeAllReady();
  }, [dag]);

  const handleAutoAdvance = useCallback(async () => {
    await dag.autoAdvanceAll();
  }, [dag]);

  const _handleExecuteNode = useCallback(
    (nodeId: string) => withResult(() => dag.executeNode(nodeId)),
    [dag, withResult],
  );

  const interactiveNodes = useMemo(
    () =>
      filteredNodes.map((node) => ({
        ...node,
        data: { ...(node.data as DAGNodeData), onExecuteNode: _handleExecuteNode },
      })),
    [filteredNodes, _handleExecuteNode],
  );

  return (
    <div className="flex flex-col h-full">
      <DAGToolbar
        onBrainDump={handleBrainDump}
        onAutoFlow={handleAutoFlow}
        onUndo={dag.undo}
        onRedo={dag.redo}
        canUndo={dag.canUndo}
        canRedo={dag.canRedo}
        loading={dag.operationLoading || dag.batchExecuting}
        stageFilter={stageFilter}
        onStageFilterChange={setStageFilter}
      >
        {/* Execution toggle button */}
        <div className="w-px h-6 bg-border" />
        <button
          onClick={() => setShowExecution(!showExecution)}
          className={`px-3 py-1.5 text-sm font-theme-data rounded transition-colors ${
            showExecution
              ? 'bg-emerald-600 text-white'
              : 'bg-surface border border-border text-text-muted hover:text-text'
          }`}
          data-testid="execution-toggle"
        >
          {dag.graphStats.completionPct > 0
            ? `Execution (${dag.graphStats.completionPct}%)`
            : 'Execution'}
        </button>
      </DAGToolbar>

      <div className="flex flex-1 overflow-hidden relative">
        <div className="flex-1 h-full relative">
          <DAGStageLanes activeStage={stageFilter as DAGStage | null} />
          <ReactFlow
            nodes={interactiveNodes}
            edges={filteredEdges}
            onNodesChange={(changes) => {
              // Apply position changes directly
              dag.setNodes((nds) => {
                const updated = [...nds];
                for (const change of changes) {
                  if (change.type === 'position' && change.position) {
                    const idx = updated.findIndex((n) => n.id === change.id);
                    if (idx >= 0) {
                      updated[idx] = { ...updated[idx], position: change.position };
                    }
                  }
                }
                return updated;
              });
            }}
            onConnect={onConnect}
            onNodeContextMenu={handleNodeContextMenu}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            className="bg-bg"
          >
            <Background color="#334155" gap={20} />
            <Controls />
            <MiniMap
              nodeColor={(node) => {
                const data = node.data as DAGNodeData;
                return STAGE_COLORS[data.stage] || '#6366f1';
              }}
              className="!bg-surface !border-border"
            />
          </ReactFlow>
        </div>

        {/* Context Menu */}
        {contextMenu && (
          <NodeContextMenu
            nodeId={contextMenu.nodeId}
            stage={contextMenu.stage}
            x={contextMenu.x}
            y={contextMenu.y}
            onClose={() => setContextMenu(null)}
            onDebate={handleDebate}
            onDecompose={handleDecompose}
            onPrioritize={handlePrioritize}
            onAssignAgents={handleAssignAgents}
            onExecute={handleExecute}
            onFindPrecedents={handleFindPrecedents}
            onDelete={dag.deleteNode}
          />
        )}

        {/* AI Operation Panel */}
        {showPanel && (
          <AIOperationPanel
            loading={dag.operationLoading}
            error={dag.operationError}
            result={lastResult}
            onDismiss={() => {
              setShowPanel(false);
              setLastResult(null);
            }}
          />
        )}

        {/* Execution Sidebar */}
        {showExecution && (
          <ExecutionSidebar
            nodes={dag.nodes}
            executing={dag.batchExecuting}
            onExecuteAll={handleExecuteAll}
            onAutoAdvance={handleAutoAdvance}
            onValidate={handleValidate}
            validationErrors={validationErrors}
            executionHistory={dag.executionHistory}
            onClose={() => setShowExecution(false)}
          />
        )}
      </div>
    </div>
  );
}
