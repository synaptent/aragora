'use client';

import type { ReactNode } from 'react';

export interface PanelContainerProps {
  children: ReactNode;
  className?: string;
  /** Use compact padding (0.75rem instead of 1rem) */
  compact?: boolean;
  /** Use accent border color */
  accent?: boolean;
}

/**
 * Standardized container for sidebar panels.
 * Provides consistent styling across all panels in both light and dark modes.
 *
 * @example
 * ```tsx
 * <PanelContainer>
 *   <PanelHeader title="My Panel" />
 *   <div className="panel-content">
 *     {content}
 *   </div>
 * </PanelContainer>
 * ```
 */
export function PanelContainer({
  children,
  className = '',
  compact = false,
  accent = false,
}: PanelContainerProps) {
  const baseClasses = 'panel';
  const sizeClass = compact ? 'panel-compact' : '';
  const accentClass = accent ? 'panel-accent' : '';

  return (
    <div className={`${baseClasses} ${sizeClass} ${accentClass} ${className}`.trim()}>
      {children}
    </div>
  );
}

export interface PanelHeaderSimpleProps {
  title: string;
  badge?: number | string;
  icon?: string;
  actions?: ReactNode;
  className?: string;
  /** Use smaller title style (uppercase, tracking) */
  small?: boolean;
}

/**
 * Simple panel header for consistent styling.
 * Use this when you don't need refresh/expand functionality.
 */
export function PanelHeaderSimple({
  title,
  badge,
  icon,
  actions,
  className = '',
  small = false,
}: PanelHeaderSimpleProps) {
  return (
    <div className={`panel-header ${className}`}>
      <div className="flex items-center gap-2">
        {icon && <span>{icon}</span>}
        <h3 className={small ? 'panel-title-sm' : 'panel-title'}>{title}</h3>
        {badge !== undefined && <span className="panel-badge">{badge}</span>}
      </div>
      {actions && <div className="panel-actions">{actions}</div>}
    </div>
  );
}

export interface CollapsiblePanelHeaderProps {
  title: string;
  isExpanded: boolean;
  onToggle: () => void;
  badge?: number | string;
  className?: string;
}

/**
 * Collapsible header for inline expand/collapse panels.
 * Used for panels that start collapsed and expand on click.
 */
export function CollapsiblePanelHeader({
  title,
  isExpanded,
  onToggle,
  badge,
  className = '',
}: CollapsiblePanelHeaderProps) {
  return (
    <div
      className={`panel-collapsible-header ${className}`}
      onClick={onToggle}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onToggle()}
    >
      <div className="flex items-center gap-2">
        <span className="text-[var(--accent)] text-xs">{'>'}</span>
        <span className="panel-title-sm">{title}</span>
        {badge !== undefined && <span className="panel-badge">{badge}</span>}
      </div>
      <span className="panel-toggle">{isExpanded ? '[COLLAPSE]' : '[EXPAND]'}</span>
    </div>
  );
}
