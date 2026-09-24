'use client';

import type { StreamEvent } from '@/hooks/useEventStream';

interface InlineDebatePanelProps {
  nodeId: string;
  events: StreamEvent[];
  isActive: boolean;
}

export function InlineDebatePanel({ nodeId: _nodeId, events, isActive }: InlineDebatePanelProps) {
  const debateEvents = events.filter((e) => e.category === 'debate');

  if (debateEvents.length === 0 && !isActive) return null;

  // Extract participating agents
  const agents = [...new Set(debateEvents.map((e) => e.data.agent as string).filter(Boolean))];

  // Find consensus event
  const consensusEvent = debateEvents.find((e) => e.type === 'CONSENSUS' || e.type === 'consensus');
  const confidence = consensusEvent?.data?.confidence as number | undefined;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
          Debate {isActive ? '(Live)' : '(Complete)'}
        </h4>
        {isActive && <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />}
      </div>

      {/* Agents */}
      {agents.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {agents.map((agent) => (
            <span
              key={agent}
              className="px-2 py-0.5 text-[10px] font-theme-data bg-indigo-500/10 text-indigo-400 rounded border border-indigo-500/20"
            >
              {agent}
            </span>
          ))}
        </div>
      )}

      {/* Confidence */}
      {confidence !== undefined && (
        <div className="space-y-1">
          <div className="flex justify-between text-[10px] font-theme-data text-text-muted">
            <span>Confidence</span>
            <span>{Math.round(confidence * 100)}%</span>
          </div>
          <div className="h-1.5 bg-bg rounded-full overflow-hidden">
            <div
              className="h-full bg-emerald-500 rounded-full transition-all"
              style={{ width: `${confidence * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Event Timeline */}
      <div className="space-y-1 max-h-40 overflow-y-auto">
        {debateEvents.slice(-8).map((e) => (
          <div key={e.id} className="flex items-start gap-2 text-[11px] font-theme-data">
            <span
              className={`flex-shrink-0 mt-0.5 w-1.5 h-1.5 rounded-full ${
                e.type.includes('CONSENSUS') || e.type === 'consensus'
                  ? 'bg-emerald-500'
                  : e.type.includes('CRITIQUE') || e.type === 'critique'
                    ? 'bg-amber-500'
                    : e.type.includes('VOTE') || e.type === 'vote'
                      ? 'bg-blue-500'
                      : 'bg-gray-500'
              }`}
            />
            <span className="text-text-muted truncate">{e.summary}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
