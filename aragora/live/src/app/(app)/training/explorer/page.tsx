'use client';
import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { ErrorWithRetry } from '@/components/ErrorWithRetry';

interface TrainingStats {
  total_debates: number;
  total_messages: number;
  debates_with_consensus: number;
  average_confidence: number;
  topic_distribution: Record<string, number>;
  agent_distribution: Record<string, number>;
  date_range: { earliest: string; latest: string };
}

interface FormatSchema {
  name: string;
  description: string;
  fields: Array<{ name: string; type: string; description: string }>;
  example: Record<string, unknown>;
}

interface TrainingRecord {
  id: string;
  debate_id: string;
  type: 'sft' | 'dpo';
  input?: string;
  output?: string;
  chosen?: string;
  rejected?: string;
  confidence: number;
  topic?: string;
  agent?: string;
}

type FormatType = 'sft' | 'dpo' | 'gauntlet';
type TabType = 'stats' | 'preview' | 'export';

export default function TrainingExplorerPage() {
  const { config } = useBackend();
  const backendUrl = config.api;
  const [activeTab, setActiveTab] = useState<TabType>('stats');
  const [stats, setStats] = useState<TrainingStats | null>(null);
  const [formats, setFormats] = useState<Record<string, FormatSchema>>({});
  const [selectedFormat, setSelectedFormat] = useState<FormatType>('sft');
  const [previewData, setPreviewData] = useState<TrainingRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.7);
  const [previewLimit] = useState(10);

  const fetchStats = useCallback(async () => {
    try {
      const response = await fetch(`${backendUrl}/api/training/stats`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setStats(data);
    } catch (err) {
      logger.error('Failed to fetch stats:', err);
      throw err;
    }
  }, [backendUrl]);

  const fetchFormats = useCallback(async () => {
    try {
      const response = await fetch(`${backendUrl}/api/training/formats`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setFormats(data.formats || {});
    } catch (err) {
      logger.error('Failed to fetch formats:', err);
    }
  }, [backendUrl]);

  const fetchPreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      const params = new URLSearchParams({
        preview: 'true',
        limit: previewLimit.toString(),
        min_confidence: confidenceThreshold.toString(),
      });
      const response = await fetch(`${backendUrl}/api/training/export/${selectedFormat}?${params}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setPreviewData(data.records || data.examples || []);
    } catch (err) {
      logger.error('Failed to fetch preview:', err);
      setError(err instanceof Error ? err.message : 'Failed to load preview');
    } finally {
      setPreviewLoading(false);
    }
  }, [backendUrl, selectedFormat, previewLimit, confidenceThreshold]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([fetchStats(), fetchFormats()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [fetchStats, fetchFormats]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (activeTab === 'preview') {
      fetchPreview();
    }
  }, [activeTab, selectedFormat, fetchPreview]);

  const handleExport = async () => {
    setExporting(true);
    try {
      const params = new URLSearchParams({ min_confidence: confidenceThreshold.toString() });
      const response = await fetch(`${backendUrl}/api/training/export/${selectedFormat}?${params}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `training-${selectedFormat}-${Date.now()}.jsonl`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  const renderStatsTab = () => (
    <div className="space-y-6">
      <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">Dataset Statistics</h2>

      {!stats ? (
        <p className="text-text-muted">No statistics available</p>
      ) : (
        <>
          {/* Overview Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-4 bg-surface border border-border rounded-lg text-center">
              <div className="text-3xl font-theme-data font-bold text-[var(--accent)]">
                {stats.total_debates}
              </div>
              <div className="text-xs text-text-muted mt-1">Total Debates</div>
            </div>
            <div className="p-4 bg-surface border border-border rounded-lg text-center">
              <div className="text-3xl font-theme-data font-bold text-text">
                {stats.total_messages}
              </div>
              <div className="text-xs text-text-muted mt-1">Total Messages</div>
            </div>
            <div className="p-4 bg-surface border border-border rounded-lg text-center">
              <div className="text-3xl font-theme-data font-bold text-text">
                {stats.debates_with_consensus}
              </div>
              <div className="text-xs text-text-muted mt-1">With Consensus</div>
            </div>
            <div className="p-4 bg-surface border border-border rounded-lg text-center">
              <div className="text-3xl font-theme-data font-bold text-text">
                {(stats.average_confidence * 100).toFixed(0)}%
              </div>
              <div className="text-xs text-text-muted mt-1">Avg Confidence</div>
            </div>
          </div>

          {/* Date Range */}
          {stats.date_range && (
            <div className="p-4 bg-surface border border-border rounded-lg">
              <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-2">
                Date Range
              </h3>
              <div className="text-sm font-theme-data text-text">
                {new Date(stats.date_range.earliest).toLocaleDateString()} -{' '}
                {new Date(stats.date_range.latest).toLocaleDateString()}
              </div>
            </div>
          )}

          {/* Topic Distribution */}
          {stats.topic_distribution && Object.keys(stats.topic_distribution).length > 0 && (
            <div className="p-4 bg-surface border border-border rounded-lg">
              <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
                Topic Distribution
              </h3>
              <div className="space-y-2">
                {Object.entries(stats.topic_distribution)
                  .sort(([, a], [, b]) => b - a)
                  .slice(0, 10)
                  .map(([topic, count]) => (
                    <div key={topic} className="flex items-center gap-3">
                      <div className="flex-1">
                        <div className="flex justify-between text-xs mb-1">
                          <span className="text-text truncate max-w-xs">{topic}</span>
                          <span className="text-text-muted">{count}</span>
                        </div>
                        <div className="h-2 bg-bg rounded overflow-hidden">
                          <div
                            className="h-full bg-[var(--accent)]/60"
                            style={{
                              width: `${(count / Math.max(...Object.values(stats.topic_distribution))) * 100}%`,
                            }}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Agent Distribution */}
          {stats.agent_distribution && Object.keys(stats.agent_distribution).length > 0 && (
            <div className="p-4 bg-surface border border-border rounded-lg">
              <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
                Agent Distribution
              </h3>
              <div className="flex flex-wrap gap-2">
                {Object.entries(stats.agent_distribution)
                  .sort(([, a], [, b]) => b - a)
                  .map(([agent, count]) => (
                    <span
                      key={agent}
                      className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] rounded"
                    >
                      {agent}: {count}
                    </span>
                  ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );

  const renderPreviewTab = () => (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">Data Preview</h2>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-xs text-text-muted">Format:</label>
            <select
              value={selectedFormat}
              onChange={(e) => setSelectedFormat(e.target.value as FormatType)}
              className="px-2 py-1 bg-bg border border-border rounded text-sm font-theme-data"
            >
              <option value="sft">SFT</option>
              <option value="dpo">DPO</option>
              <option value="gauntlet">Gauntlet</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-text-muted">Min Confidence:</label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={confidenceThreshold}
              onChange={(e) => setConfidenceThreshold(parseFloat(e.target.value))}
              className="w-20"
            />
            <span className="text-xs font-theme-data text-text">
              {(confidenceThreshold * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      </div>

      {/* Format Schema */}
      {formats[selectedFormat] && (
        <div className="p-4 bg-surface border border-border rounded-lg">
          <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-2">
            {formats[selectedFormat].name} Format
          </h3>
          <p className="text-sm text-text-muted mb-3">{formats[selectedFormat].description}</p>
          <div className="space-y-1">
            {formats[selectedFormat].fields?.map((field) => (
              <div key={field.name} className="flex items-center gap-2 text-xs font-theme-data">
                <span className="text-[var(--accent)]">{field.name}</span>
                <span className="text-text-muted">({field.type})</span>
                <span className="text-text">{field.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Preview Records */}
      {previewLoading ? (
        <div className="flex items-center justify-center py-8">
          <div className="text-[var(--accent)] font-theme-data animate-pulse">
            Loading preview...
          </div>
        </div>
      ) : previewData.length === 0 ? (
        <div className="p-8 bg-surface border border-border rounded-lg text-center">
          <p className="text-text-muted font-theme-data">No training records match the criteria</p>
        </div>
      ) : (
        <div className="space-y-3">
          {previewData.map((record, idx) => (
            <div key={record.id || idx} className="p-4 bg-surface border border-border rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2 py-0.5 text-xs font-theme-data rounded ${
                      record.type === 'sft'
                        ? 'bg-blue-500/20 text-blue-400'
                        : 'bg-purple-500/20 text-purple-400'
                    }`}
                  >
                    {record.type?.toUpperCase() || selectedFormat.toUpperCase()}
                  </span>
                  {record.topic && <span className="text-xs text-text-muted">{record.topic}</span>}
                </div>
                <span className="text-xs font-theme-data text-text-muted">
                  Confidence: {(record.confidence * 100).toFixed(0)}%
                </span>
              </div>

              {/* SFT Format */}
              {(record.input || record.output) && (
                <div className="space-y-2">
                  {record.input && (
                    <div>
                      <div className="text-xs text-text-muted mb-1">Input:</div>
                      <div className="text-sm text-text bg-bg p-2 rounded font-theme-data overflow-x-auto">
                        {record.input.substring(0, 300)}
                        {record.input.length > 300 ? '...' : ''}
                      </div>
                    </div>
                  )}
                  {record.output && (
                    <div>
                      <div className="text-xs text-text-muted mb-1">Output:</div>
                      <div className="text-sm text-text bg-bg p-2 rounded font-theme-data overflow-x-auto">
                        {record.output.substring(0, 300)}
                        {record.output.length > 300 ? '...' : ''}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* DPO Format */}
              {(record.chosen || record.rejected) && (
                <div className="grid md:grid-cols-2 gap-3">
                  {record.chosen && (
                    <div>
                      <div className="text-xs text-[var(--accent)] mb-1">Chosen:</div>
                      <div className="text-sm text-text bg-bg p-2 rounded font-theme-data overflow-x-auto">
                        {record.chosen.substring(0, 200)}
                        {record.chosen.length > 200 ? '...' : ''}
                      </div>
                    </div>
                  )}
                  {record.rejected && (
                    <div>
                      <div className="text-xs text-red-400 mb-1">Rejected:</div>
                      <div className="text-sm text-text bg-bg p-2 rounded font-theme-data overflow-x-auto">
                        {record.rejected.substring(0, 200)}
                        {record.rejected.length > 200 ? '...' : ''}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderExportTab = () => (
    <div className="space-y-6">
      <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">
        Export Training Data
      </h2>

      <div className="p-4 bg-surface border border-border rounded-lg">
        <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-4">
          Export Settings
        </h3>

        <div className="space-y-4">
          {/* Format Selection */}
          <div>
            <label className="block text-xs font-theme-data text-text-muted uppercase mb-2">
              Format
            </label>
            <div className="flex gap-2">
              {(['sft', 'dpo', 'gauntlet'] as FormatType[]).map((fmt) => (
                <button
                  key={fmt}
                  onClick={() => setSelectedFormat(fmt)}
                  className={`flex-1 px-4 py-3 rounded border-2 transition-all font-theme-data text-sm ${
                    selectedFormat === fmt
                      ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                      : 'border-border text-text-muted hover:border-[var(--accent)]/50'
                  }`}
                >
                  <div className="font-bold">{fmt.toUpperCase()}</div>
                  <div className="text-xs opacity-70">
                    {fmt === 'sft' && 'Supervised Fine-Tuning'}
                    {fmt === 'dpo' && 'Direct Preference Optimization'}
                    {fmt === 'gauntlet' && 'Adversarial Examples'}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Confidence Threshold */}
          <div>
            <label className="block text-xs font-theme-data text-text-muted uppercase mb-2">
              Minimum Confidence: {(confidenceThreshold * 100).toFixed(0)}%
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={confidenceThreshold}
              onChange={(e) => setConfidenceThreshold(parseFloat(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-text-muted mt-1">
              <span>0%</span>
              <span>50%</span>
              <span>100%</span>
            </div>
          </div>

          {/* Export Button */}
          <button
            onClick={handleExport}
            disabled={exporting}
            className={`w-full px-4 py-3 rounded font-theme-data font-bold transition-all ${
              exporting
                ? 'bg-border text-text-muted cursor-not-allowed'
                : 'bg-[var(--accent)]/20 border-2 border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30'
            }`}
          >
            {exporting ? 'Exporting...' : `Export ${selectedFormat.toUpperCase()} Data`}
          </button>
        </div>
      </div>

      {/* Format Info */}
      <div className="p-4 bg-surface border border-border rounded-lg">
        <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
          Format Details
        </h3>
        <div className="space-y-3 text-sm text-text-muted">
          <div>
            <div className="font-theme-data text-text">SFT (Supervised Fine-Tuning)</div>
            <p>
              Input-output pairs from winning debate responses. Best for teaching models debate
              patterns.
            </p>
          </div>
          <div>
            <div className="font-theme-data text-text">DPO (Direct Preference Optimization)</div>
            <p>
              Chosen/rejected pairs showing which responses won debates. Best for alignment
              training.
            </p>
          </div>
          <div>
            <div className="font-theme-data text-text">Gauntlet (Adversarial)</div>
            <p>
              Attack patterns and vulnerabilities from red-team testing. Best for robustness
              training.
            </p>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-bg text-text relative overflow-hidden">
      <Scanlines />
      <CRTVignette />

      <div className="max-w-6xl mx-auto px-4 py-8 relative z-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <Link href="/" className="hover:opacity-80 transition-opacity">
            <AsciiBannerCompact />
          </Link>
          <div className="flex items-center gap-4">
            <Link
              href="/training/models"
              className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
            >
              [MODELS]
            </Link>
            <ThemeToggle />
            <BackendSelector />
          </div>
        </div>

        {/* Title */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <Link
              href="/training"
              className="text-[var(--accent)] hover:underline font-theme-data text-sm"
            >
              Training
            </Link>
            <span className="text-text-muted">/</span>
            <span className="text-text font-theme-data text-sm">Explorer</span>
          </div>
          <h1 className="text-3xl font-theme-data font-bold text-[var(--accent)] mb-2">
            Training Data Explorer
          </h1>
          <p className="text-text-muted font-theme-data text-sm">
            Browse, preview, and export debate data for model fine-tuning
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-6">
            <ErrorWithRetry error={error} onRetry={loadData} />
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-2 mb-6 border-b border-border pb-2">
          <button
            onClick={() => setActiveTab('stats')}
            className={`px-4 py-2 font-theme-data text-sm rounded-t transition-colors ${
              activeTab === 'stats'
                ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-b-2 border-[var(--accent)]'
                : 'text-text-muted hover:text-text'
            }`}
          >
            Statistics
          </button>
          <button
            onClick={() => setActiveTab('preview')}
            className={`px-4 py-2 font-theme-data text-sm rounded-t transition-colors ${
              activeTab === 'preview'
                ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-b-2 border-[var(--accent)]'
                : 'text-text-muted hover:text-text'
            }`}
          >
            Preview
          </button>
          <button
            onClick={() => setActiveTab('export')}
            className={`px-4 py-2 font-theme-data text-sm rounded-t transition-colors ${
              activeTab === 'export'
                ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-b-2 border-[var(--accent)]'
                : 'text-text-muted hover:text-text'
            }`}
          >
            Export
          </button>
        </div>

        {/* Content */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="text-[var(--accent)] font-theme-data animate-pulse">Loading...</div>
          </div>
        ) : (
          <div>
            {activeTab === 'stats' && renderStatsTab()}
            {activeTab === 'preview' && renderPreviewTab()}
            {activeTab === 'export' && renderExportTab()}
          </div>
        )}
      </div>
    </div>
  );
}
