'use client';

export interface CalibrationData {
  brier_score: number;
  ece: number;
  trust_tier: 'excellent' | 'good' | 'moderate' | 'poor' | 'unrated';
  prediction_count: number;
}

interface TrustBadgeProps {
  calibration?: CalibrationData | null;
  size?: 'sm' | 'md' | 'lg';
}

const TIER_CONFIG: Record<
  CalibrationData['trust_tier'],
  { color: string; bg: string; label: string }
> = {
  excellent: { color: 'text-green-400', bg: 'bg-green-400', label: 'Excellent' },
  good: { color: 'text-[var(--acid-cyan)]', bg: 'bg-cyan-400', label: 'Good' },
  moderate: { color: 'text-yellow-400', bg: 'bg-yellow-400', label: 'Moderate' },
  poor: { color: 'text-red-400', bg: 'bg-red-400', label: 'Poor' },
  unrated: { color: 'text-gray-500', bg: 'bg-gray-500', label: 'Unrated' },
};

export function TrustBadge({ calibration, size = 'md' }: TrustBadgeProps) {
  if (!calibration) return null;

  const tier = TIER_CONFIG[calibration.trust_tier] ?? TIER_CONFIG.unrated;

  const tooltip = [
    `Brier: ${calibration.brier_score.toFixed(3)}`,
    `ECE: ${calibration.ece.toFixed(3)}`,
    `${calibration.prediction_count} predictions`,
  ].join(' | ');

  const dot = <span className={`inline-block w-2 h-2 rounded-full ${tier.bg}`} />;

  if (size === 'sm') {
    return (
      <span className="inline-flex items-center" title={tooltip}>
        {dot}
      </span>
    );
  }

  if (size === 'lg') {
    return (
      <span
        className={`inline-flex items-center gap-1.5 font-theme-data text-xs ${tier.color}`}
        title={tooltip}
      >
        {dot}
        <span>{tier.label}</span>
        <span className="text-text-muted">{calibration.brier_score.toFixed(2)}</span>
      </span>
    );
  }

  // md (default)
  return (
    <span
      className={`inline-flex items-center gap-1.5 font-theme-data text-xs ${tier.color}`}
      title={tooltip}
    >
      {dot}
      <span>{tier.label}</span>
    </span>
  );
}
