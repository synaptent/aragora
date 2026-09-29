'use client';

interface Finding {
  severity: 'critical' | 'high' | 'medium' | 'low';
  title: string;
  recommendation: string;
  attackType: string;
}

interface GauntletValidationPanelProps {
  nodeId: string;
  findings: Finding[];
  verdict: string;
  loading: boolean;
}

const SEVERITY_CONFIG: Record<string, { bg: string; text: string; border: string; label: string }> =
  {
    critical: {
      bg: 'bg-red-500/10',
      text: 'text-red-400',
      border: 'border-red-500/30',
      label: 'CRIT',
    },
    high: {
      bg: 'bg-orange-500/10',
      text: 'text-orange-400',
      border: 'border-orange-500/30',
      label: 'HIGH',
    },
    medium: {
      bg: 'bg-yellow-500/10',
      text: 'text-yellow-400',
      border: 'border-yellow-500/30',
      label: 'MED',
    },
    low: {
      bg: 'bg-blue-500/10',
      text: 'text-blue-400',
      border: 'border-blue-500/30',
      label: 'LOW',
    },
  };

export function GauntletValidationPanel({
  nodeId: _nodeId,
  findings,
  verdict,
  loading,
}: GauntletValidationPanelProps) {
  if (loading) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <span>{'\u{1F6E1}'}</span>
          <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
            Gauntlet Validation
          </h4>
          <div className="w-3 h-3 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
        </div>
        <div className="text-xs font-theme-data text-text-muted animate-pulse">
          Running adversarial tests...
        </div>
      </div>
    );
  }

  if (findings.length === 0) return null;

  const counts = findings.reduce(
    (acc, f) => {
      acc[f.severity] = (acc[f.severity] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span>{'\u{1F6E1}'}</span>
        <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
          Gauntlet Validation
        </h4>
      </div>

      {/* Summary */}
      <div className="flex gap-2">
        {Object.entries(counts).map(([sev, count]) => {
          const c = SEVERITY_CONFIG[sev] || SEVERITY_CONFIG.low;
          return (
            <span
              key={sev}
              className={`px-2 py-0.5 text-[10px] font-theme-data rounded border ${c.bg} ${c.text} ${c.border}`}
            >
              {c.label}: {count}
            </span>
          );
        })}
      </div>

      {/* Verdict */}
      {verdict && (
        <div
          className={`px-3 py-2 text-xs font-theme-data rounded border ${
            verdict.toLowerCase().includes('pass')
              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
              : 'bg-red-500/10 text-red-400 border-red-500/30'
          }`}
        >
          Verdict: {verdict}
        </div>
      )}

      {/* Findings List */}
      <div className="space-y-1.5 max-h-48 overflow-y-auto">
        {findings.map((f, i) => {
          const c = SEVERITY_CONFIG[f.severity] || SEVERITY_CONFIG.low;
          return (
            <div key={i} className={`px-2.5 py-2 rounded border ${c.border} bg-bg`}>
              <div className="flex items-center gap-2 mb-1">
                <span
                  className={`px-1.5 py-0.5 text-[9px] font-theme-data font-bold rounded ${c.bg} ${c.text}`}
                >
                  {c.label}
                </span>
                <span className="text-xs font-theme-data text-text truncate">{f.title}</span>
              </div>
              <p className="text-[10px] font-theme-data text-text-muted">{f.recommendation}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
