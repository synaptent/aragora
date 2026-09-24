'use client';

import React from 'react';
import { useLayout } from '@/context/LayoutContext';
import { useRightSidebar } from '@/context/RightSidebarContext';

export function RightSidebar() {
  const { rightSidebarOpen, isMobile, rightSidebarWidth, closeRightSidebar } = useLayout();
  const { title, subtitle, statsContent, propertiesContent, actionsContent, activityContent } =
    useRightSidebar();

  // Don't render on mobile or when closed
  if (isMobile || !rightSidebarOpen) {
    return null;
  }

  return (
    <aside
      className="fixed top-12 right-0 h-[calc(100vh-48px)] bg-[var(--surface)] border-l border-[var(--border)] z-30 transition-all duration-200 overflow-hidden"
      style={{ width: rightSidebarWidth }}
    >
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="p-4 border-b border-[var(--border)]">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-[var(--text)]">{title || 'Context'}</h2>
              {subtitle && <p className="text-xs text-[var(--text-muted)] mt-0.5">{subtitle}</p>}
            </div>
            <button
              onClick={closeRightSidebar}
              className="p-1 hover:bg-[var(--surface-elevated)] rounded transition-colors text-[var(--text-muted)]"
              title="Close panel"
            >
              <span className="font-theme-data">×</span>
            </button>
          </div>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto">
          {/* Stats section */}
          {statsContent && (
            <div className="p-4 border-b border-[var(--border)]">
              <h3 className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider mb-3">
                Stats
              </h3>
              {statsContent}
            </div>
          )}

          {/* Properties section */}
          {propertiesContent && (
            <div className="p-4 border-b border-[var(--border)]">
              <h3 className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider mb-3">
                Properties
              </h3>
              {propertiesContent}
            </div>
          )}

          {/* Actions section */}
          {actionsContent && (
            <div className="p-4 border-b border-[var(--border)]">
              <h3 className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider mb-3">
                Actions
              </h3>
              {actionsContent}
            </div>
          )}

          {/* Activity section */}
          {activityContent && (
            <div className="p-4">
              <h3 className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider mb-3">
                Activity
              </h3>
              {activityContent}
            </div>
          )}

          {/* Empty state */}
          {!statsContent && !propertiesContent && !actionsContent && !activityContent && (
            <div className="p-4 text-center text-[var(--text-muted)]">
              <p className="text-sm">No context available</p>
              <p className="text-xs mt-1">Select an item to see details</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
