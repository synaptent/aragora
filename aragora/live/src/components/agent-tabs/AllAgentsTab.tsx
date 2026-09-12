'use client';

import type { RefObject } from 'react';
import { RoleBadge } from '../RoleBadge';
import { getAgentColors } from '@/utils/agentColors';
import type { TimelineMessage, AgentData } from './types';
import { ROLE_ICONS } from './types';

interface AllAgentsTabProps {
  unifiedTimeline: TimelineMessage[];
  agentData: AgentData[];
  autoScroll: boolean;
  scrollRef: RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  onJumpToLatest: () => void;
}

export function AllAgentsTab({
  unifiedTimeline,
  agentData,
  autoScroll,
  scrollRef,
  onScroll,
  onJumpToLatest,
}: AllAgentsTabProps) {
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Unified Header */}
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-sm text-text-muted">
            Activity Timeline • {unifiedTimeline.length} messages from {agentData.length} agents
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-text-muted">
          {autoScroll ? (
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse" />
              Live
            </span>
          ) : (
            <button
              onClick={onJumpToLatest}
              className="px-2 py-1 bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30 hover:bg-[var(--accent)]/30"
            >
              ↓ Jump to Latest
            </button>
          )}
        </div>
      </div>

      {/* Unified Timeline */}
      <div
        ref={scrollRef as React.RefObject<HTMLDivElement>}
        onScroll={onScroll}
        className="flex-1 overflow-y-auto p-4 space-y-3"
      >
        {unifiedTimeline.length === 0 ? (
          <div className="text-center text-text-muted py-8">Waiting for agent responses...</div>
        ) : (
          unifiedTimeline.map((msg, idx) => {
            const colors = getAgentColors(msg.agent);
            const roleIcon = ROLE_ICONS[msg.role] || ROLE_ICONS.default;
            return (
              <div key={idx} className={`${colors.bg} border ${colors.border} p-3 rounded`}>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-sm">{roleIcon}</span>
                  <span className={`font-medium text-sm ${colors.text}`}>{msg.agent}</span>
                  <RoleBadge role={msg.role} cognitiveRole={msg.cognitiveRole} />
                  {msg.round > 0 && (
                    <span className="px-1.5 py-0.5 text-xs bg-surface rounded border border-border">
                      R{msg.round}
                    </span>
                  )}
                  <span className="text-xs text-text-muted ml-auto">
                    {new Date(msg.timestamp * 1000).toLocaleTimeString()}
                  </span>
                </div>
                <div className="agent-output text-sm whitespace-pre-wrap break-words">
                  {msg.content}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
