'use client';

import { useState, useEffect, useCallback, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface Document {
  id: string;
  filename: string;
  status: string;
  chunk_count: number;
}

const AUDIT_TYPES = [
  {
    id: 'security',
    name: 'Security',
    description: 'Detect exposed credentials, injection risks, data exposure',
  },
  {
    id: 'compliance',
    name: 'Compliance',
    description: 'Check GDPR, HIPAA, SOC2 compliance issues',
  },
  {
    id: 'consistency',
    name: 'Consistency',
    description: 'Find contradictions, outdated references',
  },
  { id: 'quality', name: 'Quality', description: 'Identify ambiguity, missing documentation' },
];

const MODELS = [
  {
    id: 'gemini-3-pro',
    name: 'Gemini 3 Pro',
    description: '1M token context - best for large documents',
  },
  {
    id: 'claude-3.5-sonnet',
    name: 'Claude 3.5 Sonnet',
    description: 'Deep reasoning for complex analysis',
  },
  { id: 'gpt-4-turbo', name: 'GPT-4 Turbo', description: 'Balanced performance and accuracy' },
];

function NewAuditContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();

  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(
    new Set(['security', 'compliance', 'consistency', 'quality']),
  );
  const [selectedModel, setSelectedModel] = useState('gemini-3-pro');
  const [sessionName, setSessionName] = useState('');
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const docIds = searchParams.get('documents');
    if (docIds) {
      setSelectedDocs(new Set(docIds.split(',')));
    }
  }, [searchParams]);

  const fetchDocuments = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/documents`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (response.ok) {
        const data = await response.json();
        setDocuments((data.documents || []).filter((d: Document) => d.status === 'completed'));
      }
    } catch {
      setError('Failed to fetch documents');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, tokens?.access_token]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const handleCreate = async () => {
    if (selectedDocs.size === 0) {
      setError('Select at least one document');
      return;
    }

    setCreating(true);
    setError(null);

    try {
      const response = await fetch(`${backendConfig.api}/api/audit/sessions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
        body: JSON.stringify({
          name: sessionName || undefined,
          document_ids: Array.from(selectedDocs),
          audit_types: Array.from(selectedTypes),
          model: selectedModel,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to create audit session');
      }

      const data = await response.json();

      // Start the audit
      await fetch(`${backendConfig.api}/api/audit/sessions/${data.id}/start`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });

      router.push(`/audit/view?id=${data.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create audit');
    } finally {
      setCreating(false);
    }
  };

  const totalChunks = documents
    .filter((d) => selectedDocs.has(d.id))
    .reduce((sum, d) => sum + d.chunk_count, 0);

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
            <span className="text-muted font-theme-data text-sm">{'//'} NEW AUDIT</span>
          </div>
          <div className="flex items-center gap-3">
            <BackendSelector />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6 max-w-4xl">
        <div className="mb-6">
          <h1 className="text-2xl font-theme-data mb-2">CREATE AUDIT SESSION</h1>
          <p className="text-muted">Configure and start a new document audit</p>
        </div>

        {error && (
          <div className="card p-4 mb-6 border-acid-red bg-acid-red/10">
            <div className="flex items-center gap-2 text-acid-red">
              <span>⚠️</span>
              <span className="font-theme-data text-sm">{error}</span>
              <button onClick={() => setError(null)} className="ml-auto">
                ✕
              </button>
            </div>
          </div>
        )}

        {/* Session Name */}
        <div className="card p-4 mb-4">
          <label className="block text-sm font-theme-data text-muted mb-2">
            SESSION NAME (optional)
          </label>
          <input
            type="text"
            value={sessionName}
            onChange={(e) => setSessionName(e.target.value)}
            placeholder="My Audit Session"
            className="input w-full"
          />
        </div>

        {/* Document Selection */}
        <div className="card p-4 mb-4">
          <label className="block text-sm font-theme-data text-muted mb-2">
            SELECT DOCUMENTS ({selectedDocs.size} selected, {totalChunks.toLocaleString()} chunks)
          </label>
          {loading ? (
            <div className="p-4 text-center text-muted animate-pulse">Loading...</div>
          ) : documents.length === 0 ? (
            <div className="p-4 text-center">
              <div className="text-muted mb-2">No processed documents available</div>
              <Link href="/documents" className="text-accent hover:underline">
                Upload documents →
              </Link>
            </div>
          ) : (
            <div className="max-h-64 overflow-y-auto space-y-2">
              {documents.map((doc) => (
                <label
                  key={doc.id}
                  className="flex items-center gap-3 p-2 hover:bg-surface rounded cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedDocs.has(doc.id)}
                    onChange={(e) => {
                      const next = new Set(selectedDocs);
                      if (e.target.checked) {
                        next.add(doc.id);
                      } else {
                        next.delete(doc.id);
                      }
                      setSelectedDocs(next);
                    }}
                    className="rounded"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="font-theme-data text-sm truncate">{doc.filename}</div>
                    <div className="text-xs text-muted">{doc.chunk_count} chunks</div>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>

        {/* Audit Types */}
        <div className="card p-4 mb-4">
          <label className="block text-sm font-theme-data text-muted mb-2">AUDIT TYPES</label>
          <div className="grid grid-cols-2 gap-3">
            {AUDIT_TYPES.map((type) => (
              <label
                key={type.id}
                className={`flex items-start gap-3 p-3 rounded border cursor-pointer transition-colors ${selectedTypes.has(type.id) ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/50'}`}
              >
                <input
                  type="checkbox"
                  checked={selectedTypes.has(type.id)}
                  onChange={(e) => {
                    const next = new Set(selectedTypes);
                    if (e.target.checked) {
                      next.add(type.id);
                    } else {
                      next.delete(type.id);
                    }
                    setSelectedTypes(next);
                  }}
                  className="mt-1 rounded"
                />
                <div>
                  <div className="font-theme-data text-sm">{type.name}</div>
                  <div className="text-xs text-muted">{type.description}</div>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* Model Selection */}
        <div className="card p-4 mb-6">
          <label className="block text-sm font-theme-data text-muted mb-2">PRIMARY MODEL</label>
          <div className="space-y-2">
            {MODELS.map((model) => (
              <label
                key={model.id}
                className={`flex items-start gap-3 p-3 rounded border cursor-pointer transition-colors ${selectedModel === model.id ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/50'}`}
              >
                <input
                  type="radio"
                  name="model"
                  value={model.id}
                  checked={selectedModel === model.id}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="mt-1"
                />
                <div>
                  <div className="font-theme-data text-sm">{model.name}</div>
                  <div className="text-xs text-muted">{model.description}</div>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between">
          <Link href="/audit" className="btn btn-ghost">
            ← Back to Dashboard
          </Link>
          <button
            onClick={handleCreate}
            disabled={selectedDocs.size === 0 || selectedTypes.size === 0 || creating}
            className="btn btn-primary"
          >
            {creating ? 'CREATING...' : '🔍 START AUDIT'}
          </button>
        </div>
      </main>
    </div>
  );
}

export default function NewAuditPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-background flex items-center justify-center">
          <span className="text-muted animate-pulse">Loading...</span>
        </div>
      }
    >
      <NewAuditContent />
    </Suspense>
  );
}
