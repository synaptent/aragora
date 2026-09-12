'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector } from '@/components/BackendSelector';
import { AdminSidebar } from './AdminSidebar';
import { useAuth } from '@/context/AuthContext';

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface AdminLayoutProps {
  children: React.ReactNode;
  title: string;
  description?: string;
  breadcrumbs?: BreadcrumbItem[];
  actions?: React.ReactNode;
}

export function AdminLayout({
  children,
  title,
  description,
  breadcrumbs = [],
  actions,
}: AdminLayoutProps) {
  const pathname = usePathname();
  const { user, isAuthenticated } = useAuth();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const isAdmin = isAuthenticated && (user?.role === 'admin' || user?.role === 'owner');

  // Build default breadcrumbs from pathname
  const defaultBreadcrumbs: BreadcrumbItem[] = [{ label: 'Admin', href: '/admin' }];

  if (pathname && pathname !== '/admin') {
    const segments = pathname.replace('/admin/', '').split('/');
    segments.forEach((segment, idx) => {
      const href = '/admin/' + segments.slice(0, idx + 1).join('/');
      defaultBreadcrumbs.push({
        label: segment.charAt(0).toUpperCase() + segment.slice(1).replace(/-/g, ' '),
        href: idx === segments.length - 1 ? undefined : href,
      });
    });
  }

  const displayBreadcrumbs = breadcrumbs.length > 0 ? breadcrumbs : defaultBreadcrumbs;

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <div className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50 h-12">
          <div className="container mx-auto px-4 h-full flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link href="/">
                <AsciiBannerCompact connected={true} />
              </Link>
              <span className="text-[var(--accent)]/40 font-theme-data">|</span>
              <Link
                href="/admin"
                className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                [ADMIN]
              </Link>
            </div>
            <div className="flex items-center gap-4">
              {isAuthenticated && user && (
                <div className="font-theme-data text-xs text-text-muted">
                  <span className="text-[var(--accent)]">*</span> {user.email || user.name}
                </div>
              )}
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Sidebar */}
        <AdminSidebar
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        />

        {/* Main Content */}
        <main
          className="transition-all duration-200"
          style={{ marginLeft: sidebarCollapsed ? '64px' : '224px' }}
        >
          {/* Breadcrumbs */}
          <div className="border-b border-[var(--accent)]/20 bg-surface/40 px-6 py-2">
            <nav className="flex items-center gap-2 font-theme-data text-xs">
              {displayBreadcrumbs.map((crumb, idx) => (
                <React.Fragment key={idx}>
                  {idx > 0 && <span className="text-text-muted">/</span>}
                  {crumb.href ? (
                    <Link
                      href={crumb.href}
                      className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
                    >
                      {crumb.label}
                    </Link>
                  ) : (
                    <span className="text-text">{crumb.label}</span>
                  )}
                </React.Fragment>
              ))}
            </nav>
          </div>

          {/* Page Header */}
          <div className="px-6 py-6 border-b border-[var(--accent)]/10">
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">{title}</h1>
                {description && (
                  <p className="text-text-muted font-theme-data text-sm">{description}</p>
                )}
              </div>
              {actions && <div className="flex items-center gap-2">{actions}</div>}
            </div>
          </div>

          {/* Access Warning */}
          {!isAdmin && (
            <div className="mx-6 mt-6">
              <div className="card p-4 border-acid-yellow/40 bg-acid-yellow/5">
                <div className="flex items-center gap-2 text-[var(--acid-yellow)] font-theme-data text-sm">
                  <span>!</span>
                  <span>Admin access required. Some features may be restricted.</span>
                </div>
              </div>
            </div>
          )}

          {/* Page Content */}
          <div className="px-6 py-6">{children}</div>

          {/* Footer */}
          <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8 mx-6">
            <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
            <p className="text-text-muted">{'>'} ARAGORA // ENTERPRISE ADMINISTRATION</p>
          </footer>
        </main>
      </div>
    </>
  );
}

export default AdminLayout;
