'use client';

import { useState, useMemo } from 'react';
import type { ScenarioResult } from './types';

export interface GridViewProps {
  results: ScenarioResult[];
  onSelectCompare: (left: number, right: number) => void;
}

export function GridView({ results, onSelectCompare }: GridViewProps) {
  // Extract all unique parameter keys
  const allParamKeys = useMemo(() => {
    const keys = new Set<string>();
    results.forEach((r) => Object.keys(r.parameters).forEach((k) => keys.add(k)));
    return Array.from(keys);
  }, [results]);

  const [selectedForCompare, setSelectedForCompare] = useState<number | null>(null);
  const [focusedIndex, setFocusedIndex] = useState<number>(0);

  const handleCellClick = (index: number) => {
    if (selectedForCompare === null) {
      setSelectedForCompare(index);
    } else if (selectedForCompare !== index) {
      onSelectCompare(selectedForCompare, index);
      setSelectedForCompare(null);
    } else {
      setSelectedForCompare(null);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent, index: number) => {
    const cols =
      window.innerWidth >= 1280
        ? 4
        : window.innerWidth >= 1024
          ? 3
          : window.innerWidth >= 640
            ? 2
            : 1;
    let newIndex = index;

    switch (e.key) {
      case 'ArrowRight':
        newIndex = Math.min(results.length - 1, index + 1);
        break;
      case 'ArrowLeft':
        newIndex = Math.max(0, index - 1);
        break;
      case 'ArrowDown':
        newIndex = Math.min(results.length - 1, index + cols);
        break;
      case 'ArrowUp':
        newIndex = Math.max(0, index - cols);
        break;
      case 'Enter':
      case ' ':
        e.preventDefault();
        handleCellClick(index);
        return;
      case 'Escape':
        if (selectedForCompare !== null) {
          setSelectedForCompare(null);
        }
        return;
      default:
        return;
    }

    if (newIndex !== index) {
      e.preventDefault();
      setFocusedIndex(newIndex);
      // Focus the new cell
      const cell = document.getElementById(`grid-cell-${newIndex}`);
      cell?.focus();
    }
  };

  return (
    <div className="overflow-x-auto" role="grid" aria-label="Scenario comparison grid">
      <div className="text-xs font-theme-data text-text-muted mb-2" id="grid-instructions">
        Click or press Enter on two scenarios to compare them. Use arrow keys to navigate.
        {selectedForCompare !== null && (
          <span className="text-purple ml-2">
            Selected: {results[selectedForCompare]?.scenario_name} - select another to compare (Esc
            to cancel)
          </span>
        )}
      </div>
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3"
        role="rowgroup"
        aria-describedby="grid-instructions"
      >
        {results.map((r, i) => (
          <div
            key={i}
            id={`grid-cell-${i}`}
            onClick={() => handleCellClick(i)}
            onKeyDown={(e) => handleKeyDown(e, i)}
            tabIndex={i === focusedIndex ? 0 : -1}
            role="gridcell"
            aria-selected={selectedForCompare === i}
            aria-label={`${r.scenario_name}${r.is_baseline ? ' (baseline)' : ''}: ${r.consensus_reached ? 'consensus reached' : 'no consensus'}, ${(r.confidence * 100).toFixed(0)}% confidence`}
            className={`p-3 border cursor-pointer transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-purple/50 ${
              selectedForCompare === i
                ? 'border-purple bg-purple/20 scale-105'
                : r.is_baseline
                  ? 'border-gold/40 hover:border-gold'
                  : r.consensus_reached
                    ? 'border-[var(--accent)]/40 hover:border-[var(--accent)]'
                    : 'border-[var(--crimson)]/40 hover:border-[var(--crimson)]'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span
                className={`text-xs font-theme-data ${r.is_baseline ? 'text-gold' : 'text-text'}`}
              >
                {r.scenario_name}
              </span>
              <span
                className={`w-2 h-2 rounded-full ${r.consensus_reached ? 'bg-[var(--accent)]' : 'bg-[var(--crimson)]'}`}
              />
            </div>

            {/* Mini parameter grid */}
            <div className="space-y-1 mb-2">
              {allParamKeys.slice(0, 3).map((key) => (
                <div key={key} className="flex justify-between text-[10px] font-theme-data">
                  <span className="text-text-muted">{key}:</span>
                  <span className="text-[var(--acid-cyan)]">
                    {String(r.parameters[key] || '-')}
                  </span>
                </div>
              ))}
            </div>

            {/* Confidence bar */}
            <div className="h-1 bg-bg rounded-full overflow-hidden">
              <div
                className={`h-full ${r.consensus_reached ? 'bg-[var(--accent)]' : 'bg-[var(--crimson)]'}`}
                style={{ width: `${r.confidence * 100}%` }}
              />
            </div>
            <div className="text-[10px] font-theme-data text-text-muted mt-1 text-right">
              {(r.confidence * 100).toFixed(0)}%
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default GridView;
