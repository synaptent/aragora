'use client';

import { Suspense, useState, useCallback, useEffect, useMemo } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import { usePipeline } from '@/hooks/usePipeline';
import { usePipelineWebSocket } from '@/hooks/usePipelineWebSocket';
import { useSWRFetch } from '@/hooks/useSWRFetch';
import { StatusBadge } from '@/components/pipeline-canvas/StatusBadge';
import { ExecutionProgressOverlay } from '@/components/pipeline-canvas/ExecutionProgressOverlay';
import { FeedbackLoopPanel } from '@/components/pipeline-canvas/FeedbackLoopPanel';
import { AutoTransitionSuggestion } from '@/components/pipeline-canvas/AutoTransitionSuggestion';
import type { TransitionSuggestion } from '@/components/pipeline-canvas/AutoTransitionSuggestion';
import type { PipelineStageType, PipelineResultResponse, ExecutionStatus } from '@/components/pipeline-canvas/types';
import { UseCaseWizard } from '@/components/wizards/UseCaseWizard';

const PipelineCanvas = dynamic(
  () => import('@/components/pipeline-canvas/PipelineCanvas').then((m) => m.PipelineCanvas),
  { ssr: false, loading: () => <CanvasLoadingState /> },
);

const UnifiedPipelineCanvas = dynamic(
  () => import('@/components/pipeline-canvas/UnifiedPipelineCanvas').then((m) => m.UnifiedPipelineCanvas),
  { ssr: false, loading: () => <CanvasLoadingState /> },
);

const FractalPipelineCanvas = dynamic(
  () => import('@/components/pipeline-canvas/FractalPipelineCanvas').then((m) => m.FractalPipelineCanvas),
  { ssr: false, loading: () => <CanvasLoadingState /> },
);

const UnifiedDAGCanvas = dynamic(
  () => import('@/components/unified-dag/UnifiedDAGCanvas').then((m) => m.UnifiedDAGCanvas),
  { ssr: false, loading: () => <CanvasLoadingState /> },
);

const ProvenanceExplorer = dynamic(
  () => import('@/components/ProvenanceExplorer').then((m) => m.ProvenanceExplorer),
  { ssr: false, loading: () => <CanvasLoadingState /> },
);

const ScenarioMatrix = dynamic(
  () => import('@/components/scenario-matrix').then((m) => m.ScenarioMatrixView),
  { ssr: false, loading: () => <CanvasLoadingState /> },
);

function CanvasLoadingState() {
  return (
    <div className="flex-1 flex items-center justify-center bg-bg">
      <div className="text-center">
        <div className="animate-pulse text-acid-green text-xl font-mono mb-2">
          Loading Pipeline Canvas...
        </div>
        <p className="text-text-muted text-sm">Initializing Xyflow</p>
      </div>
    </div>
  );
}

/** Map transition target stages to the next stage for advancement */
const _NEXT_STAGE: Record<string, PipelineStageType> = {
  ideas: 'goals',
  goals: 'actions',
  actions: 'orchestration',
};

export default function PipelinePage() {
  return (
    <Suspense fallback={<CanvasLoadingState />}>
      <PipelinePageContent />
    </Suspense>
  );
}

