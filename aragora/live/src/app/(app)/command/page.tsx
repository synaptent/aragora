'use client';

import { Suspense, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { useCommandCenter } from '@/hooks/useCommandCenter';
import { BrainDumpInput } from '@/components/command/BrainDumpInput';
import { CommandStatusBar } from '@/components/command/CommandStatusBar';
import { LiveActivityFeed } from '@/components/command/LiveActivityFeed';
import { NodeContextPanel } from '@/components/command/NodeContextPanel';
import { AutoFlowOrchestrator } from '@/components/command/AutoFlowOrchestrator';

const UnifiedDAGCanvas = dynamic(
  () => import('@/components/unified-dag/UnifiedDAGCanvas').then((m) => m.UnifiedDAGCanvas),
  { ssr: false, loading: () => <CanvasLoading /> },
);

function CanvasLoading() {
  return (
    <div className="flex-1 flex items-center justify-center bg-bg">
      <div className="text-center">
        <div className="animate-pulse text-[var(--accent)] text-xl font-theme-data mb-2">
          Loading Command Center...
        </div>
        <p className="text-text-muted text-sm font-theme-data">Initializing canvas</p>
      </div>
    </div>
  );
}

export default function CommandPage() {
  return (
    <Suspense fallback={<CanvasLoading />}>
      <CommandPageContent />
    </Suspense>
  );
}

function CommandPageContent() {
  const cc = useCommandCenter();

  const handleAutoFlowAll = useCallback(() => {
    // Re-trigger auto-flow on all ideas
  }, []);

  return (
    <div className="flex flex-col h-[calc(100vh-64px)] bg-bg">
      {/* Status Bar */}
      <CommandStatusBar
        stats={cc.stats}
        onAutoFlowAll={handleAutoFlowAll}
        onValidateAll={() => {}}
        onExecuteReady={() => {}}
        loading={cc.dag.operationLoading}
      />

      {/* Main Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Center: Brain Dump or DAG Canvas */}
        <div className="flex-1 flex flex-col relative">
          {!cc.graphId ? (
            <div className="flex-1 flex items-center justify-center p-8">
              <BrainDumpInput onSubmit={cc.submitBrainDump} loading={cc.autoFlowPhase !== null} />
            </div>
          ) : (
            <div className="flex-1 relative">
              <UnifiedDAGCanvas graphId={cc.graphId} />
            </div>
          )}

          {/* Auto-Flow Overlay */}
          {cc.autoFlowPhase && cc.autoFlowPhase !== 'complete' && (
            <AutoFlowOrchestrator
              currentPhase={cc.autoFlowPhase}
              phaseProgress={0.5}
              nodesCreated={cc.stats.totalNodes}
              onPause={() => {}}
              onSkipToEnd={() => {}}
              onCancel={() => {}}
            />
          )}
        </div>

        {/* Right Sidebar: Node Context Panel */}
        {cc.selectedNode && (
          <NodeContextPanel
            node={cc.selectedNode}
            events={cc.nodeEvents}
            onAction={cc.handleNodeAction}
            onClose={() => cc.setSelectedNodeId(null)}
          />
        )}
      </div>

      {/* Bottom: Live Activity Feed */}
      <LiveActivityFeed
        events={cc.events}
        onEventClick={(id) => {
          const event = cc.events.find((e) => e.id === id);
          if (event?.nodeId) cc.setSelectedNodeId(event.nodeId);
        }}
      />
    </div>
  );
}
