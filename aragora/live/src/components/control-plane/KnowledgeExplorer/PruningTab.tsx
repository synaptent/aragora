'use client';

import { useState, useEffect } from 'react';
import { usePruning, type PruningAction } from '@/hooks/usePruning';

export interface PruningTabProps {
  workspaceId?: string;
  onPruneComplete?: () => void;
}

/**
 * Pruning tab for archiving/deleting stale knowledge items.
 */
export function PruningTab({ workspaceId = 'default', onPruneComplete }: PruningTabProps) {
  const {
    prunableItems,
    history,
    lastResult,
    isLoading,
    error,
    getPrunableItems,
    pruneItems,
    autoPrune,
    getHistory,
    restoreItem,
  } = usePruning({ workspaceId });

  const [stalenessThreshold, setStalenessThreshold] = useState(0.9);
  const [minAgeDays, setMinAgeDays] = useState(30);
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());
  const [pruneAction, setPruneAction] = useState<PruningAction>('archive');
  const [showHistory, setShowHistory] = useState(false);
  const [confirmPrune, setConfirmPrune] = useState(false);

  // Load items on mount
  useEffect(() => {
    getPrunableItems(stalenessThreshold, minAgeDays);
  }, [getPrunableItems, stalenessThreshold, minAgeDays]);

  const handleScan = async () => {
    await getPrunableItems(stalenessThreshold, minAgeDays);
    setSelectedItems(new Set());
  };

  const handleLoadHistory = async () => {
    await getHistory();
    setShowHistory(true);
  };

  const toggleSelectItem = (nodeId: string) => {
    const newSelected = new Set(selectedItems);
    if (newSelected.has(nodeId)) {
      newSelected.delete(nodeId);
    } else {
      newSelected.add(nodeId);
    }
    setSelectedItems(newSelected);
  };

  const toggleSelectAll = () => {
    if (selectedItems.size === prunableItems.length) {
      setSelectedItems(new Set());
    } else {
      setSelectedItems(new Set(prunableItems.map((item) => item.node_id)));
    }
  };

  const handlePrune = async () => {
    if (selectedItems.size === 0) return;

    const result = await pruneItems(Array.from(selectedItems), pruneAction, 'manual_prune');
    if (result?.success) {
      setSelectedItems(new Set());
      setConfirmPrune(false);
      onPruneComplete?.();
    }
  };

  const handleAutoPrune = async (dryRun: boolean) => {
    const result = await autoPrune({ stalenessThreshold, minAgeDays, action: pruneAction, dryRun });
    if (result && !dryRun && result.items_pruned > 0) {
      onPruneComplete?.();
    }
  };

  const handleRestore = async (nodeId: string) => {
    const success = await restoreItem(nodeId);
    if (success) {
      await getHistory();
    }
  };

  const getActionBadge = (action: PruningAction) => {
    switch (action) {
      case 'archive':
        return (
          <span className="px-2 py-0.5 text-xs rounded bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]">
            Archive
          </span>
        );
      case 'delete':
        return (
          <span className="px-2 py-0.5 text-xs rounded bg-[var(--crimson)]/20 text-[var(--crimson)]">
            Delete
          </span>
        );
      case 'demote':
        return (
          <span className="px-2 py-0.5 text-xs rounded bg-acid-yellow/20 text-[var(--acid-yellow)]">
            Demote
          </span>
        );
      case 'flag':
        return (
          <span className="px-2 py-0.5 text-xs rounded bg-purple-500/20 text-purple-400">Flag</span>
        );
      default:
        return null;
    }
  };

  const getStalenessColor = (score: number) => {
    if (score >= 0.95) return 'text-[var(--crimson)]';
    if (score >= 0.9) return 'text-[var(--acid-yellow)]';
    return 'text-text-muted';
  };

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-text-muted">Staleness:</span>
          <input
            type="range"
            min="0.5"
            max="1.0"
            step="0.05"
            value={stalenessThreshold}
            onChange={(e) => setStalenessThreshold(parseFloat(e.target.value))}
            className="w-20"
          />
          <span className="font-theme-data text-[var(--acid-cyan)] w-12">
            {(stalenessThreshold * 100).toFixed(0)}%
          </span>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-text-muted">Min Age:</span>
          <input
            type="number"
            min="1"
            max="365"
            value={minAgeDays}
            onChange={(e) => setMinAgeDays(parseInt(e.target.value) || 30)}
            className="w-16 px-2 py-1 bg-panel-bg border border-panel-border rounded font-theme-data"
          />
          <span className="text-text-muted">days</span>
        </label>
        <select
          value={pruneAction}
          onChange={(e) => setPruneAction(e.target.value as PruningAction)}
          className="px-2 py-1 text-sm bg-panel-bg border border-panel-border rounded"
        >
          <option value="archive">Archive</option>
          <option value="delete">Delete</option>
          <option value="demote">Demote</option>
          <option value="flag">Flag</option>
        </select>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={handleScan}
          disabled={isLoading}
          className="px-3 py-1.5 text-sm border border-[var(--acid-cyan)] text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 rounded disabled:opacity-50"
        >
          {isLoading ? 'Scanning...' : 'Scan'}
        </button>
        <button
          onClick={handleLoadHistory}
          disabled={isLoading}
          className="px-3 py-1.5 text-sm border border-text-muted text-text-muted hover:bg-text-muted/10 rounded disabled:opacity-50"
        >
          History
        </button>
        <button
          onClick={() => handleAutoPrune(true)}
          disabled={isLoading}
          className="px-3 py-1.5 text-sm border border-acid-yellow text-[var(--acid-yellow)] hover:bg-acid-yellow/10 rounded disabled:opacity-50"
        >
          Preview Auto-Prune
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="p-3 bg-[var(--crimson)]/10 border border-[var(--crimson)] rounded text-sm text-[var(--crimson)]">
          {error}
        </div>
      )}

      {/* Last Result */}
      {lastResult && (
        <div className="p-3 border border-panel-border rounded bg-panel-bg text-sm">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold">
              {lastResult.success ? 'Pruning Complete' : 'Pruning Failed'}
            </span>
            {lastResult.success && (
              <span className="text-success">{lastResult.items_pruned} items pruned</span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs text-text-muted">
            <div>Analyzed: {lastResult.items_analyzed}</div>
            <div>Archived: {lastResult.items_archived}</div>
            <div>Deleted: {lastResult.items_deleted}</div>
            <div>Demoted: {lastResult.items_demoted}</div>
          </div>
        </div>
      )}

      {/* History Modal */}
      {showHistory && (
        <div className="p-4 border border-panel-border rounded bg-panel-bg max-h-64 overflow-y-auto">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Pruning History</h3>
            <button
              onClick={() => setShowHistory(false)}
              className="text-text-muted hover:text-text-primary"
            >
              ✕
            </button>
          </div>
          {history.length === 0 ? (
            <div className="text-center text-text-muted py-4">No pruning history</div>
          ) : (
            <div className="space-y-2">
              {history.map((entry) => (
                <div
                  key={entry.history_id}
                  className="p-2 border border-panel-border rounded text-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-theme-data">
                      {new Date(entry.executed_at).toLocaleString()}
                    </span>
                    {getActionBadge(entry.action)}
                  </div>
                  <div className="text-text-muted mt-1">
                    {entry.items_pruned} items · {entry.reason} · by {entry.executed_by}
                  </div>
                  {entry.action === 'archive' && entry.pruned_item_ids.length > 0 && (
                    <button
                      onClick={() => handleRestore(entry.pruned_item_ids[0])}
                      className="mt-1 text-[var(--acid-cyan)] hover:underline"
                    >
                      Restore first item
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Items List */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={selectedItems.size === prunableItems.length && prunableItems.length > 0}
              onChange={toggleSelectAll}
              className="rounded"
            />
            <span className="text-text-muted">
              {prunableItems.length} prunable item{prunableItems.length !== 1 ? 's' : ''}
              {selectedItems.size > 0 && ` (${selectedItems.size} selected)`}
            </span>
          </div>
          {selectedItems.size > 0 && (
            <>
              {confirmPrune ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--acid-yellow)]">Confirm {pruneAction}?</span>
                  <button
                    onClick={handlePrune}
                    disabled={isLoading}
                    className="px-2 py-1 text-xs bg-[var(--crimson)] text-white rounded disabled:opacity-50"
                  >
                    Yes, {pruneAction}
                  </button>
                  <button
                    onClick={() => setConfirmPrune(false)}
                    className="px-2 py-1 text-xs border border-text-muted rounded"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmPrune(true)}
                  className="px-3 py-1 text-sm border border-[var(--crimson)] text-[var(--crimson)] hover:bg-[var(--crimson)]/10 rounded"
                >
                  {pruneAction.charAt(0).toUpperCase() + pruneAction.slice(1)} Selected
                </button>
              )}
            </>
          )}
        </div>

        {prunableItems.length === 0 && !isLoading && (
          <div className="p-8 text-center text-text-muted">
            No items match the pruning criteria.
          </div>
        )}

        {prunableItems.map((item) => (
          <div
            key={item.node_id}
            className={`p-3 border rounded ${
              selectedItems.has(item.node_id)
                ? 'border-[var(--acid-cyan)] bg-[var(--acid-cyan)]/5'
                : 'border-panel-border hover:border-text-muted'
            }`}
          >
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={selectedItems.has(item.node_id)}
                onChange={() => toggleSelectItem(item.node_id)}
                className="mt-1 rounded"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-theme-data text-sm truncate">{item.node_id}</span>
                  {getActionBadge(item.recommended_action)}
                </div>
                <div className="text-sm text-text-muted truncate mb-2">{item.content_preview}</div>
                <div className="flex flex-wrap items-center gap-3 text-xs">
                  <span>
                    Staleness:{' '}
                    <span className={`font-theme-data ${getStalenessColor(item.staleness_score)}`}>
                      {(item.staleness_score * 100).toFixed(0)}%
                    </span>
                  </span>
                  <span>
                    Confidence:{' '}
                    <span className="font-theme-data">{(item.confidence * 100).toFixed(0)}%</span>
                  </span>
                  <span>
                    Retrievals: <span className="font-theme-data">{item.retrieval_count}</span>
                  </span>
                  <span>Tier: {item.tier}</span>
                </div>
                <div className="text-xs text-text-muted mt-1">{item.prune_reason}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
