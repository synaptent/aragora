'use client';

import Link from 'next/link';

interface Vertical {
  id: string;
  name: string;
  icon: string;
  path: string;
  description: string;
  color: string;
}

const VERTICALS: Vertical[] = [
  {
    id: 'legal',
    name: 'LEGAL',
    icon: '{}',
    path: '/verticals/legal',
    description: 'Contract analysis, case research, compliance',
    color:
      'text-[var(--acid-cyan)] hover:text-[var(--acid-cyan)]/80 hover:bg-[var(--acid-cyan)]/10',
  },
  {
    id: 'healthcare',
    name: 'HEALTHCARE',
    icon: '+',
    path: '/verticals/healthcare',
    description: 'Clinical decisions, research synthesis',
    color: 'text-[var(--accent)] hover:text-[var(--accent)]/80 hover:bg-[var(--accent)]/10',
  },
  {
    id: 'finance',
    name: 'FINANCE',
    icon: '$',
    path: '/verticals/finance',
    description: 'Risk analysis, investment thesis testing',
    color: 'text-gold hover:text-gold/80 hover:bg-gold/10',
  },
  {
    id: 'engineering',
    name: 'ENGINEERING',
    icon: '#',
    path: '/verticals/engineering',
    description: 'Architecture review, code analysis',
    color: 'text-acid-purple hover:text-acid-purple/80 hover:bg-acid-purple/10',
  },
  {
    id: 'research',
    name: 'RESEARCH',
    icon: '~',
    path: '/verticals/research',
    description: 'Literature review, hypothesis testing',
    color: 'text-warning hover:text-warning/80 hover:bg-warning/10',
  },
];

interface VerticalChipProps {
  vertical: Vertical;
}

function VerticalChip({ vertical }: VerticalChipProps) {
  return (
    <Link
      href={vertical.path}
      className={`
        inline-flex items-center gap-2 px-3 py-2
        border border-[var(--accent)]/20
        font-theme-data text-[10px] tracking-wider
        transition-all duration-200
        ${vertical.color}
      `}
    >
      <span className="opacity-60">{vertical.icon}</span>
      <span>{vertical.name}</span>
    </Link>
  );
}

export function VerticalCards() {
  return (
    <section className="py-6">
      {/* Section Header */}
      <div className="text-center mb-4">
        <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest">
          BY INDUSTRY
        </h2>
      </div>

      {/* Vertical Chips */}
      <div className="flex flex-wrap justify-center gap-2">
        {VERTICALS.map((vertical) => (
          <VerticalChip key={vertical.id} vertical={vertical} />
        ))}
      </div>

      {/* Subtitle */}
      <p className="text-center text-text-muted/30 font-theme-data text-[9px] mt-3">
        Pre-configured specialists for domain-specific analysis
      </p>
    </section>
  );
}

export { VERTICALS };
export type { Vertical };
