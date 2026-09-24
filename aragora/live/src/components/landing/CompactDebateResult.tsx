'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { DebateResponse } from '../DebateResultPreview';

// ---------------------------------------------------------------------------
// Agent chip color mapping by model family
// ---------------------------------------------------------------------------

interface AgentChipStyle {
  text: string;
  bg: string;
}

const AGENT_CHIP_COLORS: Record<string, AgentChipStyle> = {
  claude: { text: '#0369a1', bg: '#e0f2fe' },
  gpt: { text: '#92400e', bg: '#fef3c7' },
  grok: { text: '#9d174d', bg: '#fce7f3' },
  gemini: { text: '#7c3aed', bg: '#ede9fe' },
  mistral: { text: '#0f766e', bg: '#ccfbf1' },
  deepseek: { text: '#dc2626', bg: '#fee2e2' },
};

const DEFAULT_CHIP: AgentChipStyle = { text: '#6b7280', bg: '#f3f4f6' };

function agentChipStyle(name: string): AgentChipStyle {
  const lower = name.toLowerCase();
  for (const [key, style] of Object.entries(AGENT_CHIP_COLORS)) {
    if (lower.includes(key)) return style;
  }
  return DEFAULT_CHIP;
}

// ---------------------------------------------------------------------------
// Markdown strip helper (plain-text summary)
// ---------------------------------------------------------------------------

