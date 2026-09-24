'use client';

import { useState } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import type { StreamingMessageCardProps } from './types';

/** Derive a reasoning phase label from the message content length and available data. */
function getReasoningPhase(message: {
  content: string;
  reasoning?: unknown[];
  evidence?: unknown[];
  reasoningPhase?: string;
}): string | null {
  if (message.reasoningPhase) return message.reasoningPhase;
  if (message.evidence && message.evidence.length > 0) return 'CITING EVIDENCE';
  if (message.reasoning && message.reasoning.length > 0) return 'FORMING ARGUMENT';
  if (message.content.length < 40) return 'ANALYZING';
  if (message.content.length < 200) return 'FORMING ARGUMENT';
  return 'CRITIQUING';
}

export function StreamingMessageCard({ message }: StreamingMessageCardProps) {
  const colors = getAgentColors(message.agent);
  const [showReasoning, setShowReasoning] = useState(false);

  const hasReasoning =
    (message.reasoning && message.reasoning.length > 0) ||
    (message.evidence && message.evidence.length > 0) ||
    (message.confidence !== null && message.confidence !== undefined);

  const phase = getReasoningPhase(message);

  return (
    <div className={`${colors.bg} border-2 ${colors.border} p-4 animate-pulse min-h-[120px]`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`font-theme-data font-bold text-sm ${colors.text}`}>
            {message.agent.toUpperCase()}
          </span>
          <span className="text-xs text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 px-1 animate-pulse">
            STREAMING
          </span>
          {phase && (
            <span className="text-[10px] font-theme-data text-[var(--accent)]/80 border border-[var(--accent)]/20 px-1 uppercase tracking-wider">
              {phase}
            </span>
          )}
          {message.confidence !== null && message.confidence !== undefined && (
            <span className="text-xs text-[var(--acid-yellow)] border border-acid-yellow/30 px-1">
              {Math.round(message.confidence * 100)}% conf
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {hasReasoning && (
            <button
              onClick={() => setShowReasoning(!showReasoning)}
              className="text-[10px] font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors border border-border px-1"
            >
              {showReasoning ? '[HIDE REASONING]' : '[SHOW REASONING]'}
            </button>
          )}
          <span className="text-[10px] text-text-muted font-theme-data">
            {Math.round((Date.now() - message.startTime) / 1000)}s
          </span>
        </div>
      </div>

      {/* Collapsible reasoning panel */}
      {showReasoning && hasReasoning && (
        <div className="mb-3 border border-[var(--accent)]/20 bg-bg/50 p-2 space-y-2">
          {message.reasoning && message.reasoning.length > 0 && (
            <div>
              <div className="text-[10px] font-theme-data text-[var(--acid-cyan)] uppercase mb-1">
                Reasoning Chain
              </div>
              <div className="space-y-1">
                {message.reasoning.map((step, idx) => (
                  <div
                    key={idx}
                    className="text-xs text-text-muted font-theme-data pl-2 border-l border-[var(--acid-cyan)]/30"
                  >
                    {step.step !== undefined && (
                      <span className="text-[var(--acid-cyan)] mr-1">#{step.step}</span>
                    )}
                    {step.thinking}
                  </div>
                ))}
              </div>
            </div>
          )}

          {message.evidence && message.evidence.length > 0 && (
            <div>
              <div className="text-[10px] font-theme-data text-[var(--acid-yellow)] uppercase mb-1">
                Evidence Sources
              </div>
              <div className="space-y-1">
                {message.evidence.map((source, idx) => (
                  <div
                    key={idx}
                    className="text-xs text-text-muted font-theme-data pl-2 border-l border-acid-yellow/30"
                  >
                    {source.title}
                    {source.relevance !== undefined && (
                      <span className="text-[var(--acid-yellow)] ml-2">
                        ({Math.round(source.relevance * 100)}%)
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {message.confidence !== null && message.confidence !== undefined && (
            <div>
              <div className="text-[10px] font-theme-data text-[var(--accent)] uppercase mb-1">
                Confidence
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 bg-bg border border-border rounded-full overflow-hidden">
                  <div
                    className="h-full bg-[var(--accent)] transition-all duration-300"
                    style={{ width: `${Math.round(message.confidence * 100)}%` }}
                  />
                </div>
                <span className="text-xs font-theme-data text-[var(--accent)]">
                  {Math.round(message.confidence * 100)}%
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="text-sm text-text whitespace-pre-wrap">
        {message.content}
        <span className="inline-block w-2 h-4 bg-[var(--acid-cyan)] ml-1 animate-pulse">|</span>
      </div>
    </div>
  );
}
