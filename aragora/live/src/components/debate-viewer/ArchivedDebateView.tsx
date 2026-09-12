'use client';

import { useState } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import { TranscriptMessageCard } from './TranscriptMessageCard';
import { DebateForkPanel } from './DebateForkPanel';
import { DownloadSection } from './DownloadSection';
import { BroadcastPanel } from '@/components/broadcast';
import { RhetoricalPanel } from './RhetoricalPanel';
import { TricksterAlert } from './TricksterAlert';
import { EvidenceLinkGraph } from './EvidenceLinkGraph';
import { logger } from '@/utils/logger';
import type { ArchivedDebateViewProps, TranscriptMessage } from './types';

export function ArchivedDebateView({ debate, onShare, copied }: ArchivedDebateViewProps) {
  const [showForkPanel, setShowForkPanel] = useState(false);

  const messageCount = (debate.transcript as unknown as TranscriptMessage[])?.length || 0;

  return (
    <div className="space-y-6">
      {/* Debate Header */}
      <div className="bg-surface border border-[var(--accent)]/30 p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xs text-text-muted font-theme-data mb-2">
              DEBATE {'// '}CYCLE {debate.cycle_number} {'// '}
              {debate.phase.toUpperCase()}
            </div>
            <h1 className="text-lg font-theme-data text-[var(--accent)] mb-4">{debate.task}</h1>
            <div className="flex flex-wrap gap-2">
              {debate.agents.map((agent) => {
                const colors = getAgentColors(agent);
                return (
                  <span
                    key={agent}
                    className={`px-2 py-1 text-xs font-theme-data ${colors.bg} ${colors.text} ${colors.border} border`}
                  >
                    {agent}
                  </span>
                );
              })}
            </div>
          </div>

          <div className="flex flex-col items-end gap-2">
            <div className="flex gap-2">
              <button
                onClick={() => setShowForkPanel(!showForkPanel)}
                className={`px-3 py-1 text-xs font-theme-data transition-colors ${
                  showForkPanel
                    ? 'bg-accent text-bg hover:bg-accent/80'
                    : 'bg-surface border border-accent/50 text-accent hover:bg-accent/10'
                }`}
              >
                {showForkPanel ? '[HIDE FORK]' : '[FORK]'}
              </button>
              <button
                onClick={onShare}
                className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors"
              >
                {copied ? '[COPIED!]' : '[SHARE LINK]'}
              </button>
            </div>
            <div className="text-xs text-text-muted font-theme-data">
              {new Date(debate.created_at).toLocaleString()}
            </div>
          </div>
        </div>

        {/* Consensus Status */}
        <div className="mt-4 pt-4 border-t border-[var(--accent)]/20 flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${debate.consensus_reached ? 'bg-green-400' : 'bg-yellow-400'}`}
            />
            <span className="text-xs font-theme-data text-text-muted">
              {debate.consensus_reached ? 'CONSENSUS REACHED' : 'NO CONSENSUS'}
            </span>
          </div>
          <div className="text-xs font-theme-data text-text-muted">
            CONFIDENCE: {Math.round(debate.confidence * 100)}%
          </div>
          {debate.vote_tally && Object.keys(debate.vote_tally).length > 0 && (
            <div className="text-xs font-theme-data text-text-muted">
              VOTES:{' '}
              {Object.entries(debate.vote_tally)
                .map(([k, v]) => `${k}:${v}`)
                .join(' ')}
            </div>
          )}
        </div>
      </div>

      {/* Fork Panel */}
      {showForkPanel && (
        <DebateForkPanel
          debateId={debate.id}
          messageCount={messageCount}
          onForkCreated={(result) => {
            logger.debug('Fork created:', result);
            // Could navigate to the new fork or show a success message
          }}
          onFollowupCreated={(result) => {
            logger.debug('Follow-up created:', result);
            // Could navigate to the new follow-up debate
          }}
        />
      )}

      {/* Winning Proposal */}
      {debate.winning_proposal && (
        <div className="bg-gradient-to-br from-accent/10 to-purple-500/10 border-2 border-accent/50 p-6">
          <div className="text-xs text-accent font-theme-data mb-2 uppercase tracking-wider">
            Winning Proposal
          </div>
          <div className="text-text whitespace-pre-wrap font-theme-data text-sm">
            {debate.winning_proposal}
          </div>
        </div>
      )}

      {/* Debate Quality Analysis */}
      <TricksterAlert debateId={debate.id} />
      <RhetoricalPanel debateId={debate.id} />
      <EvidenceLinkGraph debateId={debate.id} />

      {/* Transcript */}
      <div className="bg-surface border border-[var(--accent)]/30">
        <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
            {'>'} DEBATE TRANSCRIPT
          </span>
        </div>
        <div className="p-4 space-y-4 max-h-[600px] overflow-y-auto">
          {(debate.transcript as unknown as TranscriptMessage[]).map((msg, idx) => (
            <TranscriptMessageCard key={idx} message={msg} />
          ))}
        </div>
      </div>

      {/* Download Section */}
      <div className="bg-surface border border-[var(--accent)]/30">
        <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
            {'>'} DOWNLOAD TRANSCRIPT
          </span>
        </div>
        <div className="p-4">
          <DownloadSection debateId={debate.id} isCompleted={true} />
        </div>
      </div>

      {/* Broadcast Panel */}
      <BroadcastPanel debateId={debate.id} debateTitle={debate.task} />

      {/* Metadata */}
      <div className="text-center text-xs font-theme-data text-text-muted py-4 border-t border-[var(--accent)]/20">
        <div>DEBATE ID: {debate.id}</div>
        <div>LOOP: {debate.loop_id}</div>
      </div>
    </div>
  );
}
