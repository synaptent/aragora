'use client';

type Severity = 'critical' | 'high' | 'medium' | 'low';

interface Risk {
  severity: Severity;
  target: string;
  message: string;
}

interface RiskRegisterProps {
  risks: Risk[];
}

const SEVERITY_STYLES: Record<Severity, { badge: string; text: string }> = {
  critical: {
    badge: 'bg-[var(--crimson)]/20 text-[var(--crimson)] border-[var(--crimson)]/40',
    text: 'text-[var(--crimson)]',
  },
  high: {
    badge: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
    text: 'text-[var(--acid-yellow)]',
  },
  medium: {
    badge: 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40',
    text: 'text-[var(--acid-cyan)]',
  },
  low: { badge: 'bg-surface text-text-muted border-border', text: 'text-text-muted' },
};

export function RiskRegister({ risks }: RiskRegisterProps) {
  if (risks.length === 0) {
    return (
      <div className="text-center text-text-muted font-theme-data text-xs py-4">
        No risks detected
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {risks.map((risk, idx) => {
        const style = SEVERITY_STYLES[risk.severity];
        return (
          <div
            key={idx}
            className="flex items-start gap-3 bg-surface rounded border border-border p-3"
          >
            <span
              className={`font-theme-data text-[10px] uppercase px-1.5 py-0.5 rounded border shrink-0 ${style.badge}`}
            >
              {risk.severity}
            </span>
            <div className="min-w-0">
              <div className={`font-theme-data text-xs font-bold ${style.text}`}>{risk.target}</div>
              <div className="font-theme-data text-xs text-text-muted mt-0.5 break-words">
                {risk.message}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
