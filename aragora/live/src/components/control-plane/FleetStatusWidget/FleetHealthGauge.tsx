'use client';

import { useMemo } from 'react';

export interface FleetHealthGaugeProps {
  /** Health percentage (0-100) */
  health: number;
  /** Size of the gauge in pixels */
  size?: number;
  /** Stroke width */
  strokeWidth?: number;
  /** Show percentage text */
  showLabel?: boolean;
  /** Optional className for the container */
  className?: string;
}

/**
 * Circular gauge component displaying fleet health percentage.
 * Uses acid-green/yellow/crimson based on health level.
 */
export function FleetHealthGauge({
  health,
  size = 80,
  strokeWidth = 6,
  showLabel = true,
  className = '',
}: FleetHealthGaugeProps) {
  const { color, bgColor, label } = useMemo(() => {
    if (health >= 80) {
      return { color: 'stroke-green-400', bgColor: 'stroke-green-900/30', label: 'Healthy' };
    }
    if (health >= 50) {
      return { color: 'stroke-yellow-400', bgColor: 'stroke-yellow-900/30', label: 'Degraded' };
    }
    return { color: 'stroke-crimson', bgColor: 'stroke-red-900/30', label: 'Critical' };
  }, [health]);

  // Calculate SVG parameters
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (health / 100) * circumference;
  const center = size / 2;

  return (
    <div className={`relative inline-flex flex-col items-center ${className}`}>
      <svg width={size} height={size} className="transform -rotate-90">
        {/* Background circle */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className={bgColor}
        />
        {/* Progress circle */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className={`${color} transition-all duration-500`}
        />
      </svg>

      {/* Center text */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-lg font-theme-data font-bold text-text">{Math.round(health)}%</span>
      </div>

      {/* Label below gauge */}
      {showLabel && <span className="mt-1 text-xs font-theme-data text-text-muted">{label}</span>}
    </div>
  );
}

export default FleetHealthGauge;
