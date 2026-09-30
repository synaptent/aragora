'use client';

import { useState, useMemo } from 'react';

export interface ComplianceFramework {
  framework_id: string;
  name: string;
  description: string;
  level: 'mandatory' | 'recommended' | 'optional';
  vertical_id: string;
  rules_count: number;
  enabled: boolean;
}

export interface ComplianceFrameworkListProps {
  frameworks: ComplianceFramework[];
  onSelectFramework?: (framework: ComplianceFramework) => void;
  verticals: Array<{ id: string; name: string }>;
  selectedVertical: string | null;
  onVerticalChange: (vertical: string | null) => void;
  className?: string;
}

const LEVEL_COLORS: Record<string, string> = {
  mandatory: 'bg-red-900/30 text-red-400 border-red-800/30',
  recommended: 'bg-yellow-900/30 text-yellow-400 border-yellow-800/30',
  optional: 'bg-blue-900/30 text-blue-400 border-blue-800/30',
};

export function ComplianceFrameworkList({
  frameworks,
  onSelectFramework,
  verticals,
  selectedVertical,
  onVerticalChange,
  className = '',
}: ComplianceFrameworkListProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const filteredFrameworks = useMemo(() => {
    let result = frameworks;
    if (selectedVertical) {
      result = result.filter((fw) => fw.vertical_id === selectedVertical);
    }
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (fw) =>
          fw.name.toLowerCase().includes(query) || fw.description.toLowerCase().includes(query),
      );
    }
    return result;
  }, [frameworks, selectedVertical, searchQuery]);

  const groupedFrameworks = useMemo(() => {
    const groups: Record<string, ComplianceFramework[]> = {};
    filteredFrameworks.forEach((fw) => {
      if (!groups[fw.vertical_id]) groups[fw.vertical_id] = [];
      groups[fw.vertical_id].push(fw);
    });
    return groups;
  }, [filteredFrameworks]);

  const handleClick = (fw: ComplianceFramework) => {
    setExpandedId(expandedId === fw.framework_id ? null : fw.framework_id);
    onSelectFramework?.(fw);
  };

  return (
    <div className={className}>
      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search frameworks..."
          className="flex-1 min-w-[200px] px-3 py-2 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none"
        />
        <select
          value={selectedVertical || ''}
          onChange={(e) => onVerticalChange(e.target.value || null)}
          className="px-3 py-2 text-sm bg-bg border border-border rounded focus:border-[var(--accent)] focus:outline-none"
        >
          <option value="">All Verticals</option>
          {verticals.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
      </div>

      {/* Frameworks */}
      {Object.keys(groupedFrameworks).length === 0 ? (
        <div className="text-center py-8 text-text-muted">No frameworks found</div>
      ) : (
        <div className="space-y-6">
          {Object.entries(groupedFrameworks).map(([verticalId, vFrameworks]) => {
            const vertical = verticals.find((v) => v.id === verticalId);
            return (
              <div key={verticalId}>
                {!selectedVertical && (
                  <h3 className="font-theme-data font-bold text-text mb-3">
                    {vertical?.name || verticalId}
                  </h3>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {vFrameworks.map((fw) => (
                    <div
                      key={fw.framework_id}
                      onClick={() => handleClick(fw)}
                      className={`p-4 bg-bg border rounded-lg cursor-pointer transition-all ${
                        expandedId === fw.framework_id
                          ? 'border-[var(--accent)]'
                          : 'border-border hover:border-text-muted'
                      } ${!fw.enabled ? 'opacity-60' : ''}`}
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div>
                          <h4 className="font-theme-data font-bold text-text">{fw.name}</h4>
                          <span className="text-xs font-theme-data text-text-muted">
                            {fw.framework_id.toUpperCase()}
                          </span>
                        </div>
                        <span
                          className={`px-2 py-0.5 text-xs font-theme-data uppercase rounded border ${LEVEL_COLORS[fw.level]}`}
                        >
                          {fw.level}
                        </span>
                      </div>
                      <p className="text-sm text-text-muted mb-3">{fw.description}</p>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-text-muted">{fw.rules_count} rules</span>
                        <span
                          className={`px-2 py-0.5 rounded ${fw.enabled ? 'bg-green-900/30 text-green-400' : 'bg-surface text-text-muted'}`}
                        >
                          {fw.enabled ? 'ENABLED' : 'DISABLED'}
                        </span>
                      </div>
                      {expandedId === fw.framework_id && (
                        <div className="mt-4 pt-4 border-t border-border">
                          <div className="flex gap-2">
                            <button className="flex-1 px-3 py-1.5 text-xs font-theme-data bg-surface border border-border rounded hover:border-[var(--accent)] transition-colors">
                              Configure
                            </button>
                            <button
                              className={`flex-1 px-3 py-1.5 text-xs font-theme-data rounded transition-colors ${
                                fw.enabled
                                  ? 'bg-red-900/30 text-red-400 border border-red-800/30'
                                  : 'bg-green-900/30 text-green-400 border border-green-800/30'
                              }`}
                            >
                              {fw.enabled ? 'Disable' : 'Enable'}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
