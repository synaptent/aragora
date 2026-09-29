'use client';

import { useState } from 'react';
import Link from 'next/link';
import Markdown from 'react-markdown';
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
  original_question?: string;
  interpreted_question?: string;
  tldr?: string;
  short_answer?: string;
  result_mode?: string;
  result_warning?: string;
  upgrade_cta?: { title: string; message: string; action_url: string; action_label: string };
}

// ---------------------------------------------------------------------------
// Agent color mapping
// ---------------------------------------------------------------------------

const AGENT_STYLES: Record<string, { text: string; dot: string }> = {
  analyst: { text: 'text-[var(--acid-cyan)]', dot: 'var(--acid-cyan, #00e5ff)' },
  critic: { text: 'text-[var(--crimson)]', dot: 'var(--crimson, #ff0040)' },
  moderator: { text: 'text-[var(--acid-green)]', dot: 'var(--acid-green, #39ff14)' },
  contrarian: { text: 'text-[var(--acid-yellow)]', dot: 'var(--acid-yellow, #ffd700)' },
  synthesizer: { text: 'text-[var(--acid-magenta)]', dot: 'var(--acid-magenta, #ff00ff)' },
};

function agentColor(name: string): string {
  return AGENT_STYLES[name]?.text || 'text-[var(--acid-cyan)]';
}

function agentDot(name: string): string {
  return AGENT_STYLES[name]?.dot || 'var(--acid-cyan, #00e5ff)';
}

function stripMarkdownForSummary(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]+\)/g, ' ')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*>\s?/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

function deriveShortAnswer(result: DebateResponse): string {
  const fallbackContent =
    result.short_answer || result.final_answer || Object.values(result.proposals)[0] || '';
  const cleaned = stripMarkdownForSummary(fallbackContent);
  if (!cleaned) return 'The agent outputs are available below.';

  const sentenceMatch = cleaned.match(/^(.{1,220}?[.!?])(?:\s|$)/);
  if (sentenceMatch?.[1]) {
    return sentenceMatch[1].trim();
  }

  if (cleaned.length <= 220) return cleaned;
  return `${cleaned.slice(0, 217).trimEnd()}...`;
}

function isPreviewResult(result: DebateResponse): boolean {
  return (
    result.result_mode === 'preview' ||
    (result.verdict === 'needs_review' &&
      result.critiques.length === 0 &&
      result.votes.length === 0)
  );
}

function ConfidenceGauge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const hue = value > 0.7 ? 120 : value > 0.4 ? 50 : 0; // green → yellow → red
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-2 flex-1 rounded-full overflow-hidden"
        style={{ backgroundColor: 'var(--border)', maxWidth: '120px' }}
      >
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: `hsl(${hue}, 80%, 50%)` }}
        />
      </div>
      <span className="text-xs font-theme-data" style={{ color: `hsl(${hue}, 80%, 50%)` }}>
        {pct}%
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface DebateResultPreviewProps {
  result: DebateResponse;
  condensed?: boolean;
  onFlagWrongAnswer?: (result: DebateResponse) => void;
  onOpenFullDebate?: (result: DebateResponse, surface: 'quick_read' | 'share_bar') => void;
  onShare?: (result: DebateResponse) => void;
}

export const RETURN_URL_KEY = RETURN_URL_STORAGE_KEY;
export const PENDING_DEBATE_KEY = 'aragora_pending_debate';

