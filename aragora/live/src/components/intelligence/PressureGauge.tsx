'use client';

interface PressureGaugeProps {
  pressure: number; // 0-1
  byTier?: Record<string, number>;
  recommendation?: string;
  loading?: boolean;
}

function pressureColor(p: number): string {
  if (p < 0.5) return '#39ff14'; // green
  if (p < 0.75) return '#ffff00'; // yellow
  return '#dc143c'; // red/crimson
}

function pressureLabel(p: number): string {
  if (p < 0.3) return 'LOW';
  if (p < 0.6) return 'MODERATE';
  if (p < 0.8) return 'HIGH';
  return 'CRITICAL';
}

export function PressureGauge({
  pressure,
  byTier,
  recommendation,
  loading = false,
}: PressureGaugeProps) {
  if (loading) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">{'>'} MEMORY PRESSURE</h3>
        <div className="animate-pulse flex flex-col items-center">
          <div className="w-32 h-32 rounded-full bg-surface" />
          <div className="h-4 bg-surface rounded w-1/2 mt-4" />
        </div>
      </div>
    );
  }

  const clamped = Math.max(0, Math.min(1, pressure));
  const pct = Math.round(clamped * 100);
  const color = pressureColor(clamped);
  const label = pressureLabel(clamped);

  // SVG arc parameters
  const size = 140;
  const strokeWidth = 12;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  // Arc goes from 135deg to 405deg (270deg sweep)
  const sweepAngle = 270;
  const arcLength = (sweepAngle / 360) * circumference;
  const filledLength = arcLength * clamped;
  const _dashOffset = arcLength - filledLength;

  return (
    <div className="card p-4">
      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">{'>'} MEMORY PRESSURE</h3>

      <div className="flex flex-col items-center">
        {/* SVG Gauge */}
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="mb-3">
          {/* Background arc */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            strokeDasharray={`${arcLength} ${circumference}`}
            strokeDashoffset={0}
            strokeLinecap="round"
            className="text-surface"
            transform={`rotate(135 ${size / 2} ${size / 2})`}
          />
          {/* Filled arc */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeDasharray={`${filledLength} ${circumference}`}
            strokeDashoffset={0}
            strokeLinecap="round"
            transform={`rotate(135 ${size / 2} ${size / 2})`}
            style={{ transition: 'stroke-dasharray 0.5s ease, stroke 0.5s ease' }}
          />
          {/* Center text */}
          <text
            x={size / 2}
            y={size / 2 - 6}
            textAnchor="middle"
            dominantBaseline="central"
            fill={color}
            className="font-theme-data"
            fontSize="28"
            fontWeight="bold"
          >
            {pct}%
          </text>
          <text
            x={size / 2}
            y={size / 2 + 18}
            textAnchor="middle"
            dominantBaseline="central"
            fill={color}
            className="font-theme-data"
            fontSize="10"
            opacity={0.8}
          >
            {label}
          </text>
        </svg>

        {/* Per-tier breakdown */}
        {byTier && Object.keys(byTier).length > 0 && (
          <div className="w-full grid grid-cols-2 gap-2 mb-3">
            {Object.entries(byTier).map(([tier, value]) => (
              <div key={tier} className="flex justify-between text-xs font-theme-data px-2">
                <span className="text-text-muted uppercase">{tier}</span>
                <span className="text-text">{Math.round(value * 100)}%</span>
              </div>
            ))}
          </div>
        )}

        {/* Recommendation */}
        {recommendation && (
          <div className="w-full border-t border-[var(--accent)]/10 pt-3 mt-1">
            <p className="text-text-muted text-xs font-theme-data text-center">{recommendation}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default PressureGauge;
