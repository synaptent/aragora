'use client';

import { useState, useEffect, useCallback } from 'react';
import { useDebateFork, type ForkNode } from '@/hooks/useDebateFork';
import { ForkTreeView } from './ForkTreeView';
import { ForkComparisonPanel } from './ForkComparisonPanel';

interface ForkVisualizerProps {
  debateId: string;
  messageCount?: number;
  onForkSelect?: (fork: ForkNode) => void;
}

export function ForkVisualizer({ debateId, messageCount = 0, onForkSelect }: ForkVisualizerProps) {
  const fork = useDebateFork(debateId);
  const { loadForks } = fork;
  const [activeTab, setActiveTab] = useState<'tree' | 'compare'>('tree');
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [branchPoint, setBranchPoint] = useState(0);
  const [modifiedContext, setModifiedContext] = useState('');

  useEffect(() => {
    loadForks();
  }, [loadForks]);

  const handleNodeSelect = useCallback(
    (node: ForkNode) => {
      onForkSelect?.(node);
    },
    [onForkSelect],
  );

  const handleCompareSelect = useCallback(
    (node: ForkNode, slot: 0 | 1) => {
      fork.selectForComparison(node, slot);
      if (fork.selectedNodes[0] && fork.selectedNodes[1]) {
        setActiveTab('compare');
      }
    },
    [fork],
  );

  const handleCreateFork = useCallback(async () => {
    const result = await fork.createFork(branchPoint, modifiedContext || undefined);
    if (result) {
      setShowCreateForm(false);
      setBranchPoint(0);
      setModifiedContext('');
    }
  }, [fork, branchPoint, modifiedContext]);

  const forkCountLabel = fork.forks.length === 1 ? 'fork' : 'forks';

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50">
      <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
          {'>'} FORK EXPLORER
        </span>
        <div className="flex items-center gap-2">
          {fork.hasForks && (
            <span className="text-xs font-theme-data text-text-muted">
              {fork.forks.length} {forkCountLabel}
            </span>
          )}
          <button
            onClick={() => setShowCreateForm(!showCreateForm)}
            className="px-2 py-1 text-xs font-theme-data border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
          >
            [+ FORK]
          </button>
          <button
            onClick={() => fork.loadForks()}
            disabled={fork.loading}
            className="px-2 py-1 text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
          >
            {fork.loading ? '...' : '[REFRESH]'}
          </button>
        </div>
      </div>

      {showCreateForm && (
        <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-surface/30 space-y-3">
          <div className="text-xs font-theme-data text-text-muted">CREATE COUNTERFACTUAL FORK</div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Branch Point (Round)
              </label>
              <input
                type="number"
                min={0}
                max={messageCount}
                value={branchPoint}
                onChange={(e) => setBranchPoint(parseInt(e.target.value) || 0)}
                className="w-full px-2 py-1 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Modified Context
              </label>
              <input
                type="text"
                value={modifiedContext}
                onChange={(e) => setModifiedContext(e.target.value)}
                placeholder="What if we assumed..."
                className="w-full px-2 py-1 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setShowCreateForm(false)}
              className="px-3 py-1 text-xs font-theme-data text-text-muted hover:text-text"
            >
              [CANCEL]
            </button>
            <button
              onClick={handleCreateFork}
              disabled={fork.forking}
              className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/20 disabled:opacity-50"
            >
              {fork.forking ? 'CREATING...' : 'CREATE FORK'}
            </button>
          </div>
        </div>
      )}

      {fork.hasForks && (
        <div className="flex border-b border-[var(--accent)]/10">
          {(['tree', 'compare'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              disabled={tab === 'compare' && !fork.canCompare}
              className={`flex-1 px-4 py-2 text-xs font-theme-data uppercase transition-colors disabled:opacity-30 ${activeTab === tab ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-[var(--accent)]/5' : 'text-text-muted hover:text-text'}`}
            >
              {tab === 'tree' ? 'FORK TREE' : 'COMPARE'}
            </button>
          ))}
        </div>
      )}

      {fork.error && (
        <div className="px-4 py-2 border-b border-acid-red/30">
          <div className="p-2 text-xs font-theme-data text-acid-red bg-acid-red/10 border border-acid-red/30">
            {'>'} {fork.error}
          </div>
        </div>
      )}

      <div className="p-4">
        {fork.loading && !fork.hasForks ? (
          <div className="text-center py-8 text-xs font-theme-data text-text-muted animate-pulse">
            Loading forks...
          </div>
        ) : !fork.hasForks ? (
          <div className="text-center py-8 text-xs font-theme-data text-text-muted">
            <p>No forks yet for this debate.</p>
            <p className="mt-2">Click [+ FORK] to create a counterfactual branch.</p>
          </div>
        ) : activeTab === 'tree' ? (
          <ForkTreeView
            tree={fork.forkTree}
            onNodeSelect={handleNodeSelect}
            onCompareSelect={handleCompareSelect}
            selectedNodes={fork.selectedNodes}
          />
        ) : fork.comparisonData ? (
          <ForkComparisonPanel comparison={fork.comparisonData} onClear={fork.clearSelection} />
        ) : (
          <div className="text-center py-8 text-xs font-theme-data text-text-muted">
            Select two forks to compare.
          </div>
        )}
      </div>
    </div>
  );
}

export default ForkVisualizer;
