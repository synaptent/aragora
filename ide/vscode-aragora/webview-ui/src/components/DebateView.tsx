import { useRef, useEffect } from 'react';
import type { DebateState, DebateMessage, DebateConsensus } from '../types';
import { getAgentColor } from '../types';
import { TokenMetrics } from './TokenMetrics';

interface DebateViewProps {
  debate: DebateState | undefined;
  connectionStatus: 'connected' | 'disconnected' | 'connecting';
  onStartDebate: (question: string, agents: string[], rounds: number) => void;
  onStopDebate: (debateId: string) => void;
  onCopyResult: (debateId: string) => void;
  onExportDebate: (debateId: string, format: 'json' | 'markdown' | 'html') => void;
  onSendFeedback: (debateId: string, vote: 'up' | 'down') => void;
}

export function DebateView({
  debate,
  connectionStatus,
  onStartDebate,
  onStopDebate,
  onCopyResult,
  onExportDebate,
  onSendFeedback,
}: DebateViewProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [debate?.messages.length]);

  if (!debate) {
    return (
      <div className="empty-state">
        <div className="empty-icon">💭</div>
        <h2>No Active Debate</h2>
        <p>Start a debate to see multi-agent discussion here.</p>
        <button className="primary-button" onClick={() => onStartDebate('', [], 3)}>
          Start New Debate
        </button>
      </div>
    );
  }

  return (
    <div className="debate-view">
      {/* Header */}
      <div className="debate-header">
        <div className="debate-title">
          <h1>{debate.question}</h1>
          <div className="debate-meta">
            <span className={`status-badge ${debate.status}`}>{debate.status}</span>
            <span className="round-indicator">
              Round {debate.currentRound}/{debate.totalRounds}
            </span>
            {connectionStatus === 'connected' && <span className="live-indicator">● LIVE</span>}
          </div>
        </div>
        {debate.status === 'running' && (
          <button className="stop-button" onClick={() => onStopDebate(debate.id)}>
            Stop Debate
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="messages-container">
        {debate.messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {debate.status === 'running' && (
          <div className="typing-indicator">
            <span>Agents discussing...</span>
            <div className="dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Consensus Card */}
      {debate.consensus && (
        <ConsensusCard
          consensus={debate.consensus}
          debateId={debate.id}
          onCopy={onCopyResult}
          onExport={onExportDebate}
          onFeedback={onSendFeedback}
        />
      )}

      {/* Token Metrics */}
      {debate.totalTokens && <TokenMetrics usage={debate.totalTokens} />}
    </div>
  );
}

function MessageBubble({ message }: { message: DebateMessage }) {
  const agentColor = getAgentColor(message.agent.name);

  return (
    <div className="message-bubble">
      <div className="agent-avatar" style={{ backgroundColor: agentColor }}>
        {message.agent.name.charAt(0).toUpperCase()}
      </div>
      <div className="message-content">
        <div className="message-header">
          <span className="agent-name" style={{ color: agentColor }}>
            {message.agent.name}
          </span>
          <span className="agent-provider">({message.agent.provider})</span>
          <span className="message-round">Round {message.round}</span>
        </div>
        <div className="message-text">{message.content}</div>
        {message.tokens && (
          <div className="message-tokens">{message.tokens.totalTokens.toLocaleString()} tokens</div>
        )}
      </div>
    </div>
  );
}

interface ConsensusCardProps {
  consensus: DebateConsensus;
  debateId: string;
  onCopy: (debateId: string) => void;
  onExport: (debateId: string, format: 'json' | 'markdown' | 'html') => void;
  onFeedback: (debateId: string, vote: 'up' | 'down') => void;
}

function ConsensusCard({ consensus, debateId, onCopy, onExport, onFeedback }: ConsensusCardProps) {
  return (
    <div className="consensus-card">
      <div className="consensus-header">
        <h2>✨ Consensus Reached</h2>
        <div className="consensus-meta">
          <span className="confidence">{(consensus.confidence * 100).toFixed(0)}% confidence</span>
          <span className="method">via {consensus.method}</span>
        </div>
      </div>

      <div className="consensus-answer">{consensus.answer}</div>

      <div className="consensus-agents">
        <span className="label">Agreeing:</span>
        {consensus.agreeingAgents.map((agent) => (
          <span
            key={agent}
            className="agent-chip"
            style={{ backgroundColor: getAgentColor(agent) }}
          >
            {agent}
          </span>
        ))}
      </div>

      {consensus.dissent && consensus.dissent.length > 0 && (
        <div className="consensus-dissent">
          <span className="label">Dissent:</span>
          {consensus.dissent.map((d) => (
            <div key={d.agent} className="dissent-item">
              <strong>{d.agent}:</strong> {d.reason}
            </div>
          ))}
        </div>
      )}

      <div className="consensus-actions">
        <button onClick={() => onCopy(debateId)}>📋 Copy</button>
        <button onClick={() => onExport(debateId, 'markdown')}>📄 Export</button>
        <div className="feedback-buttons">
          <button
            className="feedback-up"
            onClick={() => onFeedback(debateId, 'up')}
            title="Good result"
          >
            👍
          </button>
          <button
            className="feedback-down"
            onClick={() => onFeedback(debateId, 'down')}
            title="Could be better"
          >
            👎
          </button>
        </div>
      </div>
    </div>
  );
}
