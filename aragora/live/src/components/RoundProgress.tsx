'use client';

import { useMemo } from 'react';
import type { StreamEvent } from '@/types/events';

interface RoundProgressProps {
  events: StreamEvent[];
  totalRounds?: number;
}

interface RoundData {
  round: number;
  status: 'pending' | 'active' | 'complete';
  stage: string;
  agentCount: number;
  hasConsensus: boolean;
  startTime?: number;
  endTime?: number;
}

// Heavy3-inspired round stages
const ROUND_STAGES: Record<number, { name: string; description: string }> = {
  1: { name: 'Initial Proposals', description: 'Agents present first opinions' },
  2: { name: 'Peer Review', description: 'Agents critique each other' },
  3: { name: 'Revisions', description: 'Agents refine based on feedback' },
  4: { name: 'Final Synthesis', description: 'Synthesizer creates verdict' },
  5: { name: 'Cross-Examination', description: 'Deep probing of conclusions' },
  6: { name: 'Verdict', description: 'Final recommendation delivered' },
};

export function RoundProgress({ events, totalRounds = 4 }: RoundProgressProps) {
  const roundData = useMemo(() => {
    const rounds: Record<number, RoundData> = {};

    // Initialize rounds
    for (let i = 1; i <= totalRounds; i++) {
      rounds[i] = {
        round: i,
        status: 'pending',
        stage: ROUND_STAGES[i]?.name || `Round ${i}`,
        agentCount: 0,
        hasConsensus: false,
      };
    }

    // Find the highest round with activity
    let maxActiveRound = 0;

    events.forEach((event) => {
      const round = event.round || 0;
      if (round > 0 && round <= totalRounds) {
        if (round > maxActiveRound) {
          maxActiveRound = round;
        }

        if (!rounds[round].startTime || event.timestamp < rounds[round].startTime!) {
          rounds[round].startTime = event.timestamp;
        }
        if (!rounds[round].endTime || event.timestamp > rounds[round].endTime!) {
          rounds[round].endTime = event.timestamp;
        }

        if (event.type === 'agent_message') {
          rounds[round].agentCount++;
        }

        if (event.type === 'consensus') {
          rounds[round].hasConsensus = true;
        }
      }
    });

    // Update statuses
    for (let i = 1; i <= totalRounds; i++) {
      if (i < maxActiveRound) {
        rounds[i].status = 'complete';
      } else if (i === maxActiveRound) {
        rounds[i].status = 'active';
      } else {
        rounds[i].status = 'pending';
      }
    }

    return Object.values(rounds);
  }, [events, totalRounds]);

  const activeRound = roundData.find((r) => r.status === 'active');
  const completedCount = roundData.filter((r) => r.status === 'complete').length;

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-medium text-text-muted uppercase tracking-wider">
          Debate Rounds
        </h2>
        <span className="text-xs text-text-muted">
          {completedCount}/{totalRounds} complete
        </span>
      </div>

      {/* Round Timeline */}
      <div className="flex items-start gap-1">
        {roundData.map((round, index) => (
          <div key={round.round} className="flex items-center flex-1">
            <RoundBlock round={round} />
            {index < roundData.length - 1 && (
              <div
                className={`h-0.5 flex-1 mx-1 ${
                  round.status === 'complete' ? 'bg-success' : 'bg-border'
                }`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Active Round Detail */}
      {activeRound && (
        <div className="mt-4 p-3 bg-accent/10 border border-accent/30 rounded-lg">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 bg-accent rounded-full animate-pulse" />
                <span className="text-sm font-medium text-accent">
                  Round {activeRound.round}: {activeRound.stage}
                </span>
              </div>
              <p className="text-xs text-text-muted mt-1">
                {ROUND_STAGES[activeRound.round]?.description || 'In progress...'}
              </p>
            </div>
            <div className="text-right text-xs text-text-muted">
              <div>{activeRound.agentCount} responses</div>
              {activeRound.startTime && (
                <div>Started {new Date(activeRound.startTime * 1000).toLocaleTimeString()}</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

interface RoundBlockProps {
  round: RoundData;
}

function RoundBlock({ round }: RoundBlockProps) {
  const statusConfig = {
    pending: { bg: 'bg-surface', border: 'border-border', text: 'text-text-muted', icon: '○' },
    active: { bg: 'bg-accent/20', border: 'border-accent', text: 'text-accent', icon: '●' },
    complete: { bg: 'bg-success/20', border: 'border-success', text: 'text-success', icon: '✓' },
  };

  const config = statusConfig[round.status];

  return (
    <div
      className={`
        flex-1 p-2 rounded-lg border transition-all
        ${config.bg} ${config.border}
      `}
    >
      <div className="flex items-center gap-1.5">
        <span className={`text-xs ${config.text}`}>{config.icon}</span>
        <span className={`text-xs font-medium ${config.text}`}>R{round.round}</span>
      </div>
      <div className="text-xs text-text-muted mt-0.5 truncate" title={round.stage}>
        {round.stage}
      </div>
      {round.agentCount > 0 && (
        <div className="text-xs text-text-muted mt-0.5">
          {round.agentCount} msg{round.agentCount !== 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
}

// Compact version for header use
export function RoundIndicator({ events, totalRounds = 4 }: RoundProgressProps) {
  const currentRound = useMemo(() => {
    let maxRound = 0;
    events.forEach((event) => {
      if (event.round && event.round > maxRound) {
        maxRound = event.round;
      }
    });
    return maxRound;
  }, [events]);

  return (
    <div className="flex items-center gap-1">
      {Array.from({ length: totalRounds }, (_, i) => i + 1).map((round) => (
        <div
          key={round}
          className={`w-2 h-2 rounded-full transition-all ${
            round < currentRound
              ? 'bg-success'
              : round === currentRound
                ? 'bg-accent animate-pulse'
                : 'bg-border'
          }`}
          title={`Round ${round}`}
        />
      ))}
    </div>
  );
}
