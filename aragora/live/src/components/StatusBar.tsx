'use client';

import { useState, useEffect } from 'react';
import type { StreamEvent } from '@/types/events';

interface StatusBarProps {
  connected: boolean;
  events: StreamEvent[];
  cycle?: number;
  phase?: string;
}

export function StatusBar({ connected, events, cycle = 0, phase = 'idle' }: StatusBarProps) {
  const [time, setTime] = useState('');
  const [uptime, setUptime] = useState(0);

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString('en-US', { hour12: false }));
    };

    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      setUptime((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const formatUptime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  // Get last event type
  const lastEvent = events.length > 0 ? events[events.length - 1] : null;
  const lastEventType = lastEvent?.type || 'none';

  // Phase indicator
  const phaseColors: Record<string, string> = {
    idle: 'text-text-muted',
    debate: 'text-[var(--accent)]',
    evolution: 'text-[var(--acid-cyan)]',
    judgment: 'text-purple',
    execution: 'text-gold',
  };

  return (
    <div className="bg-surface border-t border-[var(--accent)]/30 text-xs font-theme-data">
      <div className="container mx-auto px-4 py-1.5 flex items-center justify-between gap-4">
        {/* Left section */}
        <div className="flex items-center gap-4">
          {/* Connection status */}
          <div className="flex items-center gap-1.5">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                connected ? 'bg-[var(--accent)] animate-pulse' : 'bg-[var(--crimson)]'
              }`}
            />
            <span className={connected ? 'text-[var(--accent)]' : 'text-[var(--crimson)]'}>
              {connected ? 'ONLINE' : 'OFFLINE'}
            </span>
          </div>

          {/* Separator */}
          <span className="text-border">|</span>

          {/* Phase */}
          <div className="flex items-center gap-1.5">
            <span className="text-text-muted">PHASE:</span>
            <span className={phaseColors[phase] || 'text-text'}>{phase.toUpperCase()}</span>
          </div>

          {/* Separator */}
          <span className="text-border">|</span>

          {/* Cycle */}
          <div className="flex items-center gap-1.5">
            <span className="text-text-muted">CYCLE:</span>
            <span className="text-[var(--acid-cyan)]">{cycle}</span>
          </div>
        </div>

        {/* Center section - Last event */}
        <div className="hidden md:flex items-center gap-1.5">
          <span className="text-text-muted">LAST:</span>
          <span className="text-[var(--acid-yellow)] truncate max-w-[200px]">
            {lastEventType.replace(/_/g, ' ').toUpperCase()}
          </span>
        </div>

        {/* Right section */}
        <div className="flex items-center gap-4">
          {/* Events count */}
          <div className="flex items-center gap-1.5">
            <span className="text-text-muted">EVENTS:</span>
            <span className="text-[var(--accent)]">{events.length}</span>
          </div>

          {/* Separator */}
          <span className="text-border">|</span>

          {/* Uptime */}
          <div className="flex items-center gap-1.5">
            <span className="text-text-muted">UP:</span>
            <span className="text-[var(--acid-cyan)]">{formatUptime(uptime)}</span>
          </div>

          {/* Separator */}
          <span className="text-border">|</span>

          {/* Time */}
          <div className="text-[var(--accent)]">{time}</div>
        </div>
      </div>
    </div>
  );
}

// Mini status for header integration
export function StatusPill({ connected, phase }: { connected: boolean; phase: string }) {
  return (
    <div className="flex items-center gap-2 px-2 py-0.5 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-xs">
      <span
        className={`w-1.5 h-1.5 rounded-full ${
          connected ? 'bg-[var(--accent)] animate-pulse' : 'bg-[var(--crimson)]'
        }`}
      />
      <span className={connected ? 'text-[var(--accent)]' : 'text-[var(--crimson)]'}>
        {phase.toUpperCase()}
      </span>
    </div>
  );
}
