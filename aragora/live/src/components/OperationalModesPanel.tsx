'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

interface OperationalMode {
  name: string;
  description: string;
  category: string;
  tool_groups?: string[];
}

interface OperationalModesPanelProps {
  apiBase?: string;
  onModeSelect?: (mode: OperationalMode) => void;
}

const DEFAULT_API_BASE = API_BASE_URL;

const CATEGORY_COLORS: Record<string, string> = {
  operational: 'text-blue-400 bg-blue-400/10 border-blue-400/30',
  debate: 'text-green-400 bg-green-400/10 border-green-400/30',
  analysis: 'text-purple-400 bg-purple-400/10 border-purple-400/30',
  security: 'text-red-400 bg-red-400/10 border-red-400/30',
};

const CATEGORY_ICONS: Record<string, string> = {
  operational: '⚙️',
  debate: '💬',
  analysis: '🔍',
  security: '🛡️',
};

export function OperationalModesPanel({
  apiBase = DEFAULT_API_BASE,
  onModeSelect,
}: OperationalModesPanelProps) {
  const { tokens } = useAuth();
  const [isExpanded, setIsExpanded] = useState(false);
  const [modes, setModes] = useState<OperationalMode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [expandedMode, setExpandedMode] = useState<string | null>(null);

  const fetchModes = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const response = await fetch(`${apiBase}/api/modes`, { headers });
      if (!response.ok) {
        throw new Error(`Failed to fetch modes: ${response.statusText}`);
      }

      const data = await response.json();
      setModes(data.modes || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load modes');
    } finally {
      setLoading(false);
    }
  }, [apiBase, tokens?.access_token]);

  useEffect(() => {
    fetchModes();
  }, [fetchModes]);

  // Get unique categories
  const categories = Array.from(new Set(modes.map((m) => m.category)));

  // Filter modes by selected category
  const filteredModes = selectedCategory
    ? modes.filter((m) => m.category === selectedCategory)
    : modes;

  // Collapsed view
  if (!isExpanded) {
    return (
      <div className="panel panel-compact cursor-pointer" onClick={() => setIsExpanded(true)}>
        <div className="flex items-center justify-between">
          <h3 className="panel-title-sm flex items-center gap-2">
            <span className="text-accent">{'>'}</span>
            OPERATIONAL_MODES
            <span className="panel-badge">{modes.length}</span>
          </h3>
          <div className="flex items-center gap-2">
            {categories.length > 0 && (
              <span className="text-xs font-theme-data text-text-muted">
                {categories.length} categories
              </span>
            )}
            <span className="panel-toggle">[EXPAND]</span>
          </div>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="panel">
        <div className="panel-empty animate-pulse">Loading modes...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel">
        <div className="bg-red-900/20 border border-red-800 rounded p-3 text-red-400 text-sm">
          {error}
        </div>
        <button onClick={fetchModes} className="mt-2 text-sm text-accent hover:underline">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header mb-4">
        <h3 className="panel-title-sm flex items-center gap-2">
          <span className="text-accent">{'>'}</span>
          OPERATIONAL_MODES
        </h3>
        <button onClick={() => setIsExpanded(false)} className="panel-toggle hover:text-accent">
          [COLLAPSE]
        </button>
      </div>

      {/* Category Filter */}
      <div className="flex gap-2 mb-4 flex-wrap">
        <button
          onClick={() => setSelectedCategory(null)}
          className={`px-3 py-1 rounded text-sm ${
            selectedCategory === null
              ? 'bg-zinc-300 dark:bg-zinc-700 text-zinc-900 dark:text-white'
              : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300'
          }`}
        >
          All ({modes.length})
        </button>
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setSelectedCategory(cat)}
            className={`px-3 py-1 rounded text-sm flex items-center gap-1 ${
              selectedCategory === cat
                ? 'bg-zinc-300 dark:bg-zinc-700 text-zinc-900 dark:text-white'
                : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300'
            }`}
          >
            <span>{CATEGORY_ICONS[cat] || '📌'}</span>
            {cat} ({modes.filter((m) => m.category === cat).length})
          </button>
        ))}
      </div>

      {/* Modes List */}
      <div className="space-y-2">
        {filteredModes.length === 0 ? (
          <div className="text-zinc-500 text-center py-4">No modes available</div>
        ) : (
          filteredModes.map((mode) => (
            <div
              key={mode.name}
              className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg overflow-hidden"
            >
              {/* Mode Header */}
              <div
                className="p-3 flex items-center justify-between cursor-pointer hover:bg-zinc-100 dark:hover:bg-zinc-700/50"
                onClick={() => setExpandedMode(expandedMode === mode.name ? null : mode.name)}
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`px-2 py-0.5 rounded text-xs border ${
                      CATEGORY_COLORS[mode.category] ||
                      'text-zinc-400 bg-zinc-400/10 border-zinc-400/30'
                    }`}
                  >
                    {mode.category}
                  </span>
                  <span className="font-medium text-white">{mode.name}</span>
                </div>
                <div className="flex items-center gap-2">
                  {onModeSelect && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onModeSelect(mode);
                      }}
                      className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded"
                    >
                      Select
                    </button>
                  )}
                  <span className="text-zinc-500">{expandedMode === mode.name ? '▼' : '▶'}</span>
                </div>
              </div>

              {/* Mode Details (Expanded) */}
              {expandedMode === mode.name && (
                <div className="px-3 pb-3 border-t border-zinc-200 dark:border-zinc-700">
                  <p className="text-zinc-500 dark:text-zinc-400 text-sm mt-2">
                    {mode.description}
                  </p>

                  {mode.tool_groups && mode.tool_groups.length > 0 && (
                    <div className="mt-3">
                      <span className="text-xs text-zinc-400 dark:text-zinc-500 uppercase">
                        Tool Groups:
                      </span>
                      <div className="flex gap-2 mt-1 flex-wrap">
                        {mode.tool_groups.map((group) => (
                          <span
                            key={group}
                            className="px-2 py-0.5 bg-zinc-200 dark:bg-zinc-700 text-zinc-700 dark:text-zinc-300 text-xs rounded"
                          >
                            {group}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <div className="mt-3 text-[10px] text-text-muted font-theme-data">
        Available debate and operational mode configurations
      </div>
    </div>
  );
}

export default OperationalModesPanel;
