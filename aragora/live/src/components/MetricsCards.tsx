'use client';

import type { NomicState, StreamEvent } from '@/types/events';

interface MetricsCardsProps {
  nomicState: NomicState | null;
  events: StreamEvent[];
}

export function MetricsCards({ nomicState, events }: MetricsCardsProps) {
  // Calculate metrics from state and events
  const cycle = nomicState?.cycle || 0;
  const phase = nomicState?.phase || 'idle';
  const completedTasks = nomicState?.completed_tasks || 0;
  const totalTasks = nomicState?.total_tasks || 0;

  // Calculate consensus from events
  const consensusEvents = events.filter((e) => e.type === 'consensus');
  const lastConsensus = consensusEvents[consensusEvents.length - 1];
  const lastConsensusData = lastConsensus?.data as Record<string, unknown> | undefined;
  const confidence = lastConsensusData?.confidence
    ? Math.round((lastConsensusData.confidence as number) * 100)
    : null;

  // Calculate duration from cycle events
  const cycleStartEvent = events.find((e) => {
    if (e.type !== 'cycle_start') return false;
    const eventData = e.data as Record<string, unknown>;
    return eventData.cycle === cycle;
  });
  const duration = cycleStartEvent
    ? Math.round((Date.now() / 1000 - cycleStartEvent.timestamp) / 60)
    : 0;

  return (
    <div className="card p-4">
      <h2 className="text-sm font-medium text-text-muted uppercase tracking-wider mb-3">Metrics</h2>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <MetricCard label="Cycle" value={cycle > 0 ? `${cycle}/3` : '-'} color="accent" />
        <MetricCard
          label="Phase"
          value={phase.charAt(0).toUpperCase() + phase.slice(1)}
          color={phase === 'idle' ? 'text-muted' : 'accent'}
        />
        <MetricCard
          label="Tasks"
          value={totalTasks > 0 ? `${completedTasks}/${totalTasks}` : '-'}
          color={completedTasks === totalTasks && totalTasks > 0 ? 'success' : 'accent'}
        />
        <MetricCard
          label="Consensus"
          value={confidence !== null ? `${confidence}%` : '-'}
          color={confidence !== null && confidence >= 70 ? 'success' : 'warning'}
        />
        <MetricCard
          label="Duration"
          value={duration > 0 ? `${duration}m` : '-'}
          color="text-muted"
        />
        <MetricCard
          label="Status"
          value={nomicState?.last_success === false ? 'Failed' : 'OK'}
          color={nomicState?.last_success === false ? 'warning' : 'success'}
        />
      </div>
    </div>
  );
}

interface MetricCardProps {
  label: string;
  value: string;
  color: string;
}

function MetricCard({ label, value, color }: MetricCardProps) {
  const colorClasses: Record<string, string> = {
    accent: 'text-accent',
    success: 'text-success',
    warning: 'text-warning',
    'text-muted': 'text-text-muted',
    purple: 'text-purple',
    gold: 'text-gold',
  };

  return (
    <div className="text-center">
      <div className="text-xs text-text-muted uppercase tracking-wide mb-1">{label}</div>
      <div className={`text-xl font-semibold ${colorClasses[color] || 'text-text'}`}>{value}</div>
    </div>
  );
}
