'use client';

interface PhaseGateProps {
  phaseFrom: string;
  phaseTo: string;
  addedNodes: { id: string; label: string }[];
  removedNodes: { id: string; label: string }[];
  unchangedCount: number;
  onApprove: () => void;
  onEdit: () => void;
  onSkipToEnd: () => void;
  onToggleFullAuto: () => void;
  fullAuto: boolean;
}

export function PhaseGate({
  phaseFrom,
  phaseTo,
  addedNodes,
  removedNodes,
  unchangedCount,
  onApprove,
  onEdit,
  onSkipToEnd,
  onToggleFullAuto,
  fullAuto,
}: PhaseGateProps) {
  return (
    <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm z-30 flex items-center justify-center">
      <div className="bg-surface border border-border rounded-xl p-6 w-[520px] shadow-2xl">
        {/* Header */}
        <div className="mb-4">
          <h3 className="text-sm font-theme-data font-bold text-text">
            Phase Complete: {phaseFrom} {'\u2192'} {phaseTo}
          </h3>
          <p className="text-xs font-theme-data text-text-muted mt-1">
            Review the changes before continuing
          </p>
        </div>

        {/* Diff View */}
        <div className="space-y-2 mb-4 max-h-48 overflow-y-auto">
          {addedNodes.map((n) => (
            <div
              key={n.id}
              className="flex items-center gap-2 px-3 py-1.5 rounded bg-emerald-500/10 border border-emerald-500/20"
            >
              <span className="text-emerald-400 text-xs font-theme-data">+ {n.label}</span>
            </div>
          ))}
          {removedNodes.map((n) => (
            <div
              key={n.id}
              className="flex items-center gap-2 px-3 py-1.5 rounded bg-red-500/10 border border-red-500/20"
            >
              <span className="text-red-400 text-xs font-theme-data">- {n.label}</span>
            </div>
          ))}
          {unchangedCount > 0 && (
            <div className="px-3 py-1.5 text-xs font-theme-data text-text-muted">
              {unchangedCount} unchanged nodes
            </div>
          )}
        </div>

        {/* Summary */}
        <div className="text-xs font-theme-data text-text-muted mb-4 p-2 bg-bg rounded border border-border">
          Found {addedNodes.length} new items from {phaseFrom}. Review and adjust?
        </div>

        {/* Full Auto Toggle */}
        <label className="flex items-center gap-2 mb-4 cursor-pointer">
          <input
            type="checkbox"
            checked={fullAuto}
            onChange={onToggleFullAuto}
            className="rounded border-border bg-bg text-[var(--accent)] focus:ring-acid-green/30"
          />
          <span className="text-xs font-theme-data text-text-muted">
            Full Auto (skip future gates)
          </span>
        </label>

        {/* Action Buttons */}
        <div className="flex items-center justify-between">
          <button
            onClick={onSkipToEnd}
            className="text-xs font-theme-data text-text-muted hover:text-text transition-colors"
          >
            Skip to End
          </button>
          <div className="flex gap-2">
            <button
              onClick={onEdit}
              className="px-4 py-2 text-xs font-theme-data text-indigo-400 border border-indigo-500/30 rounded-lg hover:bg-indigo-500/10 transition-colors"
            >
              Edit
            </button>
            <button
              onClick={onApprove}
              className="px-4 py-2 text-xs font-theme-data bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 transition-colors"
            >
              Approve & Continue
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
