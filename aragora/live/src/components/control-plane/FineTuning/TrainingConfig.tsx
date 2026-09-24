'use client';

import { useState } from 'react';
import type { AvailableModel } from './ModelSelector';

export interface TrainingParameters {
  jobName: string;
  datasetPath: string;
  loraR: number;
  loraAlpha: number;
  loraDropout: number;
  numEpochs: number;
  batchSize: number;
  learningRate: number;
  maxSeqLength: number;
  quantization: '4bit' | '8bit' | 'none';
  gradientCheckpointing: boolean;
}

export interface TrainingConfigProps {
  model: AvailableModel;
  onStartTraining: (params: TrainingParameters) => void;
  className?: string;
}

const DEFAULT_PARAMS: TrainingParameters = {
  jobName: '',
  datasetPath: '',
  loraR: 16,
  loraAlpha: 32,
  loraDropout: 0.1,
  numEpochs: 3,
  batchSize: 4,
  learningRate: 0.0002,
  maxSeqLength: 2048,
  quantization: '4bit',
  gradientCheckpointing: true,
};

export function TrainingConfig({ model, onStartTraining, className = '' }: TrainingConfigProps) {
  const [params, setParams] = useState<TrainingParameters>({
    ...DEFAULT_PARAMS,
    jobName: `${model.vertical}_specialist_v1`,
  });
  const [showAdvanced, setShowAdvanced] = useState(false);

  const updateParam = <K extends keyof TrainingParameters>(
    key: K,
    value: TrainingParameters[K],
  ) => {
    setParams((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onStartTraining(params);
  };

  const estimatedVRAM = () => {
    const baseVRAM = model.size.includes('34B') ? 40 : model.size.includes('7B') ? 8 : 2;
    const quantMult =
      params.quantization === '4bit' ? 0.25 : params.quantization === '8bit' ? 0.5 : 1;
    return Math.round(baseVRAM * quantMult);
  };

  return (
    <div className={`bg-bg border border-border rounded-lg p-4 ${className}`}>
      <h4 className="font-theme-data font-bold text-text mb-4">Training Configuration</h4>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Basic Settings */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1">JOB NAME</label>
            <input
              type="text"
              value={params.jobName}
              onChange={(e) => updateParam('jobName', e.target.value)}
              required
              className="w-full px-3 py-2 bg-surface border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              placeholder="my_specialist_model"
            />
          </div>
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1">
              DATASET PATH / ID
            </label>
            <input
              type="text"
              value={params.datasetPath}
              onChange={(e) => updateParam('datasetPath', e.target.value)}
              className="w-full px-3 py-2 bg-surface border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              placeholder="/data/training.jsonl or HF dataset"
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1">EPOCHS</label>
            <select
              value={params.numEpochs}
              onChange={(e) => updateParam('numEpochs', Number(e.target.value))}
              className="w-full px-3 py-2 bg-surface border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            >
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
              <option value={5}>5</option>
              <option value={10}>10</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1">BATCH SIZE</label>
            <select
              value={params.batchSize}
              onChange={(e) => updateParam('batchSize', Number(e.target.value))}
              className="w-full px-3 py-2 bg-surface border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            >
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={4}>4</option>
              <option value={8}>8</option>
              <option value={16}>16</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-theme-data text-text-muted mb-1">
              QUANTIZATION
            </label>
            <select
              value={params.quantization}
              onChange={(e) =>
                updateParam('quantization', e.target.value as TrainingParameters['quantization'])
              }
              className="w-full px-3 py-2 bg-surface border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            >
              <option value="4bit">4-bit (QLoRA)</option>
              <option value="8bit">8-bit</option>
              <option value="none">Full Precision</option>
            </select>
          </div>
        </div>

        {/* Resource Estimate */}
        <div className="flex items-center justify-between p-3 bg-surface border border-border rounded">
          <span className="text-xs text-text-muted">Estimated VRAM:</span>
          <span className="font-theme-data text-[var(--accent)]">~{estimatedVRAM()} GB</span>
        </div>

        {/* Advanced Settings Toggle */}
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-2 text-xs font-theme-data text-text-muted hover:text-text"
        >
          <span>{showAdvanced ? '&#x25BC;' : '&#x25B6;'}</span>
          Advanced Settings
        </button>

        {/* Advanced Settings */}
        {showAdvanced && (
          <div className="space-y-4 p-4 bg-surface border border-border rounded">
            <h5 className="font-theme-data text-xs text-text-muted mb-3">LoRA CONFIGURATION</h5>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">LoRA R</label>
                <select
                  value={params.loraR}
                  onChange={(e) => updateParam('loraR', Number(e.target.value))}
                  className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  <option value={8}>8</option>
                  <option value={16}>16</option>
                  <option value={32}>32</option>
                  <option value={64}>64</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  LoRA Alpha
                </label>
                <select
                  value={params.loraAlpha}
                  onChange={(e) => updateParam('loraAlpha', Number(e.target.value))}
                  className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  <option value={16}>16</option>
                  <option value={32}>32</option>
                  <option value={64}>64</option>
                  <option value={128}>128</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  LoRA Dropout
                </label>
                <select
                  value={params.loraDropout}
                  onChange={(e) => updateParam('loraDropout', Number(e.target.value))}
                  className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  <option value={0.0}>0.0</option>
                  <option value={0.05}>0.05</option>
                  <option value={0.1}>0.1</option>
                  <option value={0.15}>0.15</option>
                </select>
              </div>
            </div>

            <h5 className="font-theme-data text-xs text-text-muted mt-4 mb-3">
              TRAINING PARAMETERS
            </h5>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Learning Rate
                </label>
                <input
                  type="number"
                  value={params.learningRate}
                  onChange={(e) => updateParam('learningRate', Number(e.target.value))}
                  step={0.0001}
                  min={0.00001}
                  max={0.01}
                  className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Max Sequence Length
                </label>
                <select
                  value={params.maxSeqLength}
                  onChange={(e) => updateParam('maxSeqLength', Number(e.target.value))}
                  className="w-full px-3 py-2 bg-bg border border-border rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  <option value={512}>512</option>
                  <option value={1024}>1024</option>
                  <option value={2048}>2048</option>
                  <option value={4096}>4096</option>
                </select>
              </div>
            </div>

            <div className="flex items-center gap-3 mt-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={params.gradientCheckpointing}
                  onChange={(e) => updateParam('gradientCheckpointing', e.target.checked)}
                  className="rounded"
                />
                <span className="text-xs font-theme-data text-text-muted">
                  Gradient Checkpointing (saves memory)
                </span>
              </label>
            </div>
          </div>
        )}

        {/* Submit Button */}
        <button
          type="submit"
          className="w-full px-4 py-3 text-sm font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 transition-colors"
        >
          START TRAINING
        </button>
      </form>
    </div>
  );
}
