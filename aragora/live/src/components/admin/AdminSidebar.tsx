'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

interface NavItem {
  label: string;
  href: string;
  icon: string;
}

const navItems: NavItem[] = [
  { label: 'Overview', href: '/admin', icon: '~' },
  { label: 'ROI Dashboard', href: '/admin/roi-dashboard', icon: '$' },
  { label: 'Usage', href: '/admin/usage', icon: '%' },
  { label: 'Users', href: '/admin/users', icon: '@' },
  { label: 'Organizations', href: '/admin/organizations', icon: '#' },
  { label: 'Workspaces', href: '/admin/workspaces', icon: '+' },
  { label: 'Billing', href: '/admin/billing', icon: '=' },
  { label: 'Audit Logs', href: '/admin/audit', icon: '!' },
  { label: 'Security', href: '/admin/security', icon: '*' },
  { label: 'Landing', href: '/admin/landing', icon: '?' },
  { label: 'Queue', href: '/admin/queue', icon: '>' },
  { label: 'Training', href: '/admin/training', icon: '^' },
  { label: 'Personas', href: '/admin/personas', icon: '&' },
];

interface AdminSidebarProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export function AdminSidebar({ collapsed = false, onToggleCollapse }: AdminSidebarProps) {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === '/admin') {
      return pathname === '/admin';
    }
    return pathname?.startsWith(href);
  };

  return (
    <aside
      className={`
        fixed top-12 left-0 h-[calc(100vh-48px)] bg-surface border-r border-[var(--accent)]/30 z-30
        transition-all duration-200 ease-out
        ${collapsed ? 'w-16' : 'w-56'}
      `}
    >
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="p-3 border-b border-[var(--accent)]/20">
          {!collapsed && (
            <div className="font-theme-data text-sm text-[var(--accent)]">ADMIN PANEL</div>
          )}
          {collapsed && (
            <div className="font-theme-data text-lg text-[var(--accent)] text-center">A</div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto p-2 space-y-1">
          {navItems.map((item) => {
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`
                  flex items-center gap-3 px-3 py-2 rounded-md transition-colors font-theme-data text-sm
                  ${
                    active
                      ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                      : 'text-text-muted hover:bg-surface-elevated hover:text-text'
                  }
                `}
                title={collapsed ? item.label : undefined}
              >
                <span className="w-5 text-center">{item.icon}</span>
                {!collapsed && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* Collapse Toggle */}
        <div className="p-3 border-t border-[var(--accent)]/20">
          <button
            onClick={onToggleCollapse}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-md text-text-muted hover:bg-surface-elevated hover:text-text transition-colors font-theme-data text-sm"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <span>{collapsed ? '>>' : '<<'}</span>
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>
      </div>
    </aside>
  );
}

export default AdminSidebar;
