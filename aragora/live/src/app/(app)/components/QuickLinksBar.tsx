'use client';

import Link from 'next/link';
import { useProgressiveMode, type ProgressiveMode } from '@/context/ProgressiveModeContext';

interface QuickLink {
  href: string;
  label: string;
  color: string;
  minMode: ProgressiveMode;
}

const QUICK_LINKS: QuickLink[] = [
  { href: '/debates', label: 'ARCHIVE', color: 'acid-green', minMode: 'simple' },
  { href: '/debates/graph', label: 'GRAPH', color: 'acid-cyan', minMode: 'standard' },
  { href: '/debates/matrix', label: 'MATRIX', color: 'gold', minMode: 'advanced' },
  { href: '/agents', label: 'AGENTS', color: 'acid-green', minMode: 'simple' },
  { href: '/network', label: 'NETWORK', color: 'acid-green', minMode: 'standard' },
  { href: '/insights', label: 'INSIGHTS', color: 'acid-green', minMode: 'standard' },
  { href: '/evidence', label: 'EVIDENCE', color: 'acid-green', minMode: 'standard' },
  { href: '/training', label: 'TRAINING', color: 'acid-green', minMode: 'advanced' },
  { href: '/pulse', label: 'PULSE', color: 'acid-green', minMode: 'standard' },
  { href: '/gauntlet', label: 'GAUNTLET', color: 'acid-green', minMode: 'advanced' },
  { href: '/leaderboard', label: 'RANKS', color: 'gold', minMode: 'simple' },
  { href: '/analytics', label: 'ANALYTICS', color: 'acid-cyan', minMode: 'standard' },
  { href: '/probe', label: 'PROBE', color: 'acid-yellow', minMode: 'advanced' },
  { href: '/checkpoints', label: 'SAVES', color: 'acid-green', minMode: 'advanced' },
  { href: '/verify', label: 'PROOFS', color: 'acid-purple', minMode: 'advanced' },
  { href: '/quality', label: 'QUALITY', color: 'acid-cyan', minMode: 'standard' },
  { href: '/calibration', label: 'CALIBRATE', color: 'gold', minMode: 'advanced' },
  { href: '/modes', label: 'MODES', color: 'warning', minMode: 'advanced' },
  { href: '/compare', label: 'COMPARE', color: 'acid-green', minMode: 'standard' },
  { href: '/crux', label: 'CRUX', color: 'acid-purple', minMode: 'standard' },
  { href: '/red-team', label: 'REDTEAM', color: 'warning', minMode: 'expert' },
  { href: '/memory-analytics', label: 'MEM', color: 'acid-cyan', minMode: 'advanced' },
  { href: '/webhooks', label: 'HOOKS', color: 'acid-green', minMode: 'expert' },
  { href: '/scheduler', label: 'SCHEDULER', color: 'acid-cyan', minMode: 'advanced' },
  { href: '/selection', label: 'SELECTION', color: 'acid-purple', minMode: 'advanced' },
  { href: '/ml', label: 'ML', color: 'gold', minMode: 'expert' },
  { href: '/receipts', label: 'RECEIPTS', color: 'acid-cyan', minMode: 'advanced' },
  { href: '/knowledge', label: 'KNOWLEDGE', color: 'acid-purple', minMode: 'standard' },
  { href: '/broadcast', label: 'BROADCAST', color: 'gold', minMode: 'advanced' },
  { href: '/verification', label: 'VERIFY', color: 'acid-green', minMode: 'advanced' },
  { href: '/admin', label: 'ADMIN', color: 'warning', minMode: 'expert' },
  { href: '/developer', label: 'DEV', color: 'acid-green', minMode: 'expert' },
];

export function QuickLinksBar() {
  const { isFeatureVisible } = useProgressiveMode();

  return (
    <div className="hidden sm:block border-b border-[var(--accent)]/10 bg-surface/30">
      <div className="max-w-screen-2xl mx-auto px-3 sm:px-4 lg:px-6 py-1.5">
        <div className="flex items-center gap-1 overflow-x-auto scrollbar-hide">
          <span className="text-[9px] font-theme-data text-text-muted/40 mr-2 shrink-0">
            EXPLORE:
          </span>
          {QUICK_LINKS.filter((link) => isFeatureVisible(link.minMode)).map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`px-2 py-0.5 text-[10px] font-theme-data text-text-muted/60 hover:text-${link.color} hover:bg-${link.color}/5 transition-colors shrink-0`}
            >
              [{link.label}]
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
