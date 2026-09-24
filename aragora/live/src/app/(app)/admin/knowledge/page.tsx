'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';
import {
  FederationStatus,
  RegionDialog,
  type FederatedRegion,
  type RegionFormData,
} from '@/components/control-plane/KnowledgeExplorer';
import { useFederation } from '@/hooks/useFederation';
import { useGlobalKnowledge } from '@/hooks/useGlobalKnowledge';

interface MoundStats {
  total_nodes: number;
  total_relationships: number;
  nodes_by_visibility: Record<string, number>;
  global_facts_count: number;
  shared_items_count: number;
  federated_regions_count: number;
}

function StatCard({
  label,
  value,
  color = 'acid-green',
}: {
  label: string;
  value: number | string;
  color?: string;
}) {
  return (
    <div className="p-4 bg-surface rounded border border-[var(--accent)]/20">
      <div className="font-theme-data text-xs text-text-muted mb-1">{label}</div>
      <div className={`font-theme-data text-2xl text-${color}`}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
    </div>
  );
}

export default function KnowledgeAdminPage() {
  const { config: backendConfig } = useBackend();
  const { user, isAuthenticated } = useAuth();
  const [stats, setStats] = useState<MoundStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'federation' | 'global'>('overview');

  // Hooks
  const federation = useFederation();
  const globalKnowledge = useGlobalKnowledge({ isAdmin: true });

  // State for new fact form
  const [newFactContent, setNewFactContent] = useState('');
  const [newFactSource, setNewFactSource] = useState('');
  const [newFactConfidence, setNewFactConfidence] = useState(0.95);
  const [isStoringFact, setIsStoringFact] = useState(false);

  // State for region dialog
  const [regionDialogOpen, setRegionDialogOpen] = useState(false);
  const [editingRegion, setEditingRegion] = useState<FederatedRegion | undefined>(undefined);
  const [isSavingRegion, setIsSavingRegion] = useState(false);

  const isAdmin = isAuthenticated && user?.role === 'admin';

  const fetchStats = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const res = await fetch(`${backendConfig.api}/api/knowledge/mound/stats`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch stats');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchStats();
    if (isAdmin) {
      federation.loadRegions();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchStats, isAdmin]);

  const handleStoreFact = async () => {
    if (!newFactContent.trim() || !newFactSource.trim()) return;

    setIsStoringFact(true);
    try {
      await globalKnowledge.storeFact({
        content: newFactContent,
        source: newFactSource,
        confidence: newFactConfidence,
      });
      setNewFactContent('');
      setNewFactSource('');
      setNewFactConfidence(0.95);
      // Refresh stats
      await fetchStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to store fact');
    } finally {
      setIsStoringFact(false);
    }
  };

  const handleAddRegion = () => {
    setEditingRegion(undefined);
    setRegionDialogOpen(true);
  };

  const handleEditRegion = (regionId: string) => {
    const region = federation.regions.find((r) => r.id === regionId);
    if (region) {
      setEditingRegion(region);
      setRegionDialogOpen(true);
    }
  };

  const handleSaveRegion = async (data: RegionFormData) => {
    setIsSavingRegion(true);
    try {
      if (editingRegion) {
        // Update existing region
        await federation.updateRegion(editingRegion.id, {
          name: data.name,
          mode: data.mode,
          scope: data.scope,
          enabled: data.enabled,
        });
      } else {
        // Register new region
        await federation.registerRegion({
          regionId: data.regionId,
          name: data.name,
          endpointUrl: data.endpointUrl,
          apiKey: data.apiKey,
          mode: data.mode,
          scope: data.scope,
        });
      }
      setRegionDialogOpen(false);
      setEditingRegion(undefined);
      // Refresh stats
      await fetchStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save region');
    } finally {
      setIsSavingRegion(false);
    }
  };

  const handleDeleteRegion = async (regionId: string) => {
    setIsSavingRegion(true);
    try {
      await federation.deleteRegion(regionId);
      setRegionDialogOpen(false);
      setEditingRegion(undefined);
      // Refresh stats
      await fetchStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete region');
    } finally {
      setIsSavingRegion(false);
    }
  };

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
                href="/"
                className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
              >
                [DASHBOARD]
              </Link>
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
                href="/admin/knowledge"
                className="px-4 py-2 font-theme-data text-sm text-[var(--accent)] border-b-2 border-[var(--accent)]"
              >
                KNOWLEDGE
              </Link>
              <Link
                href="/admin/audit"
                className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
              >
                AUDIT
              </Link>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
                Knowledge Mound Administration
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Manage global knowledge, federation, and visibility settings.
              </p>
            </div>
            <button
              onClick={fetchStats}
              disabled={loading}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>
          </div>

          {!isAdmin && (
            <div className="card p-6 mb-6 border-acid-yellow/40">
              <div className="flex items-center gap-2 text-[var(--acid-yellow)] font-theme-data text-sm">
                <span>!</span>
                <span>Admin access required for full functionality. Sign in as admin.</span>
              </div>
            </div>
          )}

          {error && (
            <div className="card p-4 mb-6 border-acid-red/40 bg-acid-red/10">
              <p className="text-acid-red font-theme-data text-sm">{error}</p>
            </div>
          )}

          {/* Tab Navigation */}
          <div className="flex gap-2 border-b border-[var(--accent)]/20 pb-2 mb-6 overflow-x-auto">
            {(['overview', 'federation', 'global'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 font-theme-data text-sm whitespace-nowrap transition-colors ${
                  activeTab === tab
                    ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
                    : 'text-text-muted hover:text-text'
                }`}
              >
                {tab === 'overview'
                  ? 'OVERVIEW'
                  : tab === 'federation'
                    ? 'FEDERATION'
                    : 'GLOBAL FACTS'}
              </button>
            ))}
          </div>

          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Stats Grid */}
              {stats && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <StatCard label="Total Nodes" value={stats.total_nodes} />
                  <StatCard
                    label="Relationships"
                    value={stats.total_relationships}
                    color="acid-cyan"
                  />
                  <StatCard
                    label="Global Facts"
                    value={stats.global_facts_count}
                    color="acid-yellow"
                  />
                  <StatCard label="Federated Regions" value={stats.federated_regions_count} />
                </div>
              )}

              {/* Visibility Breakdown */}
              {stats?.nodes_by_visibility && (
                <div className="card p-6">
                  <h2 className="font-theme-data text-[var(--accent)] mb-4">
                    Visibility Distribution
                  </h2>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    {Object.entries(stats.nodes_by_visibility).map(([level, count]) => (
                      <div
                        key={level}
                        className="p-3 bg-surface rounded border border-[var(--accent)]/10"
                      >
                        <div className="font-theme-data text-xs text-text-muted capitalize">
                          {level}
                        </div>
                        <div className="font-theme-data text-lg text-text">
                          {count.toLocaleString()}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Quick Actions */}
              <div className="card p-6">
                <h2 className="font-theme-data text-[var(--accent)] mb-4">Quick Actions</h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <Link
                    href="/control-plane"
                    className="p-4 bg-surface rounded border border-[var(--accent)]/20 hover:border-[var(--accent)]/50 transition-colors"
                  >
                    <div className="font-theme-data text-sm text-[var(--accent)]">
                      Knowledge Explorer
                    </div>
                    <div className="font-theme-data text-xs text-text-muted mt-1">
                      Browse and query knowledge
                    </div>
                  </Link>
                  <button
                    onClick={() => setActiveTab('federation')}
                    className="p-4 bg-surface rounded border border-[var(--accent)]/20 hover:border-[var(--accent)]/50 transition-colors text-left"
                  >
                    <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                      Manage Federation
                    </div>
                    <div className="font-theme-data text-xs text-text-muted mt-1">
                      Configure multi-region sync
                    </div>
                  </button>
                  <button
                    onClick={() => setActiveTab('global')}
                    className="p-4 bg-surface rounded border border-[var(--accent)]/20 hover:border-[var(--accent)]/50 transition-colors text-left"
                  >
                    <div className="font-theme-data text-sm text-[var(--acid-yellow)]">
                      Add Global Fact
                    </div>
                    <div className="font-theme-data text-xs text-text-muted mt-1">
                      Store verified facts
                    </div>
                  </button>
                  <Link
                    href="/admin/audit"
                    className="p-4 bg-surface rounded border border-[var(--accent)]/20 hover:border-[var(--accent)]/50 transition-colors"
                  >
                    <div className="font-theme-data text-sm text-text">View Audit Logs</div>
                    <div className="font-theme-data text-xs text-text-muted mt-1">
                      Knowledge access history
                    </div>
                  </Link>
                </div>
              </div>
            </div>
          )}

          {/* Federation Tab */}
          {activeTab === 'federation' && (
            <div className="card p-0 overflow-hidden" style={{ height: 600 }}>
              <FederationStatus
                regions={federation.regions}
                isLoading={federation.isLoading}
                isAdmin={isAdmin}
                onSync={async (regionId, direction) => {
                  if (direction === 'push') {
                    await federation.syncPush(regionId);
                  } else {
                    await federation.syncPull(regionId);
                  }
                }}
                onToggleEnabled={async (regionId, enabled) => {
                  await federation.toggleRegionEnabled(regionId, enabled);
                }}
                onAddRegion={handleAddRegion}
                onEditRegion={handleEditRegion}
                error={federation.error || undefined}
              />
            </div>
          )}

          {/* Global Facts Tab */}
          {activeTab === 'global' && (
            <div className="space-y-6">
              {/* Add New Fact Form */}
              {isAdmin && (
                <div className="card p-6">
                  <h2 className="font-theme-data text-[var(--accent)] mb-4">Add Verified Fact</h2>
                  <div className="space-y-4">
                    <div>
                      <label className="block font-theme-data text-xs text-text-muted mb-1">
                        Content
                      </label>
                      <textarea
                        value={newFactContent}
                        onChange={(e) => setNewFactContent(e.target.value)}
                        placeholder="Enter the verified fact..."
                        className="w-full p-3 bg-bg border border-[var(--accent)]/30 rounded font-theme-data text-sm text-text resize-none focus:outline-none focus:border-[var(--accent)]"
                        rows={3}
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block font-theme-data text-xs text-text-muted mb-1">
                          Source
                        </label>
                        <input
                          type="text"
                          value={newFactSource}
                          onChange={(e) => setNewFactSource(e.target.value)}
                          placeholder="e.g., RFC 7231, HIPAA 164.530"
                          className="w-full p-3 bg-bg border border-[var(--accent)]/30 rounded font-theme-data text-sm text-text focus:outline-none focus:border-[var(--accent)]"
                        />
                      </div>
                      <div>
                        <label className="block font-theme-data text-xs text-text-muted mb-1">
                          Confidence ({Math.round(newFactConfidence * 100)}%)
                        </label>
                        <input
                          type="range"
                          min={0.5}
                          max={1}
                          step={0.05}
                          value={newFactConfidence}
                          onChange={(e) => setNewFactConfidence(parseFloat(e.target.value))}
                          className="w-full"
                        />
                      </div>
                    </div>
                    <button
                      onClick={handleStoreFact}
                      disabled={isStoringFact || !newFactContent.trim() || !newFactSource.trim()}
                      className="px-6 py-2 bg-acid-yellow/20 border border-acid-yellow/40 text-[var(--acid-yellow)] font-theme-data text-sm rounded hover:bg-acid-yellow/30 transition-colors disabled:opacity-50"
                    >
                      {isStoringFact ? 'Storing...' : 'Store Verified Fact'}
                    </button>
                  </div>
                </div>
              )}

              {/* Recent Global Facts */}
              <div className="card p-6">
                <h2 className="font-theme-data text-[var(--accent)] mb-4">Recent Global Facts</h2>
                <p className="font-theme-data text-sm text-text-muted">
                  Query global knowledge using the Knowledge Explorer.
                </p>
                <Link
                  href="/control-plane"
                  className="inline-block mt-4 px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors"
                >
                  Open Knowledge Explorer
                </Link>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // KNOWLEDGE ADMINISTRATION</p>
        </footer>
      </main>

      {/* Region Dialog */}
      <RegionDialog
        isOpen={regionDialogOpen}
        region={editingRegion}
        onClose={() => {
          setRegionDialogOpen(false);
          setEditingRegion(undefined);
        }}
        onSave={handleSaveRegion}
        onDelete={handleDeleteRegion}
        isSaving={isSavingRegion}
      />
    </>
  );
}
