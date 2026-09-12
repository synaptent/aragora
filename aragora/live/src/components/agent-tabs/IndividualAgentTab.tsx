'use client';

import { useState, useMemo } from 'react';
import { RoleBadge } from '../RoleBadge';
import { AgentRelationships } from '../AgentRelationships';
import { getConfidenceColor } from '@/utils/colors';
import type { AgentData, PositionEntry, MatchHistoryEntry } from './types';
import { API_BASE_URL } from '@/config';

interface IndividualAgentTabProps {
  currentAgent: AgentData;
  positions: PositionEntry[];
  positionsLoading: boolean;
  matchHistory: MatchHistoryEntry[];
  matchHistoryLoading: boolean;
  showHistory: boolean;
  showPositions: boolean;
  showMatchHistory: boolean;
  onToggleHistory: () => void;
  onTogglePositions: () => void;
  onToggleMatchHistory: () => void;
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

export function IndividualAgentTab({
  currentAgent,
  positions,
  positionsLoading,
  matchHistory,
  matchHistoryLoading,
  showHistory,
  showPositions,
  showMatchHistory,
  onToggleHistory,
  onTogglePositions,
  onToggleMatchHistory,
  apiBase = DEFAULT_API_BASE,
}: IndividualAgentTabProps) {
  const [showRelationships, setShowRelationships] = useState(false);

  const handleToggleRelationships = () => {
    setShowRelationships((prev) => !prev);
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Agent Header */}
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-3">
          <RoleBadge role={currentAgent.role} cognitiveRole={currentAgent.cognitiveRole} />
          {currentAgent.round > 0 && (
            <span className="px-2 py-0.5 text-xs bg-surface rounded border border-border">
              Round {currentAgent.round}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {currentAgent.confidence !== undefined && (
            <span className="text-sm">
              <span className="text-text-muted">Confidence:</span>{' '}
              <span
                className={`font-theme-data font-medium ${getConfidenceColor(currentAgent.confidence)}`}
              >
                {Math.round(currentAgent.confidence * 100)}%
              </span>
            </span>
          )}
          {currentAgent.citations && currentAgent.citations.length > 0 && (
            <span className="text-sm text-text-muted">
              Citations: {currentAgent.citations.length}
            </span>
          )}
          <button
            onClick={onTogglePositions}
            className={`px-2 py-1 text-xs rounded border transition-colors ${
              showPositions
                ? 'bg-purple-500 text-white border-purple-500'
                : 'bg-surface text-text-muted border-border hover:text-text'
            }`}
          >
            Positions {positions.length > 0 && `(${positions.length})`}
          </button>
          <button
            onClick={onToggleMatchHistory}
            className={`px-2 py-1 text-xs rounded border transition-colors ${
              showMatchHistory
                ? 'bg-[var(--acid-cyan)] text-black border-[var(--acid-cyan)]'
                : 'bg-surface text-text-muted border-border hover:text-text'
            }`}
          >
            Matches {matchHistory.length > 0 && `(${matchHistory.length})`}
          </button>
          <button
            onClick={handleToggleRelationships}
            className={`px-2 py-1 text-xs rounded border transition-colors ${
              showRelationships
                ? 'bg-amber-500 text-black border-amber-500'
                : 'bg-surface text-text-muted border-border hover:text-text'
            }`}
          >
            Relations
          </button>
          <button
            onClick={onToggleHistory}
            className={`px-2 py-1 text-xs rounded border transition-colors ${
              showHistory
                ? 'bg-accent text-white border-accent'
                : 'bg-surface text-text-muted border-border hover:text-text'
            }`}
          >
            {showHistory ? 'Latest' : 'History'}
          </button>
        </div>
      </div>

      {/* Response Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {showPositions ? (
          <PositionsView positions={positions} loading={positionsLoading} />
        ) : showMatchHistory ? (
          <MatchHistoryView
            history={matchHistory}
            loading={matchHistoryLoading}
            agentName={currentAgent.name}
          />
        ) : showRelationships ? (
          <AgentRelationships agentName={currentAgent.name} apiBase={apiBase} />
        ) : showHistory ? (
          <HistoryView messages={currentAgent.allMessages} />
        ) : (
          <div className="agent-output whitespace-pre-wrap break-words">
            {currentAgent.latestContent}
          </div>
        )}
      </div>
    </div>
  );
}

function PositionsView({ positions, loading }: { positions: PositionEntry[]; loading: boolean }) {
  if (loading) {
    return <div className="text-center text-text-muted py-4">Loading positions...</div>;
  }

  if (positions.length === 0) {
    return (
      <div className="text-center text-text-muted py-4">No recorded positions for this agent.</div>
    );
  }

  return (
    <div className="space-y-3">
      {positions.map((pos, idx) => (
        <div
          key={idx}
          className="p-3 bg-surface border border-border rounded-lg hover:border-purple-500/30 transition-colors"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="font-medium text-text text-sm">{pos.topic}</span>
            <div className="flex items-center gap-2 text-xs">
              <span
                className={`px-2 py-0.5 rounded ${
                  pos.confidence >= 0.8
                    ? 'bg-green-500/20 text-green-400'
                    : pos.confidence >= 0.5
                      ? 'bg-yellow-500/20 text-yellow-400'
                      : 'bg-red-500/20 text-red-400'
                }`}
              >
                {Math.round(pos.confidence * 100)}% conf
              </span>
              {pos.evidence_count > 0 && (
                <span className="text-text-muted">{pos.evidence_count} evidence</span>
              )}
            </div>
          </div>
          <p className="text-sm text-text-muted">{pos.position}</p>
          <div className="text-xs text-text-muted mt-2">
            Updated: {new Date(pos.last_updated).toLocaleDateString()}
          </div>
        </div>
      ))}
    </div>
  );
}

function HistoryView({ messages }: { messages: AgentData['allMessages'] }) {
  const sortedMessages = useMemo(
    () => [...messages].sort((a, b) => b.timestamp - a.timestamp),
    [messages],
  );

  return (
    <div className="space-y-4">
      {sortedMessages.map((msg, idx) => (
        <div key={idx} className="border-l-2 border-border pl-4">
          <div className="flex items-center gap-2 mb-2 text-xs text-text-muted">
            <span>Round {msg.round}</span>
            <span>•</span>
            <span>{new Date(msg.timestamp * 1000).toLocaleTimeString()}</span>
          </div>
          <div className="agent-output whitespace-pre-wrap break-words">{msg.content}</div>
        </div>
      ))}
    </div>
  );
}

function MatchHistoryView({
  history,
  loading,
  agentName,
}: {
  history: MatchHistoryEntry[];
  loading: boolean;
  agentName: string;
}) {
  if (loading) {
    return <div className="text-center text-text-muted py-4">Loading match history...</div>;
  }

  if (history.length === 0) {
    return (
      <div className="text-center text-text-muted py-4">No match history for this agent yet.</div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="text-xs text-text-muted mb-4">
        Showing {history.length} recent prediction{history.length !== 1 ? 's' : ''} made by{' '}
        {agentName}
      </div>
      {history.map((match, idx) => (
        <div
          key={idx}
          className="p-3 bg-surface border border-border rounded-lg hover:border-[var(--acid-cyan)]/30 transition-colors"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="font-theme-data text-xs text-text-muted">
              {match.tournament_id.slice(0, 8)}...
            </span>
            <span
              className={`px-2 py-0.5 text-xs rounded ${
                match.confidence >= 0.8
                  ? 'bg-green-500/20 text-green-400'
                  : match.confidence >= 0.5
                    ? 'bg-yellow-500/20 text-yellow-400'
                    : 'bg-red-500/20 text-red-400'
              }`}
            >
              {Math.round(match.confidence * 100)}% confident
            </span>
          </div>
          <div className="text-sm">
            <span className="text-text-muted">Predicted winner: </span>
            <span className="text-[var(--acid-cyan)] font-medium">{match.predicted_winner}</span>
          </div>
          {match.created_at && (
            <div className="text-xs text-text-muted mt-2">
              {new Date(match.created_at).toLocaleString()}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