export function DebateResultPreview({
  result,
  condensed = false,
  onFlagWrongAnswer,
  onOpenFullDebate,
  onShare,
}: DebateResultPreviewProps) {
  const saveDebateAndReturnUrl = () => {
    // Save debate results so the landing page can restore them after login
    sessionStorage.setItem(PENDING_DEBATE_KEY, JSON.stringify(result));
    // Save return URL so OAuth callback redirects back here
    sessionStorage.setItem(RETURN_URL_KEY, window.location.pathname);
  };

  const handleSignup = saveDebateAndReturnUrl;
  const handleLogin = saveDebateAndReturnUrl;

  const [copied, setCopied] = useState(false);
  const [showDetails, setShowDetails] = useState(!condensed);
  const previewOnly = isPreviewResult(result);
  const statusLabel = previewOnly
    ? 'Multi-model Preview'
    : result.consensus_reached
      ? 'Consensus Reached'
      : 'No Consensus';
  const statusTone = previewOnly
    ? 'text-[var(--acid-yellow,#ffd700)]'
    : result.consensus_reached
      ? 'text-[var(--acid-green)]'
      : 'text-[var(--warning)]';
  const questionLabel = result.original_question || result.topic;
  const interpretedLabel =
    result.interpreted_question && result.interpreted_question !== questionLabel
      ? result.interpreted_question
      : null;
  const quickAnswer = deriveShortAnswer(result);
  const showQuickRead =
    condensed || Boolean(result.original_question) || Boolean(result.result_warning);

  const handleShare = async () => {
    const shareUrl = `${window.location.origin}/debate/${result.id}`;
    const shareText = `I stress-tested "${result.topic}" with AI agents on Aragora.`;
    const completeShare = (showFeedback: boolean) => {
      if (showFeedback) {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
      onShare?.(result);
    };

    // Prefer Web Share API on mobile
    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ title: 'Aragora Debate', text: shareText, url: shareUrl });
        // Native share sheet provides its own feedback
        completeShare(false);
        return;
      } catch {
        // User cancelled or share failed — fall through to clipboard
      }
    }

    // Clipboard fallback — always show visual feedback regardless of copy success
    try {
      await navigator.clipboard.writeText(shareUrl);
    } catch {
      // Fallback for older browsers without clipboard API
      try {
        const textarea = document.createElement('textarea');
        textarea.value = shareUrl;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      } catch {
        // Even execCommand failed — feedback still shown below so user
        // can use the "View full debate" link to get the URL manually
      }
    }
    // Always show confirmation so the user knows the action registered
    completeShare(true);
  };

  return (
    <div className="text-left space-y-4 mt-8">
      {showQuickRead && (
        <div className="rounded-2xl border border-[var(--accent)]/20 bg-[var(--surface)] p-6">
          <div className="flex items-center justify-between gap-3 mb-4">
            <h2 className="text-sm font-bold text-[var(--accent)]">Quick Read</h2>
            {result.id && (
              <Link
                href={`/debate/${result.id}`}
                onClick={() => onOpenFullDebate?.(result, 'quick_read')}
                className="text-xs text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors"
              >
                Open full debate &rarr;
              </Link>
            )}
          </div>

          <div className="space-y-4">
            <div>
              <span className="block text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">
                You Asked
              </span>
              <p className="text-sm text-[var(--text)] leading-relaxed">{questionLabel}</p>
            </div>

            {interpretedLabel && (
              <div>
                <span className="block text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">
                  Aragora Debated
                </span>
                <p className="text-sm text-[var(--text)] leading-relaxed">{interpretedLabel}</p>
              </div>
            )}

            <div>
              <span className="block text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">
                Short Answer
              </span>
              <p className="text-sm text-[var(--text)] leading-relaxed">{quickAnswer}</p>
            </div>

            {(result.result_warning || previewOnly) && (
              <div className="rounded-xl border border-[var(--acid-yellow,#ffd700)]/30 bg-[var(--acid-yellow,#ffd700)]/10 px-4 py-3">
                <p className="text-xs leading-relaxed text-[var(--text-muted)]">
                  {result.result_warning ||
                    'This landing result is a condensed preview of parallel model outputs, not a full consensus proof.'}
                </p>
              </div>
            )}

            {condensed && (
              <div className="flex flex-wrap items-center gap-4">
                <button
                  type="button"
                  onClick={() => setShowDetails((current) => !current)}
                  className="text-xs font-bold text-[var(--accent)] hover:opacity-80 transition-opacity"
                >
                  {showDetails ? 'Hide transcript details' : 'Show transcript details'}
                </button>
                {onFlagWrongAnswer && (
                  <button
                    type="button"
                    onClick={() => onFlagWrongAnswer(result)}
                    className="text-xs font-bold text-[var(--crimson)] hover:opacity-80 transition-opacity"
                  >
                    This answer seems wrong
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {(!condensed || showDetails) && (
        <>
          {/* Demo mode / Live badge */}
          {result.mock_fallback && (
            <div className="flex items-center justify-between gap-3 p-3 bg-[var(--acid-yellow,#ffd700)]/10 border border-[var(--acid-yellow,#ffd700)]/30">
              <div className="flex items-center gap-2 text-[var(--acid-yellow,#ffd700)] font-theme-data text-sm">
                <span className="px-1.5 py-0.5 text-xs font-bold bg-[var(--acid-yellow,#ffd700)]/20 border border-[var(--acid-yellow,#ffd700)]/40">
                  DEMO
                </span>
                <span>
                  This debate used simulated agents
                  {result.mock_fallback_reason ? ` (${result.mock_fallback_reason})` : ''}
                </span>
              </div>
              {result.upgrade_cta && (
                <Link
                  href={result.upgrade_cta.action_url}
                  className="shrink-0 px-3 py-1.5 text-xs font-theme-data font-bold bg-[var(--acid-green)] text-[var(--bg)] hover:opacity-90 transition-opacity"
                >
                  {result.upgrade_cta.action_label}
                </Link>
              )}
            </div>
          )}
          {result.is_live && !result.mock_fallback && (
            <div className="flex items-center gap-2 text-xs font-theme-data text-[var(--acid-green)]">
              <span className="w-2 h-2 rounded-full bg-[var(--acid-green)] animate-pulse" />
              LIVE DEBATE
            </div>
          )}

          {/* Summary bar — verdict first, then metadata */}
          <div className="border border-[var(--border)] p-4 space-y-3">
            {/* Verdict status + confidence side by side */}
            <div className="flex items-center justify-between gap-4">
              <span className={`text-base font-bold font-theme-data ${statusTone}`}>
                {statusLabel}
              </span>
              <div className="flex items-center gap-2 shrink-0">
                {previewOnly ? (
                  <span className="text-xs font-theme-data text-[var(--text-muted)]">
                    Preview only
                  </span>
                ) : (
                  <>
                    <span className="text-xs font-theme-data text-[var(--text-muted)]">
                      Confidence
                    </span>
                    <ConfidenceGauge value={result.confidence} />
                  </>
                )}
              </div>
            </div>
            {/* Metadata row */}
            <div className="flex flex-wrap gap-x-4 gap-y-1 items-center text-xs font-theme-data text-[var(--text-muted)]">
              <span>
                {result.rounds_used} round{result.rounds_used !== 1 ? 's' : ''}
              </span>
              <span>|</span>
              <span>{result.duration_seconds}s</span>
              {result.participants.length > 0 && (
                <>
                  <span>|</span>
                  <span>{result.participants.length} agents</span>
                </>
              )}
            </div>
            {/* Participating agents */}
            {result.participants.length > 0 && (
              <div className="flex items-center gap-3 flex-wrap">
                {result.participants.map((name) => (
                  <span key={name} className="flex items-center gap-1 text-xs font-theme-data">
                    <span
                      className="w-2 h-2 rounded-full inline-block"
                      style={{ backgroundColor: agentDot(name) }}
                    />
                    <span className={agentColor(name)}>{name}</span>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Interpretation notice */}
          {result.interpreted_question &&
            result.interpreted_question !== (result.original_question || result.topic) && (
              <p className="text-xs text-[var(--text-muted)] italic">
                Aragora interpreted this as: {result.interpreted_question}
              </p>
            )}

          {/* TL;DR answer */}
          {result.tldr && (
            <div
              className="rounded-2xl border p-5"
              style={{
                borderColor: 'var(--accent)',
                backgroundColor: 'color-mix(in srgb, var(--accent) 5%, var(--surface))',
              }}
            >
              <div
                className="text-[11px] uppercase tracking-[0.1em] font-semibold mb-2"
                style={{ color: 'var(--accent)' }}
              >
                Summary
              </div>
              <div className="text-base font-semibold leading-relaxed text-[var(--text)]">
                {result.tldr}
              </div>
            </div>
          )}

          {/* Proposals — hidden when single-agent and verdict duplicates the proposal */}
          {(() => {
            const proposalEntries = Object.entries(result.proposals);
            const isSingleAgent = proposalEntries.length === 1;
            const singleProposalText = isSingleAgent ? proposalEntries[0][1] : '';
            const verdictDuplicatesProposal =
              isSingleAgent &&
              result.final_answer &&
              singleProposalText.trim() === result.final_answer.trim();

            // When single-agent result duplicates, show a merged "Result" section instead
            if (verdictDuplicatesProposal) {
              return (
                <div className="border border-[var(--acid-green)]/30 p-4">
                  <h3 className="text-sm text-[var(--acid-green)] mb-3 font-bold font-theme-data">
                    Result
                  </h3>
                  <div className="text-sm text-[var(--text)] leading-relaxed max-w-none [&_h1]:text-base [&_h1]:font-bold [&_h1]:mt-4 [&_h1]:mb-2 [&_h2]:text-sm [&_h2]:font-bold [&_h2]:mt-3 [&_h2]:mb-1 [&_h3]:text-sm [&_h3]:font-bold [&_h3]:mt-2 [&_h3]:mb-1 [&_p]:mb-2 [&_strong]:font-bold [&_ul]:list-disc [&_ul]:pl-4 [&_ul]:mb-2 [&_ol]:list-decimal [&_ol]:pl-4 [&_ol]:mb-2 [&_li]:mb-0.5 [&_blockquote]:border-l-2 [&_blockquote]:border-[var(--accent)] [&_blockquote]:pl-3 [&_blockquote]:italic [&_blockquote]:text-[var(--text-muted)]">
                    <Markdown>{result.final_answer}</Markdown>
                  </div>
                </div>
              );
            }

            // Multi-agent: show each proposal in a styled card matching the demo page
            return (
              <div>
                <h3 className="text-sm text-[var(--accent)] mb-4 font-bold">Proposals</h3>
                <div className="space-y-5">
                  {proposalEntries.map(([agent, content]) => (
                    <div
                      key={agent}
                      className="rounded-2xl border bg-[var(--surface)] shadow-sm"
                      style={{
                        borderColor: `${agentDot(agent)}28`,
                        boxShadow: `inset 4px 0 0 ${agentDot(agent)}`,
                        padding: '24px 28px',
                      }}
                    >
                      <div className="flex items-center gap-3 mb-3">
                        <span
                          className="w-3 h-3 rounded-full inline-block shrink-0"
                          style={{ backgroundColor: agentDot(agent) }}
                        />
                        <span
                          className="text-base font-bold uppercase tracking-wider"
                          style={{ color: agentDot(agent) }}
                        >
                          {agent}
                        </span>
                      </div>
                      <div className="text-sm text-[var(--text)] leading-relaxed max-w-none [&_h1]:text-lg [&_h1]:font-bold [&_h1]:mt-4 [&_h1]:mb-2 [&_h2]:text-base [&_h2]:font-bold [&_h2]:mt-4 [&_h2]:mb-2 [&_h3]:text-sm [&_h3]:font-bold [&_h3]:mt-3 [&_h3]:mb-1 [&_p]:mb-3 [&_strong]:font-bold [&_em]:text-[var(--text-muted)] [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_li]:mb-1 [&_blockquote]:border-l-3 [&_blockquote]:border-[var(--accent)] [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-[var(--text-muted)] [&_table]:w-full [&_table]:border-collapse [&_th]:text-left [&_th]:p-2 [&_th]:border-b [&_th]:border-[var(--border)] [&_td]:p-2 [&_td]:border-b [&_td]:border-[var(--border)]">
                        <Markdown>{content}</Markdown>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}

          {/* Critiques (first 3) */}
          {result.critiques.length > 0 && (
            <div>
              <h3 className="text-sm text-[var(--accent)] mb-4 font-bold">Critiques</h3>
              <div className="space-y-3">
                {result.critiques.slice(0, 3).map((c, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"
                    style={{ borderLeftWidth: '3px', borderLeftColor: agentDot(c.agent) }}
                  >
                    <div className="text-xs mb-2 flex items-center gap-2">
                      <span
                        className="w-2 h-2 rounded-full inline-block shrink-0"
                        style={{ backgroundColor: agentDot(c.agent) }}
                      />
                      <span className="font-bold" style={{ color: agentDot(c.agent) }}>
                        {c.agent}
                      </span>
                      <span className="text-[var(--text-muted)]">on</span>
                      <span className="font-bold" style={{ color: agentDot(c.target_agent) }}>
                        {c.target_agent}
                      </span>
                      <span className="text-[var(--text-muted)] ml-auto text-[10px] uppercase tracking-wider">
                        severity {c.severity.toFixed(1)}/10
                      </span>
                    </div>
                    <ul className="text-xs text-[var(--text-muted)] space-y-1 pl-4">
                      {c.issues.map((issue, j) => (
                        <li key={j} className="flex items-start gap-1.5">
                          <span className="text-[var(--crimson)] mt-px shrink-0">&bull;</span>
                          <span>{issue}</span>
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
            <div>
              <h3 className="text-sm text-[var(--accent)] mb-4 font-bold">Votes</h3>
              <div className="space-y-2">
                {result.votes.map((v, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-3 text-xs rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-2.5"
                  >
                    <span
                      className="w-2 h-2 rounded-full inline-block shrink-0"
                      style={{ backgroundColor: agentDot(v.agent) }}
                    />
                    <span className="font-bold" style={{ color: agentDot(v.agent) }}>
                      {v.agent}
                    </span>
                    <span className="text-[var(--text-muted)]">voted for</span>
                    <span className="font-bold" style={{ color: agentDot(v.choice) }}>
                      {v.choice}
                    </span>
                    <span className="text-[var(--text-muted)] ml-auto">
                      {(v.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Verdict — hidden when single-agent result already shown as merged "Result" */}
          {result.final_answer &&
            !(
              Object.keys(result.proposals).length === 1 &&
              Object.values(result.proposals)[0]?.trim() === result.final_answer.trim()
            ) && (
              <div className="rounded-2xl border border-[var(--accent)]/20 bg-[var(--surface)] p-6">
                <h3 className="text-sm text-[var(--accent)] mb-3 font-bold">Verdict</h3>
                <div className="text-sm text-[var(--text)] leading-relaxed max-w-none [&_h1]:text-lg [&_h1]:font-bold [&_h1]:mt-4 [&_h1]:mb-2 [&_h2]:text-base [&_h2]:font-bold [&_h2]:mt-4 [&_h2]:mb-2 [&_h3]:text-sm [&_h3]:font-bold [&_h3]:mt-3 [&_h3]:mb-1 [&_p]:mb-3 [&_strong]:font-bold [&_em]:text-[var(--text-muted)] [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_li]:mb-1 [&_blockquote]:border-l-3 [&_blockquote]:border-[var(--accent)] [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-[var(--text-muted)]">
                  <Markdown>{result.final_answer}</Markdown>
                </div>
                {result.dissenting_views.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-[var(--border)]">
                    <h4 className="text-xs text-[var(--text-muted)] font-bold uppercase tracking-wider mb-3">
                      Dissenting Views
                    </h4>
                    {result.dissenting_views.map((view, i) => (
                      <div
                        key={i}
                        className="text-xs text-[var(--text-muted)] leading-relaxed mb-2 [&_p]:mb-1.5 [&_strong]:text-[var(--text)]"
                      >
                        <Markdown>{view}</Markdown>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

          {/* Share bar — between Verdict and Receipt */}
          {result.id && (
            <div className="flex items-center gap-3 p-3 rounded-xl border border-[var(--border)] bg-[var(--surface)]">
              <button
                onClick={handleShare}
                className="flex-1 text-xs py-2 rounded-lg border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors font-bold"
              >
                {copied ? 'LINK COPIED!' : 'SHARE THIS DEBATE'}
              </button>
              <Link
                href={`/debate/${result.id}`}
                className="text-xs text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors"
                onClick={() => onOpenFullDebate?.(result, 'share_bar')}
              >
                View full debate &rarr;
              </Link>
            </div>
          )}

          {/* Receipt — summary visible, full download gated behind signup */}
          <div className="rounded-2xl border border-[var(--accent)]/20 bg-[var(--surface)] p-6">
            <h3 className="text-sm text-[var(--accent)] mb-4 font-bold">Decision Receipt</h3>
            <div className="grid grid-cols-2 gap-3 text-xs mb-5">
              <div>
                <span className="text-[var(--text-muted)] block text-[10px] uppercase tracking-wider mb-0.5">
                  Receipt ID
                </span>
                <span className="text-[var(--accent)] font-theme-data">
                  {result.receipt?.receipt_id || result.id}
                </span>
              </div>
              <div>
                <span className="text-[var(--text-muted)] block text-[10px] uppercase tracking-wider mb-0.5">
                  Verdict
                </span>
                <span className="text-[var(--accent)] font-medium">
                  {result.receipt?.verdict?.replace(/_/g, ' ') ||
                    (result.consensus_reached ? 'consensus reached' : 'no consensus')}
                </span>
              </div>
              <div>
                <span className="text-[var(--text-muted)] block text-[10px] uppercase tracking-wider mb-0.5">
                  Hash
                </span>
                <span className="text-[var(--text)] font-theme-data">
                  {result.receipt_hash ? result.receipt_hash.slice(0, 16) + '...' : 'pending'}
                </span>
              </div>
              <div>
                <span className="text-[var(--text-muted)] block text-[10px] uppercase tracking-wider mb-0.5">
                  Timestamp
                </span>
                <span className="font-theme-data">
                  {result.receipt?.timestamp || new Date().toISOString()}
                </span>
              </div>
            </div>
            <div className="border-t border-[var(--border)] pt-4 text-center">
              <p className="text-xs text-[var(--text-muted)] mb-4">
                Sign up to download the full receipt with evidence chains and cryptographic audit
                trail
              </p>
              <div className="flex gap-3 justify-center">
                <Link
                  href="/signup"
                  onClick={handleSignup}
                  className="text-xs px-5 py-2.5 rounded-lg bg-[var(--accent)] text-[var(--bg)] font-bold hover:opacity-90 transition-opacity"
                >
                  Sign Up Free
                </Link>
                <Link
                  href="/auth/login"
                  onClick={handleLogin}
                  className="text-xs px-5 py-2.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
                >
                  Log In
                </Link>
              </div>
            </div>
          </div>

          {/* Self-improvement link */}
          <div className="flex items-center gap-2 p-3 rounded-xl bg-[var(--surface)]/50 border border-[var(--border)]">
            <span className="text-xs text-[var(--text-muted)]">
              This debate feeds into Aragora&apos;s self-improvement cycle
            </span>
            <Link
              href="/self-improve"
              className="ml-auto shrink-0 text-xs text-[var(--accent)] hover:opacity-80 transition-opacity"
            >
              Learn more &rarr;
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
