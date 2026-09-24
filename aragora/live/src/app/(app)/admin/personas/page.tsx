'use client';

import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { PersonaEditor } from '@/components/admin/PersonaEditor';
import { useAuth } from '@/context/AuthContext';

export default function PersonasAdminPage() {
  const { config: backendConfig } = useBackend();
  const { user, isAuthenticated } = useAuth();
  const isAdmin = isAuthenticated && user?.role === 'admin';

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-4">
              <Link
                href="/admin"
                className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                [ADMIN]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Sub Navigation */}
        <div className="border-b border-[var(--accent)]/20 bg-surface/40">
          <div className="container mx-auto px-4">
            <div className="flex gap-4 overflow-x-auto">
              <Link
                href="/admin"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                SYSTEM
              </Link>
              <Link
                href="/admin/organizations"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                ORGANIZATIONS
              </Link>
              <Link
                href="/admin/users"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                USERS
              </Link>
              <Link
                href="/admin/personas"
                className="px-4 py-2 font-theme-data text-sm text-[var(--accent)] border-b-2 border-[var(--accent)]"
              >
                PERSONAS
              </Link>
              <Link
                href="/admin/audit"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                AUDIT
              </Link>
              <Link
                href="/admin/training"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                TRAINING
              </Link>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              Persona Management
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              View and manage agent personas, traits, and expertise profiles.
            </p>
          </div>

          {!isAdmin && (
            <div className="card p-6 mb-6 border-acid-yellow/40">
              <div className="flex items-center gap-2 text-[var(--acid-yellow)] font-theme-data text-sm">
                <span>!</span>
                <span>Viewing in read-only mode. Sign in as admin for full access.</span>
              </div>
            </div>
          )}

          <PanelErrorBoundary panelName="PersonaEditor">
            <PersonaEditor apiBase={`${backendConfig.api}/api`} />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // PERSONA ADMINISTRATION</p>
        </footer>
      </main>
    </>
  );
}
