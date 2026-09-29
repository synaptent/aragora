'use client';

import React from 'react';
import Link from 'next/link';
import { useLayout } from '@/context/LayoutContext';
import { useProgressiveMode, type ProgressiveMode } from '@/context/ProgressiveModeContext';
import { TopBar } from './TopBar';
import { LeftSidebar } from './LeftSidebar';
import { RightSidebar } from './RightSidebar';
import { Breadcrumbs } from '@/components/ui/Breadcrumbs';

interface AppShellProps {
  children: React.ReactNode;
}

type QuickLink = {
  label: string;
  href: string;
  external?: boolean;
  accent?: boolean;
  minMode: ProgressiveMode;
};

const QUICK_LINKS: QuickLink[] = [
  { label: 'DEBATE', href: '/arena', minMode: 'simple' },
  { label: 'DEBATES', href: '/debates', minMode: 'simple' },
  { label: 'AGENTS', href: '/agents', minMode: 'simple' },
  { label: 'KNOWLEDGE', href: '/knowledge', minMode: 'simple' },
  { label: 'ANALYTICS', href: '/analytics', minMode: 'standard' },
  { label: 'DOCS', href: '/documents', minMode: 'standard' },
  { label: 'TEMPLATES', href: '/templates', minMode: 'standard' },
  { label: 'WORKFLOWS', href: '/workflows', minMode: 'standard' },
  { label: 'CONNECTORS', href: '/connectors', minMode: 'advanced' },
  { label: 'MEMORY', href: '/memory', minMode: 'advanced' },
  { label: 'GALLERY', href: '/gallery', minMode: 'advanced' },
  { label: 'LEADERBOARD', href: '/leaderboard', minMode: 'advanced' },
  { label: 'REVIEWS', href: '/reviews', minMode: 'advanced' },
  { label: 'GAUNTLET', href: '/gauntlet', minMode: 'advanced' },
  { label: 'INBOX', href: '/inbox', minMode: 'advanced' },
  { label: 'TOURNAMENTS', href: '/tournaments', minMode: 'advanced' },
  { label: 'PRICING', href: '/pricing', minMode: 'advanced' },
  { label: 'GENESIS', href: '/genesis', minMode: 'expert' },
  { label: 'INTROSPECTION', href: '/introspection', minMode: 'expert' },
  { label: 'STATUS', href: '/system-status', minMode: 'expert' },
  { label: 'ABOUT', href: '/about', minMode: 'expert' },
  { label: 'ORACLE', href: '/oracle', accent: true, minMode: 'expert' },
];

export function AppShell({ children }: AppShellProps) {
  const { leftSidebarOpen, rightSidebarOpen, isMobile, leftSidebarWidth, rightSidebarWidth } =
    useLayout();
  const { isFeatureVisible } = useProgressiveMode();

  const visibleLinks = QUICK_LINKS.filter((link) => isFeatureVisible(link.minMode));

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      {/* Top Bar - always visible */}
      <TopBar />

      {/* Main layout container */}
      <div className="flex pt-12">
        {' '}
        {/* pt-12 = 48px for top bar */}
        {/* Left Sidebar */}
        <LeftSidebar />
        {/* Main content area */}
        <main
          id="main-content"
          aria-label="Main content"
          className="flex-1 min-w-0 transition-all duration-200"
          style={{
            marginLeft: isMobile ? 0 : leftSidebarOpen ? leftSidebarWidth : 0,
            marginRight: isMobile ? 0 : rightSidebarOpen ? rightSidebarWidth : 0,
          }}
        >
          <div className="h-[calc(100vh-48px)] overflow-auto">
            {/* Breadcrumbs + quick links */}
            <div className="border-b border-[var(--border)] bg-[var(--surface)]/30 px-3 sm:px-4 lg:px-6 py-2 flex items-center gap-4">
              <div className="min-w-0">
                <Breadcrumbs />
              </div>
              <div className="hidden md:block h-4 w-px bg-[var(--border)]/60" aria-hidden="true" />
              <nav
                aria-label="Quick links"
                className="breadcrumb-links flex-1 overflow-x-auto whitespace-nowrap"
              >
                <div className="flex items-center gap-3 pr-2 text-xs font-theme-data text-text-muted">
                  {visibleLinks.map((link) => {
                    if (link.external) {
                      return (
                        <a
                          key={link.label}
                          href={link.href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={`transition-colors ${link.accent ? 'text-[var(--acid-cyan)] hover:text-[var(--accent)]' : 'hover:text-[var(--accent)]'}`}
                        >
                          [{link.label}]
                        </a>
                      );
                    }
                    return (
                      <Link
                        key={link.label}
                        href={link.href}
                        className="hover:text-[var(--accent)] transition-colors"
                      >
                        [{link.label}]
                      </Link>
                    );
                  })}
                </div>
              </nav>
            </div>

            {/* Page content */}
            <div className="max-w-screen-2xl mx-auto px-3 sm:px-4 lg:px-6 py-4">{children}</div>
          </div>
        </main>
        {/* Right Sidebar */}
        <RightSidebar />
      </div>

      {/* Mobile overlay when left sidebar is open */}
      {isMobile && leftSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40"
          onClick={() => {
            // This will be handled by the context
          }}
        />
      )}
    </div>
  );
}
