'use client';

import { useRef, useEffect } from 'react';
import type { StreamEvent, EventCategory } from '@/hooks/useEventStream';

interface LiveActivityFeedProps {
  events: StreamEvent[];
  onEventClick: (id: string) => void;
}

const CATEGORY_ICONS: Record<EventCategory, string> = {
  debate: '\u2694',
  execution: '\u25B6',
  knowledge: '\uD83D\uDCDA',
  memory: '\uD83D\uDCBE',
  verification: '\uD83D\uDD2C',
  gauntlet: '\uD83D\uDEE1',
  system: '\u2699',
};

const CATEGORY_COLORS: Record<EventCategory, string> = {
  debate: 'border-indigo-500/30 text-indigo-400',
  execution: 'border-emerald-500/30 text-emerald-400',
  knowledge: 'border-violet-500/30 text-violet-400',
  memory: 'border-cyan-500/30 text-cyan-400',
  verification: 'border-blue-500/30 text-blue-400',
  gauntlet: 'border-amber-500/30 text-amber-400',
  system: 'border-gray-500/30 text-gray-400',
};

const SEVERITY_RING: Record<string, string> = {
  error: 'ring-1 ring-red-500/50',
  warning: 'ring-1 ring-amber-500/50',
  success: 'ring-1 ring-emerald-500/50',
  info: '',
};

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function LiveActivityFeed({ events, onEventClick }: LiveActivityFeedProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft = scrollRef.current.scrollWidth;
    }
  }, [events.length]);

  if (events.length === 0) {
    return (
      <div className="h-12 border-t border-border bg-surface/50 flex items-center justify-center">
        <span className="text-xs font-theme-data text-text-muted">Waiting for events...</span>
      </div>
    );
  }

  return (
    <div className="border-t border-border bg-surface/50">
      <div
        ref={scrollRef}
        className="flex items-center gap-2 px-4 py-2 overflow-x-auto scrollbar-thin"
      >
        {events.slice(-50).map((event) => (
          <button
            key={event.id}
            onClick={() => onEventClick(event.id)}
            className={`flex-shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border bg-bg/50 hover:bg-bg transition-colors text-xs font-theme-data ${CATEGORY_COLORS[event.category]} ${SEVERITY_RING[event.severity]}`}
            title={event.summary}
          >
            <span>{CATEGORY_ICONS[event.category]}</span>
            <span className="max-w-[180px] truncate">{event.summary}</span>
            <span className="text-text-muted/50 text-[10px]">{formatTime(event.timestamp)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