function PipelinePageContent() {
  const {
    pipelineData,
    setPipelineData,
    isDemo,
    createFromIdeas,
    createFromBrainDump,
    createFromDebate,
    advanceStage,
    executePipeline,
    executeWithSelfImprove,
    approveTransition,
    rejectTransition,
    loadDemo,
    reset,
    loading,
    executing,
    error,
  } = usePipeline();

  const searchParams = useSearchParams();

  const [showIdeaInput, setShowIdeaInput] = useState(false);
  const [showDebateInput, setShowDebateInput] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const [showAdvancedStart, setShowAdvancedStart] = useState(false);
  const [ideaText, setIdeaText] = useState('');
  const [brainDumpText, setBrainDumpText] = useState('');
  const [debateJson, setDebateJson] = useState('');
  const [debateError, setDebateError] = useState('');
  const [key, setKey] = useState(0);
  const [debateImportStatus, setDebateImportStatus] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'stages' | 'unified' | 'fractal' | 'provenance' | 'scenario' | 'dag'>('stages');
  const [showLearningPanel, setShowLearningPanel] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [dismissedSuggestions, setDismissedSuggestions] = useState<Set<string>>(new Set());

  // Execution progress tracking
  const [currentStage, setCurrentStage] = useState<string | undefined>();
  const [completedSubtasks, setCompletedSubtasks] = useState(0);
  const [totalSubtasks, setTotalSubtasks] = useState(0);

  // Fetch latest pipeline data from API via SWR for initial load / refresh
  const {
    data: swrPipelineData,
    isLoading: swrLoading,
  } = useSWRFetch<PipelineResultResponse>(
    '/api/v1/canvas/pipeline',
    { refreshInterval: 30000, enabled: !pipelineData && !isDemo },
  );

  // If SWR fetched a pipeline and we don't have one from user actions, use it
  useEffect(() => {
    if (swrPipelineData && !pipelineData && swrPipelineData.pipeline_id) {
      setPipelineData(swrPipelineData);
    }
  }, [swrPipelineData, pipelineData, setPipelineData]);

  const wsStageStarted = useCallback((event: { stage: string }) => {
    setCurrentStage(event.stage);
  }, []);

  const wsStageCompleted = useCallback(() => {
    setKey((k) => k + 1);
  }, []);

  const wsStepProgress = useCallback((event: { completed?: number; total?: number }) => {
    if (event.completed !== undefined) setCompletedSubtasks(event.completed);
    if (event.total !== undefined) setTotalSubtasks(event.total);
  }, []);

  const wsCompleted = useCallback(() => {
    setExecuteStatus('success');
    setKey((k) => k + 1);
  }, []);

  const wsFailed = useCallback(() => {
    setExecuteStatus('failed');
    setKey((k) => k + 1);
  }, []);

  const { isConnected, completedStages: wsCompletedStages, streamedNodes } = usePipelineWebSocket({
    pipelineId: pipelineData?.pipeline_id,
    enabled: !!pipelineData && !isDemo,
    onStageStarted: wsStageStarted,
    onStageCompleted: wsStageCompleted,
    onStepProgress: wsStepProgress,
    onCompleted: wsCompleted,
    onFailed: wsFailed,
  });

  // Auto-import from debate when ?from=debate&id=xxx is present
  useEffect(() => {
    const from = searchParams?.get('from');
    const debateId = searchParams?.get('id');
    if (from === 'debate' && debateId && !pipelineData) {
      setDebateImportStatus('Fetching debate results...');
      fetch(`/api/v1/debates/${encodeURIComponent(debateId)}`)
        .then((res) => {
          if (!res.ok) throw new Error(`Failed to fetch debate: ${res.status}`);
          return res.json();
        })
        .then((debate) => {
          // Extract proposals/conclusions as cartographer-style data
          const nodes = (debate.proposals || debate.conclusions || debate.messages || []).map(
            (item: Record<string, unknown>, i: number) => ({
              id: (item.id as string) || `debate-node-${i}`,
              type: (item.type as string) || 'proposal',
              summary: (item.summary as string) || (item.content as string) || '',
              content: (item.content as string) || (item.summary as string) || '',
            }),
          );
          if (nodes.length === 0) {
            setDebateImportStatus('No proposals found in debate');
            return;
          }
          setDebateImportStatus(`Importing ${nodes.length} debate proposals...`);
          return createFromDebate({ nodes, edges: [] });
        })
        .then(() => {
          setDebateImportStatus(null);
          setKey((k) => k + 1);
        })
        .catch((err) => {
          setDebateImportStatus(`Import failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
        });
    }
    // Only run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFromIdeas = useCallback(async () => {
    const ideas = ideaText
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean);
    if (ideas.length > 0) {
      await createFromIdeas(ideas);
      setShowIdeaInput(false);
      setIdeaText('');
      setKey((k) => k + 1);
    }
  }, [ideaText, createFromIdeas]);

  const handleFromDebate = useCallback(async () => {
    setDebateError('');
    try {
      const data = JSON.parse(debateJson);
      if (!data.nodes || !Array.isArray(data.nodes)) {
        setDebateError('JSON must have a "nodes" array');
        return;
      }
      await createFromDebate(data);
      setShowDebateInput(false);
      setDebateJson('');
      setKey((k) => k + 1);
    } catch {
      setDebateError('Invalid JSON — paste ArgumentCartographer export');
    }
  }, [debateJson, createFromDebate]);

  const handleBrainDump = useCallback(async () => {
    if (brainDumpText.trim()) {
      await createFromBrainDump(brainDumpText);
      setBrainDumpText('');
      setKey((k) => k + 1);
    }
  }, [brainDumpText, createFromBrainDump]);

  // Estimate idea count from brain dump text (client-side heuristic)
  const estimatedIdeaCount = (() => {
    const text = brainDumpText.trim();
    if (!text) return 0;
    // Count bullet points, numbered items, or sentences
    const bullets = (text.match(/^[\s]*[-*>•]\s+/gm) || []).length;
    const numbered = (text.match(/^[\s]*\d+[.)]\s+/gm) || []).length;
    if (bullets > 1) return bullets;
    if (numbered > 1) return numbered;
    // Paragraph mode
    const paragraphs = text.split(/\n\s*\n/).filter((p) => p.trim().length > 20);
    if (paragraphs.length > 1) return paragraphs.length;
    // Sentence mode
    const sentences = text.split(/[.!?]+/).filter((s) => s.trim().length > 15);
    return Math.max(sentences.length, 1);
  })();

  const handleDemo = useCallback(() => {
    loadDemo();
    setKey((k) => k + 1);
  }, [loadDemo]);

  const handleNew = useCallback(() => {
    reset();
    setExecuteStatus('idle');
    setCurrentStage(undefined);
    setCompletedSubtasks(0);
    setTotalSubtasks(0);
    setKey((k) => k + 1);
  }, [reset]);

  const handleStageAdvance = useCallback(
    (pipelineId: string, stage: PipelineStageType) => {
      advanceStage(pipelineId, stage);
      setKey((k) => k + 1);
    },
    [advanceStage],
  );

  const handleTransitionApprove = useCallback(
    (pipelineId: string, transitionId: string) => {
      // Find the transition to determine source and target stages
      const transition = pipelineData?.transitions?.find(
        (t) => (t.id as string) === transitionId,
      );
      if (transition) {
        const fromStage = transition.from_stage as PipelineStageType;
        const toStage = transition.to_stage as PipelineStageType;
        approveTransition(pipelineId, fromStage, toStage);
        setKey((k) => k + 1);
      }
    },
    [pipelineData, approveTransition],
  );

  const handleTransitionReject = useCallback(
    (pipelineId: string, transitionId: string) => {
      const transition = pipelineData?.transitions?.find(
        (t) => (t.id as string) === transitionId,
      );
      if (transition) {
        const fromStage = transition.from_stage as PipelineStageType;
        const toStage = transition.to_stage as PipelineStageType;
        rejectTransition(pipelineId, fromStage, toStage);
      }
    },
    [pipelineData, rejectTransition],
  );

  const [executeStatus, setExecuteStatus] = useState<'idle' | 'success' | 'failed'>('idle');

  // Self-improve integration state
  const router = useRouter();
  const [showSelfImproveConfig, setShowSelfImproveConfig] = useState(false);
  const [siDryRun, setSiDryRun] = useState(false);
  const [siBudget, setSiBudget] = useState(10);

  const handleExecute = useCallback(async () => {
    if (pipelineData?.pipeline_id) {
      setExecuteStatus('idle');
      setCurrentStage(undefined);
      setCompletedSubtasks(0);
      setTotalSubtasks(0);
      try {
        await executePipeline(pipelineData.pipeline_id);
        // Status will be set by WS callbacks (wsCompleted/wsFailed)
      } catch {
        setExecuteStatus('failed');
      }
    }
  }, [pipelineData, executePipeline]);

  const orchestrationReady = pipelineData?.stage_status
    ? pipelineData.stage_status.orchestration === 'complete'
    : false;

  // Derive transition suggestions from pipeline transitions for AutoTransitionSuggestion
  const transitionSuggestions = useMemo((): TransitionSuggestion[] => {
    if (!pipelineData?.transitions) return [];
    return pipelineData.transitions
      .filter((t) => t.status === 'pending')
      .filter((t) => !dismissedSuggestions.has(t.id))
      .map((t) => ({
        node_id: t.id,
        node_label: `${t.from_stage} \u2192 ${t.to_stage}`,
        from_stage: t.from_stage as PipelineStageType,
        to_stage: t.to_stage as PipelineStageType,
        confidence: t.confidence,
        reason: t.ai_rationale || 'AI-suggested transition',
      }));
  }, [pipelineData?.transitions, dismissedSuggestions]);

  const handleSuggestionApprove = useCallback(
    (suggestion: TransitionSuggestion) => {
      if (pipelineData?.pipeline_id) {
        approveTransition(pipelineData.pipeline_id, suggestion.from_stage, suggestion.to_stage);
        setKey((k) => k + 1);
      }
    },
    [pipelineData, approveTransition],
  );

  const handleSuggestionDismiss = useCallback(
    (suggestion: TransitionSuggestion) => {
      setDismissedSuggestions((prev) => new Set(prev).add(suggestion.node_id));
    },
    [],
  );

  // Map pipeline stage_status values to ExecutionStatus for StatusBadge
  const mapStageStatus = useCallback((status: string): ExecutionStatus => {
    switch (status) {
      case 'complete': return 'succeeded';
      case 'in_progress': return 'in_progress';
      case 'failed': return 'failed';
      case 'partial': return 'partial';
      default: return 'pending';
    }
  }, []);

  const handleFractalStageChange = useCallback(
    (stage: PipelineStageType) => {
      if (pipelineData?.pipeline_id) {
        advanceStage(pipelineData.pipeline_id, stage);
        setKey((k) => k + 1);
      }
    },
    [pipelineData, advanceStage],
  );

  const _isPageLoading = loading || (swrLoading && !pipelineData);

  // Pipeline keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const isMod = e.metaKey || e.ctrlKey;
      if (!isMod) return;

      switch (e.key.toLowerCase()) {
        case 'e':
          e.preventDefault();
          if (pipelineData?.pipeline_id && orchestrationReady && !executing) {
            handleExecute();
          }
          break;
        case 's':
          e.preventDefault();
          // Save is handled by the pipeline - prevent browser save dialog
          break;
        case 'n':
          if (e.shiftKey) {
            e.preventDefault();
            handleNew();
          }
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [pipelineData, orchestrationReady, executing, handleExecute, handleNew]);

  return (
    <div className="flex flex-col h-screen bg-bg">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-border bg-surface">
        <div>
          <h1 className="text-xl font-mono font-bold text-text">
            Idea-to-Execution Pipeline
          </h1>
          <p className="text-sm text-text-muted font-mono">
            Ideas &rarr; Goals &rarr; Actions &rarr; Orchestration
          </p>
        </div>

        <div className="flex items-center gap-3">
          {pipelineData && !isDemo && (
            <span
              className={`inline-block w-2.5 h-2.5 rounded-full ${
                isConnected ? 'bg-emerald-400' : 'bg-red-400'
              }`}
              title={isConnected ? 'WebSocket connected' : 'WebSocket disconnected'}
            />
          )}

          <button
            onClick={handleNew}
            className="px-4 py-2 bg-surface border border-border text-text font-mono text-sm hover:border-text transition-colors rounded"
          >
            New Pipeline
          </button>

          {/* Stage status badges */}
          {pipelineData?.stage_status && (
            <div className="flex items-center gap-1.5">
              {(['ideas', 'goals', 'actions', 'orchestration'] as const).map((stage) => (
                <div key={stage} className="flex items-center gap-1">
                  <span className="text-[10px] font-mono text-text-muted uppercase">{stage.slice(0, 4)}</span>
                  <StatusBadge status={mapStageStatus(pipelineData.stage_status[stage])} size="sm" />
                </div>
              ))}
            </div>
          )}

          {pipelineData && (
            <>
              <div className="flex items-center bg-surface border border-border rounded overflow-hidden">
                {(['stages', 'unified', 'fractal', 'provenance', 'scenario', 'dag'] as const).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-3 py-2 text-sm font-mono transition-colors ${
                      viewMode === mode
                        ? 'bg-indigo-600 text-white'
                        : 'text-text-muted hover:text-text'
                    }`}
                  >
                    {mode.charAt(0).toUpperCase() + mode.slice(1)}
                  </button>
                ))}
              </div>

              <button
                onClick={() => { setShowIdeaInput(!showIdeaInput); setShowDebateInput(false); }}
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 text-white font-mono text-sm hover:bg-indigo-500 transition-colors rounded"
              >
                From Ideas
              </button>

              <button
                onClick={() => { setShowDebateInput(!showDebateInput); setShowIdeaInput(false); }}
                disabled={loading}
                className="px-4 py-2 bg-violet-600 text-white font-mono text-sm hover:bg-violet-500 transition-colors rounded"
              >
                From Debate
              </button>
            </>
          )}

          <button
            onClick={handleDemo}
            disabled={loading}
            className="px-4 py-2 bg-emerald-600 text-white font-mono text-sm hover:bg-emerald-500 transition-colors rounded"
          >
            {loading ? 'Loading...' : 'Try Demo'}
          </button>

          {pipelineData && orchestrationReady && (
            <>
              <button
                onClick={handleExecute}
                disabled={executing}
                className={`px-4 py-2 font-mono text-sm text-white disabled:opacity-50 transition-colors rounded ${
                  executeStatus === 'success'
                    ? 'bg-emerald-600 hover:bg-emerald-500'
                    : executeStatus === 'failed'
                      ? 'bg-red-600 hover:bg-red-500'
                      : 'bg-amber-600 hover:bg-amber-500'
                }`}
              >
                {executing
                  ? 'Executing...'
                  : executeStatus === 'success'
                    ? 'Executed'
                    : executeStatus === 'failed'
                      ? 'Failed — Retry'
                      : 'Execute Pipeline'}
              </button>
              <button
                onClick={() => setShowSelfImproveConfig(!showSelfImproveConfig)}
                className="px-3 py-2 text-xs font-mono border border-[var(--acid-green)]/40 text-[var(--acid-green)] rounded hover:bg-[var(--acid-green)]/10 transition-colors"
              >
                Execute with Aragora
              </button>
            </>
          )}
        </div>
      </header>

      {/* Self-improve config panel */}
      {showSelfImproveConfig && pipelineData && orchestrationReady && (
        <div className="px-6 py-4 border-b border-border bg-surface/50">
          <h3 className="text-sm font-mono text-[var(--acid-green)] mb-3">Self-Improvement Configuration</h3>
          <div className="max-w-lg space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-mono text-text-muted">Budget limit ($)</label>
              <input
                type="number"
                value={siBudget}
                onChange={(e) => setSiBudget(Number(e.target.value))}
                className="w-20 bg-bg border border-text-muted/30 rounded px-2 py-1 text-xs font-mono text-text"
              />
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={siDryRun}
                onChange={(e) => setSiDryRun(e.target.checked)}
                className="accent-[var(--acid-green)]"
              />
              <label className="text-xs font-mono text-text-muted">Dry run</label>
            </div>
            <button
              onClick={async () => {
                if (pipelineData?.pipeline_id) {
                  const res = await executeWithSelfImprove(pipelineData.pipeline_id, { dryRun: siDryRun });
                  if (res) {
                    window.location.href = `/self-improve?from=pipeline&id=${pipelineData.pipeline_id}`;
                  }
                }
              }}
              className="w-full px-3 py-1.5 text-xs font-mono bg-[var(--acid-green)]/20 border border-[var(--acid-green)]/40 text-[var(--acid-green)] rounded hover:bg-[var(--acid-green)]/30 transition-colors"
            >
              Launch Self-Improvement
            </button>
          </div>
        </div>
      )}

      {/* Idea input dropdown */}
      {showIdeaInput && (
        <div className="px-6 py-4 border-b border-border bg-surface/50">
          <label className="block text-sm font-mono text-text-muted mb-2">
            Enter ideas (one per line):
          </label>
          <textarea
            value={ideaText}
            onChange={(e) => setIdeaText(e.target.value)}
            rows={4}
            className="w-full max-w-lg bg-bg border border-border rounded p-3 text-sm text-text font-mono resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder={"Build a rate limiter\nAdd caching layer\nImprove API docs\nSet up monitoring"}
          />
          <div className="flex gap-2 mt-2">
            <button
              onClick={handleFromIdeas}
              disabled={!ideaText.trim() || loading}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-mono rounded hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              {loading ? 'Generating...' : 'Generate Pipeline'}
            </button>
            <button
              onClick={() => setShowIdeaInput(false)}
              className="px-4 py-2 text-sm font-mono text-text-muted hover:text-text"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Debate JSON input dropdown */}
      {showDebateInput && (
        <div className="px-6 py-4 border-b border-border bg-surface/50">
          <label className="block text-sm font-mono text-text-muted mb-2">
            Paste ArgumentCartographer JSON export:
          </label>
          <textarea
            value={debateJson}
            onChange={(e) => { setDebateJson(e.target.value); setDebateError(''); }}
            rows={6}
            className="w-full max-w-lg bg-bg border border-border rounded p-3 text-sm text-text font-mono resize-none focus:outline-none focus:ring-2 focus:ring-violet-500"
            placeholder={'{\n  "nodes": [\n    {"id": "n1", "type": "proposal", "summary": "...", "content": "..."}\n  ],\n  "edges": [\n    {"source_id": "n2", "target_id": "n1", "relation": "supports"}\n  ]\n}'}
          />
          {debateError && (
            <p className="text-xs text-red-400 font-mono mt-1">{debateError}</p>
          )}
          <div className="flex gap-2 mt-2">
            <button
              onClick={handleFromDebate}
              disabled={!debateJson.trim() || loading}
              className="px-4 py-2 bg-violet-600 text-white text-sm font-mono rounded hover:bg-violet-500 disabled:opacity-50 transition-colors"
            >
              {loading ? 'Generating...' : 'Import Debate'}
            </button>
            <button
              onClick={() => { setShowDebateInput(false); setDebateError(''); }}
              className="px-4 py-2 text-sm font-mono text-text-muted hover:text-text"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Debate import status */}
      {debateImportStatus && (
        <div className="px-6 py-2 bg-violet-500/10 border-b border-violet-500/30">
          <p className="text-sm text-violet-400 font-mono">{debateImportStatus}</p>
        </div>
      )}

      {/* Error display */}
      {error && (
        <div className="px-6 py-2 bg-red-500/10 border-b border-red-500/30">
          <p className="text-sm text-red-400 font-mono">{error}</p>
        </div>
      )}

      {/* Canvas or empty state */}
      <div className="flex-1 overflow-hidden relative">
        {/* Execution progress overlay */}
        {pipelineData && (executing || executeStatus !== 'idle') && (
          <ExecutionProgressOverlay
            executing={executing}
            currentStage={currentStage}
            completedStages={wsCompletedStages}
            streamedNodeCount={streamedNodes.length}
            completedSubtasks={completedSubtasks}
            totalSubtasks={totalSubtasks}
            executeStatus={executeStatus}
          />
        )}

        {pipelineData ? (
          viewMode === 'dag' ? (
            <UnifiedDAGCanvas
              key={`dag-${key}`}
              graphId={pipelineData.pipeline_id}
            />
          ) : viewMode === 'scenario' ? (
            <div className="h-full p-4 overflow-auto">
              <ScenarioMatrix
                key={`scenario-${key}`}
              />
            </div>
          ) : viewMode === 'provenance' ? (
            <div className="h-full p-4">
              <ProvenanceExplorer
                key={`provenance-${key}`}
                graphId={pipelineData.pipeline_id}
              />
            </div>
          ) : viewMode === 'unified' ? (
            <UnifiedPipelineCanvas
              key={`unified-${key}`}
              pipelineId={pipelineData.pipeline_id}
              initialData={pipelineData}
            />
          ) : viewMode === 'fractal' ? (
            <div className="flex h-full">
              {/* Fractal canvas main area */}
              <div className="flex-1 h-full overflow-hidden">
                <FractalPipelineCanvas
                  key={`fractal-${key}`}
                  pipelineResult={pipelineData}
                  onStageChange={handleFractalStageChange}
                />
              </div>

              {/* Sidebar with AutoTransitionSuggestion and stage status */}
              {sidebarOpen && (
                <aside className="w-72 h-full border-l border-border bg-surface overflow-y-auto flex-shrink-0">
                  <div className="p-4 space-y-4">
                    {/* Sidebar header */}
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-mono font-bold text-text uppercase tracking-wide">
                        Pipeline Status
                      </h3>
                      <button
                        onClick={() => setSidebarOpen(false)}
                        className="text-text-muted hover:text-text text-xs font-mono"
                        title="Close sidebar"
                      >
                        {'\u00D7'}
                      </button>
                    </div>

                    {/* Stage status overview */}
                    <div className="space-y-2">
                      <h4 className="text-xs font-mono text-text-muted uppercase tracking-wider">
                        Stage Progress
                      </h4>
                      {(['ideas', 'goals', 'actions', 'orchestration'] as const).map((stage) => (
                        <div
                          key={stage}
                          className="flex items-center justify-between px-2 py-1.5 rounded bg-bg/50"
                        >
                          <span className="text-xs font-mono text-text capitalize">{stage}</span>
                          <StatusBadge
                            status={mapStageStatus(pipelineData.stage_status[stage])}
                            size="sm"
                          />
                        </div>
                      ))}
                    </div>

                    {/* Transition suggestions */}
                    {transitionSuggestions.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-mono text-text-muted uppercase tracking-wider">
                          Suggested Transitions
                        </h4>
                        <AutoTransitionSuggestion
                          suggestions={transitionSuggestions}
                          onApprove={handleSuggestionApprove}
                          onDismiss={handleSuggestionDismiss}
                        />
                      </div>
                    )}

                    {/* Pipeline metadata */}
                    <div className="space-y-1.5 pt-2 border-t border-border">
                      <h4 className="text-xs font-mono text-text-muted uppercase tracking-wider">
                        Pipeline Info
                      </h4>
                      <div className="text-xs font-mono text-text-muted">
                        <span className="text-text-muted">ID: </span>
                        <span className="text-text">{pipelineData.pipeline_id.slice(0, 16)}</span>
                      </div>
                      {pipelineData.provenance_count > 0 && (
                        <div className="text-xs font-mono text-text-muted">
                          <span className="text-text-muted">Provenance links: </span>
                          <span className="text-text">{pipelineData.provenance_count}</span>
                        </div>
                      )}
                      {pipelineData.integrity_hash && (
                        <div className="text-xs font-mono text-text-muted">
                          <span className="text-text-muted">Integrity: </span>
                          <span className="text-text">{pipelineData.integrity_hash.slice(0, 12)}</span>
                        </div>
                      )}
                    </div>
                  </div>
                </aside>
              )}

              {/* Sidebar toggle when closed */}
              {!sidebarOpen && (
                <button
                  onClick={() => setSidebarOpen(true)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 px-1.5 py-3 bg-surface border border-border rounded-l text-text-muted hover:text-text text-xs font-mono z-10"
                  title="Open sidebar"
                >
                  {'\u00AB'}
                </button>
              )}
            </div>
          ) : (
            <PipelineCanvas
              key={key}
              pipelineId={pipelineData.pipeline_id}
              initialData={pipelineData}
              onStageAdvance={handleStageAdvance}
              onTransitionApprove={handleTransitionApprove}
              onTransitionReject={handleTransitionReject}
            />
          )
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="w-full max-w-2xl px-6">
              <div className="space-y-5">
                <div className="text-center">
                  <h2 className="text-2xl font-mono font-bold text-text mb-2">
                    Prompt to Execution
                  </h2>
                  <p className="text-text-muted font-mono text-sm">
                    Start with one prompt. Aragora maps ideas, goals, actions, and orchestration.
                  </p>
                </div>

                <div className="bg-surface border border-border rounded-xl p-4 md:p-5 space-y-4">
                  <label className="block text-xs font-mono uppercase tracking-wide text-text-muted">
                    1. Describe what you want to achieve
                  </label>
                  <textarea
                    className="w-full min-h-[200px] bg-bg border border-border rounded-lg p-4 text-sm text-text font-mono resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder={"Build me an execution plan for...\n\nContext:\n- Current constraints\n- Success criteria\n- Risks to avoid"}
                    value={brainDumpText}
                    onChange={(e) => setBrainDumpText(e.target.value)}
                  />
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <span className="text-sm text-text-muted font-mono">
                      ~{estimatedIdeaCount} idea{estimatedIdeaCount !== 1 ? 's' : ''} detected
                    </span>
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={handleBrainDump}
                        disabled={!brainDumpText.trim() || loading}
                        className="px-5 py-2.5 bg-indigo-600 text-white font-mono text-sm rounded-lg hover:bg-indigo-500 disabled:opacity-50 transition-colors"
                      >
                        {loading ? 'Organizing...' : 'Generate Pipeline'}
                      </button>
                      <button
                        onClick={() => setShowWizard(true)}
                        className="px-5 py-2.5 bg-amber-600 text-white font-mono text-sm rounded-lg hover:bg-amber-500 transition-colors"
                      >
                        Use Template
                      </button>
                      <button
                        onClick={handleDemo}
                        className="px-5 py-2.5 bg-emerald-600 text-white font-mono text-sm rounded-lg hover:bg-emerald-500 transition-colors"
                      >
                        Try Demo
                      </button>
                    </div>
                  </div>
                </div>

                <div className="bg-surface/40 border border-border rounded-lg p-4">
                  <button
                    onClick={() => setShowAdvancedStart((v) => !v)}
                    className="w-full flex items-center justify-between text-left"
                  >
                    <span className="text-sm font-mono text-text">
                      Advanced Input Options
                    </span>
                    <span className="text-xs font-mono text-text-muted">
                      {showAdvancedStart ? 'Hide' : 'Show'}
                    </span>
                  </button>

                  {showAdvancedStart && (
                    <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-3">
                      <button
                        onClick={() => { setShowIdeaInput(true); setShowDebateInput(false); }}
                        className="px-3 py-2 bg-surface border border-border text-text font-mono text-xs rounded hover:border-text transition-colors"
                      >
                        Structured Ideas
                      </button>
                      <button
                        onClick={() => { setShowDebateInput(true); setShowIdeaInput(false); }}
                        className="px-3 py-2 bg-violet-600/90 text-white font-mono text-xs rounded hover:bg-violet-500 transition-colors"
                      >
                        Import Debate JSON
                      </button>
                      <button
                        onClick={() => setShowWizard(true)}
                        className="px-3 py-2 bg-amber-600/90 text-white font-mono text-xs rounded hover:bg-amber-500 transition-colors"
                      >
                        Wizard Templates
                      </button>
                    </div>
                  )}
                </div>

                {showWizard && (
                  <div className="max-w-2xl mx-auto">
                    <UseCaseWizard
                      onComplete={(id) => {
                        setShowWizard(false);
                        router.push(`/debates/${id}`);
                      }}
                      onCancel={() => setShowWizard(false)}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Post-execution learning panel */}
      {pipelineData && (executeStatus === 'success' || showLearningPanel) && (
        <div className="border-t border-border bg-surface/50 px-6 py-2">
          <button
            onClick={() => setShowLearningPanel(!showLearningPanel)}
            className="flex items-center gap-2 text-xs font-mono text-acid-cyan hover:text-acid-green transition-colors py-1"
          >
            <span>{showLearningPanel ? '[-]' : '[+]'}</span>
            <span className="uppercase tracking-wider">Learning & Feedback</span>
          </button>
          {showLearningPanel && (
            <div className="pb-4">
              <FeedbackLoopPanel
                pipelineId={pipelineData.pipeline_id}
                isVisible={showLearningPanel}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
