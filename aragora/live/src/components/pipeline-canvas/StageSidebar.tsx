'use client';

import { useState, useCallback } from 'react';
import dynamic from 'next/dynamic';
import type { PipelineStageType } from './types';

// Lazy-load the stranded feature panels so they don't bloat the canvas bundle
const MemoryExplorerPanel = dynamic(
  () =>
    import('@/components/MemoryExplorerPanel').then((m) => ({ default: m.MemoryExplorerPanel })),
  { ssr: false, loading: () => <PanelLoading label="Memory Explorer" /> },
);

const EvaluationPanel = dynamic(
  () => import('@/components/EvaluationPanel').then((m) => ({ default: m.EvaluationPanel })),
  { ssr: false, loading: () => <PanelLoading label="Evaluation" /> },
);

const PluginMarketplacePanel = dynamic(
  () =>
    import('@/components/PluginMarketplacePanel').then((m) => ({
      default: m.PluginMarketplacePanel,
    })),
  { ssr: false, loading: () => <PanelLoading label="Templates" /> },
);

const GauntletRunner = dynamic(
  () => import('@/components/GauntletRunner').then((m) => ({ default: m.GauntletRunner })),
  { ssr: false, loading: () => <PanelLoading label="Gauntlet" /> },
);

const MetaPlannerView = dynamic(
  () =>
    import('@/components/self-improve/MetaPlannerView').then((m) => ({
      default: m.MetaPlannerView,
    })),
  { ssr: false, loading: () => <PanelLoading label="MetaPlanner" /> },
);

const LearningFeed = dynamic(
  () => import('@/components/self-improve/LearningFeed').then((m) => ({ default: m.LearningFeed })),
  { ssr: false, loading: () => <PanelLoading label="Learning Feed" /> },
);

function PanelLoading({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-32">
      <span className="text-xs font-theme-data text-text-muted animate-pulse">
        Loading {label}...
      </span>
    </div>
  );
}

const STAGE_PANEL_CONFIG: Record<
  PipelineStageType,
  { title: string; subtitle: string; color: string }
> = {
  ideas: {
    title: 'Memory Explorer',
    subtitle: 'Browse past debates and knowledge to seed ideas',
    color: 'text-indigo-400',
  },
  principles: {
    title: 'Principles Distillery',
    subtitle: 'Extract values, priorities, and constraints from ideas',
    color: 'text-violet-400',
  },
  goals: {
    title: 'Agent Evaluation',
    subtitle: 'View agent trust scores and goal confidence',
    color: 'text-emerald-400',
  },
  actions: {
    title: 'Workflow Templates',
    subtitle: 'Browse and apply pre-built workflow patterns',
    color: 'text-amber-400',
  },
  orchestration: {
    title: 'Gauntlet Runner',
    subtitle: 'Adversarial testing for execution plans',
    color: 'text-rose-400',
  },
};

interface StageSidebarProps {
  stage: PipelineStageType;
  isOpen: boolean;
  onClose: () => void;
}

export function StageSidebar({ stage, isOpen, onClose }: StageSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const config = STAGE_PANEL_CONFIG[stage];

  const toggleCollapse = useCallback(() => {
    setCollapsed((c) => !c);
  }, []);

  if (!isOpen) return null;

  return (
    <div
      className={`flex-shrink-0 bg-surface border-l border-border h-full overflow-y-auto transition-all duration-200 ${
        collapsed ? 'w-10' : 'w-80'
      }`}
    >
      {collapsed ? (
        <button
          onClick={toggleCollapse}
          className="w-full h-full flex items-center justify-center text-text-muted hover:text-text"
          title="Expand sidebar"
        >
          <svg
            className="w-4 h-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
          >
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
      ) : (
        <div className="p-4">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className={`text-sm font-theme-data font-bold uppercase ${config.color}`}>
                {config.title}
              </h3>
              <p className="text-xs text-text-muted mt-0.5">{config.subtitle}</p>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={toggleCollapse}
                className="text-text-muted hover:text-text text-sm p-1"
                title="Collapse"
              >
                <svg
                  className="w-3.5 h-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
              <button
                onClick={onClose}
                className="text-text-muted hover:text-text text-lg leading-none p-1"
                title="Close"
              >
                &times;
              </button>
            </div>
          </div>

          <div className="border-t border-border pt-3">
            {stage === 'ideas' && <MemoryExplorerPanel />}
            {stage === 'principles' && <MetaPlannerView />}
            {stage === 'goals' && <EvaluationPanel apiBase="" />}
            {stage === 'actions' && <PluginMarketplacePanel />}
            {stage === 'orchestration' && (
              <>
                <GauntletRunner />
                <div className="mt-4 border-t border-border pt-3">
                  <h4 className="text-xs font-theme-data text-text-muted uppercase mb-2">
                    Learning Feed
                  </h4>
                  <LearningFeed />
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
