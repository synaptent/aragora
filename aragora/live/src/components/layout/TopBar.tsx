'use client';

import React from 'react';
import Link from 'next/link';
import { Logo } from '@/components/Logo';
import { useLayout } from '@/context/LayoutContext';
import { useCommandPalette } from '@/context/CommandPaletteContext';
import { useAuth } from '@/context/AuthContext';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BudgetBadge } from '@/components/layout/BudgetBadge';
import { GlobalConnectionStatus } from '@/components/GlobalConnectionStatus';

export function TopBar() {
  const { isMobile, toggleLeftSidebar, toggleRightSidebar, rightSidebarOpen } = useLayout();
  const { open: openCommandPalette } = useCommandPalette();
  const { isAuthenticated, user, logout } = useAuth();

  return (
    <header className="fixed top-0 left-0 right-0 h-12 bg-[var(--surface)] border-b border-[var(--border)] z-50 flex items-center px-3 gap-3">
      {/* Left section: Logo (clickable to toggle sidebar) + Title */}
      <div className="flex items-center gap-2">
        {/* Aragora logo - toggles sidebar on click */}
        <Logo
          size="sm"
          pixelSize={32}
          onClick={toggleLeftSidebar}
          className="p-2 sm:p-1.5 hover:bg-[var(--surface-elevated)] rounded transition-colors"
        />

        {/* Title link */}
        <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <span className="text-[var(--acid-green)] font-theme-data font-bold text-lg tracking-tight">
            ARAGORA
          </span>
        </Link>
      </div>

      {/* Center section: Search */}
      <div className="flex-1 flex justify-center">
        <button
          onClick={openCommandPalette}
          className="flex items-center gap-2 px-3 py-1.5 bg-[var(--bg)]/50 border border-[var(--border)]/60 rounded-[var(--radius-sm)] hover:border-[var(--acid-green)]/40 hover:shadow-[0_0_8px_var(--accent-glow)] transition-all max-w-md w-full"
        >
          <span className="text-[var(--text-muted)] font-theme-data text-sm">⌘</span>
          <span className="text-[var(--text-muted)] text-sm flex-1 text-left">
            Search or command...
          </span>
          <kbd className="hidden sm:inline-block px-1.5 py-0.5 bg-[var(--surface-elevated)] border border-[var(--border)] rounded text-xs text-[var(--text-muted)] font-theme-data">
            ⌘K
          </kbd>
        </button>
      </div>

      {/* Right section: Actions */}
      <div className="flex items-center gap-2">
        {/* Right sidebar toggle (desktop only) */}
        {!isMobile && (
          <button
            onClick={toggleRightSidebar}
            className={`p-2 hover:bg-[var(--surface-elevated)] rounded transition-colors ${
              rightSidebarOpen ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'
            }`}
            aria-label="Toggle context panel"
            title={rightSidebarOpen ? 'Hide context panel' : 'Show context panel'}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            >
              <rect x="1" y="2" width="4" height="12" rx="1" />
              <line x1="7" y1="4" x2="15" y2="4" />
              <line x1="7" y1="8" x2="15" y2="8" />
              <line x1="7" y1="12" x2="15" y2="12" />
            </svg>
          </button>
        )}

        {/* Connection status indicator */}
        <GlobalConnectionStatus />

        {/* Budget usage indicator */}
        <BudgetBadge />

        {/* Visual divider */}
        <div className="hidden sm:block h-4 w-px bg-[var(--border)]" aria-hidden="true" />

        {/* Theme toggle */}
        <ThemeToggle />

        {/* Login/User menu */}
        {isAuthenticated ? (
          <div className="flex items-center gap-2">
            <span className="hidden sm:inline text-xs text-[var(--text-muted)] truncate max-w-[120px]">
              {user?.email || user?.name}
            </span>
            <button
              onClick={() => logout?.()}
              className="flex items-center gap-1.5 px-2 py-1 hover:bg-[var(--surface-elevated)] rounded transition-colors text-[var(--text-muted)] hover:text-[var(--acid-green)]"
              aria-label="Logout"
              title="Logout"
            >
              <span className="text-[var(--acid-green)] font-theme-data text-xs">●</span>
              <span className="hidden sm:inline font-theme-data text-xs">Logout</span>
            </button>
          </div>
        ) : (
          <Link
            href="/auth/login"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent)]/10 hover:bg-[var(--accent)]/20 border border-[var(--accent)]/30 rounded-md transition-colors"
            title="Login"
          >
            <span className="text-[var(--accent)] font-theme-data text-sm">→</span>
            <span className="text-[var(--accent)] text-xs font-medium hidden sm:inline">Login</span>
          </Link>
        )}
      </div>
    </header>
  );
}
