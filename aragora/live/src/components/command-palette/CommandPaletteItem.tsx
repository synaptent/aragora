'use client';

import type { SearchResult, RecentItem, QuickAction } from './types';

interface CommandPaletteItemProps {
  item: SearchResult | RecentItem | QuickAction;
  isSelected: boolean;
  index: number;
  onSelect: () => void;
  onMouseEnter: () => void;
  showType?: boolean;
}

/**
 * Get display type label for result
 */
function getTypeLabel(item: SearchResult | RecentItem | QuickAction): string {
  if ('type' in item) {
    return item.type.toUpperCase();
  }
  return 'ACTION';
}

/**
 * Get icon for the item
 */
function getIcon(item: SearchResult | RecentItem | QuickAction): string {
  return item.icon || '>';
}

/**
 * Get title for the item
 */
function getTitle(item: SearchResult | RecentItem | QuickAction): string {
  if ('label' in item) {
    return item.label;
  }
  return item.title;
}

/**
 * Get subtitle for the item
 */
function getSubtitle(item: SearchResult | RecentItem | QuickAction): string | undefined {
  if ('description' in item) {
    return item.description;
  }
  if ('subtitle' in item) {
    return item.subtitle;
  }
  return undefined;
}

/**
 * CommandPaletteItem
 *
 * Individual result item in the command palette.
 * Handles keyboard and mouse selection.
 */
export function CommandPaletteItem({
  item,
  isSelected,
  index,
  onSelect,
  onMouseEnter,
  showType = true,
}: CommandPaletteItemProps) {
  const icon = getIcon(item);
  const title = getTitle(item);
  const subtitle = getSubtitle(item);
  const typeLabel = getTypeLabel(item);

  return (
    <li
      id={`command-palette-item-${index}`}
      role="option"
      aria-selected={isSelected}
      className={`
        flex items-center gap-3 px-4 py-2 cursor-pointer transition-colors
        ${
          isSelected
            ? 'bg-[var(--accent)]/10 border-l-2 border-[var(--accent)]'
            : 'border-l-2 border-transparent hover:bg-surface-elevated'
        }
      `}
      onClick={onSelect}
      onMouseEnter={onMouseEnter}
    >
      {/* Icon */}
      <span
        className={`
          font-theme-data text-sm w-6 text-center flex-shrink-0
          ${isSelected ? 'text-[var(--accent)]' : 'text-[var(--accent)]/70'}
        `}
      >
        {icon}
      </span>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div
          className={`
            font-theme-data text-sm truncate
            ${isSelected ? 'text-[var(--accent)]' : 'text-text'}
          `}
        >
          {title}
        </div>
        {subtitle && <div className="text-text-muted text-xs truncate">{subtitle}</div>}
      </div>

      {/* Type badge */}
      {showType && (
        <span className="text-text-muted text-xs font-theme-data uppercase flex-shrink-0">
          {typeLabel}
        </span>
      )}
    </li>
  );
}

export default CommandPaletteItem;
