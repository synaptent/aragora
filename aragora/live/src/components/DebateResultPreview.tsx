'use client';

import { useState } from 'react';
import Link from 'next/link';
import { RETURN_URL_STORAGE_KEY } from '@/utils/returnUrl';

// ---------------------------------------------------------------------------
// Types (shared with Playground.tsx)
// ---------------------------------------------------------------------------

interface CritiqueResult {
  agent: string;
  target_agent: string;
  issues: string[];
  suggestions: string[];
  severity: number;
}

interface VoteResult {
  agent: string;
  choice: string;
  confidence: number;
  reasoning: string;
}

interface ReceiptResult {
  receipt_id: string;
  question: string;
  verdict: string;
  confidence: number;
  consensus: {
    reached: boolean;
    method: string;
    confidence: number;
    supporting_agents: string[];
    dissenting_agents: string[];
  };
  agents: string[];
  rounds_used: number;
  timestamp: string;
  signature: string | null;
  signature_algorithm: string | null;
}

export interface DebateResponse {
  id: string;
  topic: string;
  status: string;
  rounds_used: number;
  consensus_reached: boolean;
  confidence: number;
  verdict: string | null;
  duration_seconds: number;
  participants: string[];
  proposals: Record<string, string>;
  critiques: CritiqueResult[];
  votes: VoteResult[];
  dissenting_views: string[];
  final_answer: string;
  receipt: ReceiptResult | null;
  receipt_hash: string | null;
  is_live?: boolean;
  mock_fallback?: boolean;
  mock_fallback_reason?: string;
  upgrade_cta?: {
    title: string;
    message: string;
    action_url: string;
    action_label: string;
  };
}

// ---------------------------------------------------------------------------
// Agent color mapping
// ---------------------------------------------------------------------------

const AGENT_COLORS: Record<string, string> = {
  analyst: 'text-[var(--acid-cyan)]',
  critic: 'text-[var(--crimson)]',
  moderator: 'text-[var(--acid-green)]',
  contrarian: 'text-[var(--acid-yellow)]',
  synthesizer: 'text-[var(--acid-magenta)]',
};

