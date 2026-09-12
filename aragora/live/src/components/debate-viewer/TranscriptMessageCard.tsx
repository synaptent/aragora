'use client';

import { useMemo, useState } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import { TrustBadge } from '@/components/TrustBadge';
import type { TranscriptMessageCardProps, CruxClaim } from './types';

/**
 * Find fuzzy matches of crux statements in content.
 * Returns array of {start, end, crux} for each match.
 */
function findCruxMatches(
  content: string,
  cruxes: CruxClaim[],
): Array<{ start: number; end: number; crux: CruxClaim }> {
  const matches: Array<{ start: number; end: number; crux: CruxClaim }> = [];
  const contentLower = content.toLowerCase();

  for (const crux of cruxes) {
    // Look for substantial substring matches (at least 30 chars or full statement)
    const statement = crux.statement;
    const minLen = Math.min(30, statement.length);

    // Try to find exact match first
    const statementLower = statement.toLowerCase();
    let idx = contentLower.indexOf(statementLower);
    if (idx !== -1) {
      matches.push({ start: idx, end: idx + statement.length, crux });
      continue;
    }

    // Try matching first N characters (for truncated matches)
    const prefix = statementLower.slice(0, minLen);
    idx = contentLower.indexOf(prefix);
    if (idx !== -1 && minLen >= 30) {
      // Find where the match might end (look for sentence end or 200 chars)
      let endIdx = idx + minLen;
      const remaining = contentLower.slice(endIdx);
      const sentenceEnd = remaining.search(/[.!?\n]/);
      if (sentenceEnd !== -1 && sentenceEnd < 200) {
        endIdx += sentenceEnd + 1;
      } else {
        endIdx = Math.min(idx + 200, content.length);
      }
      matches.push({ start: idx, end: endIdx, crux });
    }
  }

  // Sort by start position and remove overlaps
  matches.sort((a, b) => a.start - b.start);
  const filtered: Array<{ start: number; end: number; crux: CruxClaim }> = [];
  for (const m of matches) {
    if (filtered.length === 0 || m.start >= filtered[filtered.length - 1].end) {
      filtered.push(m);
    }
  }

  return filtered;
}

/**
 * Render content with crux highlighting.
 */
