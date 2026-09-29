'use client';

export type BadgeVariant =
  'success' | 'warning' | 'error' | 'info' | 'neutral' | 'purple' | 'orange';

export interface StatusBadgeProps {
  label: string;
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  className?: string;
}

const variantColors: Record<BadgeVariant, string> = {
  success: 'bg-green-500/20 text-green-400 border-green-500/30',
  warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  error: 'bg-red-500/20 text-red-400 border-red-500/30',
  info: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  purple: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  orange: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  neutral: 'bg-surface text-text-muted border-border',
};

export function StatusBadge({
  label,
  variant = 'neutral',
  size = 'sm',
  className = '',
}: StatusBadgeProps) {
  const sizeClasses = size === 'sm' ? 'text-xs px-2 py-0.5' : 'text-sm px-3 py-1';

  return (
    <span className={`rounded border ${variantColors[variant]} ${sizeClasses} ${className}`}>
      {label}
    </span>
  );
}
