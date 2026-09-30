'use client';

import { useMemo, useState } from 'react';
import type { StreamEvent, TokenDeltaData } from '@/types/events';

interface TokenStreamViewerProps {
  events: StreamEvent[];
  agents?: string[];
}

interface AgentTokenStats {
  agent: string;
  totalTokens: number;
  tokensThisRound: number;
  isStreaming: boolean;
  lastUpdate: number;
  currentContent: string;
  rounds: number[];
}

// Token budget visualization
const TOKEN_BUDGET = 4096; // Typical token budget per response

export function TokenStreamViewer({ events, agents = [] }: TokenStreamViewerProps) {
  const [showDetails, setShowDetails] = useState(false);

  const agentStats = useMemo(() => {
    const stats: Record<string, AgentTokenStats> = {};

    // Initialize with known agents
    for (const agent of agents) {
      stats[agent] = {
        agent,
        totalTokens: 0,
        tokensThisRound: 0,
        isStreaming: false,
        lastUpdate: 0,
        currentContent: '',
        rounds: [],
      };
    }

    let currentRound = 1;

    for (const event of events) {
      if (event.type === 'round_start') {
        currentRound = event.round || currentRound + 1;
        // Reset round tokens for all agents
        for (const agent in stats) {
          stats[agent].tokensThisRound = 0;
        }
      }

      if (event.type === 'token_start') {
        const agent = event.agent || 'unknown';
        if (!stats[agent]) {
          stats[agent] = {
            agent,
            totalTokens: 0,
            tokensThisRound: 0,
            isStreaming: true,
            lastUpdate: event.timestamp,
            currentContent: '',
            rounds: [],
          };
        }
        stats[agent].isStreaming = true;
        stats[agent].currentContent = '';
      }

      if (event.type === 'token_delta') {
        const data = event.data as TokenDeltaData;
        if (!stats[data.agent]) {
          stats[data.agent] = {
            agent: data.agent,
            totalTokens: 0,
            tokensThisRound: 0,
            isStreaming: true,
            lastUpdate: event.timestamp,
            currentContent: '',
            rounds: [],
          };
        }

        // Rough token count (words + punctuation)
        const tokenCount = data.delta.split(/\s+/).filter(Boolean).length || 1;
        stats[data.agent].totalTokens += tokenCount;
        stats[data.agent].tokensThisRound += tokenCount;
        stats[data.agent].lastUpdate = event.timestamp;
        stats[data.agent].currentContent += data.delta;
        stats[data.agent].isStreaming = true;
      }

      if (event.type === 'token_end') {
        const agent = event.agent || 'unknown';
        if (stats[agent]) {
          stats[agent].isStreaming = false;
          if (!stats[agent].rounds.includes(currentRound)) {
            stats[agent].rounds.push(currentRound);
          }
        }
      }
    }

    return Object.values(stats).sort((a, b) => b.totalTokens - a.totalTokens);
  }, [events, agents]);

  // Calculate totals
  const totalTokens = useMemo(() => {
    return agentStats.reduce((sum, s) => sum + s.totalTokens, 0);
  }, [agentStats]);

  const activeStreamers = useMemo(() => {
    return agentStats.filter((s) => s.isStreaming);
  }, [agentStats]);

  if (agentStats.length === 0 || totalTokens === 0) {
    return null;
  }

  return (
    <div className="bg-bg-secondary rounded border border-border p-3">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-text-primary font-medium text-sm flex items-center gap-2">
          Token Usage
          {activeStreamers.length > 0 && (
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              <span className="text-xs text-green-400">{activeStreamers.length} streaming</span>
            </span>
          )}
        </h3>
        <button
          onClick={() => setShowDetails(!showDetails)}
          className="text-xs text-text-muted hover:text-text-secondary"
        >
          {showDetails ? 'Hide' : 'Details'}
        </button>
      </div>

      {/* Total tokens bar */}
      <div className="mb-3">
        <div className="flex justify-between text-xs text-text-muted mb-1">
          <span>Total</span>
          <span>{totalTokens.toLocaleString()} tokens</span>
        </div>
        <div className="h-2 bg-bg-primary rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-cyan-600 to-blue-500"
            style={{
              width: `${Math.min((totalTokens / (TOKEN_BUDGET * agents.length)) * 100, 100)}%`,
            }}
          />
        </div>
      </div>

      {/* Per-agent breakdown */}
      <div className="space-y-2">
        {agentStats.map((stat) => {
          const percentage = totalTokens > 0 ? (stat.totalTokens / totalTokens) * 100 : 0;
          const budgetUsage = (stat.tokensThisRound / TOKEN_BUDGET) * 100;

          return (
            <div key={stat.agent} className="text-sm">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className="text-text-primary font-medium">{stat.agent}</span>
                  {stat.isStreaming && (
                    <span className="text-xs text-green-400 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
                      typing
                    </span>
                  )}
                </div>
                <span className="text-text-muted text-xs">
                  {stat.totalTokens.toLocaleString()} ({percentage.toFixed(1)}%)
                </span>
              </div>

              {/* Token bar */}
              <div className="h-1.5 bg-bg-primary rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all duration-300 ${
                    stat.isStreaming
                      ? 'bg-gradient-to-r from-green-600 to-green-400'
                      : 'bg-gradient-to-r from-blue-600 to-cyan-500'
                  }`}
                  style={{ width: `${percentage}%` }}
                />
              </div>

              {/* Details */}
              {showDetails && (
                <div className="mt-1 flex items-center gap-3 text-xs text-text-muted">
                  <span>Round: {stat.tokensThisRound}</span>
                  <span>Budget: {budgetUsage.toFixed(0)}%</span>
                  <span>Rounds: {stat.rounds.length}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Live streaming preview */}
      {activeStreamers.length > 0 && showDetails && (
        <div className="mt-3 pt-3 border-t border-border">
          <h4 className="text-xs text-text-muted mb-2">Live Streams</h4>
          {activeStreamers.map((stat) => (
            <div key={stat.agent} className="mb-2">
              <span className="text-xs font-medium text-text-primary">{stat.agent}:</span>
              <p className="text-xs text-text-muted mt-1 line-clamp-2 font-theme-data">
                {stat.currentContent.slice(-200) || '...'}
                <span className="animate-pulse">|</span>
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default TokenStreamViewer;
