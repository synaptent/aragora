'use client';

import { memo } from 'react';

export interface BeliefMeterProps {
  confidence: number; // 0-1
  size?: 'sm' | 'md';
}

export const BeliefMeter = memo(function BeliefMeter({
  confidence,
  size = 'sm',
}: BeliefMeterProps) {
  const percent = Math.round(confidence * 100);
  const color =
    confidence >= 0.7 ? 'bg-emerald-400' : confidence >= 0.4 ? 'bg-amber-400' : 'bg-red-400';
  const textColor =
    confidence >= 0.7 ? 'text-emerald-400' : confidence >= 0.4 ? 'text-amber-400' : 'text-red-400';

  const barHeight = size === 'sm' ? 'h-1' : 'h-1.5';
  const barWidth = size === 'sm' ? 'w-12' : 'w-16';
  const fontSize = size === 'sm' ? 'text-[9px]' : 'text-[10px]';

  return (
    <div
      className="flex items-center gap-1"
      data-testid="belief-meter"
      title={`Confidence: ${percent}%`}
    >
      <div className={`${barWidth} ${barHeight} bg-[var(--border)] rounded-full overflow-hidden`}>
        <div
          className={`h-full ${color} rounded-full transition-all duration-300`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className={`${fontSize} font-theme-data ${textColor}`}>{percent}%</span>
    </div>
  );
});

export default BeliefMeter;
