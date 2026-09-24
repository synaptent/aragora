'use client';

/**
 * FractalBreadcrumb - Breadcrumb trail for fractal DAG navigation.
 *
 * Shows the navigation path: Ideas > "Market Research" > Goals > "Increase retention" > Actions
 * Click any breadcrumb to jump to that level.
 */

import { memo, useCallback } from 'react';
import { PIPELINE_STAGE_CONFIG, STAGE_COLOR_CLASSES } from './types';
import type { NavigationLevel } from '../../hooks/useFractalNavigation';

interface FractalBreadcrumbProps {
  /** Full navigation stack from useFractalNavigation. */
  breadcrumbs: NavigationLevel[];
  /** Called when user clicks a breadcrumb to navigate. */
  onJumpTo: (index: number) => void;
}

export const FractalBreadcrumb = memo(function FractalBreadcrumb({
  breadcrumbs,
  onJumpTo,
}: FractalBreadcrumbProps) {
  if (breadcrumbs.length <= 1) return null;

  return (
    <nav className="flex items-center gap-1 px-3 py-1.5 bg-surface/90 border border-border rounded-lg text-xs overflow-x-auto">
      {breadcrumbs.map((level, index) => (
        <BreadcrumbItem
          key={`${level.stage}-${level.nodeId ?? 'root'}-${index}`}
          level={level}
          index={index}
          isLast={index === breadcrumbs.length - 1}
          onJumpTo={onJumpTo}
        />
      ))}
    </nav>
  );
});

// ---------------------------------------------------------------------------

interface BreadcrumbItemProps {
  level: NavigationLevel;
  index: number;
  isLast: boolean;
  onJumpTo: (index: number) => void;
}

const BreadcrumbItem = memo(function BreadcrumbItem({
  level,
  index,
  isLast,
  onJumpTo,
}: BreadcrumbItemProps) {
  const handleClick = useCallback(() => {
    if (!isLast) onJumpTo(index);
  }, [index, isLast, onJumpTo]);

  const stageColors = STAGE_COLOR_CLASSES[level.stage];
  const stageConfig = PIPELINE_STAGE_CONFIG[level.stage];

  return (
    <>
      <button
        onClick={handleClick}
        disabled={isLast}
        className={`
          inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-theme-data
          transition-colors whitespace-nowrap
          ${
            isLast
              ? `${stageColors.bg} ${stageColors.text} font-bold`
              : `text-text-muted hover:${stageColors.text} hover:${stageColors.bg}`
          }
        `}
      >
        {level.nodeId ? (
          <span className="truncate max-w-[120px]">{level.label}</span>
        ) : (
          <span>{stageConfig.label}</span>
        )}
      </button>
      {!isLast && <span className="text-text-muted select-none">/</span>}
    </>
  );
});

export default FractalBreadcrumb;
