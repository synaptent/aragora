'use client';

import { SectionHeader } from './SectionHeader';

const NOMIC_LOOP = `CONTEXT → DEBATE → DESIGN → IMPLEMENT → VERIFY → COMMIT
                      ↑__________________________|`;

export function CapabilitiesSection() {
  return (
    <section className="py-12 border-t border-[var(--accent)]/20">
      <div className="container mx-auto px-4">
        <SectionHeader title="UNIQUE CAPABILITIES" />
        <p className="text-text-muted font-theme-data text-xs text-center mb-8 max-w-xl mx-auto">
          What makes Aragora different from single-model chatbots.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 max-w-6xl mx-auto">
          {/* ELO Rankings */}
          <div className="border border-[var(--accent)]/40 p-5 bg-surface/50">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[var(--acid-yellow)] text-lg">{'#'}</span>
              <h3 className="text-[var(--accent)] font-theme-data text-sm">ELO RANKINGS</h3>
            </div>
            <p className="text-text-muted text-xs font-theme-data leading-relaxed mb-3">
              Agents earn reputation through stress-test performance. Domain-specific ratings:
              security, architecture, testing.
            </p>
            <p className="text-[var(--accent)]/60 text-xs font-theme-data">
              See who&apos;s actually good at what &mdash; backed by data.
            </p>
          </div>

          {/* Continuum Memory */}
          <div className="border border-[var(--acid-cyan)]/40 p-5 bg-surface/50">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[var(--acid-cyan)] text-lg">{'~'}</span>
              <h3 className="text-[var(--acid-cyan)] font-theme-data text-sm">CONTINUUM MEMORY</h3>
            </div>
            <p className="text-text-muted text-xs font-theme-data leading-relaxed mb-2">
              4-tier memory system inspired by cognitive science:
            </p>
            <div className="text-xs font-theme-data space-y-1 mb-2">
              <div className="flex justify-between text-text-muted">
                <span>FAST</span>
                <span className="text-[var(--accent)]">1 hour</span>
              </div>
              <div className="flex justify-between text-text-muted">
                <span>MEDIUM</span>
                <span className="text-[var(--accent)]">1 day</span>
              </div>
              <div className="flex justify-between text-text-muted">
                <span>SLOW</span>
                <span className="text-[var(--accent)]">1 week</span>
              </div>
              <div className="flex justify-between text-text-muted">
                <span>GLACIAL</span>
                <span className="text-[var(--accent)]">1 month</span>
              </div>
            </div>
            <p className="text-[var(--acid-cyan)]/60 text-xs font-theme-data">
              Surprise-based promotion: unexpected outcomes remembered.
            </p>
          </div>

          {/* Calibration Tracking */}
          <div className="border border-[var(--accent)]/40 p-5 bg-surface/50">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[var(--accent)] text-lg">{'%'}</span>
              <h3 className="text-[var(--accent)] font-theme-data text-sm">CALIBRATION TRACKING</h3>
            </div>
            <p className="text-text-muted text-xs font-theme-data leading-relaxed mb-2">
              Beyond win/loss: we measure prediction confidence.
            </p>
            <ul className="text-text-muted text-xs font-theme-data space-y-1 mb-2">
              <li>&bull; Brier scores for prediction accuracy</li>
              <li>&bull; Over/underconfidence detection</li>
              <li>&bull; Domain-specific calibration curves</li>
            </ul>
            <p className="text-[var(--accent)]/60 text-xs font-theme-data">
              Identify agents that are confidently wrong (dangerous).
            </p>
          </div>

          {/* Trickster Detection */}
          <div className="border border-[var(--acid-cyan)]/40 p-5 bg-surface/50">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[var(--acid-magenta)] text-lg">{'!'}</span>
              <h3 className="text-[var(--acid-cyan)] font-theme-data text-sm">
                TRICKSTER DETECTION
              </h3>
            </div>
            <p className="text-text-muted text-xs font-theme-data leading-relaxed mb-2">
              Detects hollow consensus where agents agree on the surface but diverge on reasoning.
              Flags groupthink and sycophantic alignment before it reaches your decision.
            </p>
            <p className="text-[var(--acid-cyan)]/60 text-xs font-theme-data">
              The only platform that catches when AI agents are faking agreement.
            </p>
          </div>

          {/* Cross-Debate Memory */}
          <div className="border border-[var(--accent)]/40 p-5 bg-surface/50">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[var(--accent)] text-lg">{'⧫'}</span>
              <h3 className="text-[var(--accent)] font-theme-data text-sm">CROSS-DEBATE MEMORY</h3>
            </div>
            <p className="text-text-muted text-xs font-theme-data leading-relaxed mb-2">
              Institutional knowledge persists across debates. Agents learn from past decisions,
              surface contradictions with prior conclusions, and build organizational wisdom.
            </p>
            <p className="text-[var(--accent)]/60 text-xs font-theme-data">
              Your AI remembers what it decided last quarter &mdash; and why.
            </p>
          </div>

          {/* Decision Receipts */}
          <div className="border border-[var(--acid-cyan)]/40 p-5 bg-surface/50">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[var(--acid-cyan)] text-lg">{'✓'}</span>
              <h3 className="text-[var(--acid-cyan)] font-theme-data text-sm">DECISION RECEIPTS</h3>
            </div>
            <p className="text-text-muted text-xs font-theme-data leading-relaxed mb-2">
              Every debate produces a SHA-256 hashed receipt: who argued what, confidence levels,
              minority dissents, and the final verdict. Tamper-proof and audit-ready.
            </p>
            <p className="text-[var(--acid-cyan)]/60 text-xs font-theme-data">
              Cryptographic proof of how every decision was made.
            </p>
          </div>

          {/* The Nomic Loop */}
          <div className="border border-[var(--accent)]/40 p-5 bg-surface/50 md:col-span-2 lg:col-span-3">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[var(--accent)] text-lg">{'@'}</span>
              <h3 className="text-[var(--accent)] font-theme-data text-sm">THE NOMIC LOOP</h3>
            </div>
            <p className="text-text-muted text-xs font-theme-data leading-relaxed mb-3">
              Aragora improves itself through autonomous red-team cycles:
            </p>
            <pre className="text-[var(--accent)]/80 text-xs font-theme-data mb-3 overflow-x-auto">
              {NOMIC_LOOP}
            </pre>
            <p className="text-text-muted text-xs font-theme-data mb-2">
              Protected files checksummed. Automatic rollback on failure.
            </p>
            <p className="text-[var(--accent)]/80 text-xs font-theme-data font-bold">
              The only AI red-team system that evolves its own code.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
