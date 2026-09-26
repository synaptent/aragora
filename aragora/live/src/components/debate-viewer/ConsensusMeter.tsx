'use client';

import { useMemo } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import type { StreamEvent, VoteData, ConsensusData } from '@/types/events';

interface ConsensusMeterProps {
  events: StreamEvent[];
  agents: string[];
}

interface AgentVote {
  agent: string;
  choice: string;
  confidence: number;
  timestamp: number;
}

type ConsensusState = 'waiting' | 'diverging' | 'converging' | 'consensus' | 'deadlock';

function getConsensusState(
  votes: AgentVote[],
  totalAgents: number,
  consensusReached: boolean,
): ConsensusState {
  if (votes.length === 0) return 'waiting';
  if (consensusReached) return 'consensus';

  // Count votes per choice
  const voteCounts = new Map<string, number>();
  for (const vote of votes) {
    voteCounts.set(vote.choice, (voteCounts.get(vote.choice) || 0) + 1);
  }

  // Check for majority
  const voteCountsArray = Array.from(voteCounts.values());
  const maxVotes = voteCountsArray.length > 0 ? Math.max(...voteCountsArray) : 0;
  const majorityThreshold = Math.ceil(totalAgents / 2);

  if (maxVotes >= majorityThreshold) return 'converging';

  // Check for deadlock (even split)
  const uniqueChoices = voteCounts.size;
  if (uniqueChoices > 1 && votes.length >= totalAgents) {
    const allEqual = voteCountsArray.every((v) => v === voteCountsArray[0]);
    if (allEqual) return 'deadlock';
  }

  return 'diverging';
}

function getStateConfig(state: ConsensusState) {
  switch (state) {
    case 'waiting':
      return { color: 'text-text-muted', bg: 'bg-text-muted/20', label: 'AWAITING VOTES' };
    case 'diverging':
      return { color: 'text-yellow-400', bg: 'bg-yellow-400/20', label: 'DIVERGING' };
    case 'converging':
      return {
        color: 'text-[var(--acid-cyan)]',
        bg: 'bg-[var(--acid-cyan)]/20',
        label: 'CONVERGING',
      };
    case 'consensus':
      return { color: 'text-[var(--accent)]', bg: 'bg-[var(--accent)]/20', label: 'CONSENSUS' };
    case 'deadlock':
      return { color: 'text-[var(--crimson)]', bg: 'bg-[var(--crimson)]/20', label: 'DEADLOCK' };
  }
}

export function ConsensusMeter({ events, agents }: ConsensusMeterProps) {
  const { votes, consensusData, agreementPct, state } = useMemo(() => {
    const voteMap = new Map<string, AgentVote>();
    let consensus: ConsensusData | null = null;

    for (const event of events) {
      if (event.type === 'vote') {
        const data = event.data as VoteData;
        voteMap.set(data.agent, {
          agent: data.agent,
          choice: data.choice || data.vote || '',
          confidence: data.confidence ?? 0.5,
          timestamp: event.timestamp,
        });
      } else if (event.type === 'consensus') {
        consensus = event.data as ConsensusData;
      }
    }

    const votesList = Array.from(voteMap.values());
    const consensusReached = consensus?.reached ?? false;
    const currentState = getConsensusState(votesList, agents.length, consensusReached);

    // Calculate agreement percentage
    let agreement = 0;
    if (votesList.length > 0) {
      const voteCounts = new Map<string, number>();
      for (const vote of votesList) {
        voteCounts.set(vote.choice, (voteCounts.get(vote.choice) || 0) + 1);
      }
      const countsArray = Array.from(voteCounts.values());
      const maxVotes = countsArray.length > 0 ? Math.max(...countsArray) : 0;
      agreement = (maxVotes / agents.length) * 100;
    }

    return {
      votes: votesList,
      consensusData: consensus,
      agreementPct: agreement,
      state: currentState,
    };
  }, [events, agents]);

  const stateConfig = getStateConfig(state);

  // Group votes by choice for visualization
  const votesByChoice = useMemo(() => {
    const groups = new Map<string, AgentVote[]>();
    for (const vote of votes) {
      const existing = groups.get(vote.choice) || [];
      groups.set(vote.choice, [...existing, vote]);
    }
    return groups;
  }, [votes]);

  return (
    <div className="bg-surface border border-[var(--accent)]/30">
      <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
          {'>'} CONSENSUS METER
        </span>
        <span className={`text-xs font-theme-data ${stateConfig.color}`}>{stateConfig.label}</span>
      </div>

      <div className="p-4 space-y-4">
        {/* Agreement Gauge */}
        <div className="space-y-2">
          <div className="flex justify-between text-xs font-theme-data text-text-muted">
            <span>Agreement</span>
            <span>{agreementPct.toFixed(0)}%</span>
          </div>
          <div className="h-3 bg-bg border border-[var(--accent)]/20 overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ease-out ${stateConfig.bg}`}
              style={{ width: `${agreementPct}%` }}
            >
              <div
                className={`h-full ${stateConfig.color.replace('text-', 'bg-')} opacity-60`}
                style={{ width: '100%' }}
              />
            </div>
          </div>
        </div>

        {/* Per-Agent Votes */}
        <div className="space-y-2">
          <div className="text-xs font-theme-data text-text-muted">
            Votes ({votes.length}/{agents.length})
          </div>

          {agents.length > 0 && votes.length === 0 && (
            <div className="text-xs font-theme-data text-text-muted/60 italic py-2">
              Waiting for agents to cast votes...
            </div>
          )}

          {/* Vote Groups */}
          {Array.from(votesByChoice.entries()).map(([choice, choiceVotes]) => (
            <div key={choice} className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-theme-data text-[var(--acid-cyan)] truncate max-w-[120px]">
                  {choice}
                </span>
                <span className="text-xs font-theme-data text-text-muted">
                  ({choiceVotes.length})
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {choiceVotes.map((vote) => {
                  const colors = getAgentColors(vote.agent);
                  const confidencePct = Math.round(vote.confidence * 100);
                  return (
                    <div
                      key={vote.agent}
                      className={`px-2 py-0.5 text-xs font-theme-data ${colors.bg} ${colors.text} ${colors.border} border`}
                      title={`${vote.agent}: ${confidencePct}% confidence`}
                    >
                      <span>{vote.agent.split('-')[0]}</span>
                      <span className="ml-1 opacity-60">{confidencePct}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Consensus Result */}
        {consensusData?.reached && (
          <div className="pt-2 border-t border-[var(--accent)]/20">
            <div className="text-xs font-theme-data text-[var(--accent)] mb-1">
              CONSENSUS REACHED
            </div>
            {consensusData.answer && (
              <div className="text-xs font-theme-data text-text-primary bg-[var(--accent)]/10 p-2 border border-[var(--accent)]/30">
                {consensusData.answer}
              </div>
            )}
            {consensusData.confidence !== undefined && (
              <div className="text-xs font-theme-data text-text-muted mt-1">
                Confidence: {(consensusData.confidence * 100).toFixed(0)}%
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
