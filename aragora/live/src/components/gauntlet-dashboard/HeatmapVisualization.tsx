'use client';

import React from 'react';
import { SEVERITY_COLORS, type HeatmapData } from './types';

interface HeatmapVisualizationProps {
  data: HeatmapData;
}

export function HeatmapVisualization({ data }: HeatmapVisualizationProps) {
  if (!data.cells.length) {
    return (
      <div className="text-center py-8 text-text-muted font-theme-data text-sm">
        No findings to display
      </div>
    );
  }

  const maxCount = Math.max(...data.cells.map((c) => c.count), 1);

  return (
    <div className="space-y-4">
      {/* Heatmap grid */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="text-xs font-theme-data text-text-muted text-left p-2">Category</th>
              {data.severities.map((sev) => (
                <th
                  key={sev}
                  className="text-xs font-theme-data text-text-muted text-center p-2 capitalize"
                >
                  {sev}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.categories.map((category) => (
              <tr key={category}>
                <td className="text-xs font-theme-data text-text p-2 capitalize">
                  {category.replace(/_/g, ' ')}
                </td>
                {data.severities.map((severity) => {
                  const cell = data.cells.find(
                    (c) => c.category === category && c.severity === severity,
                  );
                  const count = cell?.count || 0;
                  const intensity = count / maxCount;
                  const bgColor = SEVERITY_COLORS[severity] || 'bg-text-muted';

                  return (
                    <td key={severity} className="p-1 text-center">
                      <div
                        className={`w-12 h-12 mx-auto rounded flex items-center justify-center font-theme-data text-sm transition-all ${
                          count > 0 ? `${bgColor}` : 'bg-surface'
                        }`}
                        style={{ opacity: count > 0 ? 0.3 + intensity * 0.7 : 0.2 }}
                        title={`${category} - ${severity}: ${count}`}
                      >
                        {count > 0 && <span className="text-bg font-bold">{count}</span>}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 justify-center text-xs font-theme-data">
        {data.severities.map((severity) => (
          <div key={severity} className="flex items-center gap-2">
            <div
              className={`w-4 h-4 rounded ${SEVERITY_COLORS[severity]}`}
              style={{ opacity: 0.7 }}
            />
            <span className="text-text-muted capitalize">{severity}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
