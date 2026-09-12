'use client';

import { useState, useCallback } from 'react';
import { useApi } from './useApi';
import type { PipelineResultResponse, PipelineStageType } from '@/components/pipeline-canvas/types';

interface PipelineCreateResponse {
  pipeline_id: string;
  stage_status: Record<PipelineStageType, string>;
  result: PipelineResultResponse;
  [key: string]: unknown;
}

interface PipelineAdvanceResponse {
  pipeline_id: string;
  advanced_to: string;
  stage_status: Record<PipelineStageType, string>;
  result: PipelineResultResponse;
}

/** Pre-built demo pipeline for "Try Demo" */
function getDemoPipeline(): PipelineResultResponse {
  return {
    pipeline_id: 'demo-pipeline-001',
    principles: null,
    ideas: {
      nodes: [
        {
          id: 'idea-1',
          type: 'ideaNode',
          position: { x: 100, y: 100 },
          data: {
            label: 'Build a rate limiter',
            idea_type: 'concept',
            stage: 'ideas',
            full_content: 'Implement a token bucket rate limiter for API endpoints',
            content_hash: 'abc12345',
          },
          style: {},
        },
        {
          id: 'idea-2',
          type: 'ideaNode',
          position: { x: 100, y: 250 },
          data: {
            label: 'Add caching layer',
            idea_type: 'concept',
            stage: 'ideas',
            full_content: 'Redis-backed caching for frequently accessed data',
            content_hash: 'def45678',
          },
          style: {},
        },
        {
          id: 'idea-3',
          type: 'ideaNode',
          position: { x: 100, y: 400 },
          data: {
            label: 'Improve API documentation',
            idea_type: 'insight',
            stage: 'ideas',
            full_content: 'OpenAPI spec generation with interactive playground',
            content_hash: 'ghi78901',
          },
          style: {},
        },
        {
          id: 'idea-4',
          type: 'ideaNode',
          position: { x: 350, y: 175 },
          data: {
            label: 'Performance monitoring',
            idea_type: 'question',
            stage: 'ideas',
            full_content: 'How do we measure API response times end-to-end?',
            content_hash: 'jkl01234',
          },
          style: {},
        },
      ],
      edges: [
        {
          id: 'e-1-4',
          source: 'idea-1',
          target: 'idea-4',
          type: 'bezier',
          label: 'supports',
          animated: true,
        },
        {
          id: 'e-2-4',
          source: 'idea-2',
          target: 'idea-4',
          type: 'bezier',
          label: 'supports',
          animated: true,
        },
      ],
      metadata: { stage: 'ideas', canvas_name: 'Demo Ideas' },
    },
    goals: {
      id: 'goals-demo',
      goals: [
        {
          id: 'goal-1',
          title: 'Achieve: API reliability under load',
          type: 'goal',
          priority: 'critical',
          description: 'Ensure API maintains <200ms P99 latency under 10K req/s',
          dependencies: [],
          source_idea_ids: ['idea-1', 'idea-2'],
          confidence: 0.85,
        },
        {
          id: 'goal-2',
          title: 'Implement: Developer experience improvements',
          type: 'strategy',
          priority: 'high',
          description: 'Interactive API docs with auto-generated examples',
          dependencies: [],
          source_idea_ids: ['idea-3'],
          confidence: 0.7,
        },
        {
          id: 'goal-3',
          title: 'Complete: Observability setup',
          type: 'milestone',
          priority: 'medium',
          description: 'End-to-end latency monitoring with alerting',
          dependencies: ['goal-1'],
          source_idea_ids: ['idea-4'],
          confidence: 0.6,
        },
      ],
      provenance: [
        {
          source_node_id: 'idea-1',
          source_stage: 'ideas',
          target_node_id: 'goal-1',
          target_stage: 'goals',
          content_hash: 'abc12345',
          timestamp: Date.now(),
          method: 'structural_extraction',
        },
        {
          source_node_id: 'idea-2',
          source_stage: 'ideas',
          target_node_id: 'goal-1',
          target_stage: 'goals',
          content_hash: 'def45678',
          timestamp: Date.now(),
          method: 'structural_extraction',
        },
        {
          source_node_id: 'idea-3',
          source_stage: 'ideas',
          target_node_id: 'goal-2',
          target_stage: 'goals',
          content_hash: 'ghi78901',
          timestamp: Date.now(),
          method: 'structural_extraction',
        },
        {
          source_node_id: 'idea-4',
          source_stage: 'ideas',
          target_node_id: 'goal-3',
          target_stage: 'goals',
          content_hash: 'jkl01234',
          timestamp: Date.now(),
          method: 'structural_extraction',
        },
      ],
      transition: {
        id: 'trans-ideas-goals',
        from_stage: 'ideas',
        to_stage: 'goals',
        status: 'pending',
        confidence: 0.72,
        ai_rationale: 'Extracted 3 goals from 4 ideas using structural analysis',
      },
    },
    actions: {
      nodes: [
        {
          id: 'step-goal-1',
          type: 'actionNode',
          position: { x: 100, y: 100 },
          data: {
            label: 'Implement rate limiter',
            step_type: 'task',
            stage: 'actions',
            description: 'Token bucket algorithm with Redis backing',
            content_hash: 'act10000',
          },
          style: {},
        },
        {
          id: 'step-goal-2',
          type: 'actionNode',
          position: { x: 100, y: 250 },
          data: {
            label: 'Set up Redis cache',
            step_type: 'task',
            stage: 'actions',
            description: 'Configure Redis with eviction policies',
            content_hash: 'act20000',
          },
          style: {},
        },
        {
          id: 'step-goal-3',
          type: 'actionNode',
          position: { x: 350, y: 175 },
          data: {
            label: 'Generate OpenAPI spec',
            step_type: 'task',
            stage: 'actions',
            description: 'Auto-generate from route decorators',
            content_hash: 'act30000',
          },
          style: {},
        },
        {
          id: 'step-goal-4',
          type: 'actionNode',
          position: { x: 350, y: 325 },
          data: {
            label: 'Deploy monitoring stack',
            step_type: 'verification',
            stage: 'actions',
            description: 'Prometheus + Grafana dashboards',
            content_hash: 'act40000',
          },
          style: {},
        },
      ],
      edges: [
        {
          id: 't-1-2',
          source: 'step-goal-1',
          target: 'step-goal-2',
          type: 'step',
          label: 'then',
          animated: true,
        },
        {
          id: 't-2-4',
          source: 'step-goal-2',
          target: 'step-goal-4',
          type: 'step',
          label: 'then',
          animated: true,
        },
        {
          id: 't-3-4',
          source: 'step-goal-3',
          target: 'step-goal-4',
          type: 'step',
          label: 'then',
          animated: true,
        },
      ],
      metadata: { stage: 'actions', canvas_name: 'Action Plan' },
    },
    orchestration: {
      nodes: [
        {
          id: 'agent-analyst',
          type: 'orchestrationNode',
          position: { x: 0, y: 0 },
          data: {
            label: 'Analyst',
            orch_type: 'agent',
            agent_type: 'claude',
            capabilities: ['research', 'analysis'],
            stage: 'orchestration',
          },
          style: {},
        },
        {
          id: 'agent-implementer',
          type: 'orchestrationNode',
          position: { x: 300, y: 0 },
          data: {
            label: 'Implementer',
            orch_type: 'agent',
            agent_type: 'codex',
            capabilities: ['code', 'debugging'],
            stage: 'orchestration',
          },
          style: {},
        },
        {
          id: 'agent-reviewer',
          type: 'orchestrationNode',
          position: { x: 600, y: 0 },
          data: {
            label: 'Reviewer',
            orch_type: 'agent',
            agent_type: 'claude',
            capabilities: ['review', 'testing'],
            stage: 'orchestration',
          },
          style: {},
        },
        {
          id: 'exec-1',
          type: 'orchestrationNode',
          position: { x: 300, y: 150 },
          data: {
            label: 'Implement rate limiter',
            orch_type: 'agent_task',
            assigned_agent: 'agent-implementer',
            stage: 'orchestration',
          },
          style: {},
        },
        {
          id: 'exec-2',
          type: 'orchestrationNode',
          position: { x: 300, y: 280 },
          data: {
            label: 'Set up Redis cache',
            orch_type: 'agent_task',
            assigned_agent: 'agent-implementer',
            stage: 'orchestration',
          },
          style: {},
        },
        {
          id: 'exec-3',
          type: 'orchestrationNode',
          position: { x: 0, y: 150 },
          data: {
            label: 'Generate OpenAPI spec',
            orch_type: 'agent_task',
            assigned_agent: 'agent-analyst',
            stage: 'orchestration',
          },
          style: {},
        },
        {
          id: 'exec-4',
          type: 'orchestrationNode',
          position: { x: 600, y: 220 },
          data: {
            label: 'Verify monitoring stack',
            orch_type: 'verification',
            assigned_agent: 'agent-reviewer',
            stage: 'orchestration',
          },
          style: {},
        },
      ],
      edges: [
        {
          id: 'assign-impl-1',
          source: 'agent-implementer',
          target: 'exec-1',
          type: 'default',
          label: 'executes',
          style: { strokeDasharray: '3 3' },
        },
        {
          id: 'assign-impl-2',
          source: 'agent-implementer',
          target: 'exec-2',
          type: 'default',
          label: 'executes',
          style: { strokeDasharray: '3 3' },
        },
        {
          id: 'assign-analyst-3',
          source: 'agent-analyst',
          target: 'exec-3',
          type: 'default',
          label: 'executes',
          style: { strokeDasharray: '3 3' },
        },
        {
          id: 'assign-rev-4',
          source: 'agent-reviewer',
          target: 'exec-4',
          type: 'default',
          label: 'executes',
          style: { strokeDasharray: '3 3' },
        },
        {
          id: 'dep-1-2',
          source: 'exec-1',
          target: 'exec-2',
          type: 'smoothstep',
          label: 'blocks',
          animated: true,
        },
        {
          id: 'dep-2-4',
          source: 'exec-2',
          target: 'exec-4',
          type: 'smoothstep',
          label: 'blocks',
          animated: true,
        },
      ],
      metadata: { stage: 'orchestration', canvas_name: 'Orchestration Plan' },
    },
    transitions: [
      {
        id: 'trans-ideas-goals',
        from_stage: 'ideas',
        to_stage: 'goals',
        status: 'pending',
        confidence: 0.72,
        ai_rationale: 'Extracted 3 goals from 4 ideas using structural analysis',
        provenance: [],
        human_notes: '',
        created_at: Date.now(),
        reviewed_at: null,
      },
      {
        id: 'trans-goals-actions',
        from_stage: 'goals',
        to_stage: 'actions',
        status: 'pending',
        confidence: 0.7,
        ai_rationale: 'Decomposed 3 goals into 4 action steps',
        provenance: [],
        human_notes: '',
        created_at: Date.now(),
        reviewed_at: null,
      },
      {
        id: 'trans-actions-orch',
        from_stage: 'actions',
        to_stage: 'orchestration',
        status: 'pending',
        confidence: 0.6,
        ai_rationale: 'Assigned 4 tasks across 3 agents',
        provenance: [],
        human_notes: '',
        created_at: Date.now(),
        reviewed_at: null,
      },
    ],
    provenance: [
      {
        source_node_id: 'idea-1',
        source_stage: 'ideas',
        target_node_id: 'goal-1',
        target_stage: 'goals',
        content_hash: 'abc12345',
        timestamp: Date.now(),
        method: 'structural_extraction',
      },
      {
        source_node_id: 'idea-2',
        source_stage: 'ideas',
        target_node_id: 'goal-1',
        target_stage: 'goals',
        content_hash: 'def45678',
        timestamp: Date.now(),
        method: 'structural_extraction',
      },
      {
        source_node_id: 'idea-3',
        source_stage: 'ideas',
        target_node_id: 'goal-2',
        target_stage: 'goals',
        content_hash: 'ghi78901',
        timestamp: Date.now(),
        method: 'structural_extraction',
      },
      {
        source_node_id: 'idea-4',
        source_stage: 'ideas',
        target_node_id: 'goal-3',
        target_stage: 'goals',
        content_hash: 'jkl01234',
        timestamp: Date.now(),
        method: 'structural_extraction',
      },
    ],
    provenance_count: 4,
    stage_status: {
      ideas: 'complete',
      principles: 'pending',
      goals: 'pending',
      actions: 'pending',
      orchestration: 'pending',
    },
    integrity_hash: 'demo0123456789ab',
  };
}