function HighlightedContent({ content, cruxes }: { content: string; cruxes?: CruxClaim[] }) {
  const parts = useMemo(() => {
    if (!cruxes || cruxes.length === 0) {
      return [{ text: content, isHighlight: false, crux: undefined }];
    }

    const matches = findCruxMatches(content, cruxes);
    if (matches.length === 0) {
      return [{ text: content, isHighlight: false, crux: undefined }];
    }

    const result: Array<{ text: string; isHighlight: boolean; crux?: CruxClaim }> = [];
    let lastEnd = 0;

    for (const match of matches) {
      // Add text before the match
      if (match.start > lastEnd) {
        result.push({ text: content.slice(lastEnd, match.start), isHighlight: false });
      }
      // Add the highlighted match
      result.push({
        text: content.slice(match.start, match.end),
        isHighlight: true,
        crux: match.crux,
      });
      lastEnd = match.end;
    }

    // Add remaining text
    if (lastEnd < content.length) {
      result.push({ text: content.slice(lastEnd), isHighlight: false });
    }

    return result;
  }, [content, cruxes]);

  return (
    <>
      {parts.map((part, i) =>
        part.isHighlight ? (
          <span
            key={i}
            className="bg-acid-yellow/20 border-b-2 border-acid-yellow text-[var(--acid-yellow)] relative group cursor-help"
            title={`Crux: ${part.crux?.statement?.slice(0, 100)}${(part.crux?.statement?.length || 0) > 100 ? '...' : ''}`}
          >
            {part.text}
            <span className="absolute -top-1 -right-1 text-[8px] bg-acid-yellow text-bg-dark px-0.5 rounded font-theme-data opacity-0 group-hover:opacity-100 transition-opacity">
              CRUX
            </span>
          </span>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

export function TranscriptMessageCard({
  message,
  cruxes,
  onChallenge,
}: TranscriptMessageCardProps) {
  const colors = getAgentColors(message.agent || 'system');
  const [showThinking, setShowThinking] = useState(false);

  // Detect synthesis messages by role or agent name
  const isSynthesis =
    message.role === 'synthesis' ||
    message.agent === 'synthesis-agent' ||
    message.agent === 'consensus';

  // Special rendering for synthesis messages - highly visible final conclusion
  if (isSynthesis) {
    return (
      <div className="relative my-6" id="synthesis-message">
        {/* Glowing border effect */}
        <div className="absolute inset-0 bg-[var(--accent)]/10 blur-xl rounded-lg" />
        {/* Synthesis header bar */}
        <div className="relative bg-[var(--accent)]/20 border-l-4 border-[var(--accent)] px-4 py-3 flex items-center justify-between rounded-t-lg">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{'🎯'}</span>
            <span className="text-[var(--accent)] font-bold text-base tracking-wider">
              FINAL SYNTHESIS
            </span>
          </div>
          {message.timestamp && (
            <span className="text-[10px] text-[var(--accent)]/70 font-theme-data">
              {new Date(message.timestamp * 1000).toLocaleTimeString()}
            </span>
          )}
        </div>
        {/* Synthesis content */}
        <div className="relative bg-bg-secondary/90 border-2 border-[var(--accent)]/40 border-t-0 p-6 rounded-b-lg">
          <div className="text-sm text-text-primary font-medium leading-relaxed whitespace-pre-wrap">
            {message.content}
          </div>
          <div className="mt-4 pt-4 border-t border-[var(--accent)]/20 flex items-center justify-between">
            <span className="text-xs text-[var(--accent)]/70 font-theme-data">
              Generated by Claude Opus 4.5
            </span>
            <span className="text-xs text-[var(--accent)]/50 font-theme-data">
              DEBATE CONCLUSION
            </span>
          </div>
        </div>
      </div>
    );
  }

  // Standard rendering for non-synthesis messages
  const hasThinking = !!message.thinking;
  const confidenceValue = message.confidence_score;
  const hasConfidence = confidenceValue !== null && confidenceValue !== undefined;

  // Color-coded confidence dot: green (>=80%), yellow (>=50%), red (<50%)
  const confidenceDotColor = hasConfidence
    ? confidenceValue >= 0.8
      ? 'bg-[var(--accent)]'
      : confidenceValue >= 0.5
        ? 'bg-acid-yellow'
        : 'bg-red-400'
    : '';

  return (
    <div className={`${colors.bg} border ${colors.border} p-4 group/card`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`font-theme-data font-bold text-sm ${colors.text}`}>
            {(message.agent || 'SYSTEM').toUpperCase()}
          </span>
          {/* Confidence indicator: colored dot + percentage */}
          {hasConfidence && (
            <span
              className="flex items-center gap-1"
              title={`Confidence: ${Math.round(confidenceValue * 100)}%`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${confidenceDotColor}`} />
              <span className="text-[10px] font-theme-data text-text-muted">
                {Math.round(confidenceValue * 100)}%
              </span>
            </span>
          )}
          {message.calibration && <TrustBadge calibration={message.calibration} size="sm" />}
          {message.role && (
            <span className="text-xs text-text-muted border border-text-muted/30 px-1">
              {message.role}
            </span>
          )}
          {/* Reasoning phase label */}
          {message.reasoning_phase && (
            <span className="text-[10px] font-theme-data text-[var(--accent)]/70 border border-[var(--accent)]/20 px-1 uppercase tracking-wider">
              {message.reasoning_phase}
            </span>
          )}
          {message.round !== undefined && message.round > 0 && (
            <span className="text-xs text-text-muted">R{message.round}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Toggle for expandable thinking section */}
          {hasThinking && (
            <button
              onClick={() => setShowThinking(!showThinking)}
              className="text-[10px] font-theme-data text-text-muted hover:text-[var(--acid-cyan)] transition-colors border border-border px-1"
            >
              {showThinking ? '[HIDE THINKING]' : '[THINKING]'}
            </button>
          )}
          {onChallenge && message.agent && (
            <button
              onClick={() => onChallenge(message.content.slice(0, 200), message.agent)}
              className="text-[10px] font-theme-data text-red-400/0 group-hover/card:text-red-400/70 hover:!text-red-400 border border-transparent group-hover/card:border-red-400/30 px-1 transition-all"
              title="Challenge this claim"
            >
              [CHALLENGE]
            </button>
          )}
          {message.timestamp && (
            <span className="text-[10px] text-text-muted font-theme-data">
              {new Date(message.timestamp * 1000).toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {/* Collapsible thinking section */}
      {showThinking && message.thinking && (
        <div className="mb-3 border border-[var(--acid-cyan)]/20 bg-bg/50 p-2">
          <div className="text-[10px] font-theme-data text-[var(--acid-cyan)] uppercase mb-1">
            Agent Thinking
          </div>
          <div className="text-xs text-text-muted font-theme-data whitespace-pre-wrap pl-2 border-l border-[var(--acid-cyan)]/30">
            {message.thinking}
          </div>
        </div>
      )}

      <div className="text-sm text-text whitespace-pre-wrap">
        <HighlightedContent content={message.content} cruxes={cruxes} />
      </div>
    </div>
  );
}
