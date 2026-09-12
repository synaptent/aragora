'use client';

import { useFeatureInfo, useFeatureStatus } from '@/context/FeaturesContext';
import type { FeatureConfig } from './types';
import { ToggleSwitch } from './ToggleSwitch';

export interface FeaturesTabProps {
  featureConfig: FeatureConfig;
  featureLoading: boolean;
  updateFeatureConfig: (key: keyof FeatureConfig, value: boolean | string | number) => void;
}

export function FeaturesTab({
  featureConfig,
  featureLoading,
  updateFeatureConfig,
}: FeaturesTabProps) {
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

  if (featureLoading) {
    return (
      <div className="card p-6 animate-pulse">
        <div className="h-32 bg-surface rounded" />
      </div>
    );
  }

  return (
    <div className="space-y-6" role="tabpanel" id="panel-features" aria-labelledby="tab-features">
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Analysis Features</h3>
        <div className="space-y-4">
          <ToggleSwitch
            label="Calibration Tracking"
            description="Track agent prediction accuracy over time"
            checked={featureConfig.calibration}
            onChange={() => updateFeatureConfig('calibration', !featureConfig.calibration)}
          />
          <ToggleSwitch
            label="Trickster (Hollow Consensus)"
            description="Detect and challenge artificial agreement"
            checked={featureConfig.trickster}
            onChange={() => updateFeatureConfig('trickster', !featureConfig.trickster)}
          />
          <ToggleSwitch
            label="Rhetorical Observer"
            description="Detect rhetorical patterns like concession and rebuttal"
            checked={featureConfig.rhetorical}
            onChange={() => updateFeatureConfig('rhetorical', !featureConfig.rhetorical)}
          />
          <ToggleSwitch
            label="Crux Analysis"
            description="Identify key points of disagreement"
            checked={featureConfig.crux}
            onChange={() => updateFeatureConfig('crux', !featureConfig.crux)}
          />
        </div>
      </div>

      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Learning & Memory</h3>
        <div className="space-y-4">
          <ToggleSwitch
            label="Continuum Memory"
            description="Multi-tier memory with surprise-based consolidation"
            checked={featureConfig.continuum_memory}
            onChange={() =>
              updateFeatureConfig('continuum_memory', !featureConfig.continuum_memory)
            }
          />
          <ToggleSwitch
            label="Consensus Memory"
            description="Store historical debate outcomes"
            checked={featureConfig.consensus_memory}
            onChange={() =>
              updateFeatureConfig('consensus_memory', !featureConfig.consensus_memory)
            }
          />
          <ToggleSwitch
            label="Supermemory (External)"
            description={supermemoryDescription}
            checked={featureConfig.supermemory}
            disabled={!supermemoryAvailable}
            onChange={() => {
              if (!supermemoryAvailable) return;
              updateFeatureConfig('supermemory', !featureConfig.supermemory);
            }}
          />
          <ToggleSwitch
            label="Prompt Evolution"
            description="Learn from debates to improve agent prompts"
            checked={featureConfig.evolution}
            onChange={() => updateFeatureConfig('evolution', !featureConfig.evolution)}
          />
        </div>
      </div>

      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Panels & UI</h3>
        <div className="space-y-4">
          <ToggleSwitch
            label="Insights Panel"
            description="Show extracted learnings and patterns"
            checked={featureConfig.insights}
            onChange={() => updateFeatureConfig('insights', !featureConfig.insights)}
          />
          <ToggleSwitch
            label="Moments Timeline"
            description="Detect significant narrative moments"
            checked={featureConfig.moments}
            onChange={() => updateFeatureConfig('moments', !featureConfig.moments)}
          />
          <ToggleSwitch
            label="Persona Laboratory"
            description="Agent personality trait detection"
            checked={featureConfig.laboratory}
            onChange={() => updateFeatureConfig('laboratory', !featureConfig.laboratory)}
          />
          <ToggleSwitch
            label="Show Advanced Metrics"
            description="Display detailed telemetry in panels"
            checked={featureConfig.show_advanced_metrics}
            onChange={() =>
              updateFeatureConfig('show_advanced_metrics', !featureConfig.show_advanced_metrics)
            }
          />
        </div>
      </div>
    </div>
  );
}

export default FeaturesTab;
