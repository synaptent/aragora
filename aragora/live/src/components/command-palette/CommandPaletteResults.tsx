'use client';

import { useRef, useEffect } from 'react';
import { CommandPaletteItem } from './CommandPaletteItem';
import type { SearchResult, RecentItem, QuickAction } from './types';

interface Section {
  id: string;
  title: string;
  items: (SearchResult | RecentItem | QuickAction)[];
}

interface CommandPaletteResultsProps {
  sections: Section[];
  selectedIndex: number;
  onSelect: (item: SearchResult | RecentItem | QuickAction, index: number) => void;
  onHover: (index: number) => void;
  isSearching: boolean;
  searchError: string | null;
  query: string;
}

/**
 * CommandPaletteResults
 *
 * Displays search results organized by sections with scrolling support.
 */
export function CommandPaletteResults({
  sections,
  selectedIndex,
  onSelect,
  onHover,
  isSearching,
  searchError,
  query,
}: CommandPaletteResultsProps) {
  const resultsRef = useRef<HTMLDivElement>(null);

  // Calculate total items for index tracking
  const allItems = sections.flatMap((s) => s.items);
  const totalItems = allItems.length;

  // Scroll selected item into view
  useEffect(() => {
    if (totalItems === 0) return;

    const selectedElement = document.getElementById(`command-palette-item-${selectedIndex}`);
    if (selectedElement && resultsRef.current) {
      const container = resultsRef.current;
      const elementTop = selectedElement.offsetTop;
      const elementBottom = elementTop + selectedElement.offsetHeight;
      const containerTop = container.scrollTop;
      const containerBottom = containerTop + container.clientHeight;

      if (elementTop < containerTop) {
        container.scrollTop = elementTop;
      } else if (elementBottom > containerBottom) {
        container.scrollTop = elementBottom - container.clientHeight;
      }
    }
  }, [selectedIndex, totalItems]);

  // Empty state
  if (totalItems === 0 && !isSearching) {
    return (
      <div className="px-4 py-8 text-center">
        {searchError ? (
          <div className="text-red-400 font-theme-data text-sm">
            <span className="text-red-500">!</span> {searchError}
          </div>
        ) : query.trim() ? (
          <div className="text-text-muted font-theme-data text-sm">
            No results found for &quot;{query}&quot;
          </div>
        ) : (
          <div className="text-text-muted font-theme-data text-sm">
            Type to search or use arrow keys
          </div>
        )}
      </div>
    );
  }

  // Loading state
  if (isSearching && totalItems === 0) {
    return (
      <div className="px-4 py-8 text-center">
        <div className="text-[var(--accent)] font-theme-data text-sm animate-pulse">
          Searching...
        </div>
      </div>
    );
  }

  // Track global index across sections
  let globalIndex = 0;

  return (
    <div ref={resultsRef} className="max-h-96 overflow-y-auto">
      {/* Live region for accessibility */}
      <div role="status" aria-live="polite" className="sr-only">
        {isSearching ? 'Searching...' : `${totalItems} results found`}
      </div>

      <ul id="command-palette-results" role="listbox" aria-label="Search results">
        {sections.map((section) => {
          if (section.items.length === 0) return null;

          const sectionStartIndex = globalIndex;

          return (
            <li key={section.id} role="group" aria-labelledby={`section-${section.id}`}>
              {/* Section header */}
              <div
                id={`section-${section.id}`}
                className="px-4 py-2 text-xs font-theme-data text-text-muted uppercase tracking-wider bg-surface/50 sticky top-0"
              >
                {section.title}
              </div>

              {/* Section items */}
              <ul role="group">
                {section.items.map((item, itemIndex) => {
                  const currentIndex = sectionStartIndex + itemIndex;
                  const isSelected = currentIndex === selectedIndex;

                  // Increment global index for next iteration
                  if (itemIndex === section.items.length - 1) {
                    globalIndex = currentIndex + 1;
                  }

                  return (
                    <CommandPaletteItem
                      key={`${section.id}-${item.id}`}
                      item={item}
                      isSelected={isSelected}
                      index={currentIndex}
                      onSelect={() => onSelect(item, currentIndex)}
                      onMouseEnter={() => onHover(currentIndex)}
                    />
                  );
                })}
              </ul>
            </li>
          );
        })}
      </ul>

      {/* Loading indicator when searching with existing results */}
      {isSearching && totalItems > 0 && (
        <div className="px-4 py-2 text-center text-[var(--accent)] font-theme-data text-xs animate-pulse border-t border-[var(--accent)]/10">
          Updating...
        </div>
      )}
    </div>
  );
}

export default CommandPaletteResults;
