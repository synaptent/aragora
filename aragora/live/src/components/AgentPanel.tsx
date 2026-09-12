'use client';

import { useState, useEffect, useRef, useMemo, memo } from 'react';
import type { StreamEvent } from '@/types/events';
import { isAgentMessage } from '@/types/events';
import { getAgentColors } from '@/utils/agentColors';

interface AgentPanelProps {
  events: StreamEvent[];
}

// Terminal-style role indicators
const ROLE_ICONS: Record<string, string> = {
  proposer: '[P]',
  critic: '[C]',
  synthesizer: '[S]',
  judge: '[J]',
  reviewer: '[R]',
  implementer: '[I]',
  default: '[>]',
};

export function AgentPanel({ events }: AgentPanelProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Memoize agent message contents for deduplication
  const agentMessageContents = useMemo(() => {
    return new Set(
      events.filter(isAgentMessage).map((e) => {
        const content = e.data.content || '';
        // Normalize: first 2000 chars, lowercase, trimmed for better deduplication accuracy
        return content.slice(0, 2000).toLowerCase().trim();
      }),
    );
  }, [events]);

  // Memoize filtered agent events to avoid recalculating on every render
  const agentEvents = useMemo(() => {
    return events.filter((e) => {
      // Always include these primary event types
      if (
        e.type === 'agent_message' ||
        e.type === 'critique' ||
        e.type === 'consensus' ||
        e.type === 'vote'
      ) {
        return true;
      }
      // For log_message, filter out duplicates more aggressively
      if (e.type === 'log_message') {
        const msg = (e.data?.message as string) || '';

        // Skip log messages that look like arena message summaries
        if (msg.match(/^\s*\[(proposer|critic|synthesizer|judge|reviewer|implementer)\]/i)) {
          return false;
        }
        // Skip vote/critique/consensus summaries (have dedicated events)
        if (msg.match(/^\s*\[(vote|critique|consensus)\]/i)) {
          return false;
        }
        // Skip round markers (redundant with agent_message)
        if (msg.match(/^\s*Round \d+:/i)) {
          return false;
        }
        // Skip agent-attributed log messages that duplicate agent_message content
        const normalizedMsg = msg.slice(0, 2000).toLowerCase().trim();
        if (agentMessageContents.has(normalizedMsg)) {
          return false;
        }
        // Skip if log message starts with agent name (likely duplicate)
        if (msg.match(/^\s*(gemini|claude|codex|grok)[-\w]*\s*:/i)) {
          return false;
        }
        return true;
      }
      return false;
    });
  }, [events, agentMessageContents]);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [agentEvents.length, autoScroll]);

  // Handle scroll to detect if user has scrolled up
  const handleScroll = () => {
    if (scrollRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
      setAutoScroll(isAtBottom);
    }
  };

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const expandAll = () => {
    const allIds = agentEvents.map((_, i) => `event-${i}`);
    setExpandedIds(new Set(allIds));
  };

  const collapseAll = () => {
    setExpandedIds(new Set());
  };

  return (
    <div className="bg-surface border border-[var(--accent)]/30 flex flex-col h-full font-theme-data">
      {/* Terminal-style header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--accent)]/20 bg-bg/50">
        <div className="flex items-center gap-2">
          <span className="text-[var(--accent)]">[</span>
          <span className="text-xs text-[var(--accent)] uppercase tracking-wider">
            AGENT_STREAM
          </span>
          <span className="text-[var(--accent)]">]</span>
          <span className="text-text-muted text-xs">
            {'// '}
            {agentEvents.length} events
          </span>
        </div>
        <div className="flex gap-1">
          <button
            onClick={expandAll}
            aria-label="Expand all events"
            className="text-xs text-text-muted hover:text-[var(--accent)] px-2 py-0.5 border border-transparent hover:border-[var(--accent)]/30 transition-colors"
          >
            [+ALL]
          </button>
          <button
            onClick={collapseAll}
            aria-label="Collapse all events"
            className="text-xs text-text-muted hover:text-[var(--accent)] px-2 py-0.5 border border-transparent hover:border-[var(--accent)]/30 transition-colors"
          >
            [-ALL]
          </button>
        </div>
      </div>
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto p-3 space-y-2">
        {agentEvents.length === 0 ? (
          <div className="text-center text-text-muted py-8 font-theme-data text-sm">
            <span className="text-[var(--accent)] animate-pulse">{'>'}</span> Awaiting agent
            activity...
          </div>
        ) : (
          agentEvents.map((event, index) => (
            <EventCard
              key={`event-${index}`}
              id={`event-${index}`}
              event={event}
              isExpanded={expandedIds.has(`event-${index}`)}
              onToggle={toggleExpand}
            />
          ))
        )}
      </div>
      {!autoScroll && agentEvents.length > 0 && (
        <button
          onClick={() => {
            setAutoScroll(true);
            if (scrollRef.current) {
              scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
            }
          }}
          aria-label="Scroll to new messages"
          className="absolute bottom-4 right-4 bg-[var(--accent)] text-bg px-3 py-1 text-xs font-theme-data shadow-glow"
        >
          [NEW MESSAGES]
        </button>
      )}
    </div>
  );
}

interface EventCardProps {
  id: string;
  event: StreamEvent;
  isExpanded: boolean;
  onToggle: (id: string) => void;
}

const EventCard = memo(function EventCard({ id, event, isExpanded, onToggle }: EventCardProps) {
  const agentName = event.agent || 'system';
  const colors = getAgentColors(agentName);
  const timestamp = new Date(event.timestamp * 1000).toLocaleTimeString();

  // Get content based on event type
  let content = '';
  let preview = '';
  let role = '';
  let icon = ROLE_ICONS.default;

  switch (event.type) {
    case 'agent_message':
      content = event.data.content as string;
      role = event.data.role as string;
      icon = ROLE_ICONS[role] || ROLE_ICONS.default;
      // Show full content in preview (no truncation for better visibility)
      preview = content;
      break;
    case 'critique':
      const issues = event.data.issues as string[];
      const severity = event.data.severity as number;
      const target = event.data.target as string;
      const critiqueContent = event.data.content as string;
      // Use full content if available, otherwise format issues
      content =
        critiqueContent ||
        `Issues with ${target}:\n${issues.map((i) => `• ${i}`).join('\n')}\n\nSeverity: ${severity.toFixed(1)}`;
      preview = `→ ${target}: ${issues.length} issues (severity ${severity.toFixed(1)})`;
      icon = '🔍';
      role = 'critic';
      break;
    case 'consensus':
      const reached = event.data.reached as boolean;
      const confidence = event.data.confidence as number;
      const answer = event.data.answer as string;
      content = answer;
      preview = `${reached ? '✓' : '✗'} Consensus ${reached ? 'reached' : 'not reached'} (${Math.round(confidence * 100)}%)`;
      icon = '⚖️';
      break;
    case 'vote':
      content = `Vote: ${event.data.vote} (confidence: ${event.data.confidence})`;
      preview = content;
      icon = '🗳️';
      break;
    case 'log_message':
      content = event.data.message as string;
      // Show full content in preview (no truncation for better visibility)
      preview = content;
      // Use agent-specific icons for attributed log messages
      icon = agentName !== 'system' ? ROLE_ICONS.default : '📝';
      break;
    default:
      content = JSON.stringify(event.data, null, 2);
      preview = event.type;
  }

  return (
    <div
      className={`${colors.bg} border ${colors.border} ${colors.glow} overflow-hidden transition-all`}
    >
      <button
        onClick={() => onToggle(id)}
        aria-expanded={isExpanded}
        aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${agentName} event details`}
        className="w-full text-left p-2 flex items-start gap-2 hover:bg-white/5 transition-colors"
      >
        {/* Terminal-style role icon */}
        <span className={`text-xs font-bold flex-shrink-0 ${colors.text}`}>{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className={`font-medium text-sm ${colors.text}`}>{agentName.toUpperCase()}</span>
            {event.round !== undefined && event.round > 0 && (
              <span className="text-[10px] text-text-muted border border-text-muted/30 px-1">
                R{event.round}
              </span>
            )}
            <span className="text-[10px] text-text-muted/70 ml-auto font-theme-data">
              {timestamp}
            </span>
          </div>
          <p className="agent-output text-text-muted text-xs whitespace-pre-wrap break-words line-clamp-4">
            {preview}
          </p>
        </div>
        <span className={`text-xs flex-shrink-0 ${colors.text}`}>{isExpanded ? '[-]' : '[+]'}</span>
      </button>
      {isExpanded && (
        <div className="px-2 pb-2 pt-0">
          <div className="agent-output bg-bg/80 border-l-2 border-[var(--accent)]/30 p-2 text-xs whitespace-pre-wrap break-words text-text">
            {content}
          </div>
        </div>
      )}
    </div>
  );
});
