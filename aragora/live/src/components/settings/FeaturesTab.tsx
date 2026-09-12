'use client';

import { useFeatureInfo, useFeatureStatus } from '@/context/FeaturesContext';
import { ToggleSwitch } from './ToggleSwitch';
import type { FeatureConfig } from './types';

interface FeaturesTabProps {
  config: FeatureConfig;
  loading: boolean;
  onUpdate: (key: keyof FeatureConfig, value: boolean | string | number) => void;
}

export function FeaturesTab({ config, loading, onUpdate }: FeaturesTabProps) {
  const supermemoryAvailable = useFeatureStatus('supermemory');
  const supermemoryInfo = useFeatureInfo('supermemory');
  const supermemoryBase =
    supermemoryInfo?.description || 'External cross-session memory sync and context injection';
  const supermemoryHint = supermemoryAvailable
    ? ''
    : supermemoryInfo?.reason || supermemoryInfo?.install_hint || '';
  const supermemoryDescription = supermemoryHint
    ? `${supermemoryBase} — ${supermemoryHint}`
    : supermemoryBase;

  if (loading) {
    return (
      <div className="card p-6 animate-pulse">
        <div className="h-32 bg-surface rounded" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Analysis Features */}
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Analysis Features</h3>
        <div className="space-y-4">
          <ToggleSwitch
            checked={config.calibration}
            onChange={() => onUpdate('calibration', !config.calibration)}
            label="Calibration Tracking"
            description="Track agent prediction accuracy over time"
          />
          <ToggleSwitch
            checked={config.trickster}
            onChange={() => onUpdate('trickster', !config.trickster)}
            label="Trickster (Hollow Consensus)"
            description="Detect and challenge artificial agreement"
          />
          <ToggleSwitch
            checked={config.rhetorical}
            onChange={() => onUpdate('rhetorical', !config.rhetorical)}
            label="Rhetorical Observer"
            description="Detect rhetorical patterns like concession and rebuttal"
          />
          <ToggleSwitch
            checked={config.crux}
            onChange={() => onUpdate('crux', !config.crux)}
            label="Crux Analysis"
            description="Identify key points of disagreement"
          />
        </div>
      </div>

      {/* Learning & Memory */}
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Learning & Memory</h3>
        <div className="space-y-4">
          <ToggleSwitch
            checked={config.continuum_memory}
            onChange={() => onUpdate('continuum_memory', !config.continuum_memory)}
            label="Continuum Memory"
            description="Multi-tier memory with surprise-based consolidation"
          />
          <ToggleSwitch
            checked={config.consensus_memory}
            onChange={() => onUpdate('consensus_memory', !config.consensus_memory)}
            label="Consensus Memory"
            description="Store historical debate outcomes"
          />
          <ToggleSwitch
            checked={config.supermemory}
            onChange={() => {
              if (!supermemoryAvailable) return;
              onUpdate('supermemory', !config.supermemory);
            }}
            label="Supermemory (External)"
            description={supermemoryDescription}
            disabled={!supermemoryAvailable}
          />
          <ToggleSwitch
            checked={config.evolution}
            onChange={() => onUpdate('evolution', !config.evolution)}
            label="Prompt Evolution"
            description="Learn from debates to improve agent prompts"
          />
        </div>
      </div>

      {/* Panels & UI */}
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Panels & UI</h3>
        <div className="space-y-4">
          <ToggleSwitch
            checked={config.insights}
            onChange={() => onUpdate('insights', !config.insights)}
            label="Insights Panel"
            description="Show extracted learnings and patterns"
          />
          <ToggleSwitch
            checked={config.moments}
            onChange={() => onUpdate('moments', !config.moments)}
            label="Moments Timeline"
            description="Detect significant narrative moments"
          />
          <ToggleSwitch
            checked={config.laboratory}
            onChange={() => onUpdate('laboratory', !config.laboratory)}
            label="Persona Laboratory"
            description="Agent personality trait detection"
          />
          <ToggleSwitch
            checked={config.show_advanced_metrics}
            onChange={() => onUpdate('show_advanced_metrics', !config.show_advanced_metrics)}
            label="Show Advanced Metrics"
            description="Display detailed telemetry in panels"
          />
        </div>
      </div>
    </div>
  );
}
