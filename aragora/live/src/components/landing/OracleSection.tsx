'use client';

import Link from 'next/link';
import { useTheme } from '@/context/ThemeContext';

const ORACLE_MODES = [
  {
    name: 'Consult',
    description: 'Quick answers with streaming responses from any model.',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    ),
  },
  {
    name: 'Divine',
    description: 'Deep analysis with extended reasoning and evidence chains.',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 16v-4" /><path d="M12 8h.01" />
      </svg>
    ),
  },
  {
    name: 'Commune',
    description: 'Full multi-agent debate with live streaming and consensus.',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
      </svg>
    ),
  },
];

export function OracleSection() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <section
      className="px-4"
      style={{
        paddingTop: 'var(--section-padding)',
        paddingBottom: 'var(--section-padding)',
        borderTop: '1px solid var(--border)',
        fontFamily: 'var(--font-landing)',
      }}
    >
      <div className="max-w-4xl mx-auto">
        <p
          className="text-center mb-4 uppercase tracking-widest"
          style={{ fontSize: isDark ? '16px' : '18px', color: 'var(--text-muted)', fontFamily: 'var(--font-landing)' }}
        >
          {isDark ? '> THE ORACLE' : 'THE ORACLE'}
        </p>
        <p
          className="text-center mb-12 max-w-xl mx-auto"
          style={{ fontSize: isDark ? '16px' : '18px', color: 'var(--text)', fontFamily: 'var(--font-landing)' }}
        >
          A real-time AI interface with three modes of consultation — from quick answers to full adversarial debates.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
          {ORACLE_MODES.map((mode) => (
            <div
              key={mode.name}
              className="transition-all hover:translate-y-[-2px]"
              style={{
                backgroundColor: 'var(--surface)',
                borderRadius: 'var(--radius-card)',
                border: '1px solid var(--border)',
                boxShadow: 'var(--shadow-card)',
                padding: '24px 20px',
              }}
            >
              <div className="flex items-center gap-3 mb-3" style={{ color: 'var(--accent)' }}>
                {mode.icon}
                <h3
                  className="font-semibold uppercase tracking-wider"
                  style={{ fontSize: '12px', color: 'var(--text)', fontFamily: 'var(--font-landing)' }}
                >
                  {mode.name}
                </h3>
              </div>
              <p
                className="leading-relaxed"
                style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-landing)', lineHeight: '1.7' }}
              >
                {mode.description}
              </p>
            </div>
          ))}
        </div>

        <div className="text-center">
          <Link
            href="/oracle"
            className="inline-block text-sm font-semibold transition-all hover:scale-[1.02]"
            style={{
              backgroundColor: 'var(--accent)',
              color: 'var(--bg)',
              borderRadius: 'var(--radius-button)',
              fontFamily: 'var(--font-landing)',
              padding: '18px 48px',
            }}
          >
            {isDark ? '> Try the Oracle' : 'Try the Oracle'}
          </Link>
        </div>
      </div>
    </section>
  );
}
