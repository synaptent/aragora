'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '@/config';

interface HeatmapCell {
  category: string;
  subcategory: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  count: number;
  examples: string[];
}

interface HeatmapData {
  gauntlet_id: string;
  categories: string[];
  cells: HeatmapCell[];
  total_findings: number;
  max_count: number;
}

interface GauntletHeatmapProps {
  gauntletId: string;
  apiBase?: string;
  compact?: boolean;
}

const severityColors: Record<string, { bg: string; text: string; border: string }> = {
  critical: { bg: 'bg-red-500', text: 'text-white', border: 'border-red-600' },
  high: { bg: 'bg-orange-500', text: 'text-white', border: 'border-orange-600' },
  medium: { bg: 'bg-yellow-500', text: 'text-black', border: 'border-yellow-600' },
  low: { bg: 'bg-blue-500', text: 'text-white', border: 'border-blue-600' },
  info: { bg: 'bg-gray-500', text: 'text-white', border: 'border-gray-600' },
};

const severityOrder = ['critical', 'high', 'medium', 'low', 'info'];

export function GauntletHeatmap({
  gauntletId,
  apiBase = API_BASE_URL,
  compact = false,
}: GauntletHeatmapProps) {
  const [data, setData] = useState<HeatmapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hoveredCell, setHoveredCell] = useState<HeatmapCell | null>(null);

  const fetchHeatmap = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`${apiBase}/api/gauntlet/${gauntletId}/heatmap`);

      if (!response.ok) {
        throw new Error('Failed to fetch heatmap data');
      }

      const json = await response.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load heatmap');
    } finally {
      setLoading(false);
    }
  }, [apiBase, gauntletId]);

  useEffect(() => {
    fetchHeatmap();
  }, [fetchHeatmap]);

  // Group cells by category and severity
  const heatmapGrid = useMemo(() => {
    if (!data?.cells) return { categories: [], grid: {} };

    const categories = [...new Set(data.cells.map((c) => c.category))];
    const grid: Record<string, Record<string, HeatmapCell>> = {};

    categories.forEach((cat) => {
      grid[cat] = {};
      severityOrder.forEach((sev) => {
        const cell = data.cells.find((c) => c.category === cat && c.severity === sev);
        if (cell) {
          grid[cat][sev] = cell;
        }
      });
    });

    return { categories, grid };
  }, [data]);

  // Calculate cell opacity based on count
  const getCellOpacity = (count: number): number => {
    if (!data?.max_count || data.max_count === 0) return 0.3;
    return 0.3 + (count / data.max_count) * 0.7;
  };

  if (loading) {
    return (
      <div className={`${compact ? 'p-2' : 'p-4'} bg-bg border border-border rounded-lg`}>
        <div className="flex items-center justify-center py-4">
          <div className="animate-spin text-[var(--accent)] text-xl">⟳</div>
          <span className="ml-2 text-text-muted text-sm font-theme-data">Loading heatmap...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`${compact ? 'p-2' : 'p-4'} bg-bg border border-red-500/30 rounded-lg`}>
        <div className="text-red-400 text-sm font-theme-data">{error}</div>
      </div>
    );
  }

  if (!data || data.cells.length === 0) {
    return (
      <div className={`${compact ? 'p-2' : 'p-4'} bg-bg border border-border rounded-lg`}>
        <div className="text-center text-text-muted text-sm font-theme-data py-4">
          No vulnerability data to display
        </div>
      </div>
    );
  }

  return (
    <div className={`${compact ? 'p-2' : 'p-4'} bg-bg border border-border rounded-lg`}>
      {/* Header */}
      {!compact && (
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="text-lg">🔥</span>
            <h3 className="text-sm font-theme-data font-bold text-text uppercase">
              Vulnerability Heatmap
            </h3>
          </div>
          <div className="text-xs text-text-muted font-theme-data">
            {data.total_findings} findings
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-2 mb-4 text-xs font-theme-data">
        <span className="text-text-muted">Severity:</span>
        {severityOrder.map((sev) => (
          <span
            key={sev}
            className={`px-2 py-0.5 rounded ${severityColors[sev].bg} ${severityColors[sev].text}`}
          >
            {sev.toUpperCase()}
          </span>
        ))}
      </div>

      {/* Heatmap Grid */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="p-2 text-left text-xs font-theme-data text-text-muted uppercase border-b border-border">
                Category
              </th>
              {severityOrder.map((sev) => (
                <th
                  key={sev}
                  className="p-2 text-center text-xs font-theme-data text-text-muted uppercase border-b border-border"
                >
                  {sev.slice(0, 4)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {heatmapGrid.categories.map((category) => (
              <tr key={category} className="hover:bg-surface/50">
                <td className="p-2 text-sm font-theme-data text-text border-b border-border/50">
                  {category}
                </td>
                {severityOrder.map((sev) => {
                  const cell = heatmapGrid.grid[category]?.[sev];
                  return (
                    <td
                      key={sev}
                      className="p-1 text-center border-b border-border/50"
                      onMouseEnter={() => cell && setHoveredCell(cell)}
                      onMouseLeave={() => setHoveredCell(null)}
                    >
                      {cell ? (
                        <div
                          className={`
                            w-10 h-10 mx-auto rounded flex items-center justify-center
                            font-theme-data text-sm font-bold cursor-pointer
                            transition-all duration-150 hover:scale-110
                            ${severityColors[sev].bg} ${severityColors[sev].text}
                            ${severityColors[sev].border} border
                          `}
                          style={{ opacity: getCellOpacity(cell.count) }}
                        >
                          {cell.count}
                        </div>
                      ) : (
                        <div className="w-10 h-10 mx-auto rounded bg-surface/30 flex items-center justify-center">
                          <span className="text-text-muted/30">-</span>
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Tooltip */}
      {hoveredCell && (
        <div className="mt-4 p-3 bg-surface border border-border rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`px-2 py-0.5 rounded text-xs font-theme-data ${severityColors[hoveredCell.severity].bg} ${severityColors[hoveredCell.severity].text}`}
            >
              {hoveredCell.severity.toUpperCase()}
            </span>
            <span className="text-sm font-theme-data text-text">
              {hoveredCell.category}
              {hoveredCell.subcategory && ` / ${hoveredCell.subcategory}`}
            </span>
          </div>
          <div className="text-xs text-text-muted font-theme-data mb-2">
            {hoveredCell.count} finding{hoveredCell.count !== 1 ? 's' : ''}
          </div>
          {hoveredCell.examples && hoveredCell.examples.length > 0 && (
            <div className="space-y-1">
              <span className="text-xs text-text-muted font-theme-data">Examples:</span>
              {hoveredCell.examples.slice(0, 3).map((example, i) => (
                <div
                  key={i}
                  className="text-xs text-text bg-bg p-1.5 rounded font-theme-data truncate"
                >
                  {example}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Summary Stats */}
      {!compact && (
        <div className="mt-4 pt-4 border-t border-border grid grid-cols-5 gap-2 text-center">
          {severityOrder.map((sev) => {
            const count = data.cells
              .filter((c) => c.severity === sev)
              .reduce((sum, c) => sum + c.count, 0);
            return (
              <div key={sev}>
                <div
                  className={`text-lg font-theme-data font-bold ${
                    count > 0
                      ? severityColors[sev].text
                          .replace('text-white', 'text-text')
                          .replace('text-black', 'text-text')
                      : 'text-text-muted'
                  }`}
                  style={{ color: count > 0 ? undefined : undefined }}
                >
                  {count}
                </div>
                <div className="text-xs text-text-muted font-theme-data uppercase">{sev}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default GauntletHeatmap;
