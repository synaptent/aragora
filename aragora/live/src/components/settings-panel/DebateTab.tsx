'use client';

import type { FeatureConfig } from './types';

export interface DebateTabProps {
  featureConfig: FeatureConfig;
  updateFeatureConfig: (key: keyof FeatureConfig, value: boolean | string | number) => void;
}

export function DebateTab({ featureConfig, updateFeatureConfig }: DebateTabProps) {
  return (
    <div className="space-y-6" role="tabpanel" id="panel-debate" aria-labelledby="tab-debate">
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Default Debate Settings</h3>
        <div className="space-y-4">
          <div>
            <label
              htmlFor="default-mode-select"
              className="font-theme-data text-sm text-text block mb-2"
            >
              Default Mode
            </label>
            <select
              id="default-mode-select"
              value={featureConfig.default_mode}
              onChange={(e) => updateFeatureConfig('default_mode', e.target.value)}
              className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            >
              <option value="standard">Standard</option>
              <option value="graph">Graph</option>
              <option value="matrix">Matrix</option>
            </select>
          </div>

          <div>
            <label
              htmlFor="default-rounds-input"
              className="font-theme-data text-sm text-text block mb-2"
            >
              Default Rounds
            </label>
            <input
              id="default-rounds-input"
              type="number"
              min={1}
              max={10}
              value={featureConfig.default_rounds}
              onChange={(e) => updateFeatureConfig('default_rounds', parseInt(e.target.value) || 9)}
              className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </div>

          <div>
            <label
              htmlFor="default-agents-input"
              className="font-theme-data text-sm text-text block mb-2"
            >
              Default Agents
            </label>
            <input
              id="default-agents-input"
              type="text"
              value={featureConfig.default_agents}
              onChange={(e) => updateFeatureConfig('default_agents', e.target.value)}
              placeholder="claude,gemini,gpt4,grok"
              className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
            />
            <p className="font-theme-data text-xs text-text-muted mt-1">
              Comma-separated list of agents
            </p>
          </div>
        </div>
      </div>

      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Alert Thresholds</h3>
        <div className="space-y-4">
          <div>
            <label
              htmlFor="consensus-threshold-range"
              className="font-theme-data text-sm text-text block mb-2"
            >
              Consensus Alert Threshold:{' '}
              {(featureConfig.consensus_alert_threshold * 100).toFixed(0)}%
            </label>
            <input
              id="consensus-threshold-range"
              type="range"
              min={0.5}
              max={1.0}
              step={0.05}
              value={featureConfig.consensus_alert_threshold}
              onChange={(e) =>
                updateFeatureConfig('consensus_alert_threshold', parseFloat(e.target.value))
              }
              className="w-full accent-acid-green"
              aria-label={`Consensus alert threshold: ${(featureConfig.consensus_alert_threshold * 100).toFixed(0)}%`}
            />
            <p className="font-theme-data text-xs text-text-muted mt-1">
              Notify when consensus confidence exceeds this threshold
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default DebateTab;
