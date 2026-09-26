'use client';

import { Suspense } from 'react';
import { CommandCenter } from '@/components/inbox/CommandCenter';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';

function CommandCenterLoading() {
  return (
    <div className="min-h-screen bg-[var(--bg)] flex items-center justify-center">
      <div className="text-center">
        <div className="text-4xl mb-4 animate-pulse">📬</div>
        <div className="text-[var(--acid-green)] font-theme-data animate-pulse">
          Loading Command Center...
        </div>
      </div>
    </div>
  );
}

export default function CommandCenterPage() {
  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-2">
                  {'>'} INBOX COMMAND CENTER
                </h1>
                <p className="text-xs text-[var(--text-muted)] font-theme-data">
                  AI-powered email triage with multi-agent prioritization
                </p>
              </div>

              {/* Status indicators */}
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 px-3 py-1 bg-surface/50 border border-[var(--accent)]/30 rounded-full">
                  <span className="w-2 h-2 bg-[var(--accent)] rounded-full animate-pulse" />
                  <span className="text-xs font-theme-data text-[var(--accent)]">Live</span>
                </div>
                <div className="flex items-center gap-2 px-3 py-1 bg-surface/50 border border-[var(--acid-cyan)]/30 rounded-full">
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                    3-Tier Scoring
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Main Command Center */}
          <Suspense fallback={<CommandCenterLoading />}>
            <CommandCenter />
          </Suspense>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2">{'═'.repeat(40)}</div>
          <p className="text-[var(--text-muted)]">
            {'>'} COMMAND CENTER // PROCESS UNRULY INBOXES WITH AI
          </p>
          <div className="text-[var(--acid-green)]/50 mt-4">{'═'.repeat(40)}</div>
        </footer>
      </main>
    </>
  );
}
