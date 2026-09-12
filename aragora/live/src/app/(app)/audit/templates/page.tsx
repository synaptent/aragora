'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface AuditPreset {
  name: string;
  description: string;
  audit_types: string[];
  consensus_threshold: number;
  custom_rules_count: number;
}

interface AuditType {
  id: string;
  display_name: string;
  description: string;
  version: string;
  capabilities: {
    supports_chunk_analysis?: boolean;
    supports_cross_document?: boolean;
    requires_llm?: boolean;
  };
}

const INDUSTRY_ICONS: Record<string, string> = {
  'Legal Due Diligence': '⚖️',
  'Financial Audit': '💰',
  'Code Security': '🔒',
};

const PRESET_COLORS: Record<string, string> = {
  'Legal Due Diligence': 'border-acid-purple hover:border-acid-purple/80 hover:bg-acid-purple/5',
  'Financial Audit': 'border-acid-yellow hover:border-acid-yellow/80 hover:bg-acid-yellow/5',
  'Code Security':
    'border-[var(--accent)] hover:border-[var(--accent)]/80 hover:bg-[var(--accent)]/5',
};

export default function AuditTemplatesPage() {
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const [presets, setPresets] = useState<AuditPreset[]>([]);
  const [auditTypes, setAuditTypes] = useState<AuditType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [presetsRes, typesRes] = await Promise.all([
        fetch(`${backendConfig.api}/api/audit/presets`, {
          headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
        }),
        fetch(`${backendConfig.api}/api/audit/types`, {
          headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
        }),
      ]);

      if (presetsRes.ok) {
        const data = await presetsRes.json();
        setPresets(data.presets || []);
      }

      if (typesRes.ok) {
        const data = await typesRes.json();
        setAuditTypes(data.audit_types || []);
      }
    } catch {
      setError('Failed to fetch audit configuration');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, tokens?.access_token]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleUsePreset = (preset: AuditPreset) => {
    const params = new URLSearchParams({
      preset: preset.name,
      types: preset.audit_types.join(','),
    });
    router.push(`/audit/new?${params.toString()}`);
  };

  return (
    <div className="min-h-screen bg-background">
      <Scanlines />
      <CRTVignette />

      <header className="border-b border-border bg-surface/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/" className="hover:text-accent">
              <AsciiBannerCompact />
            </Link>
            <span className="text-muted font-theme-data text-sm">{'//'} AUDIT TEMPLATES</span>
          </div>
          <div className="flex items-center gap-3">
            <BackendSelector />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-theme-data mb-1">AUDIT PRESETS</h1>
            <p className="text-muted text-sm">
              Pre-configured audit templates for common use cases
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/audit" className="btn btn-ghost">
              ← Dashboard
            </Link>
            <Link href="/audit/new" className="btn btn-primary">
              + New Audit
            </Link>
          </div>
        </div>

        {error && (
          <div className="card p-4 mb-6 border-acid-red bg-acid-red/10">
            <div className="flex items-center gap-2 text-acid-red">
              <span>⚠️</span>
              <span className="font-theme-data text-sm">{error}</span>
            </div>
          </div>
        )}

        {/* Industry Presets */}
        <section className="mb-8">
          <h2 className="text-lg font-theme-data text-muted mb-4">INDUSTRY PRESETS</h2>
          {loading ? (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="card p-6 animate-pulse">
                  <div className="h-6 bg-surface rounded w-2/3 mb-3" />
                  <div className="h-4 bg-surface rounded w-full mb-2" />
                  <div className="h-4 bg-surface rounded w-3/4" />
                </div>
              ))}
            </div>
          ) : presets.length === 0 ? (
            <div className="card p-8 text-center">
              <div className="text-4xl mb-3">📋</div>
              <div className="text-muted font-theme-data">NO PRESETS AVAILABLE</div>
              <div className="text-sm text-muted mt-2">
                Presets will appear here once configured
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {presets.map((preset) => (
                <div
                  key={preset.name}
                  className={`card p-6 border-2 cursor-pointer transition-all ${
                    PRESET_COLORS[preset.name] || 'border-border hover:border-accent'
                  }`}
                  onClick={() => handleUsePreset(preset)}
                >
                  <div className="flex items-start justify-between mb-3">
                    <span className="text-3xl">{INDUSTRY_ICONS[preset.name] || '📋'}</span>
                    <span className="px-2 py-1 text-xs font-theme-data bg-surface rounded">
                      {preset.custom_rules_count} rules
                    </span>
                  </div>
                  <h3 className="font-theme-data text-lg mb-2">{preset.name}</h3>
                  <p className="text-sm text-muted mb-4 line-clamp-2">{preset.description}</p>
                  <div className="flex flex-wrap gap-1 mb-4">
                    {preset.audit_types.map((type) => (
                      <span
                        key={type}
                        className="px-2 py-0.5 text-xs font-theme-data bg-accent/20 text-accent rounded"
                      >
                        {type}
                      </span>
                    ))}
                  </div>
                  <div className="flex items-center justify-between text-xs text-muted">
                    <span>Consensus: {Math.round(preset.consensus_threshold * 100)}%</span>
                    <span className="text-accent">USE PRESET →</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Audit Types */}
        <section>
          <h2 className="text-lg font-theme-data text-muted mb-4">AVAILABLE AUDIT TYPES</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {auditTypes.map((type) => (
              <div key={type.id} className="card p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <h3 className="font-theme-data">{type.display_name}</h3>
                    <span className="text-xs text-muted">v{type.version}</span>
                  </div>
                  <div className="flex gap-1">
                    {type.capabilities.supports_cross_document && (
                      <span
                        className="px-2 py-0.5 text-xs bg-acid-purple/20 text-acid-purple rounded"
                        title="Cross-document analysis"
                      >
                        CROSS-DOC
                      </span>
                    )}
                    {type.capabilities.requires_llm && (
                      <span
                        className="px-2 py-0.5 text-xs bg-acid-blue/20 text-acid-blue rounded"
                        title="Uses LLM"
                      >
                        LLM
                      </span>
                    )}
                  </div>
                </div>
                <p className="text-sm text-muted">{type.description}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Quick Start Guide */}
        <section className="mt-8">
          <div className="card p-6 bg-surface/50">
            <h2 className="text-lg font-theme-data mb-4">QUICK START</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-accent/20 text-accent flex items-center justify-center font-theme-data">
                  1
                </div>
                <div>
                  <div className="font-theme-data text-sm">SELECT PRESET</div>
                  <div className="text-xs text-muted">Choose an industry-specific preset above</div>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-accent/20 text-accent flex items-center justify-center font-theme-data">
                  2
                </div>
                <div>
                  <div className="font-theme-data text-sm">ADD DOCUMENTS</div>
                  <div className="text-xs text-muted">Upload or select documents to audit</div>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-accent/20 text-accent flex items-center justify-center font-theme-data">
                  3
                </div>
                <div>
                  <div className="font-theme-data text-sm">REVIEW FINDINGS</div>
                  <div className="text-xs text-muted">Triage, assign, and resolve issues</div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border bg-surface/50 py-4 mt-8">
        <div className="container mx-auto px-4 flex items-center justify-between text-xs text-muted font-theme-data">
          <span>ARAGORA ENTERPRISE AUDIT</span>
          <div className="flex items-center gap-4">
            <Link href="/audit" className="hover:text-accent">
              DASHBOARD
            </Link>
            <Link href="/documents" className="hover:text-accent">
              DOCUMENTS
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
