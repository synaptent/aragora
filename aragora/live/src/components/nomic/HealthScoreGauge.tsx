'use client';

interface HealthScoreGaugeProps {
  score: number;
  label?: string;
}

export function HealthScoreGauge({ score, label = 'Health Score' }: HealthScoreGaugeProps) {
  const clamped = Math.max(0, Math.min(1, score));
  const size = 120;
  const strokeWidth = 10;
  const radius = (size - strokeWidth) / 2;
  const cx = size / 2;
  const cy = size / 2;

  // Arc from 135deg to 405deg (270deg sweep)
  const startAngle = 135;
  const sweepAngle = 270;
  const endAngle = startAngle + sweepAngle;
  const filledAngle = startAngle + sweepAngle * clamped;

  const toRad = (deg: number) => (deg * Math.PI) / 180;

  const arcPath = (from: number, to: number) => {
    const x1 = cx + radius * Math.cos(toRad(from));
    const y1 = cy + radius * Math.sin(toRad(from));
    const x2 = cx + radius * Math.cos(toRad(to));
    const y2 = cy + radius * Math.sin(toRad(to));
    const largeArc = to - from > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2}`;
  };

  const color = clamped >= 0.7 ? '#39FF14' : clamped >= 0.4 ? '#FFD700' : '#DC143C';

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* Background arc */}
        <path
          d={arcPath(startAngle, endAngle)}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          className="text-border"
        />
        {/* Filled arc */}
        {clamped > 0 && (
          <path
            d={arcPath(startAngle, filledAngle)}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
          />
        )}
        {/* Center text */}
        <text
          x={cx}
          y={cy - 2}
          textAnchor="middle"
          dominantBaseline="central"
          className="font-theme-data fill-text"
          fontSize="24"
          fontWeight="bold"
        >
          {(clamped * 100).toFixed(0)}
        </text>
        <text
          x={cx}
          y={cy + 18}
          textAnchor="middle"
          dominantBaseline="central"
          className="font-theme-data fill-text-muted"
          fontSize="10"
        >
          / 100
        </text>
      </svg>
      <span className="font-theme-data text-xs text-text-muted mt-1">{label}</span>
    </div>
  );
}
