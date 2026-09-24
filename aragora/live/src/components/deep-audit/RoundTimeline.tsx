'use client';

import { RoleBadge } from '../RoleBadge';
import { CitationBadge } from '../CitationsPanel';
import type { RoundData, AuditRoundInfo } from './types';
import { STATUS_CONFIG, AUDIT_ROUNDS } from './types';

interface RoundTimelineProps {
  roundData: RoundData[];
  expandedRound: number | null;
  onExpandRound: (round: number | null) => void;
}

export function RoundTimeline({ roundData, expandedRound, onExpandRound }: RoundTimelineProps) {
  return (
    <div className="p-4">
      <div className="space-y-2">
        {AUDIT_ROUNDS.map((auditRound) => {
          const data = roundData.find((r) => r.round === auditRound.round);
          const isExpanded = expandedRound === auditRound.round;
          const status = data?.status || 'pending';
          const config = STATUS_CONFIG[status];

          return (
            <div
              key={auditRound.round}
              className={`rounded-lg border transition-all ${config.bg} ${config.border}`}
            >
              <RoundHeader
                auditRound={auditRound}
                data={data}
                status={status}
                isExpanded={isExpanded}
                config={config}
                onToggle={() => onExpandRound(isExpanded ? null : auditRound.round)}
              />
              {isExpanded && data && data.messages.length > 0 && (
                <RoundMessages messages={data.messages} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface RoundHeaderProps {
  auditRound: AuditRoundInfo;
  data: RoundData | undefined;
  status: RoundData['status'];
  isExpanded: boolean;
  config: (typeof STATUS_CONFIG)[keyof typeof STATUS_CONFIG];
  onToggle: () => void;
}

function RoundHeader({ auditRound, data, status, isExpanded, config, onToggle }: RoundHeaderProps) {
  return (
    <button onClick={onToggle} className="w-full p-3 text-left" disabled={status === 'pending'}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-lg">{auditRound.icon}</span>
          <div>
            <div className="flex items-center gap-2">
              <span className={`text-sm font-medium ${config.text}`}>
                Round {auditRound.round}: {auditRound.name}
              </span>
              {status === 'active' && (
                <span className="w-2 h-2 bg-accent rounded-full animate-pulse" />
              )}
              {status === 'complete' && <span className="text-success text-xs">✓</span>}
            </div>
            <p className="text-xs text-text-muted">{auditRound.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {data && data.messages.length > 0 && (
            <span className="text-xs text-text-muted">
              {data.messages.length} response{data.messages.length !== 1 ? 's' : ''}
            </span>
          )}
          {status !== 'pending' && (
            <span className="text-text-muted text-xs">{isExpanded ? '▼' : '▶'}</span>
          )}
        </div>
      </div>
    </button>
  );
}

interface RoundMessagesProps {
  messages: RoundData['messages'];
}

function RoundMessages({ messages }: RoundMessagesProps) {
  return (
    <div className="px-3 pb-3 space-y-2">
      {messages.map((msg, idx) => (
        <div key={idx} className="p-2 bg-bg rounded border border-border">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-text">{msg.agent}</span>
              <RoleBadge role={msg.role} cognitiveRole={msg.cognitiveRole} size="sm" />
            </div>
            <div className="flex items-center gap-2">
              {msg.confidence !== undefined && (
                <span
                  className={`text-xs font-theme-data ${
                    msg.confidence >= 0.8
                      ? 'text-green-400'
                      : msg.confidence >= 0.6
                        ? 'text-yellow-400'
                        : 'text-red-400'
                  }`}
                >
                  {Math.round(msg.confidence * 100)}%
                </span>
              )}
              {msg.citations !== undefined && msg.citations > 0 && (
                <CitationBadge count={msg.citations} />
              )}
            </div>
          </div>
          <p className="agent-output text-text-muted whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
            {msg.content.slice(0, 500)}
            {msg.content.length > 500 && '...'}
          </p>
        </div>
      ))}
    </div>
  );
}
