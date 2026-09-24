'use client';

import { useRef, useState, useMemo, useCallback } from 'react';

interface VirtualListProps<T> {
  items: T[];
  height?: number;
  itemHeight: number;
  renderItem: (item: T, index: number) => React.ReactNode;
  className?: string;
  overscanCount?: number;
}

/**
 * Simple virtualized list that only renders visible items.
 * Uses CSS transforms for smooth scrolling.
 */
export function VirtualList<T>({
  items,
  height = 400,
  itemHeight,
  renderItem,
  className = '',
  overscanCount = 3,
}: VirtualListProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  // Calculate visible range
  const { startIndex, endIndex, offsetY } = useMemo(() => {
    const start = Math.max(0, Math.floor(scrollTop / itemHeight) - overscanCount);
    const visibleCount = Math.ceil(height / itemHeight);
    const end = Math.min(items.length - 1, start + visibleCount + overscanCount * 2);
    return { startIndex: start, endIndex: end, offsetY: start * itemHeight };
  }, [scrollTop, itemHeight, height, items.length, overscanCount]);

  // Use regular list for small item counts (virtualization overhead not worth it)
  if (items.length <= 15) {
    return (
      <div className={`overflow-y-auto ${className}`} style={{ maxHeight: height }}>
        {items.map((item, index) => (
          <div key={index}>{renderItem(item, index)}</div>
        ))}
      </div>
    );
  }

  const totalHeight = items.length * itemHeight;
  const visibleItems = items.slice(startIndex, endIndex + 1);

  return (
    <div
      ref={containerRef}
      className={`overflow-y-auto ${className}`}
      style={{ height, position: 'relative' }}
      onScroll={handleScroll}
    >
      {/* Spacer to maintain scroll height */}
      <div style={{ height: totalHeight, position: 'relative' }}>
        {/* Visible items positioned absolutely */}
        <div style={{ position: 'absolute', top: offsetY, left: 0, right: 0 }}>
          {visibleItems.map((item, i) => (
            <div key={startIndex + i} style={{ height: itemHeight }}>
              {renderItem(item, startIndex + i)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default VirtualList;
