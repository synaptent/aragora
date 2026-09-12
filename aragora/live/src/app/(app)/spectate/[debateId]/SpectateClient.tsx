'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { WS_URL } from '@/config';
import { ThemeEffects } from '@/components/ThemeEffects';
import { useRightSidebar } from '@/context/RightSidebarContext';
import { TimelineView } from '@/components/spectate/TimelineView';
import { SummaryView } from '@/components/spectate/SummaryView';
import {
  useSpectateStore,
  EVENT_STYLES,
  selectFilteredEvents,
  type SpectatorEvent,
  type SpectatorEventType,
} from '@/store/spectateStore';

type SpectateViewMode = 'feed' | 'timeline' | 'summary';

export default function SpectateClient() {
  const params = useParams();
  const debateId = params.debateId as string;

  const eventListRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [viewMode, setViewMode] = useState<SpectateViewMode>('feed');

  // Store state
  const {
    connectionStatus,
    error,
    task,
    agents,
    currentRound,
    events,
    autoScroll,
    showTimestamps,
    connect,
    setConnectionStatus,
    setError,
    addEvent,
    setTask,
    setAutoScroll,
    setShowTimestamps,
    reset,
  } = useSpectateStore();

  const filteredEvents = useSpectateStore(selectFilteredEvents);

  const { setContext, clearContext } = useRightSidebar();

  // Connect to WebSocket
  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    connect(debateId);

    const wsUrl = WS_URL.replace(/\/ws$/, '');
    const ws = new WebSocket(`${wsUrl}/spectate/${debateId}`);

    ws.onopen = () => {
      setConnectionStatus('connected');
      setError(null);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // Handle different message types
        if (data.type === 'metadata') {
          if (data.task) setTask(data.task);
        } else {
          // It's a spectator event
          addEvent({
            type: data.type as SpectatorEventType,
            timestamp: data.timestamp || Date.now() / 1000,
            agent: data.agent || null,
            details: data.details || null,
            metric: data.metric ?? null,
            round: data.round ?? null,
          });
        }
      } catch (err) {
        console.error('Failed to parse spectator event:', err);
      }
    };

    ws.onerror = () => {
      setError('Connection error. The debate may have ended.');
      setConnectionStatus('error');
    };

    ws.onclose = (event) => {
      if (event.code === 1000) {
        // Normal closure - debate ended
        setConnectionStatus('disconnected');
      } else {
        setError('Connection lost. Attempting to reconnect...');
        setConnectionStatus('error');
        // Try to reconnect after 3 seconds
        setTimeout(() => {
          if (wsRef.current?.readyState !== WebSocket.OPEN) {
            connectWebSocket();
          }
        }, 3000);
      }
    };

    wsRef.current = ws;
  }, [debateId, connect, setConnectionStatus, setError, setTask, addEvent]);

  // Initialize connection
  useEffect(() => {
    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000, 'Leaving spectate');
        wsRef.current = null;
      }
      reset();
    };
  }, [debateId, connectWebSocket, reset]);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (autoScroll && eventListRef.current) {
      eventListRef.current.scrollTop = eventListRef.current.scrollHeight;
    }
  }, [events, autoScroll]);

  // Set up right sidebar
  useEffect(() => {
    setContext({
      title: 'Spectating',
      subtitle: task ? task.slice(0, 30) + (task.length > 30 ? '...' : '') : 'Loading...',
      statsContent: (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Round</span>
            <span className="text-sm font-theme-data text-[var(--acid-green)]">{currentRound}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Events</span>
            <span className="text-sm font-theme-data text-[var(--acid-cyan)]">{events.length}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Agents</span>
            <span className="text-sm font-theme-data text-[var(--acid-cyan)]">{agents.length}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Status</span>
            <span
              className={`text-sm font-theme-data ${
                connectionStatus === 'connected'
                  ? 'text-success'
                  : connectionStatus === 'error'
                    ? 'text-crimson'
                    : 'text-warning'
              }`}
            >
              {connectionStatus.toUpperCase()}
            </span>
          </div>
        </div>
      ),
      actionsContent: (
        <div className="space-y-2">
          <Link
            href="/spectate"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center btn-theme-secondary"
          >
            ← BACK TO LIST
          </Link>
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`block w-full px-3 py-2 text-xs font-theme-data text-center border transition-colors ${
              autoScroll
                ? 'bg-accent/10 text-accent border-accent/30'
                : 'bg-surface text-text-muted border-border'
            }`}
          >
            AUTO-SCROLL {autoScroll ? 'ON' : 'OFF'}
          </button>
          <button
            onClick={() => setShowTimestamps(!showTimestamps)}
            className={`block w-full px-3 py-2 text-xs font-theme-data text-center border transition-colors ${
              showTimestamps
                ? 'bg-acid-cyan/10 text-acid-cyan border-acid-cyan/30'
                : 'bg-surface text-text-muted border-border'
            }`}
          >
            TIMESTAMPS {showTimestamps ? 'ON' : 'OFF'}
          </button>
        </div>
      ),
    });

    return () => clearContext();
  }, [
    task,
    currentRound,
    events.length,
    agents.length,
    connectionStatus,
    autoScroll,
    showTimestamps,
    setContext,
    clearContext,
    setAutoScroll,
    setShowTimestamps,
  ]);

  // Format timestamp
  const formatTimestamp = (ts: number) => {
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  };

  return (
    <>
      <ThemeEffects opacity={0.02} />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="max-w-6xl mx-auto px-4 py-8">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <Link
                  href="/spectate"
                  className="text-text-muted hover:text-[var(--accent)] transition-colors"
                >
                  ← Back
                </Link>
                <div className="flex items-center gap-2">
                  {connectionStatus === 'connected' && (
                    <div className="w-3 h-3 bg-crimson rounded-full animate-pulse" />
                  )}
                  <h1 className="text-xl font-theme-data text-[var(--accent)]">SPECTATING</h1>
                </div>
              </div>

              {/* Connection Status Badge */}
              <div
                className={`px-3 py-1 text-xs font-theme-data border badge-theme ${
                  connectionStatus === 'connected'
                    ? 'bg-success/10 text-success border-success/30'
                    : connectionStatus === 'connecting'
                      ? 'bg-warning/10 text-warning border-warning/30'
                      : 'bg-crimson/10 text-crimson border-crimson/30'
                }`}
              >
                {connectionStatus.toUpperCase()}
              </div>
            </div>

            {/* Task */}
            {task && <p className="text-text-muted text-sm font-theme-data">{task}</p>}
          </div>

          {/* Error Banner */}
          {error && (
            <div className="mb-4 border border-warning/30 bg-warning/10 p-3">
              <p className="text-warning text-sm font-theme-data">{error}</p>
            </div>
          )}

          {/* Agents Bar */}
          {agents.length > 0 && (
            <div className="mb-4 flex flex-wrap gap-2">
              {agents.map((agent) => (
                <span
                  key={agent}
                  className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30"
                >
                  {agent}
                </span>
              ))}
              <span className="px-3 py-1 text-xs font-theme-data bg-surface text-text-muted border border-border">
                Round {currentRound}
              </span>
            </div>
          )}

          {/* View Mode Tabs */}
          <div className="card-theme overflow-hidden">
            <div className="flex items-center border-b border-border bg-surface-elevated/80">
              {/* Tab buttons */}
              <div className="flex">
                {(
                  [
                    { key: 'feed', label: 'FEED' },
                    { key: 'timeline', label: 'TIMELINE' },
                    { key: 'summary', label: 'SUMMARY' },
                  ] as const
                ).map((tab) => (
                  <button
                    key={tab.key}
                    onClick={() => setViewMode(tab.key)}
                    className={`px-4 py-2 text-xs font-theme-data transition-colors border-b-2 ${
                      viewMode === tab.key
                        ? 'text-[var(--accent)] border-[var(--accent)] bg-[var(--accent)]/5'
                        : 'text-text-muted border-transparent hover:text-text hover:bg-surface/50'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {/* Feed meta (only visible in feed mode) */}
              {viewMode === 'feed' && (
                <div className="ml-auto px-4 flex items-center gap-3">
                  <span className="text-xs font-theme-data text-[var(--accent)]">
                    {filteredEvents.length} events
                  </span>
                  <span className="text-xs font-theme-data text-text-muted">
                    {autoScroll ? 'Auto-scrolling' : 'Scroll paused'}
                  </span>
                </div>
              )}
            </div>

            {/* Feed View */}
            {viewMode === 'feed' && (
              <div
                ref={eventListRef}
                className="h-[500px] overflow-y-auto p-4 space-y-2 font-theme-data text-sm"
                onScroll={(e) => {
                  const target = e.target as HTMLDivElement;
                  const atBottom =
                    target.scrollHeight - target.scrollTop <= target.clientHeight + 50;
                  if (!atBottom && autoScroll) {
                    setAutoScroll(false);
                  }
                }}
              >
                {filteredEvents.length === 0 ? (
                  <div className="flex items-center justify-center h-full">
                    <div className="text-center text-text-muted">
                      <div className="w-8 h-8 border-2 border-accent/30 border-t-accent rounded-full animate-spin mx-auto mb-4" />
                      <p>Waiting for events...</p>
                    </div>
                  </div>
                ) : (
                  filteredEvents.map((event, index) => (
                    <EventLine
                      key={`${event.timestamp}-${index}`}
                      event={event}
                      showTimestamp={showTimestamps}
                      formatTimestamp={formatTimestamp}
                    />
                  ))
                )}
              </div>
            )}

            {/* Timeline View */}
            {viewMode === 'timeline' && (
              <div className="h-[500px] overflow-y-auto">
                <TimelineView />
              </div>
            )}

            {/* Summary View */}
            {viewMode === 'summary' && (
              <div className="h-[500px] overflow-y-auto">
                <SummaryView />
              </div>
            )}
          </div>

          {/* Legend */}
          <div className="mt-4 card-theme-info p-4">
            <h3 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3">EVENT TYPES</h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-2">
              {Object.entries(EVENT_STYLES).map(([type, style]) => (
                <div key={type} className="flex items-center gap-2 text-xs font-theme-data">
                  <span>{style.icon}</span>
                  <span className={style.color}>{style.label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

// Event Line Component
function EventLine({
  event,
  showTimestamp,
  formatTimestamp,
}: {
  event: SpectatorEvent;
  showTimestamp: boolean;
  formatTimestamp: (ts: number) => string;
}) {
  const style = EVENT_STYLES[event.type] || {
    icon: '•',
    color: 'text-text-muted',
    label: 'UNKNOWN',
  };

  return (
    <div className="flex items-start gap-2 py-1 hover:bg-[var(--accent)]/5 px-2 -mx-2 rounded">
      {/* Timestamp */}
      {showTimestamp && (
        <span className="text-text-muted/50 text-xs shrink-0 w-20">
          [{formatTimestamp(event.timestamp)}]
        </span>
      )}

      {/* Round */}
      {event.round !== null && (
        <span className="text-[var(--acid-cyan)]/70 text-xs shrink-0">R{event.round}</span>
      )}

      {/* Icon */}
      <span className="shrink-0">{style.icon}</span>

      {/* Agent */}
      {event.agent && (
        <span className="text-[var(--accent)] font-bold shrink-0">{event.agent}</span>
      )}

      {/* Details */}
      {event.details && <span className="text-text truncate">{event.details}</span>}

      {/* Metric */}
      {event.metric !== null && (
        <span className="text-text-muted text-xs shrink-0">({event.metric.toFixed(2)})</span>
      )}
    </div>
  );
}
