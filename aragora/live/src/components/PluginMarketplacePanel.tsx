'use client';

import { useState, useEffect, useCallback } from 'react';
import { ErrorWithRetry } from './RetryButton';
import { fetchWithRetry } from '@/utils/retry';
import { API_BASE_URL } from '@/config';
import { PluginRunModal } from './PluginRunModal';
import { logger } from '@/utils/logger';

interface PluginManifest {
  name: string;
  version: string;
  description: string;
  author: string;
  capabilities: string[];
  requirements: string[];
  entry_point: string;
  timeout_seconds: number;
  max_memory_mb: number;
  python_packages: string[];
  system_tools: string[];
  license: string;
  homepage: string;
  tags: string[];
  created_at: string;
  requirements_satisfied?: boolean;
  missing_requirements?: string[];
  installed_at?: string;
  user_config?: Record<string, unknown>;
}

interface BackendConfig {
  apiUrl: string;
  wsUrl: string;
}

interface PluginMarketplacePanelProps {
  backendConfig?: BackendConfig;
}

const DEFAULT_API_BASE = API_BASE_URL;

const CAPABILITY_COLORS: Record<string, { text: string; bg: string }> = {
  code_analysis: { text: 'text-[var(--acid-cyan)]', bg: 'bg-[var(--acid-cyan)]/20' },
  lint: { text: 'text-[var(--acid-yellow)]', bg: 'bg-acid-yellow/20' },
  security_scan: { text: 'text-acid-red', bg: 'bg-acid-red/20' },
  type_check: { text: 'text-[var(--accent)]', bg: 'bg-[var(--accent)]/20' },
  test_runner: { text: 'text-[var(--acid-cyan)]', bg: 'bg-[var(--acid-cyan)]/20' },
  benchmark: { text: 'text-[var(--acid-yellow)]', bg: 'bg-acid-yellow/20' },
  formatter: { text: 'text-[var(--accent)]', bg: 'bg-[var(--accent)]/20' },
  evidence_fetch: { text: 'text-[var(--acid-cyan)]', bg: 'bg-[var(--acid-cyan)]/20' },
  documentation: { text: 'text-text', bg: 'bg-surface' },
  formal_verify: { text: 'text-acid-red', bg: 'bg-acid-red/20' },
  property_check: { text: 'text-[var(--acid-yellow)]', bg: 'bg-acid-yellow/20' },
  custom: { text: 'text-text-muted', bg: 'bg-surface' },
};

const REQUIREMENT_INFO: Record<string, { icon: string; description: string }> = {
  read_files: { icon: '📖', description: 'Can read local files' },
  write_files: { icon: '📝', description: 'Can write local files' },
  run_commands: { icon: '⚡', description: 'Can execute shell commands' },
  network: { icon: '🌐', description: 'Makes network requests' },
  high_memory: { icon: '🧠', description: 'Requires >1GB RAM' },
  long_running: { icon: '⏱️', description: 'May run >60 seconds' },
  python_packages: { icon: '📦', description: 'External Python packages' },
  system_tools: { icon: '🔧', description: 'External system tools' },
};