function stripMarkdown(text: string): string {
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

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface CompactDebateResultProps {
  result: DebateResponse;
  onWrongAnswer?: (result: DebateResponse) => void;
  onShare?: (result: DebateResponse) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CompactDebateResult({ result, onWrongAnswer, onShare }: CompactDebateResultProps) {
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
  const [shareCopied, setShareCopied] = useState(false);
  const participants = result.participants ?? [];
  const proposals = result.proposals ?? {};

  const tldr =
    result.tldr || (result.final_answer ? stripMarkdown(result.final_answer).slice(0, 200) : '');

  const originalQuestion = result.original_question || result.topic;
  const interpretedQuestion = result.interpreted_question;
  const showInterpretation =
    Boolean(interpretedQuestion) && interpretedQuestion !== originalQuestion;

  const confidencePct = Math.round(result.confidence * 100);
  const agentCount = participants.length || Object.keys(proposals).length;
  const rounds = result.rounds_used;
  const duration = result.duration_seconds;

  // Determine which round a proposal came from (if proposals keyed by "agent:round" or just "agent")
  function proposalRound(agent: string): number | null {
    // proposals may be keyed as "agent" or "agent_round_N" — best-effort heuristic
    const roundMatch = agent.match(/_round_(\d+)$/);
    if (roundMatch) return Number.parseInt(roundMatch[1], 10);
    return null;
  }

  function agentDisplayName(agent: string): string {
    return agent.replace(/_round_\d+$/, '');
  }

  // Get proposal text for an agent (look up by name, stripping round suffix)
  function getProposalText(agent: string): string {
    if (proposals[agent]) {
      return stripMarkdown(proposals[agent]).slice(0, 200);
    }
    // Try matching by display name prefix
    for (const [key, val] of Object.entries(proposals)) {
      if (key === agent || agentDisplayName(key) === agent) {
        return stripMarkdown(val).slice(0, 200);
      }
    }
    return '';
  }

  // Agents to show as chips: participants list, or fall back to proposal keys
  const chipAgents = participants.length > 0 ? participants : Object.keys(proposals);

  async function handleShare() {
    const shareUrl = result.id
      ? `${window.location.origin}/debate/${result.id}`
      : window.location.href;
    try {
      if (typeof navigator.share === 'function') {
        await navigator.share({
          title: 'Aragora Debate',
          text: `I stress-tested "${result.topic}" with AI agents on Aragora.`,
          url: shareUrl,
        });
        onShare?.(result);
        return;
      }
    } catch {
      // fall through to clipboard
    }
    try {
      await navigator.clipboard.writeText(shareUrl);
    } catch {
      try {
        const ta = document.createElement('textarea');
        ta.value = shareUrl;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      } catch {
        // ignore
      }
    }
    setShareCopied(true);
    setTimeout(() => setShareCopied(false), 2000);
    onShare?.(result);
  }

  return (
    <div className="text-left mt-8 space-y-4" style={{ fontFamily: 'var(--font-landing)' }}>
      {/* 1. Interpretation line */}
      {showInterpretation && (
        <p className="text-sm italic" style={{ color: 'var(--text-muted)' }}>
          Aragora interpreted this as:{' '}
          <span style={{ color: 'var(--text)' }}>{interpretedQuestion}</span>
        </p>
      )}

      {/* 2. TL;DR answer card */}
      <div
        className="rounded-2xl p-5"
        style={{ border: '2px solid var(--accent)', backgroundColor: 'var(--surface)' }}
      >
        <span
          className="block text-[10px] uppercase tracking-widest font-bold mb-2"
          style={{ color: 'var(--accent)' }}
        >
          Aragora&apos;s Answer
        </span>
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text)' }}>
          {tldr || 'See full debate for details.'}
        </p>
      </div>

      {/* 3. Metadata row */}
      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
        {confidencePct}% confidence
        {agentCount > 0 && ` · ${agentCount} agent${agentCount !== 1 ? 's' : ''}`}
        {rounds > 0 && ` · ${rounds} round${rounds !== 1 ? 's' : ''}`}
        {duration > 0 && ` · ${duration}s`}
      </p>

      {/* 4. Agent chips */}
      {chipAgents.length > 0 && (
        <div>
          <div className="flex flex-wrap gap-2">
            {chipAgents.map((agent) => {
              const chipStyle = agentChipStyle(agent);
              const displayName = agentDisplayName(agent);
              const round = proposalRound(agent);
              const isExpanded = expandedAgent === agent;

              return (
                <button
                  key={agent}
                  type="button"
                  onClick={() => setExpandedAgent(isExpanded ? null : agent)}
                  className="rounded-full text-xs font-semibold px-3 py-1 transition-opacity hover:opacity-80 cursor-pointer"
                  style={{ color: chipStyle.text, backgroundColor: chipStyle.bg, border: 'none' }}
                >
                  {displayName}
                  {round !== null && <span className="ml-1 opacity-60">r{round}</span>}
                </button>
              );
            })}
          </div>

          {/* Collapsible proposal panel */}
          {expandedAgent &&
            (() => {
              const chipStyle = agentChipStyle(expandedAgent);
              const displayName = agentDisplayName(expandedAgent);
              const round = proposalRound(expandedAgent);
              const proposalText = getProposalText(expandedAgent);

              return (
                <div
                  className="mt-3 rounded-xl p-4 text-sm"
                  style={{
                    backgroundColor: 'var(--surface)',
                    border: `1px solid ${chipStyle.bg}`,
                    borderLeft: `3px solid ${chipStyle.text}`,
                  }}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className="text-xs font-bold uppercase tracking-wide"
                      style={{ color: chipStyle.text }}
                    >
                      {displayName}
                    </span>
                    {round !== null && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded"
                        style={{ color: chipStyle.text, backgroundColor: chipStyle.bg }}
                      >
                        Round {round}
                      </span>
                    )}
                  </div>
                  {proposalText ? (
                    <>
                      <p style={{ color: 'var(--text)', lineHeight: 1.6 }}>
                        {proposalText}
                        {proposalText.length >= 200 && '…'}
                      </p>
                      {result.id && (
                        <Link
                          href={`/debate/${result.id}`}
                          className="inline-block mt-2 text-xs font-semibold hover:opacity-70 transition-opacity"
                          style={{ color: chipStyle.text }}
                        >
                          Read more →
                        </Link>
                      )}
                    </>
                  ) : (
                    <p style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
                      No proposal text available.
                    </p>
                  )}
                </div>
              );
            })()}
        </div>
      )}

      {/* 5. Receipt row — omitted entirely when receipt_hash is null */}
      {result.receipt_hash && (
        <p className="text-xs font-theme-data" style={{ color: 'var(--text-muted)' }}>
          {result.receipt_hash.slice(0, 16)}…
          {result.receipt?.timestamp && <span className="ml-2">{result.receipt.timestamp}</span>}
        </p>
      )}

      {/* 6. Actions */}
      <div className="flex flex-wrap items-center gap-3 pt-1">
        {result.id && (
          <Link
            href={`/debate/${result.id}`}
            className="text-sm font-semibold hover:opacity-70 transition-opacity"
            style={{ color: 'var(--accent)' }}
          >
            View full debate →
          </Link>
        )}
        <button
          type="button"
          onClick={handleShare}
          className="text-sm font-semibold px-4 py-1.5 rounded-full transition-opacity hover:opacity-70 cursor-pointer"
          style={{
            border: '1px solid var(--accent)',
            color: 'var(--accent)',
            backgroundColor: 'transparent',
          }}
        >
          {shareCopied ? 'Copied!' : 'Share'}
        </button>
        {onWrongAnswer && (
          <button
            type="button"
            onClick={() => onWrongAnswer(result)}
            className="text-sm font-semibold transition-opacity hover:opacity-70 cursor-pointer"
            style={{ color: 'var(--text-muted)', background: 'none', border: 'none', padding: 0 }}
          >
            Wrong answer?
          </button>
        )}
      </div>
    </div>
  );
}
