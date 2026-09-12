'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';

interface WsEvent {
  id: number;
  type: string;
  data: unknown;
  timestamp: Date;
}

export function WebSocketViewer() {
  const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8765';
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [filter, setFilter] = useState('');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const wsRef = useRef<WebSocket | null>(null);
  const idRef = useRef(0);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [events]);

  const connect = useCallback(() => {
    if (wsRef.current) return;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
    };
    ws.onerror = () => {
      setConnected(false);
      wsRef.current = null;
    };
    ws.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data);
        const evt: WsEvent = {
          id: ++idRef.current,
          type: parsed.type || parsed.event || 'message',
          data: parsed,
          timestamp: new Date(),
        };
        setEvents((prev) => [...prev.slice(-499), evt]);
      } catch {
        const evt: WsEvent = {
          id: ++idRef.current,
          type: 'raw',
          data: msg.data,
          timestamp: new Date(),
        };
        setEvents((prev) => [...prev.slice(-499), evt]);
      }
    };

    wsRef.current = ws;
  }, [wsUrl]);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const toggleExpand = useCallback((id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const filtered = filter
    ? events.filter((e) => e.type.toLowerCase().includes(filter.toLowerCase()))
    : events;

  const EVENT_COLORS: Record<string, string> = {
    debate_start: 'text-emerald-400',
    debate_end: 'text-emerald-400',
    round_start: 'text-blue-400',
    agent_message: 'text-amber-400',
    critique: 'text-purple-400',
    vote: 'text-cyan-400',
    consensus: 'text-[var(--acid-green)]',
    error: 'text-red-400',
  };

  return (
    <div className="h-full flex flex-col bg-[var(--bg)]">
      {/* Controls */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border)] shrink-0">
        <button
          onClick={connected ? disconnect : connect}
          className={`px-3 py-1.5 text-xs font-theme-data font-bold transition-colors ${
            connected
              ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
              : 'bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80'
          }`}
        >
          {connected ? 'DISCONNECT' : 'CONNECT'}
        </button>
        <div className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-red-400'}`} />
        <code className="text-xs font-theme-data text-[var(--text-muted)] truncate flex-1">
          {wsUrl}
        </code>
        <input
          type="text"
          placeholder="Filter events..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-40 px-2 py-1 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)]"
        />
        <button
          onClick={() => setEvents([])}
          className="text-[10px] font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)]"
        >
          CLEAR
        </button>
      </div>

      {/* Event log */}
      <div ref={logRef} className="flex-1 overflow-y-auto font-theme-data">
        {filtered.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-xs text-[var(--text-muted)]">
              {connected ? 'Waiting for events...' : 'Connect to start receiving events.'}
            </p>
          </div>
        )}
        {filtered.map((evt) => (
          <div
            key={evt.id}
            className="border-b border-[var(--border)]/50 hover:bg-[var(--surface)]/30"
          >
            <button
              onClick={() => toggleExpand(evt.id)}
              className="w-full text-left px-4 py-1.5 flex items-center gap-3"
            >
              <span className="text-[10px] text-[var(--text-muted)] w-20 shrink-0">
                {evt.timestamp.toLocaleTimeString()}
              </span>
              <span
                className={`text-xs font-bold ${EVENT_COLORS[evt.type] || 'text-[var(--text-muted)]'}`}
              >
                {evt.type}
              </span>
              <span className="text-[10px] text-[var(--text-muted)] ml-auto">
                {expanded.has(evt.id) ? '[-]' : '[+]'}
              </span>
            </button>
            {expanded.has(evt.id) && (
              <pre className="px-4 pb-2 text-[10px] text-[var(--text-muted)] whitespace-pre-wrap max-h-40 overflow-y-auto">
                {typeof evt.data === 'string' ? evt.data : JSON.stringify(evt.data, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
