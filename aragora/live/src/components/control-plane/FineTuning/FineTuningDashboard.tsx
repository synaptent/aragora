'use client';

import { useState, useCallback } from 'react';
import { ModelSelector, type AvailableModel } from './ModelSelector';
import { TrainingConfig, type TrainingParameters } from './TrainingConfig';
import { JobMonitor } from './JobMonitor';
import { useFineTuning, type FineTuningJob, type CreateJobData } from '@/hooks/useFineTuning';

// Re-export the type for backward compatibility
export type { FineTuningJob };

export interface FineTuningDashboardProps {
  onJobCreated?: (job: FineTuningJob) => void;
  onJobCancelled?: (jobId: string) => void;
  /** Polling interval in ms for job updates (default 30000, 0 to disable) */
  pollInterval?: number;
  className?: string;
}

type TabId = 'new' | 'jobs' | 'models';

export function FineTuningDashboard({
  onJobCreated,
  onJobCancelled,
  pollInterval = 30000,
  className = '',
}: FineTuningDashboardProps) {
  // Use the fine-tuning hook
  const { jobs, stats, loading, error, createJob, startJob, cancelJob } = useFineTuning({
    autoLoad: true,
    pollInterval,
  });

  const [activeTab, setActiveTab] = useState<TabId>('jobs');
  const [selectedModel, setSelectedModel] = useState<AvailableModel | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  // Handle job creation
  const handleStartTraining = useCallback(
    async (params: TrainingParameters) => {
      if (!selectedModel) return;

      setIsCreating(true);
      try {
        // Build the job creation data
        const jobData: CreateJobData = {
          name: params.jobName,
          vertical: selectedModel.vertical,
          base_model: selectedModel.id,
          training_config: {
            lora_r: params.loraR,
            lora_alpha: params.loraAlpha,
            lora_dropout: params.loraDropout,
            num_epochs: params.numEpochs,
            batch_size: params.batchSize,
            learning_rate: params.learningRate,
            max_seq_length: params.maxSeqLength,
            quantization: params.quantization,
            gradient_checkpointing: params.gradientCheckpointing,
            dataset_path: params.datasetPath || undefined,
          },
        };

        const job = await createJob(jobData);
        if (job) {
          // Optionally start the job immediately
          await startJob(job.id);
          onJobCreated?.(job);
          setActiveTab('jobs');
          setSelectedModel(null);
        }
      } finally {
        setIsCreating(false);
      }
    },
    [selectedModel, createJob, startJob, onJobCreated],
  );

  // Handle job cancellation
  const handleCancelJob = useCallback(
    async (jobId: string) => {
      const success = await cancelJob(jobId);
      if (success) {
        onJobCancelled?.(jobId);
      }
    },
    [cancelJob, onJobCancelled],
  );

  return (
    <div className={`bg-surface border border-border rounded-lg overflow-hidden ${className}`}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-bg">
        <h3 className="text-sm font-theme-data font-bold text-[var(--accent)]">
          FINE-TUNING PIPELINE
        </h3>
        <p className="text-xs text-text-muted mt-1">
          {loading
            ? 'Loading...'
            : error
              ? `Error: ${error}`
              : 'Train domain-specific models with LoRA adapters'}
        </p>
      </div>

      {/* Stats Bar */}
      <div className="grid grid-cols-4 gap-3 p-4 border-b border-border">
        <div className="text-center">
          <div className="text-xl font-bold text-cyan-400">{stats.running}</div>
          <div className="text-xs text-text-muted">Training</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-bold text-yellow-400">{stats.queued}</div>
          <div className="text-xs text-text-muted">Queued</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-bold text-[var(--accent)]">{stats.completed}</div>
          <div className="text-xs text-text-muted">Completed</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-bold text-red-400">{stats.failed}</div>
          <div className="text-xs text-text-muted">Failed</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border">
        {(['jobs', 'new', 'models'] as TabId[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`
              px-4 py-2 text-xs font-theme-data uppercase transition-colors
              ${
                activeTab === tab
                  ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-bg'
                  : 'text-text-muted hover:text-text'
              }
            `}
          >
            {tab === 'new' ? 'New Job' : tab === 'jobs' ? 'Active Jobs' : 'Available Models'}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="p-4">
        {loading && jobs.length === 0 && (
          <div className="text-center py-8 text-text-muted font-theme-data">
            Loading training jobs...
          </div>
        )}

        {!loading && error && (
          <div className="text-center py-8 text-red-400 font-theme-data">Error: {error}</div>
        )}

        {activeTab === 'jobs' && !loading && !error && (
          <JobMonitor jobs={jobs} onCancelJob={handleCancelJob} />
        )}

        {activeTab === 'new' && (
          <div className="space-y-6">
            {isCreating && (
              <div className="p-4 bg-bg border border-[var(--accent)]/30 rounded text-center">
                <p className="font-theme-data text-[var(--accent)]">Creating training job...</p>
              </div>
            )}
            <ModelSelector selectedModel={selectedModel} onSelectModel={setSelectedModel} />
            {selectedModel && !isCreating && (
              <TrainingConfig model={selectedModel} onStartTraining={handleStartTraining} />
            )}
          </div>
        )}

        {activeTab === 'models' && (
          <ModelSelector
            showAllModels
            onSelectModel={(model) => {
              setSelectedModel(model);
              setActiveTab('new');
            }}
          />
        )}
      </div>
    </div>
  );
}
