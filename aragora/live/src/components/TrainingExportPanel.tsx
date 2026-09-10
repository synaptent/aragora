'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useAragoraClient } from '@/hooks/useAragoraClient';
import { LoadingSpinner } from './LoadingSpinner';
import { ApiError } from './ApiError';
import {
  PipelineProgress,
  DataPreview,
  TrainingPricingPanel,
  type ExportType,
  type OutputFormat,
  type PipelineStage,
  type PipelineStatus,
  type ExportStats,
  type FormatsResponse,
  type ExportResult,
} from './training-export';

export function TrainingExportPanel() {
  const client = useAragoraClient();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'export' | 'formats' | 'history' | 'pricing'>(
    'export',
  );

  // Data state
  const [stats, setStats] = useState<ExportStats | null>(null);
  const [formats, setFormats] = useState<FormatsResponse | null>(null);
  const [lastExport, setLastExport] = useState<ExportResult | null>(null);

  // Export form state
  const [exportType, setExportType] = useState<ExportType>('sft');
  const [outputFormat, setOutputFormat] = useState<OutputFormat>('json');
  const [limit, setLimit] = useState(100);
  const [minConfidence, setMinConfidence] = useState(0.7);
  const [minSuccessRate, setMinSuccessRate] = useState(0.6);
  const [minConfidenceDiff, setMinConfidenceDiff] = useState(0.1);
  const [persona, setPersona] = useState<'all' | 'gdpr' | 'hipaa' | 'ai_act'>('all');
  const [minSeverity, setMinSeverity] = useState(0.5);
  const [includeCritiques, setIncludeCritiques] = useState(true);
  const [includePatterns, setIncludePatterns] = useState(true);
  const [includeDebates, setIncludeDebates] = useState(true);
  const [isExporting, setIsExporting] = useState(false);

  // Pipeline status state
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus>({
    stage: 'idle',
    progress: 0,
    message: '',
    recordsProcessed: 0,
    totalRecords: 0,
  });

  // Preview state
  const [previewData, setPreviewData] = useState<unknown[]>([]);
  const [showPreview, setShowPreview] = useState(false);
  const progressTimerRef = useRef<NodeJS.Timeout | null>(null);

  const fetchData = useCallback(async () => {
    if (!client) return;
    setLoading(true);
    setError(null);

    try {
      const [statsRes, formatsRes] = await Promise.all([
        client.training.stats().catch((err) => {
          console.warn('[TrainingExportPanel] Failed to fetch training stats:', err);
          return null;
        }),
        client.training.formats().catch((err) => {
          console.warn('[TrainingExportPanel] Failed to fetch export formats:', err);
          return null;
        }),
      ]);

      if (statsRes) setStats(statsRes as unknown as ExportStats);
      if (formatsRes) setFormats(formatsRes as unknown as FormatsResponse);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load training data');
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Simulate pipeline progress
  const simulatePipelineProgress = (
    stage: PipelineStage,
    targetProgress: number,
    totalRecords: number,
  ) => {
    return new Promise<void>((resolve) => {
      const startProgress = pipelineStatus.progress;
      const increment = (targetProgress - startProgress) / 10;
      let current = startProgress;
      let recordsProcessed = 0;
      const recordIncrement = Math.floor(totalRecords / 10);

      progressTimerRef.current = setInterval(() => {
        current += increment;
        recordsProcessed = Math.min(recordsProcessed + recordIncrement, totalRecords);

        if (current >= targetProgress) {
          setPipelineStatus({
            stage,
            progress: targetProgress,
            message: '',
            recordsProcessed: totalRecords,
            totalRecords,
          });
          if (progressTimerRef.current) clearInterval(progressTimerRef.current);
          resolve();
        } else {
          setPipelineStatus({
            stage,
            progress: Math.round(current),
            message: '',
            recordsProcessed,
            totalRecords,
          });
        }
      }, 100);
    });
  };

  const runExport = async () => {
    if (!client) return;
    setIsExporting(true);
    setError(null);
    setShowPreview(false);

    // Initialize pipeline
    setPipelineStatus({
      stage: 'collecting',
      progress: 0,
      message: 'Starting export pipeline...',
      recordsProcessed: 0,
      totalRecords: limit,
    });

    try {
      // Stage 1: Collecting
      await simulatePipelineProgress('collecting', 25, limit);

      // Stage 2: Filtering
      setPipelineStatus((prev) => ({
        ...prev,
        stage: 'filtering',
        message: 'Applying quality filters...',
      }));
      await simulatePipelineProgress('filtering', 50, limit);

      // Stage 3: Transforming
      setPipelineStatus((prev) => ({
        ...prev,
        stage: 'transforming',
        message: 'Transforming to export format...',
      }));
      await simulatePipelineProgress('transforming', 75, limit);

      // Stage 4: Exporting (actual API call)
      setPipelineStatus((prev) => ({
        ...prev,
        stage: 'exporting',
        message: 'Generating export file...',
      }));

      let result: unknown;

      if (exportType === 'sft') {
        result = await client.training.exportSFT({
          min_confidence: minConfidence,
          min_success_rate: minSuccessRate,
          limit,
          include_critiques: includeCritiques,
          include_patterns: includePatterns,
          include_debates: includeDebates,
          format: outputFormat,
        });
      } else if (exportType === 'dpo') {
        result = await client.training.exportDPO({
          min_confidence_diff: minConfidenceDiff,
          limit,
          format: outputFormat,
        });
      } else {
        result = await client.training.exportGauntlet({
          persona: persona === 'all' ? undefined : (persona as 'gdpr' | 'hipaa' | 'ai_act'),
          min_severity: minSeverity,
          limit,
          format: outputFormat,
        });
      }

      // Complete
      const exportResult = result as ExportResult;
      setPipelineStatus({
        stage: 'complete',
        progress: 100,
        message: `Exported ${exportResult.total_records} records successfully!`,
        recordsProcessed: exportResult.total_records,
        totalRecords: exportResult.total_records,
      });

      setLastExport(exportResult);
      setPreviewData(exportResult.records || []);
      setShowPreview(true);
      setActiveTab('history');

      // Refresh stats
      const statsRes = await client.training.stats().catch((err) => {
        console.warn('[TrainingExportPanel] Failed to refresh stats after export:', err);
        return null;
      });
      if (statsRes) setStats(statsRes as unknown as ExportStats);
    } catch (e) {
      setPipelineStatus({
        stage: 'error',
        progress: pipelineStatus.progress,
        message: e instanceof Error ? e.message : 'Export failed',
        recordsProcessed: 0,
        totalRecords: limit,
      });
      setError(e instanceof Error ? e.message : 'Export failed');
    } finally {
      setIsExporting(false);
      if (progressTimerRef.current) {
        clearInterval(progressTimerRef.current);
      }
    }
  };

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (progressTimerRef.current) {
        clearInterval(progressTimerRef.current);
      }
    };
  }, []);

  const downloadExport = () => {
    if (!lastExport) return;

    let content: string;
    let filename: string;

    if (lastExport.format === 'jsonl' && lastExport.data) {
      content = lastExport.data;
      filename = `${lastExport.export_type}_export_${Date.now()}.jsonl`;
    } else {
      content = JSON.stringify(lastExport.records || [], null, 2);
      filename = `${lastExport.export_type}_export_${Date.now()}.json`;
    }

    const blob = new Blob([content], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const tabs = [
    { id: 'export' as const, label: 'Export' },
    { id: 'formats' as const, label: 'Formats' },
    { id: 'history' as const, label: 'History' },
    { id: 'pricing' as const, label: 'Pricing' },
  ];

  // Reset pipeline when export type changes
  useEffect(() => {
    setPipelineStatus({
      stage: 'idle',
      progress: 0,
      message: '',
      recordsProcessed: 0,
      totalRecords: 0,
    });
    setShowPreview(false);
    setPreviewData([]);
  }, [exportType]);

  if (loading && !stats) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <LoadingSpinner />
      </div>
    );
  }

  if (error && !stats) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <ApiError error={error} onRetry={fetchData} />
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-700">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <span className="text-blue-400">&#x1F4BE;</span>
          Training Data Export
        </h2>
        <p className="text-sm text-slate-400 mt-1">Export debate data for model fine-tuning</p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-700">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'text-blue-400 border-b-2 border-blue-400 bg-slate-800/50'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4">
        {/* Export Tab */}
        {activeTab === 'export' && (
          <div className="space-y-6">
            {/* Export Type Selection */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">Export Type</label>
              <div className="grid grid-cols-3 gap-3">
                {(['sft', 'dpo', 'gauntlet'] as const).map((type) => (
                  <button
                    key={type}
                    onClick={() => setExportType(type)}
                    className={`p-3 rounded-lg border text-left transition-colors ${
                      exportType === type
                        ? 'border-blue-500 bg-blue-500/10 text-white'
                        : 'border-slate-600 hover:border-slate-500 text-slate-300'
                    }`}
                  >
                    <p className="font-medium uppercase">{type}</p>
                    <p className="text-xs text-slate-400 mt-1">
                      {type === 'sft' && 'Supervised Fine-Tuning'}
                      {type === 'dpo' && 'Direct Preference Optimization'}
                      {type === 'gauntlet' && 'Adversarial Training'}
                    </p>
                  </button>
                ))}
              </div>
            </div>

            {/* SFT Options */}
            {exportType === 'sft' && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-1">
                      Min Confidence
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.1"
                      value={minConfidence}
                      onChange={(e) => setMinConfidence(parseFloat(e.target.value))}
                      className="w-full"
                    />
                    <p className="text-xs text-slate-400 mt-1">{minConfidence.toFixed(1)}</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-1">
                      Min Success Rate
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.1"
                      value={minSuccessRate}
                      onChange={(e) => setMinSuccessRate(parseFloat(e.target.value))}
                      className="w-full"
                    />
                    <p className="text-xs text-slate-400 mt-1">{minSuccessRate.toFixed(1)}</p>
                  </div>
                </div>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <input
                      type="checkbox"
                      checked={includeCritiques}
                      onChange={(e) => setIncludeCritiques(e.target.checked)}
                      className="rounded"
                    />
                    Include Critiques
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <input
                      type="checkbox"
                      checked={includePatterns}
                      onChange={(e) => setIncludePatterns(e.target.checked)}
                      className="rounded"
                    />
                    Include Patterns
                  </label>
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <input
                      type="checkbox"
                      checked={includeDebates}
                      onChange={(e) => setIncludeDebates(e.target.checked)}
                      className="rounded"
                    />
                    Include Debates
                  </label>
                </div>
              </div>
            )}

            {/* DPO Options */}
            {exportType === 'dpo' && (
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">
                  Min Confidence Diff
                </label>
                <input
                  type="range"
                  min="0"
                  max="0.5"
                  step="0.05"
                  value={minConfidenceDiff}
                  onChange={(e) => setMinConfidenceDiff(parseFloat(e.target.value))}
                  className="w-full"
                />
                <p className="text-xs text-slate-400 mt-1">{minConfidenceDiff.toFixed(2)}</p>
              </div>
            )}

            {/* Gauntlet Options */}
            {exportType === 'gauntlet' && (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1">
                    Persona Filter
                  </label>
                  <select
                    value={persona}
                    onChange={(e) =>
                      setPersona(e.target.value as 'all' | 'gdpr' | 'hipaa' | 'ai_act')
                    }
                    className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-white"
                  >
                    <option value="all">All Personas</option>
                    <option value="gdpr">GDPR</option>
                    <option value="hipaa">HIPAA</option>
                    <option value="ai_act">AI Act</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1">
                    Min Severity
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.1"
                    value={minSeverity}
                    onChange={(e) => setMinSeverity(parseFloat(e.target.value))}
                    className="w-full"
                  />
                  <p className="text-xs text-slate-400 mt-1">{minSeverity.toFixed(1)}</p>
                </div>
              </div>
            )}

            {/* Common Options */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">Limit</label>
                <input
                  type="number"
                  min="1"
                  max="10000"
                  value={limit}
                  onChange={(e) => setLimit(parseInt(e.target.value) || 100)}
                  className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-white"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">
                  Output Format
                </label>
                <select
                  value={outputFormat}
                  onChange={(e) => setOutputFormat(e.target.value as OutputFormat)}
                  className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-white"
                >
                  <option value="json">JSON</option>
                  <option value="jsonl">JSONL</option>
                </select>
              </div>
            </div>

            {/* Pipeline Progress (shown during export) */}
            {isExporting && <PipelineProgress status={pipelineStatus} />}

            {/* Data Preview (shown after export) */}
            {showPreview && previewData.length > 0 && !isExporting && (
              <DataPreview records={previewData} exportType={exportType} />
            )}

            {/* Export Button */}
            <button
              onClick={runExport}
              disabled={isExporting || !stats?.available_exporters?.includes(exportType)}
              className={`w-full py-3 rounded-lg font-medium transition-colors ${
                isExporting || !stats?.available_exporters?.includes(exportType)
                  ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                  : 'bg-blue-600 hover:bg-blue-500 text-white'
              }`}
            >
              {isExporting ? (
                <span className="flex items-center justify-center gap-2">
                  <LoadingSpinner /> Exporting...
                </span>
              ) : !stats?.available_exporters?.includes(exportType) ? (
                `${exportType.toUpperCase()} Exporter Not Available`
              ) : (
                `Export ${exportType.toUpperCase()} Data`
              )}
            </button>

            {/* Pipeline Complete Message */}
            {pipelineStatus.stage === 'complete' && !isExporting && (
              <div className="flex items-center gap-2 text-green-400 text-sm">
                <span>&#x2713;</span>
                <span>{pipelineStatus.message}</span>
              </div>
            )}

            {error && <p className="text-red-400 text-sm">{error}</p>}
          </div>
        )}

        {/* Formats Tab */}
        {activeTab === 'formats' && formats && (
          <div className="space-y-6">
            {Object.entries(formats.formats).map(([key, format]) => (
              <div key={key} className="bg-slate-800 rounded-lg p-4">
                <h3 className="text-white font-medium uppercase">{key}</h3>
                <p className="text-slate-400 text-sm mt-1">{format.description}</p>
                <p className="text-slate-500 text-xs mt-2">{format.use_case}</p>
                <details className="mt-3">
                  <summary className="text-blue-400 text-sm cursor-pointer hover:text-blue-300">
                    View Schema
                  </summary>
                  <pre className="mt-2 text-xs text-slate-300 bg-slate-900 p-2 rounded overflow-x-auto">
                    {JSON.stringify(format.schema, null, 2)}
                  </pre>
                </details>
              </div>
            ))}
          </div>
        )}

        {/* History Tab */}
        {activeTab === 'history' && (
          <div className="space-y-4">
            {lastExport ? (
              <div className="bg-slate-800 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-white font-medium">Latest Export</h3>
                  <button
                    onClick={downloadExport}
                    className="px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-sm text-white transition-colors"
                  >
                    Download
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-slate-400">Type</p>
                    <p className="text-white uppercase">{lastExport.export_type}</p>
                  </div>
                  <div>
                    <p className="text-slate-400">Records</p>
                    <p className="text-white">{lastExport.total_records}</p>
                  </div>
                  <div>
                    <p className="text-slate-400">Format</p>
                    <p className="text-white">{lastExport.format}</p>
                  </div>
                  <div>
                    <p className="text-slate-400">Exported</p>
                    <p className="text-white">
                      {new Date(lastExport.exported_at).toLocaleString()}
                    </p>
                  </div>
                </div>
                <details className="mt-3">
                  <summary className="text-blue-400 text-sm cursor-pointer hover:text-blue-300">
                    View Parameters
                  </summary>
                  <pre className="mt-2 text-xs text-slate-300 bg-slate-900 p-2 rounded overflow-x-auto">
                    {JSON.stringify(lastExport.parameters, null, 2)}
                  </pre>
                </details>
              </div>
            ) : (
              <p className="text-slate-400 text-center py-8">
                No exports yet. Run an export to see results here.
              </p>
            )}

            {/* Previous exports from stats */}
            {stats?.exported_files && stats.exported_files.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-slate-300 mb-3">
                  Exported Files ({stats.exported_files.length})
                </h3>
                <div className="space-y-2">
                  {stats.exported_files.map((file, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between p-3 bg-slate-800 rounded"
                    >
                      <div>
                        <p className="text-white text-sm font-theme-data">{file.name}</p>
                        <p className="text-slate-400 text-xs">
                          {(file.size_bytes / 1024).toFixed(1)} KB
                        </p>
                      </div>
                      <p className="text-slate-500 text-xs">
                        {new Date(file.modified_at).toLocaleDateString()}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Pricing Tab */}
        {activeTab === 'pricing' && (
          <TrainingPricingPanel
            currentUsage={{
              recordsExported: lastExport?.total_records || 0,
              exportsThisMonth: stats?.exported_files?.length || 0,
              lastExportDate: lastExport?.exported_at || null,
              tier: 'starter',
            }}
          />
        )}
      </div>
    </div>
  );
}

export default TrainingExportPanel;
