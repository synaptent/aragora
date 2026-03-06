'use client';

import { useState } from 'react';
import Link from 'next/link';

interface TeaserResultProps {
  verdict: string;
  confidence: number;
  explanation: string;
  debateId?: string;
  topic?: string;
  participants?: string[];
  proposals?: Record<string, string>;
  receiptHash?: string;
}

const VERDICT_COLORS: Record<string, string> = {
  approved: 'var(--acid-green)',
  approved_with_conditions: 'var(--acid-cyan)',
  needs_review: 'var(--acid-yellow, #ffd700)',
  rejected: 'var(--crimson, #ff0040)',
  consensus_reached: 'var(--acid-green)',
  'analysis complete': 'var(--acid-cyan)',
};

function verdictColor(verdict: string): string {
  const key = verdict.toLowerCase().replace(/\s+/g, '_');
  return VERDICT_COLORS[key] || VERDICT_COLORS[verdict.toLowerCase()] || 'var(--acid-green)';
}

function verdictLabel(verdict: string): string {
  return verdict
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const AGENT_COLORS = [
  'var(--acid-cyan)',
  'var(--acid-magenta)',
  'var(--acid-green)',
  '#f59e0b',
  '#a78bfa',
];

function agentColor(index: number): string {
  return AGENT_COLORS[index % AGENT_COLORS.length];
}

export function TeaserResult({
  verdict,
  confidence,
  explanation,
  debateId,
  topic,
  participants,
  proposals,
  receiptHash,
}: TeaserResultProps) {
  const confidencePercent = Math.round(confidence * 100);
  const [copied, setCopied] = useState(false);
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());

  const vColor = verdictColor(verdict);

  // Show up to 4 agents with excerpts of their proposals
  const visibleAgents = (participants ?? []).slice(0, 4);

  const shareUrl = debateId
    ? `${typeof window !== 'undefined' ? window.location.origin : ''}/debate/${debateId}`
    : undefined;

  const shareText = topic
    ? `I stress-tested "${topic}" with AI agents on Aragora. Here's what they decided:`
    : 'I stress-tested a decision with AI agents on Aragora. Here\'s what they decided:';

  const handleShare = async () => {
    if (!shareUrl) return;

    if (typeof navigator !== 'undefined' && navigator.share) {
      try {
        await navigator.share({
          title: 'Aragora Debate Result',
          text: shareText,
          url: shareUrl,
        });
        return;
      } catch {
        // User cancelled or share failed — fall through to clipboard
      }
    }

    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(`${shareText}\n${shareUrl}`);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {
        // Clipboard API denied — ignore silently
      }
    }
  };

  const toggleAgent = (agent: string) => {
    setExpandedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(agent)) next.delete(agent);
      else next.add(agent);
      return next;
    });
  };

  return (
    <div className="border border-[var(--acid-green)]/30 bg-[var(--surface)]/50">
      {/* Verdict Hero — prominent at top */}
      <div className="p-5 border-b border-[var(--acid-green)]/20">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div className="flex-1 min-w-0">
            <p className="text-xs font-mono text-[var(--text-muted)] mb-1 uppercase tracking-wider">
              VERDICT
            </p>
            <span
              className="text-xl font-mono font-bold"
              style={{ color: vColor }}
            >
              {verdictLabel(verdict)}
            </span>
          </div>
          {/* Confidence gauge */}
          <div className="shrink-0 text-right">
            <p className="text-xs font-mono text-[var(--text-muted)] mb-1 uppercase tracking-wider">
              CONFIDENCE
            </p>
            <div className="flex items-center gap-2 justify-end">
              <div className="w-20 h-2 bg-[var(--bg)] border border-[var(--acid-green)]/20 overflow-hidden">
                <div
                  className="h-full transition-all duration-700"
                  style={{
                    width: `${confidencePercent}%`,
                    backgroundColor: confidencePercent >= 70 ? 'var(--acid-green)' : confidencePercent >= 50 ? '#f59e0b' : 'var(--crimson, #ff0040)',
                  }}
                />
              </div>
              <span className="text-sm font-mono font-bold" style={{ color: vColor }}>
                {confidencePercent}%
              </span>
            </div>
          </div>
        </div>
        {/* Topic */}
        {topic && (
          <p className="text-xs font-mono text-[var(--text-muted)]/60 truncate" title={topic}>
            on: &ldquo;{topic.length > 80 ? topic.slice(0, 80) + '...' : topic}&rdquo;
          </p>
        )}
      </div>

      {/* Summary explanation — show more content */}
      <div className="p-4 border-b border-[var(--acid-green)]/20">
        <p className="text-xs font-mono text-[var(--text-muted)] uppercase tracking-wider mb-2">
          SUMMARY
        </p>
        <p className="text-sm font-mono text-[var(--text)] leading-relaxed">
          {explanation.length > 500 ? explanation.slice(0, 500) + '...' : explanation}
        </p>
      </div>

      {/* Agent Positions — expandable */}
      {visibleAgents.length > 0 && proposals && (
        <div className="p-4 border-b border-[var(--acid-green)]/20">
          <p className="text-xs font-mono text-[var(--text-muted)] uppercase tracking-wider mb-3">
            AGENT POSITIONS ({visibleAgents.length} of {participants?.length ?? 0})
          </p>
          <div className="space-y-2">
            {visibleAgents.map((agent, idx) => {
              const raw = proposals[agent] ?? '';
              const isExpanded = expandedAgents.has(agent);
              const preview = raw.length > 160 ? raw.slice(0, 160) + '...' : raw;
              const color = agentColor(idx);
              return (
                <div
                  key={agent}
                  className="border border-[var(--border)] bg-[var(--bg)]/30"
                >
                  <button
                    onClick={() => toggleAgent(agent)}
                    className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-[var(--acid-green)]/5 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
                      <span className="text-xs font-mono font-bold" style={{ color }}>
                        {agent.toUpperCase()}
                      </span>
                    </div>
                    <span className="text-xs font-mono text-[var(--text-muted)]/60">
                      {isExpanded ? '▲ collapse' : '▼ expand'}
                    </span>
                  </button>
                  {raw && (
                    <div className="px-3 pb-3">
                      <p className="text-xs font-mono text-[var(--text-muted)] leading-relaxed">
                        {isExpanded ? raw : preview}
                      </p>
                      {raw.length > 160 && !isExpanded && (
                        <button
                          onClick={() => toggleAgent(agent)}
                          className="mt-1 text-xs font-mono text-[var(--acid-cyan)] hover:underline"
                        >
                          Read full argument
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {(participants?.length ?? 0) > 4 && (
            <p className="text-xs font-mono text-[var(--text-muted)]/60 mt-2">
              + {(participants?.length ?? 0) - 4} more agent{(participants?.length ?? 0) - 4 > 1 ? 's' : ''} in full transcript
            </p>
          )}
        </div>
      )}

      {/* Share Button — prominent */}
      <div className="p-4 border-b border-[var(--acid-green)]/20">
        {debateId && shareUrl ? (
          <button
            onClick={handleShare}
            className="w-full py-2.5 font-mono font-bold text-sm border border-[var(--acid-green)] text-[var(--acid-green)]
                       hover:bg-[var(--acid-green)]/10 transition-colors flex items-center justify-center gap-2"
          >
            <span>{copied ? '✓ LINK COPIED!' : 'SHARE THIS DEBATE'}</span>
          </button>
        ) : (
          <button
            onClick={() => {
              const text = `I analyzed "${topic || 'a decision'}" with AI agents on Aragora.ai`;
              if (typeof navigator !== 'undefined' && navigator.clipboard) {
                navigator.clipboard.writeText(text).then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                }).catch(() => {});
              }
            }}
            className="w-full py-2.5 font-mono font-bold text-sm border border-[var(--acid-green)]/50 text-[var(--acid-green)]/70
                       hover:border-[var(--acid-green)] hover:text-[var(--acid-green)] transition-colors"
          >
            {copied ? '✓ COPIED!' : 'SHARE ARAGORA.AI'}
          </button>
        )}
      </div>

      {/* Receipt Hash */}
      {receiptHash && (
        <div className="px-4 py-3 border-b border-[var(--acid-green)]/20">
          <div className="flex items-center gap-3 p-2 bg-[var(--bg)]/50 border border-[var(--border)]">
            <span className="text-xs font-mono text-[var(--acid-green)]">&#10003;</span>
            <div className="min-w-0 flex-1">
              <span className="text-xs font-mono text-[var(--text-muted)] block">SHA-256 DECISION RECEIPT</span>
              <p className="text-xs font-mono text-[var(--text-muted)]/60 truncate" title={receiptHash}>
                {receiptHash}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* CTA */}
      <div className="p-4 bg-[var(--acid-green)]/5">
        <Link
          href="/onboarding"
          className="block w-full py-3 text-center font-mono font-bold text-sm bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors"
        >
          GET FULL RECEIPTS — START FREE
        </Link>
        <p className="text-center text-xs font-mono text-[var(--text-muted)] mt-2">
          30 seconds to set up. Full audit trails, shareable receipts, team collaboration.
        </p>
        <p className="text-center text-xs font-mono text-[var(--text-muted)] mt-1">
          Already have an account?{' '}
          <Link href="/login" className="text-[var(--acid-cyan)] hover:underline">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
