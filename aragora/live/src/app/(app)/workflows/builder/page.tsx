'use client';

import { useState, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { useToastContext } from '@/context/ToastContext';
import { logger } from '@/utils/logger';
import { useWorkflowBuilder } from '@/hooks';
import type {
  WorkflowNode,
  WorkflowEdge,
  WorkflowTemplate,
  WorkflowStepType,
  WorkflowNodeData,
} from '@/components/workflow-builder/types';

// Dynamic import for WorkflowCanvas to avoid SSR issues with React Flow
const WorkflowCanvas = dynamic(
  () => import('@/components/workflow-builder/WorkflowCanvas').then((m) => m.WorkflowCanvas),
  { ssr: false, loading: () => <CanvasLoadingState /> },
);

const TemplateBrowser = dynamic(
  () => import('@/components/workflow-builder/TemplateBrowser').then((m) => m.TemplateBrowser),
  { ssr: false },
);

function CanvasLoadingState() {
  return (
    <div className="flex-1 flex items-center justify-center bg-bg">
      <div className="text-center">
        <div className="animate-pulse text-[var(--accent)] text-xl font-theme-data mb-2">
          Loading Canvas...
        </div>
        <p className="text-text-muted text-sm">Initializing workflow builder</p>
      </div>
    </div>
  );
}

// Convert template steps to React Flow nodes
function templateToNodes(template: WorkflowTemplate): {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
} {
  const nodes: WorkflowNode[] = [];
  const edges: WorkflowEdge[] = [];
  const stepPositions: Record<string, { x: number; y: number }> = {};

  // Calculate positions in a vertical layout
  let yOffset = 50;
  const xCenter = 400;

  template.steps.forEach((step, _index) => {
    const position = { x: xCenter - 90, y: yOffset };
    stepPositions[step.id] = position;

    // Map step type to node type
    let nodeType: WorkflowStepType = 'task';
    if (step.type === 'debate') nodeType = 'debate';
    else if (step.type === 'decision') nodeType = 'decision';
    else if (step.type === 'human_checkpoint') nodeType = 'human_checkpoint';
    else if (step.type === 'memory_read') nodeType = 'memory_read';
    else if (step.type === 'memory_write') nodeType = 'memory_write';
    else if (step.type === 'parallel') nodeType = 'parallel';
    else if (step.type === 'loop') nodeType = 'loop';

    // Create node data based on step config
    const nodeData: Record<string, unknown> = {
      stepId: step.id,
      label: step.name,
      description: step.description,
      type: nodeType,
    };

    // Add type-specific data
    if (step.config) {
      if (nodeType === 'debate') {
        nodeData.agents = step.config.agents || ['claude', 'gpt4'];
        nodeData.rounds = step.config.rounds || 2;
        nodeData.topicTemplate = step.config.topic_template;
      } else if (nodeType === 'task') {
        nodeData.taskType = step.config.task_type || 'transform';
        nodeData.functionName = step.config.function_name;
        nodeData.template = step.config.template;
        nodeData.validationRules = step.config.validation_rules;
      } else if (nodeType === 'decision') {
        nodeData.condition = step.config.condition || 'true';
        nodeData.trueTarget = step.config.true_target;
        nodeData.falseTarget = step.config.false_target;
      } else if (nodeType === 'human_checkpoint') {
        nodeData.approvalType = step.config.approval_type || 'review';
        nodeData.requiredRole = step.config.required_role;
        nodeData.requiredRoles = step.config.required_roles;
        nodeData.checklist = step.config.checklist;
        nodeData.notificationRoles = step.config.notification_roles;
      } else if (nodeType === 'memory_read') {
        nodeData.queryTemplate = step.config.query_template || '';
        nodeData.domains = step.config.domains || [];
      } else if (nodeType === 'memory_write') {
        nodeData.domain = step.config.domain || '';
        nodeData.retentionYears = step.config.retention_years;
      }
    }

    const node = {
      id: step.id,
      type: nodeType,
      position,
      data: nodeData as unknown as WorkflowNodeData,
    };
    nodes.push(node as WorkflowNode);

    yOffset += 150; // Spacing between nodes
  });

  // Create edges from transitions
  template.transitions.forEach((transition, index) => {
    edges.push({
      id: `edge-${index}`,
      source: transition.from,
      target: transition.to,
      animated: true,
      style: { stroke: '#10b981', strokeWidth: 2 },
      data: { condition: transition.condition },
    });
  });

  return { nodes, edges };
}

export default function WorkflowBuilderPage() {
  const { showToast } = useToastContext();
  const [showTemplates, setShowTemplates] = useState(false);
  const [workflowName, setWorkflowName] = useState('Untitled Workflow');
  const [initialNodes, setInitialNodes] = useState<WorkflowNode[]>([]);
  const [initialEdges, setInitialEdges] = useState<WorkflowEdge[]>([]);
  const [key, setKey] = useState(0); // Force re-render when loading template
  const [isExecuting, setIsExecuting] = useState(false);

  // Hook provides save, execute, template operations with auto-save + keyboard shortcuts
  const {
    saveWorkflow: _saveWorkflow,
    createWorkflow,
    executeWorkflow,
    isSaving: _isSaving,
  } = useWorkflowBuilder({
    autoSave: false, // Manual save via canvas button
    enableKeyboardShortcuts: true,
  });

  const handleSave = useCallback(
    async (_nodes: WorkflowNode[], _edges: WorkflowEdge[]) => {
      try {
        await createWorkflow(workflowName);
        showToast('Workflow saved successfully', 'success');
      } catch {
        showToast('Failed to save workflow', 'error');
      }
    },
    [workflowName, showToast, createWorkflow],
  );

  const handleSelectTemplate = useCallback((template: WorkflowTemplate) => {
    const { nodes, edges } = templateToNodes(template);
    setInitialNodes(nodes);
    setInitialEdges(edges);
    setWorkflowName(template.name);
    setShowTemplates(false);
    setKey((k) => k + 1); // Force canvas re-render
  }, []);

  const handleSaveAndExecute = useCallback(
    async (_nodes: WorkflowNode[], _edges: WorkflowEdge[]) => {
      setIsExecuting(true);
      try {
        // Save workflow via hook (handles auth, retries)
        const _saved = await createWorkflow(workflowName);

        // Execute workflow via hook
        const executionId = await executeWorkflow({ inputs: {} });
        showToast(`Workflow started! Execution ID: ${executionId}`, 'success');

        // Redirect to runtime page to monitor execution
        window.location.href = `/workflows/runtime?execution=${executionId}`;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Execution failed';
        logger.error('Workflow execution error:', error);
        showToast(message, 'error');
      } finally {
        setIsExecuting(false);
      }
    },
    [workflowName, showToast, createWorkflow, executeWorkflow],
  );

  return (
    <div className="flex flex-col h-screen bg-bg">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-border bg-surface">
        <div className="flex items-center gap-4">
          <div>
            <input
              type="text"
              value={workflowName}
              onChange={(e) => setWorkflowName(e.target.value)}
              className="text-xl font-theme-data font-bold text-text bg-transparent border-none focus:outline-none focus:ring-2 focus:ring-acid-green rounded px-2 -mx-2"
            />
            <p className="text-sm text-text-muted font-theme-data">Workflow Builder</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowTemplates(true)}
            className="px-4 py-2 bg-surface border border-border text-text font-theme-data text-sm hover:border-[var(--accent)] transition-colors rounded flex items-center gap-2"
          >
            <span>📁</span>
            <span>Templates</span>
          </button>
          <a
            href="/workflows/runtime"
            className="px-4 py-2 bg-surface border border-border text-text-muted font-theme-data text-sm hover:text-text hover:border-text transition-colors rounded flex items-center gap-2"
          >
            <span>📊</span>
            <span>Runtime</span>
          </a>
          <a
            href="/workflows"
            className="px-4 py-2 bg-surface border border-border text-text-muted font-theme-data text-sm hover:text-text hover:border-text transition-colors rounded"
          >
            My Workflows
          </a>
        </div>
      </header>

      {/* Canvas */}
      <div className="flex-1 overflow-hidden">
        <WorkflowCanvas
          key={key}
          initialNodes={initialNodes}
          initialEdges={initialEdges}
          onSave={handleSave}
          onExecute={handleSaveAndExecute}
          isExecuting={isExecuting}
        />
      </div>

      {/* Template Browser Modal */}
      {showTemplates && (
        <TemplateBrowser onSelect={handleSelectTemplate} onClose={() => setShowTemplates(false)} />
      )}
    </div>
  );
}