function agentColor(name: string): string {
  return AGENT_COLORS[name] || 'text-[var(--acid-cyan)]';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface DebateResultPreviewProps {
  result: DebateResponse;
}

export const RETURN_URL_KEY = RETURN_URL_STORAGE_KEY;
export const PENDING_DEBATE_KEY = 'aragora_pending_debate';

export function DebateResultPreview({ result }: DebateResultPreviewProps) {
  const saveDebateAndReturnUrl = () => {
    // Save debate results so the landing page can restore them after login
    sessionStorage.setItem(PENDING_DEBATE_KEY, JSON.stringify(result));
    // Save return URL so OAuth callback redirects back here
    sessionStorage.setItem(RETURN_URL_KEY, window.location.pathname);
  };

  const handleSignup = saveDebateAndReturnUrl;
  const handleLogin = saveDebateAndReturnUrl;

  const [copied, setCopied] = useState(false);

  const handleShare = async () => {
    const shareUrl = `${window.location.origin}/debate/${result.id}`;
    const shareText = `I stress-tested "${result.topic}" with AI agents on Aragora.`;

    // Prefer Web Share API on mobile
    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ title: 'Aragora Debate', text: shareText, url: shareUrl });
        return;
      } catch {
        // User cancelled or share failed — fall through to clipboard
      }
    }

    // Clipboard fallback
    try {
      await navigator.clipboard.writeText(shareUrl);
    } catch {
      // Fallback for older browsers without clipboard API
      const textarea = document.createElement('textarea');
      textarea.value = shareUrl;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="text-left space-y-4 mt-8">
      {/* Demo mode / Live badge */}
      {result.mock_fallback && (
        <div className="flex items-center justify-between gap-3 p-3 bg-[var(--acid-yellow,#ffd700)]/10 border border-[var(--acid-yellow,#ffd700)]/30">
          <div className="flex items-center gap-2 text-[var(--acid-yellow,#ffd700)] font-mono text-sm">
            <span className="px-1.5 py-0.5 text-xs font-bold bg-[var(--acid-yellow,#ffd700)]/20 border border-[var(--acid-yellow,#ffd700)]/40">
              DEMO
            </span>
            <span>This debate used simulated agents{result.mock_fallback_reason ? ` (${result.mock_fallback_reason})` : ''}</span>
          </div>
          {result.upgrade_cta && (
            <Link
              href={result.upgrade_cta.action_url}
              className="shrink-0 px-3 py-1.5 text-xs font-mono font-bold bg-[var(--acid-green)] text-[var(--bg)] hover:opacity-90 transition-opacity"
            >
              {result.upgrade_cta.action_label}
            </Link>
          )}
        </div>
      )}
      {result.is_live && !result.mock_fallback && (
        <div className="flex items-center gap-2 text-xs font-mono text-[var(--acid-green)]">
          <span className="w-2 h-2 rounded-full bg-[var(--acid-green)] animate-pulse" />
          LIVE DEBATE
        </div>
      )}

      {/* Summary bar */}
      <div className="border border-[var(--border)] p-4 flex flex-wrap gap-4 items-center text-sm font-mono">
        <span
          className={
            result.consensus_reached
              ? 'text-[var(--acid-green)]'
              : 'text-[var(--warning)]'
          }
        >
          {result.consensus_reached ? 'Consensus Reached' : 'No Consensus'}
        </span>
        <span className="text-[var(--text-muted)]">|</span>
        <span className="text-[var(--text-muted)]">
          Confidence: {(result.confidence * 100).toFixed(0)}%
        </span>
        <span className="text-[var(--text-muted)]">|</span>
        <span className="text-[var(--text-muted)]">
          {result.rounds_used} round{result.rounds_used !== 1 ? 's' : ''}
        </span>
        <span className="text-[var(--text-muted)]">|</span>
        <span className="text-[var(--text-muted)]">
          {result.duration_seconds}s
        </span>
      </div>

      {/* Proposals */}
      <div className="border border-[var(--border)] p-4">
        <h3 className="text-sm text-[var(--acid-green)] mb-4 font-bold font-mono">
          Proposals
        </h3>
        <div className="space-y-4">
          {Object.entries(result.proposals).map(([agent, content]) => (
            <div key={agent}>
              <h4 className={`text-sm font-bold mb-1 font-mono ${agentColor(agent)}`}>
                {agent}
              </h4>
              <p className="text-xs text-[var(--text-muted)] whitespace-pre-wrap leading-relaxed">
                {content}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Critiques (first 3) */}
      {result.critiques.length > 0 && (
        <div className="border border-[var(--border)] p-4">
          <h3 className="text-sm text-[var(--acid-green)] mb-4 font-bold font-mono">
            Critiques
          </h3>
          <div className="space-y-3">
            {result.critiques.slice(0, 3).map((c, i) => (
              <div key={i} className="border-l-2 border-[var(--border)] pl-3">
                <div className="text-xs mb-1 font-mono">
                  <span className={agentColor(c.agent)}>{c.agent}</span>
                  <span className="text-[var(--text-muted)]"> on </span>
                  <span className={agentColor(c.target_agent)}>
                    {c.target_agent}
                  </span>
                  <span className="text-[var(--text-muted)] ml-2">
                    severity {c.severity.toFixed(1)}/10
                  </span>
                </div>
                <ul className="text-xs text-[var(--text-muted)] space-y-0.5">
                  {c.issues.map((issue, j) => (
                    <li key={j} className="flex items-start gap-1">
                      <span className="text-[var(--crimson)]">-</span>
                      {issue}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Votes */}
      {result.votes.length > 0 && (
        <div className="border border-[var(--border)] p-4">
          <h3 className="text-sm text-[var(--acid-green)] mb-4 font-bold font-mono">
            Votes
          </h3>
          <div className="space-y-2">
            {result.votes.map((v, i) => (
              <div key={i} className="text-xs flex items-center gap-2 font-mono">
                <span className={agentColor(v.agent)}>{v.agent}</span>
                <span className="text-[var(--text-muted)]">voted for</span>
                <span className={`font-bold ${agentColor(v.choice)}`}>
                  {v.choice}
                </span>
                <span className="text-[var(--text-muted)]">
                  ({(v.confidence * 100).toFixed(0)}%)
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Verdict — visible to everyone */}
      {result.final_answer && (
        <div className="border border-[var(--acid-green)]/30 p-4">
          <h3 className="text-sm text-[var(--acid-green)] mb-3 font-bold font-mono">
            Verdict
          </h3>
          <p className="text-sm text-[var(--text)] whitespace-pre-wrap leading-relaxed font-mono">
            {result.final_answer}
          </p>
          {result.dissenting_views.length > 0 && (
            <div className="mt-3 pt-3 border-t border-[var(--border)]">
              <h4 className="text-xs text-[var(--text-muted)] font-bold font-mono mb-2">
                Dissenting Views
              </h4>
              {result.dissenting_views.map((view, i) => (
                <p key={i} className="text-xs text-[var(--text-muted)] whitespace-pre-wrap leading-relaxed mb-1">
                  {view}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Share bar — between Verdict and Receipt */}
      {result.id && (
        <div className="flex items-center gap-3 p-3 border border-[var(--border)]">
          <button
            onClick={handleShare}
            className="flex-1 font-mono text-xs py-2 border border-[var(--acid-green)] text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors font-bold"
          >
            {copied ? 'LINK COPIED!' : 'SHARE THIS DEBATE'}
          </button>
          <Link
            href={`/debate/${result.id}`}
            className="font-mono text-xs text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
          >
            View full debate &rarr;
          </Link>
        </div>
      )}

      {/* Receipt — summary visible, full download gated behind signup */}
      <div className="border border-[var(--acid-green)]/30 p-4">
        <h3 className="text-sm text-[var(--acid-green)] mb-3 font-bold font-mono">
          Decision Receipt
        </h3>
        <div className="grid grid-cols-2 gap-2 text-xs font-mono mb-4">
          <div>
            <span className="text-[var(--text-muted)]">Receipt ID: </span>
            <span className="text-[var(--acid-cyan)]">
              {result.receipt?.receipt_id || result.id}
            </span>
          </div>
          <div>
            <span className="text-[var(--text-muted)]">Verdict: </span>
            <span className="text-[var(--acid-green)]">
              {result.receipt?.verdict?.replace(/_/g, ' ') || (result.consensus_reached ? 'consensus reached' : 'no consensus')}
            </span>
          </div>
          <div>
            <span className="text-[var(--text-muted)]">Hash: </span>
            <span className="text-[var(--text)]">
              {result.receipt_hash ? result.receipt_hash.slice(0, 16) + '...' : 'pending'}
            </span>
          </div>
          <div>
            <span className="text-[var(--text-muted)]">Timestamp: </span>
            <span>{result.receipt?.timestamp || new Date().toISOString()}</span>
          </div>
        </div>
        <div className="border-t border-[var(--border)] pt-3 text-center">
          <p className="font-mono text-xs text-[var(--text-muted)] mb-3">
            Sign up to download the full receipt with evidence chains and cryptographic audit trail
          </p>
          <div className="flex gap-3 justify-center">
            <Link
              href="/signup"
              onClick={handleSignup}
              className="font-mono text-xs px-4 py-2 bg-[var(--acid-green)] text-[var(--bg)] font-bold hover:opacity-90 transition-opacity"
            >
              Sign Up Free
            </Link>
            <Link
              href="/auth/login"
              onClick={handleLogin}
              className="font-mono text-xs px-4 py-2 border border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--acid-green)] hover:text-[var(--acid-green)] transition-colors"
            >
              Log In
            </Link>
          </div>
        </div>
      </div>

      {/* Self-improvement link */}
      <div className="flex items-center gap-2 p-3 bg-[var(--surface)]/50 border border-[var(--border)]">
        <span className="text-xs font-mono text-[var(--text-muted)]">
          This debate feeds into Aragora&apos;s self-improvement cycle
        </span>
        <Link
          href="/self-improve"
          className="ml-auto shrink-0 text-xs font-mono text-[var(--acid-cyan)] hover:text-[var(--acid-green)] transition-colors"
        >
          Learn more &rarr;
        </Link>
      </div>
    </div>
  );
}
