'use client';

import { useState, useEffect, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { ErrorWithRetry } from '@/components/ErrorWithRetry';
import { logger } from '@/utils/logger';

interface IndexProgress {
  repository_id: string;
  status: 'pending' | 'indexing' | 'completed' | 'failed' | 'unknown';
  files_discovered: number;
  files_processed: number;
  nodes_created: number;
  current_file?: string;
  started_at?: string;
  error?: string;
}

interface IndexedRepository {
  repository_name: string;
  workspace_id: string;
  total_nodes: number;
  total_files: number;
  node_types: Record<string, number>;
  last_indexed?: string;
  status?: string;
}

interface Entity {
  id: string;
  content?: string;
  metadata: {
    kind?: string;
    name?: string;
    file_path?: string;
    line_start?: number;
    [key: string]: unknown;
  };
}

interface _GraphEntity {
  id: string;
  name: string;
  kind: string;
  mentions?: number;
}

interface GraphStats {
  total_nodes: number;
  total_edges: number;
  node_types: Record<string, number>;
  edge_types: Record<string, number>;
}

const statusColors: Record<string, string> = {
  pending: 'text-[var(--acid-yellow)]',
  indexing: 'text-[var(--acid-cyan)] animate-pulse',
  completed: 'text-[var(--accent)]',
  failed: 'text-[var(--crimson)]',
  unknown: 'text-text-muted',
};

export default function RepositoryPage() {
  const { config: backendConfig } = useBackend();
  const [activeTab, setActiveTab] = useState<'repos' | 'index' | 'browse' | 'graph'>('repos');
  const [error, setError] = useState<string | null>(null);

  // Repository list state
  const [repositories, setRepositories] = useState<IndexedRepository[]>([]);
  const [loadingRepos, setLoadingRepos] = useState(true);

  // Index state
  const [repoPath, setRepoPath] = useState('');
  const [workspaceId, setWorkspaceId] = useState('default');
  const [includePatterns, setIncludePatterns] = useState('*,**/*');
  const [excludePatterns, setExcludePatterns] = useState(
    'node_modules/**,*.pyc,__pycache__/**,.git/**',
  );
  const [maxFileSize, setMaxFileSize] = useState(1000000);
  const [maxFiles, setMaxFiles] = useState(10000);
  const [extractSymbols, setExtractSymbols] = useState(true);
  const [extractDeps, setExtractDeps] = useState(true);
  const [incrementalUpdate, setIncrementalUpdate] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [progress, setProgress] = useState<IndexProgress | null>(null);
  const [pollingInterval, setPollingInterval] = useState<NodeJS.Timeout | null>(null);

  // Browse state
  const [browseRepoId, setBrowseRepoId] = useState('');
  const [entityKind, setEntityKind] = useState('');
  const [filePath, setFilePath] = useState('');
  const [entities, setEntities] = useState<Entity[]>([]);
  const [browsing, setBrowsing] = useState(false);
  const [totalEntities, setTotalEntities] = useState(0);

  // Graph state
  const [graphRepoId, setGraphRepoId] = useState('');
  const [entityId, setEntityId] = useState('');
  const [graphDepth, setGraphDepth] = useState(2);
  const [graphDirection, setGraphDirection] = useState<'both' | 'dependencies' | 'dependents'>(
    'both',
  );
  const [graphStats, setGraphStats] = useState<GraphStats | null>(null);
  const [graphEntities, setGraphEntities] = useState<Entity[]>([]);
  const [loadingGraph, setLoadingGraph] = useState(false);

  // Fetch repositories
  const fetchRepositories = useCallback(async () => {
    try {
      setLoadingRepos(true);
      // Try to get known repository IDs from the orchestrator or mound
      const knownRepos = ['aragora', 'default']; // Common repo names to check
      const repos: IndexedRepository[] = [];

      for (const repoId of knownRepos) {
        try {
          const res = await fetch(
            `${backendConfig.api}/api/repository/${encodeURIComponent(repoId)}`,
          );
          if (res.ok) {
            const data = await res.json();
            repos.push({
              repository_name: repoId,
              workspace_id: data.workspace_id || 'default',
              total_nodes: data.total_nodes || 0,
              total_files: data.total_files || 0,
              node_types: data.node_types || {},
              last_indexed: data.last_indexed,
              status: 'indexed',
            });
          }
        } catch {
          // Repo doesn't exist, skip
        }
      }
      setRepositories(repos);
    } catch (err) {
      logger.error('Failed to fetch repositories:', err);
    } finally {
      setLoadingRepos(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchRepositories();
  }, [fetchRepositories]);

  // Poll for indexing progress
  const _pollProgress = useCallback(
    async (repoId: string) => {
      try {
        const res = await fetch(
          `${backendConfig.api}/api/repository/${encodeURIComponent(repoId)}/status`,
        );
        if (res.ok) {
          const data = await res.json();
          setProgress(data);

          if (data.status === 'completed' || data.status === 'failed') {
            if (pollingInterval) {
              clearInterval(pollingInterval);
              setPollingInterval(null);
            }
            setIndexing(false);
            fetchRepositories();
          }
        }
      } catch (err) {
        logger.error('Failed to poll progress:', err);
      }
    },
    [backendConfig.api, pollingInterval, fetchRepositories],
  );

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingInterval) {
        clearInterval(pollingInterval);
      }
    };
  }, [pollingInterval]);

  const handleStartIndex = async () => {
    if (!repoPath.trim()) return;
    setIndexing(true);
    setProgress({
      repository_id: repoPath,
      status: 'indexing',
      files_discovered: 0,
      files_processed: 0,
      nodes_created: 0,
    });
    setError(null);

    const endpoint = incrementalUpdate ? '/api/repository/incremental' : '/api/repository/index';

    try {
      const res = await fetch(`${backendConfig.api}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_path: repoPath,
          workspace_id: workspaceId,
          crawl_config: {
            include_patterns: includePatterns
              .split(',')
              .map((p) => p.trim())
              .filter(Boolean),
            exclude_patterns: excludePatterns
              .split(',')
              .map((p) => p.trim())
              .filter(Boolean),
            max_file_size_bytes: maxFileSize,
            max_files: maxFiles,
            extract_symbols: extractSymbols,
            extract_dependencies: extractDeps,
          },
        }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.result) {
          setProgress({
            repository_id: repoPath,
            status: data.success ? 'completed' : 'failed',
            files_discovered: data.result.files_discovered || 0,
            files_processed: data.result.files_processed || 0,
            nodes_created: data.result.nodes_created || 0,
            error: data.result.errors?.join(', '),
          });
          fetchRepositories();
        }
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.error || 'Indexing failed');
        setProgress((prev) => (prev ? { ...prev, status: 'failed', error: errData.error } : null));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Indexing failed');
      setProgress((prev) =>
        prev
          ? { ...prev, status: 'failed', error: err instanceof Error ? err.message : 'Failed' }
          : null,
      );
    } finally {
      setIndexing(false);
    }
  };

  const handleDeleteRepository = async (repoId: string) => {
    if (
      !confirm(
        `Are you sure you want to delete the indexed repository "${repoId}"? This cannot be undone.`,
      )
    ) {
      return;
    }

    try {
      const res = await fetch(`${backendConfig.api}/api/repository/${encodeURIComponent(repoId)}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId }),
      });

      if (res.ok) {
        fetchRepositories();
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.error || 'Failed to delete repository');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete repository');
    }
  };

  const handleBrowse = async () => {
    if (!browseRepoId.trim()) return;
    setBrowsing(true);
    setEntities([]);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (entityKind) params.set('kind', entityKind);
      if (filePath) params.set('file_path', filePath);
      params.set('limit', '50');

      const res = await fetch(
        `${backendConfig.api}/api/repository/${encodeURIComponent(browseRepoId)}/entities?${params}`,
      );

      if (res.ok) {
        const data = await res.json();
        setEntities(data.entities || []);
        setTotalEntities(data.total || 0);
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.error || 'Failed to browse entities');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to browse entities');
    } finally {
      setBrowsing(false);
    }
  };

  const handleLoadGraph = async () => {
    if (!graphRepoId.trim()) return;
    setLoadingGraph(true);
    setGraphStats(null);
    setGraphEntities([]);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (entityId) params.set('entity_id', entityId);
      params.set('depth', graphDepth.toString());
      params.set('direction', graphDirection);

      const res = await fetch(
        `${backendConfig.api}/api/repository/${encodeURIComponent(graphRepoId)}/graph?${params}`,
      );

      if (res.ok) {
        const data = await res.json();
        if (data.statistics) {
          setGraphStats(data.statistics);
        }
        if (data.entities) {
          setGraphEntities(data.entities);
        }
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.error || 'Failed to load graph');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load graph');
    } finally {
      setLoadingGraph(false);
    }
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-8">
          {/* Title */}
          <div className="mb-8">
            <h1 className="text-2xl font-theme-data font-bold text-[var(--accent)] mb-2">
              [REPOSITORY_INDEXER]
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Index and explore codebase structure for knowledge retrieval
            </p>
          </div>

          {error && (
            <ErrorWithRetry error={error} onRetry={() => setError(null)} className="mb-6" />
          )}

          {/* Tabs */}
          <div className="flex gap-2 mb-6 border-b border-border pb-2">
            {(['repos', 'index', 'browse', 'graph'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 font-theme-data text-sm transition-colors ${
                  activeTab === tab
                    ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
                    : 'text-text-muted hover:text-text'
                }`}
              >
                {tab === 'repos' ? 'REPOSITORIES' : tab.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Repositories Tab */}
          {activeTab === 'repos' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-theme-data text-[var(--accent)]">
                  [INDEXED REPOSITORIES]
                </h3>
                <button
                  onClick={() => setActiveTab('index')}
                  className="px-4 py-2 font-theme-data text-sm bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors"
                >
                  [+ INDEX NEW]
                </button>
              </div>

              {loadingRepos ? (
                <div className="text-center py-12">
                  <div className="text-[var(--accent)] font-theme-data animate-pulse">
                    Loading repositories...
                  </div>
                </div>
              ) : repositories.length === 0 ? (
                <div className="card p-8 text-center">
                  <div className="text-text-muted font-theme-data mb-4">
                    No repositories indexed yet.
                  </div>
                  <button
                    onClick={() => setActiveTab('index')}
                    className="px-4 py-2 font-theme-data text-sm border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                  >
                    [INDEX A REPOSITORY]
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {repositories.map((repo) => (
                    <div
                      key={repo.repository_name}
                      className="card p-4 hover:border-[var(--accent)]/50 transition-colors"
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div>
                          <h4 className="font-theme-data font-bold text-[var(--accent)]">
                            {repo.repository_name}
                          </h4>
                          <span className="text-xs font-theme-data text-text-muted">
                            Workspace: {repo.workspace_id}
                          </span>
                        </div>
                        <span className="px-2 py-0.5 text-xs font-theme-data text-[var(--accent)] bg-[var(--accent)]/10 border border-[var(--accent)]/30 rounded">
                          INDEXED
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-2 mb-3">
                        <div className="p-2 bg-bg rounded border border-border">
                          <div className="text-xs font-theme-data text-text-muted">Nodes</div>
                          <div className="font-theme-data text-lg text-[var(--acid-cyan)]">
                            {repo.total_nodes.toLocaleString()}
                          </div>
                        </div>
                        <div className="p-2 bg-bg rounded border border-border">
                          <div className="text-xs font-theme-data text-text-muted">Files</div>
                          <div className="font-theme-data text-lg text-accent">
                            {repo.total_files.toLocaleString()}
                          </div>
                        </div>
                      </div>

                      {repo.node_types && Object.keys(repo.node_types).length > 0 && (
                        <div className="mb-3">
                          <div className="text-xs font-theme-data text-text-muted mb-1">
                            Node Types
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {Object.entries(repo.node_types)
                              .slice(0, 4)
                              .map(([type, count]) => (
                                <span
                                  key={type}
                                  className="px-2 py-0.5 text-xs font-theme-data bg-surface text-text-muted rounded"
                                >
                                  {type}: {count}
                                </span>
                              ))}
                          </div>
                        </div>
                      )}

                      <div className="flex gap-2">
                        <button
                          onClick={() => {
                            setBrowseRepoId(repo.repository_name);
                            setActiveTab('browse');
                          }}
                          className="flex-1 py-1.5 font-theme-data text-xs border border-[var(--acid-cyan)] text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                        >
                          [BROWSE]
                        </button>
                        <button
                          onClick={() => {
                            setGraphRepoId(repo.repository_name);
                            setActiveTab('graph');
                          }}
                          className="flex-1 py-1.5 font-theme-data text-xs border border-accent text-accent hover:bg-accent/10 transition-colors"
                        >
                          [GRAPH]
                        </button>
                        <button
                          onClick={() => handleDeleteRepository(repo.repository_name)}
                          className="py-1.5 px-2 font-theme-data text-xs border border-[var(--crimson)] text-[var(--crimson)] hover:bg-[var(--crimson)]/10 transition-colors"
                        >
                          [X]
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Index Tab */}
          {activeTab === 'index' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="card p-4">
                <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                  [INDEX REPOSITORY]
                </h3>

                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      Repository Path *
                    </label>
                    <input
                      type="text"
                      value={repoPath}
                      onChange={(e) => setRepoPath(e.target.value)}
                      placeholder="/path/to/repository"
                      className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      Workspace ID
                    </label>
                    <input
                      type="text"
                      value={workspaceId}
                      onChange={(e) => setWorkspaceId(e.target.value)}
                      placeholder="default"
                      className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-theme-data text-text-muted mb-1">
                        Include Patterns
                      </label>
                      <input
                        type="text"
                        value={includePatterns}
                        onChange={(e) => setIncludePatterns(e.target.value)}
                        placeholder="*,**/*"
                        className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-theme-data text-text-muted mb-1">
                        Exclude Patterns
                      </label>
                      <input
                        type="text"
                        value={excludePatterns}
                        onChange={(e) => setExcludePatterns(e.target.value)}
                        placeholder="node_modules/**,.git/**"
                        className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-theme-data text-text-muted mb-1">
                        Max File Size (bytes)
                      </label>
                      <input
                        type="number"
                        value={maxFileSize}
                        onChange={(e) => setMaxFileSize(parseInt(e.target.value) || 1000000)}
                        className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-theme-data text-text-muted mb-1">
                        Max Files
                      </label>
                      <input
                        type="number"
                        value={maxFiles}
                        onChange={(e) => setMaxFiles(parseInt(e.target.value) || 10000)}
                        className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                      />
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-4">
                    <label className="flex items-center gap-2 text-sm font-theme-data">
                      <input
                        type="checkbox"
                        checked={extractSymbols}
                        onChange={(e) => setExtractSymbols(e.target.checked)}
                        className="rounded border-border"
                      />
                      <span className="text-text-muted">Extract Symbols</span>
                    </label>
                    <label className="flex items-center gap-2 text-sm font-theme-data">
                      <input
                        type="checkbox"
                        checked={extractDeps}
                        onChange={(e) => setExtractDeps(e.target.checked)}
                        className="rounded border-border"
                      />
                      <span className="text-text-muted">Extract Dependencies</span>
                    </label>
                    <label className="flex items-center gap-2 text-sm font-theme-data">
                      <input
                        type="checkbox"
                        checked={incrementalUpdate}
                        onChange={(e) => setIncrementalUpdate(e.target.checked)}
                        className="rounded border-border"
                      />
                      <span className="text-[var(--acid-cyan)]">Incremental Update</span>
                    </label>
                  </div>

                  <button
                    onClick={handleStartIndex}
                    disabled={indexing || !repoPath.trim()}
                    className="w-full py-3 font-theme-data text-sm bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
                  >
                    {indexing
                      ? '[INDEXING...]'
                      : incrementalUpdate
                        ? '[RUN INCREMENTAL UPDATE]'
                        : '[START FULL INDEX]'}
                  </button>
                </div>
              </div>

              <div className="card p-4">
                <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">[PROGRESS]</h3>

                {progress ? (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <span className="font-theme-data text-sm text-text-muted">Status</span>
                      <span className={`font-theme-data text-sm ${statusColors[progress.status]}`}>
                        {progress.status.toUpperCase()}
                      </span>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      <div className="p-3 bg-bg rounded border border-border">
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          Files Discovered
                        </div>
                        <div className="text-xl font-theme-data text-[var(--accent)]">
                          {progress.files_discovered}
                        </div>
                      </div>
                      <div className="p-3 bg-bg rounded border border-border">
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          Files Processed
                        </div>
                        <div className="text-xl font-theme-data text-[var(--acid-cyan)]">
                          {progress.files_processed}
                        </div>
                      </div>
                      <div className="p-3 bg-bg rounded border border-border">
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          Nodes Created
                        </div>
                        <div className="text-xl font-theme-data text-accent">
                          {progress.nodes_created}
                        </div>
                      </div>
                    </div>

                    {progress.current_file && (
                      <div>
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          Current File
                        </div>
                        <div className="text-sm font-theme-data text-text truncate">
                          {progress.current_file}
                        </div>
                      </div>
                    )}

                    {progress.error && (
                      <div className="p-3 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded">
                        <div className="text-xs font-theme-data text-[var(--crimson)]">
                          {progress.error}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-center py-12 text-text-muted font-theme-data text-sm">
                    Enter a repository path and click Start Index
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Browse Tab */}
          {activeTab === 'browse' && (
            <div className="space-y-6">
              <div className="card p-4">
                <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                  [BROWSE ENTITIES]
                </h3>

                <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      Repository ID *
                    </label>
                    <input
                      type="text"
                      value={browseRepoId}
                      onChange={(e) => setBrowseRepoId(e.target.value)}
                      placeholder="repository-name"
                      className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      Kind (optional)
                    </label>
                    <select
                      value={entityKind}
                      onChange={(e) => setEntityKind(e.target.value)}
                      className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                    >
                      <option value="">All</option>
                      <option value="file">File</option>
                      <option value="class">Class</option>
                      <option value="function">Function</option>
                      <option value="method">Method</option>
                      <option value="variable">Variable</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      File Path (optional)
                    </label>
                    <input
                      type="text"
                      value={filePath}
                      onChange={(e) => setFilePath(e.target.value)}
                      placeholder="src/..."
                      className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>
                  <div className="flex items-end">
                    <button
                      onClick={handleBrowse}
                      disabled={browsing || !browseRepoId.trim()}
                      className="w-full py-2 font-theme-data text-sm bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
                    >
                      {browsing ? '[LOADING...]' : '[BROWSE]'}
                    </button>
                  </div>
                </div>
              </div>

              {entities.length > 0 && (
                <div className="card p-4">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-theme-data text-[var(--accent)]">[ENTITIES]</h3>
                    <span className="text-xs font-theme-data text-text-muted">
                      Showing {entities.length} of {totalEntities}
                    </span>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full font-theme-data text-sm">
                      <thead>
                        <tr className="border-b border-border">
                          <th className="text-left py-2 px-2 text-text-muted">ID</th>
                          <th className="text-left py-2 px-2 text-text-muted">Kind</th>
                          <th className="text-left py-2 px-2 text-text-muted">Name</th>
                          <th className="text-left py-2 px-2 text-text-muted">File</th>
                          <th className="text-left py-2 px-2 text-text-muted">Line</th>
                        </tr>
                      </thead>
                      <tbody>
                        {entities.map((entity) => (
                          <tr
                            key={entity.id}
                            className="border-b border-border/50 hover:bg-surface/50"
                          >
                            <td
                              className="py-2 px-2 text-[var(--acid-cyan)] truncate max-w-[120px]"
                              title={entity.id}
                            >
                              {entity.id.slice(0, 12)}...
                            </td>
                            <td className="py-2 px-2 text-[var(--accent)]">
                              {entity.metadata.kind || '-'}
                            </td>
                            <td className="py-2 px-2">{entity.metadata.name || '-'}</td>
                            <td className="py-2 px-2 text-text-muted truncate max-w-[200px]">
                              {entity.metadata.file_path || '-'}
                            </td>
                            <td className="py-2 px-2 text-text-muted">
                              {entity.metadata.line_start || '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {entities.length === 0 && !browsing && browseRepoId && (
                <div className="card p-8 text-center">
                  <div className="text-text-muted font-theme-data">
                    No entities found. The repository may not be indexed.
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Graph Tab */}
          {activeTab === 'graph' && (
            <div className="space-y-6">
              <div className="card p-4">
                <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                  [RELATIONSHIP GRAPH]
                </h3>

                <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mb-4">
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      Repository ID *
                    </label>
                    <input
                      type="text"
                      value={graphRepoId}
                      onChange={(e) => setGraphRepoId(e.target.value)}
                      placeholder="repository-name"
                      className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      Entity ID (optional)
                    </label>
                    <input
                      type="text"
                      value={entityId}
                      onChange={(e) => setEntityId(e.target.value)}
                      placeholder="For specific entity"
                      className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      Depth
                    </label>
                    <input
                      type="number"
                      value={graphDepth}
                      onChange={(e) => setGraphDepth(parseInt(e.target.value) || 2)}
                      min={1}
                      max={5}
                      className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-1">
                      Direction
                    </label>
                    <select
                      value={graphDirection}
                      onChange={(e) => setGraphDirection(e.target.value as typeof graphDirection)}
                      className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                    >
                      <option value="both">Both</option>
                      <option value="dependencies">Dependencies</option>
                      <option value="dependents">Dependents</option>
                    </select>
                  </div>
                  <div className="flex items-end">
                    <button
                      onClick={handleLoadGraph}
                      disabled={loadingGraph || !graphRepoId.trim()}
                      className="w-full py-2 font-theme-data text-sm bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
                    >
                      {loadingGraph ? '[LOADING...]' : '[LOAD GRAPH]'}
                    </button>
                  </div>
                </div>
              </div>

              {graphStats && (
                <div className="card p-4">
                  <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                    [GRAPH STATISTICS]
                  </h3>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                    <div className="p-3 bg-bg rounded border border-border">
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        Total Nodes
                      </div>
                      <div className="text-xl font-theme-data text-[var(--accent)]">
                        {graphStats.total_nodes}
                      </div>
                    </div>
                    <div className="p-3 bg-bg rounded border border-border">
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        Total Edges
                      </div>
                      <div className="text-xl font-theme-data text-[var(--acid-cyan)]">
                        {graphStats.total_edges}
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <div className="text-xs font-theme-data text-text-muted mb-2">Node Types</div>
                      <div className="space-y-1">
                        {Object.entries(graphStats.node_types || {}).map(([type, count]) => (
                          <div
                            key={type}
                            className="flex items-center justify-between text-sm font-theme-data"
                          >
                            <span className="text-text-muted">{type}</span>
                            <span className="text-[var(--accent)]">{count}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-theme-data text-text-muted mb-2">Edge Types</div>
                      <div className="space-y-1">
                        {Object.entries(graphStats.edge_types || {}).map(([type, count]) => (
                          <div
                            key={type}
                            className="flex items-center justify-between text-sm font-theme-data"
                          >
                            <span className="text-text-muted">{type}</span>
                            <span className="text-[var(--acid-cyan)]">{count}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {graphEntities.length > 0 && (
                <div className="card p-4">
                  <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                    [RELATED ENTITIES]
                  </h3>

                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {graphEntities.map((entity) => (
                      <div key={entity.id} className="p-3 bg-bg rounded border border-border">
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-theme-data text-sm text-[var(--accent)]">
                            {entity.metadata?.name}
                          </span>
                          <span className="text-xs font-theme-data text-text-muted px-2 py-0.5 bg-surface rounded">
                            {entity.metadata?.kind}
                          </span>
                        </div>
                        <div className="text-xs font-theme-data text-text-muted truncate">
                          {entity.metadata?.file_path}
                          {entity.metadata?.line_start && `:${entity.metadata.line_start}`}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </>
  );
}
