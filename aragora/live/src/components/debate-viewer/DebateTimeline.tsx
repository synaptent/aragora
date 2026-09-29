'use client';

import { useState, useMemo, useCallback } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import type { StreamEvent } from '@/types/events';
import type { TranscriptMessage } from '@/hooks/useDebateWebSocket';

interface DebateTimelineProps {
  messages: TranscriptMessage[];
  streamEvents: StreamEvent[];
  agents: string[];
}

// Events relevant for timeline display
const TIMELINE_EVENT_TYPES = new Set([
  'debate_start',
  'round_start',
  'agent_message',
  'agent_thinking',
  'agent_evidence',
  'agent_confidence',
  'critique',
  'vote',
  'consensus',
  'synthesis',
  'debate_end',
  'intervention_pause',
  'intervention_resume',
  'intervention_inject',
  'hollow_consensus',
  'trickster_intervention',
]);

interface TimelineEntry {
  id: string;
  timestamp: number;
  type: string;
  agent?: string;
  content: string;
  detail?: string;
  round?: number;
}

const EVENT_LABELS: Record<string, string> = {
  debate_start: 'DEBATE STARTED',
  round_start: 'ROUND',
  agent_message: 'MESSAGE',
  agent_thinking: 'THINKING',
  agent_evidence: 'EVIDENCE',
  agent_confidence: 'CONFIDENCE',
  critique: 'CRITIQUE',
  vote: 'VOTE',
  consensus: 'CONSENSUS',
  synthesis: 'SYNTHESIS',
  debate_end: 'DEBATE ENDED',
  intervention_pause: 'PAUSED',
  intervention_resume: 'RESUMED',
  intervention_inject: 'INJECTED',
  hollow_consensus: 'HOLLOW CONSENSUS',
  trickster_intervention: 'TRICKSTER',
};

const EVENT_COLORS: Record<string, string> = {
  debate_start: 'text-fuchsia-400 border-fuchsia-400/30',
  round_start: 'text-cyan-400 border-cyan-400/30',
  agent_message: 'text-blue-400 border-blue-400/30',
  agent_thinking: 'text-purple-400 border-purple-400/30',
  agent_evidence: 'text-yellow-400 border-yellow-400/30',
  agent_confidence: 'text-green-400 border-green-400/30',
  critique: 'text-red-400 border-red-400/30',
  vote: 'text-amber-400 border-amber-400/30',
  consensus: 'text-green-400 border-green-400/30',
  synthesis: 'text-green-400 border-green-400/30',
  debate_end: 'text-fuchsia-400 border-fuchsia-400/30',
  intervention_pause: 'text-yellow-400 border-yellow-400/30',
  intervention_resume: 'text-green-400 border-green-400/30',
  intervention_inject: 'text-[var(--acid-yellow)] border-acid-yellow/30',
  hollow_consensus: 'text-red-400 border-red-400/30',
  trickster_intervention: 'text-red-400 border-red-400/30',
};

