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
  const truncated = explanation.length > 200 ? explanation.slice(0, 200) + '...' : explanation;
  const [copied, setCopied] = useState(false);

  // Show up to 3 agents with excerpts of their proposals
  const visibleAgents = (participants ?? []).slice(0, 3);

  const shareUrl = debateId
    ? `${typeof window !== 'undefined' ? window.location.origin : ''}/debate/${debateId}`
    : undefined;

  const shareText = topic
    ? `I stress-tested "${topic}" with AI agents on Aragora. Here's what they decided:`
    : 'I stress-tested a decision with AI agents on Aragora. Here\'s what they decided:';

  const handleShare = async () => {
    if (!shareUrl) return;

    // Prefer Web Share API where available
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

    // Clipboard fallback
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

  return (
    <div className="border border-[var(--acid-green)]/30 bg-[var(--surface)]/50">
      {/* Result Header */}
      <div className="p-4 border-b border-[var(--acid-green)]/20">
        <div className="flex items-center justify-between mb-3">
          <span className="px-3 py-1 text-sm font-mono font-bold bg-[var(--acid-green)]/20 text-[var(--acid-green)] border border-[var(--acid-green)]/30">
            {verdict}
          </span>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-[var(--text-muted)]">CONFIDENCE</span>
            <div className="w-24 h-2 bg-[var(--bg)] border border-[var(--acid-green)]/20 overflow-hidden">
              <div
                className="h-full bg-[var(--acid-green)] transition-all duration-500"
                style={{ width: `${confidencePercent}%` }}
              />
            </div>
            <span className="text-xs font-mono text-[var(--acid-green)]">{confidencePercent}%</span>
          </div>
        </div>
      </div>

      {/* Visible Explanation */}
      <div className="p-4 border-b border-[var(--acid-green)]/20">
        <p className="text-sm font-mono text-[var(--text)] leading-relaxed">
          {truncated}
        </p>
      </div>

      {/* Agent Positions */}
      {visibleAgents.length > 0 && proposals && (
        <div className="p-4 border-b border-[var(--acid-green)]/20 space-y-3">
          <span className="text-xs font-mono text-[var(--text-muted)] uppercase tracking-wider">
            Agent Positions
          </span>
          {visibleAgents.map((agent) => {
            const raw = proposals[agent] ?? '';
            const excerpt = raw.length > 100 ? raw.slice(0, 100) + '...' : raw;
            return (
              <div
                key={agent}
                className="p-3 bg-[var(--bg)]/50 border border-[var(--border)]"
              >
                <span className="text-xs font-mono font-bold text-[var(--acid-green)]">
                  {agent.toUpperCase()}
                </span>
                {excerpt && (
                  <p className="mt-1 text-xs font-mono text-[var(--text-muted)] leading-relaxed">
                    {excerpt}
                  </p>
                )}
              </div>
            );
          })}
          {(participants?.length ?? 0) > 3 && (
            <p className="text-xs font-mono text-[var(--text-muted)]/60">
              + {(participants?.length ?? 0) - 3} more agent{(participants?.length ?? 0) - 3 > 1 ? 's' : ''}
            </p>
          )}
        </div>
      )}

      {/* Share Button */}
      {debateId && shareUrl && (
        <div className="p-4 border-b border-[var(--acid-green)]/20">
          <button
            onClick={handleShare}
            className="w-full py-3 font-mono font-bold text-sm border border-[var(--acid-green)] text-[var(--acid-green)]
                       hover:bg-[var(--acid-green)]/10 transition-colors"
          >
            {copied ? 'LINK COPIED!' : 'SHARE THIS DEBATE'}
          </button>
        </div>
      )}

      {/* Receipt Hash */}
      {receiptHash && (
        <div className="p-4 border-b border-[var(--acid-green)]/20">
          <div className="flex items-center gap-3 p-3 bg-[var(--bg)]/50 border border-[var(--border)]">
            <span className="text-xs font-mono text-[var(--acid-green)]">&#10003;</span>
            <div className="min-w-0">
              <span className="text-xs font-mono text-[var(--text-muted)]">SHA-256 DECISION RECEIPT</span>
              <p className="text-xs font-mono text-[var(--text-muted)]/60 truncate" title={receiptHash}>
                {receiptHash}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* CTA */}
      <div className="p-4 border-t border-[var(--acid-green)]/20 bg-[var(--acid-green)]/5">
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