export function PluginMarketplacePanel({ backendConfig }: PluginMarketplacePanelProps) {
  const apiBase = backendConfig?.apiUrl || DEFAULT_API_BASE;

  const [plugins, setPlugins] = useState<PluginManifest[]>([]);
  const [installedPlugins, setInstalledPlugins] = useState<Set<string>>(new Set());
  const [selectedPlugin, setSelectedPlugin] = useState<PluginManifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [usingDemoData, setUsingDemoData] = useState(false);
  const [filterCapability, setFilterCapability] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [installingPlugin, setInstallingPlugin] = useState<string | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);
  const [runModalPlugin, setRunModalPlugin] = useState<PluginManifest | null>(null);
  const [installedError, setInstalledError] = useState<string | null>(null);

  const fetchPlugins = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetchWithRetry(`${apiBase}/api/plugins`, undefined, { maxRetries: 2 });

      if (response.ok) {
        const data = await response.json();
        setPlugins(data.plugins || []);
        setError(null);
        setUsingDemoData(false);
      } else {
        // Demo data when API unavailable
        setUsingDemoData(true);
        setPlugins([
          {
            name: 'security-scan',
            version: '1.0.0',
            description: 'Scan code for security vulnerabilities using static analysis',
            author: 'aragora',
            capabilities: ['security_scan', 'code_analysis'],
            requirements: ['read_files'],
            entry_point: 'security_scan:run',
            timeout_seconds: 120,
            max_memory_mb: 512,
            python_packages: ['bandit'],
            system_tools: [],
            license: 'MIT',
            homepage: 'https://github.com/aragora/plugins',
            tags: ['security', 'analysis'],
            created_at: new Date().toISOString(),
          },
          {
            name: 'test-runner',
            version: '1.2.0',
            description: 'Execute test suites and report results',
            author: 'aragora',
            capabilities: ['test_runner'],
            requirements: ['read_files', 'run_commands'],
            entry_point: 'test_runner:run',
            timeout_seconds: 300,
            max_memory_mb: 1024,
            python_packages: ['pytest'],
            system_tools: [],
            license: 'MIT',
            homepage: '',
            tags: ['testing'],
            created_at: new Date().toISOString(),
          },
          {
            name: 'code-formatter',
            version: '2.0.0',
            description: 'Format code according to style guidelines',
            author: 'aragora',
            capabilities: ['formatter'],
            requirements: ['read_files', 'write_files'],
            entry_point: 'code_formatter:run',
            timeout_seconds: 60,
            max_memory_mb: 256,
            python_packages: ['black', 'isort'],
            system_tools: [],
            license: 'MIT',
            homepage: '',
            tags: ['formatting', 'style'],
            created_at: new Date().toISOString(),
          },
        ]);
        setError(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch plugins');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  const fetchPluginDetails = useCallback(
    async (pluginName: string) => {
      try {
        const response = await fetchWithRetry(`${apiBase}/api/plugins/${pluginName}`, undefined, {
          maxRetries: 2,
        });

        if (response.ok) {
          const data = await response.json();
          setSelectedPlugin(data);
        }
      } catch (err) {
        logger.error('Failed to fetch plugin details:', err);
      }
    },
    [apiBase],
  );

  const fetchInstalledPlugins = useCallback(async () => {
    try {
      setInstalledError(null);
      const response = await fetchWithRetry(`${apiBase}/api/plugins/installed`, undefined, {
        maxRetries: 2,
      });

      if (response.ok) {
        const data = await response.json();
        const installed = new Set<string>(
          (data.installed || []).map((p: PluginManifest) => p.name),
        );
        setInstalledPlugins(installed);
      } else if (response.status === 401) {
        // User not authenticated - this is expected
        setInstalledError('auth');
      } else {
        setInstalledError('Failed to load installed plugins');
      }
    } catch (err) {
      setInstalledError(err instanceof Error ? err.message : 'Connection error');
    }
  }, [apiBase]);

  const handleInstallPlugin = useCallback(
    async (pluginName: string) => {
      setInstallingPlugin(pluginName);
      setInstallError(null);

      try {
        const response = await fetch(`${apiBase}/api/plugins/${pluginName}/install`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
        });

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.error || 'Failed to install plugin');
        }

        setInstalledPlugins((prev) => new Set([...prev, pluginName]));
      } catch (err) {
        setInstallError(err instanceof Error ? err.message : 'Failed to install plugin');
      } finally {
        setInstallingPlugin(null);
      }
    },
    [apiBase],
  );

  const handleUninstallPlugin = useCallback(
    async (pluginName: string) => {
      setInstallingPlugin(pluginName);
      setInstallError(null);

      try {
        const response = await fetch(`${apiBase}/api/plugins/${pluginName}/install`, {
          method: 'DELETE',
          credentials: 'include',
        });

        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.error || 'Failed to uninstall plugin');
        }

        setInstalledPlugins((prev) => {
          const next = new Set(prev);
          next.delete(pluginName);
          return next;
        });
      } catch (err) {
        setInstallError(err instanceof Error ? err.message : 'Failed to uninstall plugin');
      } finally {
        setInstallingPlugin(null);
      }
    },
    [apiBase],
  );

  useEffect(() => {
    fetchPlugins();
    fetchInstalledPlugins();
  }, [fetchPlugins, fetchInstalledPlugins]);

  // Filter plugins
  const filteredPlugins = plugins.filter((plugin) => {
    const matchesCapability = !filterCapability || plugin.capabilities.includes(filterCapability);
    const matchesSearch =
      !searchQuery ||
      plugin.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      plugin.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      plugin.tags.some((tag) => tag.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchesCapability && matchesSearch;
  });

  // Get unique capabilities for filter
  const allCapabilities = Array.from(new Set(plugins.flatMap((p) => p.capabilities)));

  if (loading && plugins.length === 0) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3">
          <div className="animate-spin w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
          <span className="font-theme-data text-text-muted">Loading plugins...</span>
        </div>
      </div>
    );
  }

  if (error && plugins.length === 0) {
    return <ErrorWithRetry error={error || 'Failed to load plugins'} onRetry={fetchPlugins} />;
  }

  return (
    <div className="space-y-6">
      {/* Demo Mode Indicator */}
      {usingDemoData && (
        <div className="bg-warning/10 border border-warning/30 rounded px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-warning">⚠</span>
            <span className="font-theme-data text-sm text-warning">
              Demo Mode - Showing example plugins (API unavailable)
            </span>
          </div>
          <button
            onClick={fetchPlugins}
            className="font-theme-data text-xs text-warning hover:text-warning/80 transition-colors"
          >
            [RETRY]
          </button>
        </div>
      )}

      {/* Search and Filter */}
      <div className="card p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block font-theme-data text-xs text-text-muted mb-2">
              Search Plugins
            </label>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by name, description, or tags..."
              className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
          <div>
            <label className="block font-theme-data text-xs text-text-muted mb-2">
              Filter by Capability
            </label>
            <select
              value={filterCapability}
              onChange={(e) => setFilterCapability(e.target.value)}
              className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            >
              <option value="">All Capabilities</option>
              {allCapabilities.map((cap) => (
                <option key={cap} value={cap}>
                  {cap.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="card p-4">
        <div className="grid grid-cols-4 gap-4 text-center">
          <div>
            <div className="text-2xl font-theme-data text-[var(--accent)]">{plugins.length}</div>
            <div className="text-xs font-theme-data text-text-muted">Total Plugins</div>
          </div>
          <div>
            <div className="text-2xl font-theme-data text-accent">
              {installedError === 'auth' ? (
                <span className="text-text-muted" title="Login to see installed plugins">
                  --
                </span>
              ) : installedError ? (
                <span className="text-warning" title={installedError}>
                  ?
                </span>
              ) : (
                installedPlugins.size
              )}
            </div>
            <div className="text-xs font-theme-data text-text-muted">
              {installedError === 'auth' ? 'Login Required' : 'Installed'}
            </div>
          </div>
          <div>
            <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
              {allCapabilities.length}
            </div>
            <div className="text-xs font-theme-data text-text-muted">Capabilities</div>
          </div>
          <div>
            <div className="text-2xl font-theme-data text-[var(--acid-yellow)]">
              {filteredPlugins.length}
            </div>
            <div className="text-xs font-theme-data text-text-muted">Showing</div>
          </div>
        </div>
      </div>

      {/* Plugin Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredPlugins.map((plugin) => {
          const isInstalled = installedPlugins.has(plugin.name);
          return (
            <button
              key={plugin.name}
              onClick={() => {
                setSelectedPlugin(plugin);
                fetchPluginDetails(plugin.name);
              }}
              className={`card p-4 text-left transition-all hover:border-[var(--accent)]/60 ${
                selectedPlugin?.name === plugin.name
                  ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                  : ''
              } ${isInstalled ? 'ring-1 ring-accent/50' : ''}`}
            >
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <h3 className="font-theme-data text-[var(--accent)] font-bold">{plugin.name}</h3>
                  {isInstalled && (
                    <span className="px-1.5 py-0.5 text-[10px] font-theme-data bg-accent/20 text-accent rounded">
                      INSTALLED
                    </span>
                  )}
                </div>
                <span className="text-xs font-theme-data text-text-muted">v{plugin.version}</span>
              </div>

              <p className="font-theme-data text-xs text-text-muted mb-3 line-clamp-2">
                {plugin.description}
              </p>

              {/* Capabilities */}
              <div className="flex flex-wrap gap-1 mb-3">
                {plugin.capabilities.slice(0, 3).map((cap) => {
                  const style = CAPABILITY_COLORS[cap] || CAPABILITY_COLORS.custom;
                  return (
                    <span
                      key={cap}
                      className={`text-xs font-theme-data px-2 py-0.5 rounded ${style.bg} ${style.text}`}
                    >
                      {cap.replace(/_/g, ' ')}
                    </span>
                  );
                })}
                {plugin.capabilities.length > 3 && (
                  <span className="text-xs font-theme-data text-text-muted">
                    +{plugin.capabilities.length - 3}
                  </span>
                )}
              </div>

              {/* Tags */}
              {plugin.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {plugin.tags.slice(0, 3).map((tag) => (
                    <span key={tag} className="text-xs font-theme-data text-text-muted">
                      #{tag}
                    </span>
                  ))}
                </div>
              )}

              {/* Author */}
              <div className="mt-2 text-xs font-theme-data text-text-muted">by {plugin.author}</div>
            </button>
          );
        })}
      </div>

      {filteredPlugins.length === 0 && (
        <div className="card p-8 text-center">
          <p className="text-text-muted font-theme-data">No plugins match your search criteria.</p>
        </div>
      )}

      {/* Selected Plugin Details */}
      {selectedPlugin && (
        <div className="card p-6 border-2 border-[var(--accent)]/40">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="text-xl font-theme-data text-[var(--accent)] font-bold">
                {selectedPlugin.name}
              </h2>
              <p className="text-sm font-theme-data text-text-muted">
                v{selectedPlugin.version} by {selectedPlugin.author}
              </p>
            </div>
            <button
              onClick={() => setSelectedPlugin(null)}
              className="text-text-muted hover:text-text transition-colors"
              aria-label="Close plugin details"
            >
              [X]
            </button>
          </div>

          <p className="font-theme-data text-sm text-text mb-6">{selectedPlugin.description}</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Capabilities */}
            <div>
              <h4 className="font-theme-data text-xs text-[var(--acid-cyan)] mb-2">CAPABILITIES</h4>
              <div className="space-y-1">
                {selectedPlugin.capabilities.map((cap) => {
                  const style = CAPABILITY_COLORS[cap] || CAPABILITY_COLORS.custom;
                  return (
                    <div
                      key={cap}
                      className={`px-3 py-1.5 rounded ${style.bg} ${style.text} font-theme-data text-sm`}
                    >
                      {cap.replace(/_/g, ' ')}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Requirements */}
            <div>
              <h4 className="font-theme-data text-xs text-[var(--acid-yellow)] mb-2">
                REQUIREMENTS
              </h4>
              <div className="space-y-1">
                {selectedPlugin.requirements.map((req) => {
                  const info = REQUIREMENT_INFO[req] || { icon: '?', description: req };
                  return (
                    <div
                      key={req}
                      className="px-3 py-1.5 rounded bg-surface font-theme-data text-sm flex items-center gap-2"
                    >
                      <span>{info.icon}</span>
                      <span className="text-text-muted">{info.description}</span>
                    </div>
                  );
                })}
              </div>

              {selectedPlugin.requirements_satisfied !== undefined && (
                <div
                  className={`mt-2 text-xs font-theme-data ${
                    selectedPlugin.requirements_satisfied ? 'text-[var(--accent)]' : 'text-acid-red'
                  }`}
                >
                  {selectedPlugin.requirements_satisfied
                    ? 'All requirements satisfied'
                    : `Missing: ${selectedPlugin.missing_requirements?.join(', ')}`}
                </div>
              )}
            </div>
          </div>

          {/* Technical Details */}
          <div className="mt-6 p-4 bg-surface rounded">
            <h4 className="font-theme-data text-xs text-[var(--acid-cyan)] mb-3">
              TECHNICAL DETAILS
            </h4>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 font-theme-data text-xs">
              <div>
                <span className="text-text-muted">Entry Point:</span>
                <div className="text-text">{selectedPlugin.entry_point}</div>
              </div>
              <div>
                <span className="text-text-muted">Timeout:</span>
                <div className="text-text">{selectedPlugin.timeout_seconds}s</div>
              </div>
              <div>
                <span className="text-text-muted">Max Memory:</span>
                <div className="text-text">{selectedPlugin.max_memory_mb}MB</div>
              </div>
              <div>
                <span className="text-text-muted">License:</span>
                <div className="text-text">{selectedPlugin.license}</div>
              </div>
            </div>

            {selectedPlugin.python_packages.length > 0 && (
              <div className="mt-3">
                <span className="text-text-muted text-xs">Python Packages: </span>
                <span className="text-text text-xs">
                  {selectedPlugin.python_packages.join(', ')}
                </span>
              </div>
            )}

            {selectedPlugin.system_tools.length > 0 && (
              <div className="mt-1">
                <span className="text-text-muted text-xs">System Tools: </span>
                <span className="text-text text-xs">{selectedPlugin.system_tools.join(', ')}</span>
              </div>
            )}
          </div>

          {/* Install Error */}
          {installError && (
            <div className="mt-4 p-3 bg-warning/10 border border-warning/30 rounded text-xs font-theme-data text-warning">
              {installError}
            </div>
          )}

          {/* Actions */}
          <div className="mt-6 flex flex-wrap gap-4">
            {selectedPlugin.homepage && (
              <a
                href={selectedPlugin.homepage}
                target="_blank"
                rel="noopener noreferrer"
                className="px-4 py-2 bg-surface border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/10 transition-colors"
              >
                View Documentation
              </a>
            )}
            {installedPlugins.has(selectedPlugin.name) ? (
              <>
                <button
                  className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
                  disabled={installingPlugin === selectedPlugin.name}
                  onClick={() => setRunModalPlugin(selectedPlugin)}
                >
                  Run Plugin
                </button>
                <button
                  className="px-4 py-2 bg-warning/20 border border-warning/40 text-warning font-theme-data text-sm rounded hover:bg-warning/30 transition-colors disabled:opacity-50"
                  disabled={installingPlugin === selectedPlugin.name}
                  onClick={() => handleUninstallPlugin(selectedPlugin.name)}
                >
                  {installingPlugin === selectedPlugin.name ? 'Uninstalling...' : 'Uninstall'}
                </button>
              </>
            ) : (
              <button
                className="px-4 py-2 bg-accent/20 border border-accent/40 text-accent font-theme-data text-sm rounded hover:bg-accent/30 transition-colors disabled:opacity-50"
                disabled={installingPlugin === selectedPlugin.name}
                onClick={() => handleInstallPlugin(selectedPlugin.name)}
              >
                {installingPlugin === selectedPlugin.name ? 'Installing...' : 'Install Plugin'}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-4">
        <button
          onClick={fetchPlugins}
          disabled={loading}
          className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
        >
          {loading ? 'Refreshing...' : 'Refresh Plugins'}
        </button>
      </div>

      {/* Run Modal */}
      {runModalPlugin && (
        <PluginRunModal
          plugin={runModalPlugin}
          onClose={() => setRunModalPlugin(null)}
          apiBase={apiBase}
        />
      )}
    </div>
  );
}