export function DebateTimeline({ messages, streamEvents, agents }: DebateTimelineProps) {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [expandedEntries, setExpandedEntries] = useState<Set<string>>(new Set());
  const [filterTypes, setFilterTypes] = useState<Set<string>>(new Set(TIMELINE_EVENT_TYPES));

  const timelineEntries = useMemo(() => {
    const entries: TimelineEntry[] = [];

    // Add stream events
    for (const event of streamEvents) {
      if (!TIMELINE_EVENT_TYPES.has(event.type)) continue;

      const data = event.data as Record<string, unknown>;
      let content = '';
      let detail = '';

      switch (event.type) {
        case 'debate_start':
          content = (data.task as string) || 'Debate started';
          detail = `Agents: ${((data.agents as string[]) || []).join(', ')}`;
          break;
        case 'round_start':
          content = `Round ${(data.round as number) || event.round || '?'}`;
          break;
        case 'agent_thinking':
          content = (data.thinking as string) || 'Reasoning...';
          break;
        case 'agent_evidence':
          content = `Considering ${((data.sources as unknown[]) || []).length} source(s)`;
          detail = ((data.sources as Array<{ title: string }>) || [])
            .map((s) => s.title)
            .join(', ');
          break;
        case 'agent_confidence':
          content = `Confidence: ${Math.round(((data.confidence as number) || 0) * 100)}%`;
          if (data.reason) detail = data.reason as string;
          break;
        case 'critique':
          content = (data.content as string) || 'Critique submitted';
          break;
        case 'vote':
          content = `Voted: ${(data.choice as string) || (data.vote as string) || '?'}`;
          if (data.confidence)
            detail = `Confidence: ${Math.round((data.confidence as number) * 100)}%`;
          break;
        case 'consensus':
          content = (data.reached as boolean) ? 'Consensus reached' : 'No consensus';
          break;
        case 'synthesis':
          content = (data.content as string) || 'Synthesis generated';
          break;
        case 'debate_end':
          content = 'Debate completed';
          break;
        case 'intervention_pause':
          content = 'Debate paused by user';
          break;
        case 'intervention_resume':
          content = 'Debate resumed';
          break;
        case 'intervention_inject':
          content = `Injected: ${(data.content_preview as string) || 'argument'}`;
          break;
        default:
          content = event.type;
      }

      entries.push({
        id: `event-${event.type}-${event.timestamp}-${entries.length}`,
        timestamp: event.timestamp || 0,
        type: event.type,
        agent: event.agent || (data.agent as string) || undefined,
        content,
        detail,
        round: event.round || (data.round as number) || undefined,
      });
    }

    // Add messages that don't have corresponding stream events
    for (const msg of messages) {
      entries.push({
        id: `msg-${msg.agent}-${msg.timestamp}-${entries.length}`,
        timestamp: msg.timestamp || 0,
        type: 'agent_message',
        agent: msg.agent,
        content: msg.content.slice(0, 200) + (msg.content.length > 200 ? '...' : ''),
        detail: msg.content.length > 200 ? msg.content : undefined,
        round: msg.round,
      });
    }

    // Sort by timestamp
    entries.sort((a, b) => a.timestamp - b.timestamp);

    return entries;
  }, [messages, streamEvents]);

  const filteredEntries = useMemo(() => {
    return timelineEntries.filter((entry) => {
      if (!filterTypes.has(entry.type)) return false;
      if (selectedAgent && entry.agent && entry.agent !== selectedAgent) return false;
      return true;
    });
  }, [timelineEntries, filterTypes, selectedAgent]);

  const toggleEntry = useCallback((id: string) => {
    setExpandedEntries((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const toggleFilter = useCallback((type: string) => {
    setFilterTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);

  const formatTime = useCallback((ts: number) => {
    if (!ts) return '--:--:--';
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }, []);

  return (
    <div className="bg-surface border border-[var(--accent)]/30">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
          {'>'} DEBATE TIMELINE ({filteredEntries.length} events)
        </span>
        <div className="flex items-center gap-2">
          {/* Agent filter */}
          <select
            value={selectedAgent || ''}
            onChange={(e) => setSelectedAgent(e.target.value || null)}
            className="text-[10px] font-theme-data bg-bg border border-border text-text-muted px-1 py-0.5"
          >
            <option value="">All Agents</option>
            {agents.map((agent) => (
              <option key={agent} value={agent}>
                {agent}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Type filters */}
      <div className="px-4 py-2 border-b border-border flex flex-wrap gap-1">
        {Array.from(TIMELINE_EVENT_TYPES).map((type) => (
          <button
            key={type}
            onClick={() => toggleFilter(type)}
            className={`px-1.5 py-0.5 text-[10px] font-theme-data border transition-colors ${
              filterTypes.has(type)
                ? `${EVENT_COLORS[type] || 'text-text-muted border-border'} bg-surface`
                : 'text-text-muted/50 border-border/50 bg-bg'
            }`}
          >
            {EVENT_LABELS[type] || type}
          </button>
        ))}
      </div>

      {/* Timeline entries */}
      <div className="p-4 space-y-0 max-h-[600px] overflow-y-auto">
        {filteredEntries.length === 0 ? (
          <div className="text-center text-text-muted text-xs font-theme-data py-8">
            No timeline events to display
          </div>
        ) : (
          filteredEntries.map((entry, idx) => {
            const colors = entry.agent ? getAgentColors(entry.agent) : null;
            const eventColor = EVENT_COLORS[entry.type] || 'text-text-muted border-border';
            const isExpanded = expandedEntries.has(entry.id);

            return (
              <div key={entry.id} className="flex gap-3 group">
                {/* Timeline line */}
                <div className="flex flex-col items-center">
                  <div
                    className={`w-2 h-2 rounded-full border ${eventColor} bg-bg shrink-0 mt-1.5`}
                  />
                  {idx < filteredEntries.length - 1 && (
                    <div className="w-px flex-1 bg-border min-h-[16px]" />
                  )}
                </div>

                {/* Entry content */}
                <div
                  className="flex-1 pb-3 cursor-pointer"
                  onClick={() => (entry.detail ? toggleEntry(entry.id) : undefined)}
                >
                  <div className="flex items-center gap-2 text-[10px] font-theme-data">
                    <span className="text-text-muted">{formatTime(entry.timestamp)}</span>
                    <span className={eventColor.split(' ')[0]}>
                      [{EVENT_LABELS[entry.type] || entry.type.toUpperCase()}]
                    </span>
                    {entry.agent && colors && (
                      <span className={`${colors.text}`}>{entry.agent}</span>
                    )}
                    {entry.round !== undefined && (
                      <span className="text-text-muted">R{entry.round}</span>
                    )}
                  </div>
                  <div className="text-xs text-text font-theme-data mt-0.5">{entry.content}</div>
                  {isExpanded && entry.detail && (
                    <div className="text-xs text-text-muted font-theme-data mt-1 pl-2 border-l border-border whitespace-pre-wrap">
                      {entry.detail}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