interface PipelineExecuteConfig {
  /** Preview execution plan without running agents */
  dry_run?: boolean;
  /** Generate a DecisionReceipt on completion */
  enable_receipts?: boolean;
  /** Stages to include (default: all) */
  stages?: string[];
}

interface PipelineExecuteResponse {
  pipeline_id: string;
  execution_id: string;
  status: string;
  agent_tasks: number;
  total_orchestration_nodes: number;
  /** Only present in dry_run mode */
  stages_complete?: string[];
  stages_incomplete?: string[];
}

const STAGE_ORDER: PipelineStageType[] = ['ideas', 'goals', 'actions', 'orchestration'];

export function usePipeline() {
  const api = useApi<PipelineCreateResponse>();
  const advanceApi = useApi<PipelineAdvanceResponse>();
  const getApi = useApi<PipelineResultResponse>();
  const stageApi = useApi<{ stage: string; data: unknown }>();
  const executeApi = useApi<PipelineExecuteResponse>();
  const selfImproveApi = useApi<{
    data: { run_id: string; status: string; goal: string; pipeline_id: string };
  }>();
  const [pipelineData, setPipelineData] = useState<PipelineResultResponse | null>(null);
  const [isDemo, setIsDemo] = useState(false);

  const createFromDebate = useCallback(
    async (cartographerData: Record<string, unknown>, autoAdvance = true) => {
      const result = await api.post('/api/v1/canvas/pipeline/from-debate', {
        cartographer_data: cartographerData,
        auto_advance: autoAdvance,
      });
      if (result?.result) {
        setPipelineData(result.result);
      }
      return result;
    },
    [api],
  );

  const createFromIdeas = useCallback(
    async (ideas: string[], autoAdvance = true) => {
      const result = await api.post('/api/v1/canvas/pipeline/from-ideas', {
        ideas,
        auto_advance: autoAdvance,
      });
      if (result?.result) {
        setPipelineData(result.result);
      }
      return result;
    },
    [api],
  );

  const createFromBrainDump = useCallback(
    async (text: string, context?: string) => {
      const result = await api.post('/api/v1/canvas/pipeline/from-braindump', {
        text,
        context: context ?? '',
        use_unified_orchestrator: true,
        skip_execution: true,
      });
      if (result?.result) {
        setPipelineData(result.result);
      }
      return result;
    },
    [api],
  );

  const advanceStage = useCallback(
    async (pipelineId: string, targetStage: PipelineStageType) => {
      // Demo mode: advance stages client-side without backend call
      if (isDemo && pipelineData) {
        const targetIdx = STAGE_ORDER.indexOf(targetStage);
        if (targetIdx < 0) return null;
        const newStatus = { ...pipelineData.stage_status } as Record<PipelineStageType, string>;
        // Mark all stages up to target as complete
        for (let i = 0; i <= targetIdx; i++) {
          newStatus[STAGE_ORDER[i]] = 'complete';
        }
        // Mark transitions up to target as approved
        const newTransitions = (pipelineData.transitions || []).map((t) => {
          const toIdx = STAGE_ORDER.indexOf(t.to_stage as PipelineStageType);
          if (toIdx >= 0 && toIdx <= targetIdx) {
            return { ...t, status: 'approved' };
          }
          return t;
        });
        const updated = { ...pipelineData, stage_status: newStatus, transitions: newTransitions };
        setPipelineData(updated);
        return null;
      }
      const result = await advanceApi.post('/api/v1/canvas/pipeline/advance', {
        pipeline_id: pipelineId,
        target_stage: targetStage,
      });
      if (result?.result) {
        setPipelineData(result.result);
      }
      return result;
    },
    [advanceApi, isDemo, pipelineData],
  );

  const getPipeline = useCallback(
    async (pipelineId: string) => {
      const result = await getApi.get(`/api/v1/canvas/pipeline/${pipelineId}`);
      if (result) {
        setPipelineData(result);
      }
      return result;
    },
    [getApi],
  );

  const getStage = useCallback(
    (pipelineId: string, stage: PipelineStageType) =>
      stageApi.get(`/api/v1/canvas/pipeline/${pipelineId}/stage/${stage}`),
    [stageApi],
  );

  const executePipeline = useCallback(
    async (pipelineId: string, config?: PipelineExecuteConfig) => {
      const result = await executeApi.post(`/api/v1/canvas/pipeline/${pipelineId}/execute`, {
        dry_run: config?.dry_run ?? false,
        enable_receipts: config?.enable_receipts ?? true,
        ...(config?.stages ? { stages: config.stages } : {}),
      });
      return result;
    },
    [executeApi],
  );

  const executeWithSelfImprove = useCallback(
    async (
      pipelineId: string,
      options?: { budgetLimit?: number; dryRun?: boolean; requireApproval?: boolean },
    ) => {
      try {
        const res = await selfImproveApi.post(
          `/api/v1/canvas/pipeline/${pipelineId}/self-improve`,
          {
            budget_limit: options?.budgetLimit ?? 10,
            dry_run: options?.dryRun ?? false,
            require_approval: options?.requireApproval ?? true,
          },
        );
        return res as {
          data: { run_id: string; status: string; goal: string; pipeline_id: string };
        };
      } catch {
        return null;
      }
    },
    [selfImproveApi],
  );

  const loadDemo = useCallback(async () => {
    // Try server-side demo (creates a stored pipeline that can be executed)
    try {
      const result = await api.post('/api/v1/canvas/pipeline/demo', {});
      if (result?.result) {
        setPipelineData(result.result);
        setIsDemo(true);
        return;
      }
    } catch {
      // Server unavailable — fall back to client-side demo data
    }
    setPipelineData(getDemoPipeline());
    setIsDemo(true);
  }, [api]);

  const reset = useCallback(() => {
    setPipelineData(null);
    setIsDemo(false);
  }, []);

  const approveTransition = useCallback(
    async (
      pipelineId: string,
      fromStage: PipelineStageType,
      toStage: PipelineStageType,
      comment?: string,
    ) => {
      const result = await advanceApi.post('/api/v1/canvas/pipeline/approve-transition', {
        pipeline_id: pipelineId,
        from_stage: fromStage,
        to_stage: toStage,
        comment: comment ?? '',
      });
      if (result?.result) {
        setPipelineData(result.result);
      }
      return result;
    },
    [advanceApi],
  );

  const rejectTransition = useCallback(
    async (
      pipelineId: string,
      fromStage: PipelineStageType,
      toStage: PipelineStageType,
      reason?: string,
    ) => {
      const result = await advanceApi.post('/api/v1/canvas/pipeline/approve-transition', {
        pipeline_id: pipelineId,
        from_stage: fromStage,
        to_stage: toStage,
        approved: false,
        comment: reason ?? '',
      });
      if (result?.result) {
        setPipelineData(result.result);
      }
      return result;
    },
    [advanceApi],
  );

  return {
    pipelineData,
    setPipelineData,
    isDemo,
    createFromDebate,
    createFromIdeas,
    createFromBrainDump,
    advanceStage,
    getPipeline,
    getStage,
    executePipeline,
    executeWithSelfImprove,
    approveTransition,
    rejectTransition,
    loadDemo,
    reset,
    loading: api.loading || advanceApi.loading || getApi.loading,
    executing: executeApi.loading || selfImproveApi.loading,
    error:
      api.error || advanceApi.error || getApi.error || executeApi.error || selfImproveApi.error,
  };
}
