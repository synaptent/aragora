/**
 * Feature Flags System
 *
 * Centralized feature flag management for Aragora.
 * Allows gating experimental features and A/B testing.
 */

import { logger } from '@/utils/logger';

export type FeatureStatus = 'stable' | 'beta' | 'alpha' | 'deprecated';

export interface FeatureFlag {
  /** Whether the feature is enabled */
  enabled: boolean;
  /** Human-readable label for UI */
  label: string;
  /** Feature maturity status */
  status: FeatureStatus;
  /** Optional description */
  description?: string;
  /** Whether to show in UI (some flags are internal only) */
  showInUI?: boolean;
}

/**
 * Feature flags configuration
 *
 * To add a new feature flag:
 * 1. Add entry here with appropriate status
 * 2. Use `isFeatureEnabled('FEATURE_NAME')` to check
 * 3. Optionally use `<FeatureGate feature="FEATURE_NAME">` component
 */
export const FEATURES: Record<string, FeatureFlag> = {
  // Stable features (enabled by default)
  STANDARD_DEBATES: {
    enabled: true,
    label: 'Standard Debates',
    status: 'stable',
    description: 'Linear debate with critique rounds',
    showInUI: false,
  },
  FORK_VISUALIZER: {
    enabled: true,
    label: 'Fork Visualizer',
    status: 'stable',
    description: 'Visualize and compare debate forks',
    showInUI: true,
  },
  PLUGIN_MARKETPLACE: {
    enabled: true,
    label: 'Plugin Marketplace',
    status: 'stable',
    description: 'Browse and install plugins',
    showInUI: true,
  },
  PULSE_SCHEDULER: {
    enabled: true,
    label: 'Pulse Scheduler',
    status: 'stable',
    description: 'Automated trending topic debates',
    showInUI: true,
  },
  AGENT_RECOMMENDER: {
    enabled: true,
    label: 'Agent Recommender',
    status: 'stable',
    description: 'AI-powered agent selection',
    showInUI: true,
  },

  // Beta features (enabled but marked as beta)
  BATCH_DEBATES: {
    enabled: true,
    label: 'Batch Debates',
    status: 'beta',
    description: 'Run multiple debates in parallel',
    showInUI: true,
  },
  EVIDENCE_EXPLORER: {
    enabled: true,
    label: 'Evidence Explorer',
    status: 'beta',
    description: 'Browse and search evidence chains',
    showInUI: true,
  },

  // Beta features (enabled, recently promoted from alpha)
  GRAPH_DEBATES: {
    enabled: true,
    label: 'Graph Debates',
    status: 'beta',
    description: 'Branching debate exploring multiple paths',
    showInUI: true,
  },
  MATRIX_DEBATES: {
    enabled: true,
    label: 'Matrix Debates',
    status: 'beta',
    description: 'Parallel scenarios for comparison',
    showInUI: true,
  },
  FORMAL_VERIFICATION: {
    enabled: true,
    label: 'Formal Verification',
    status: 'beta',
    description: 'Z3/Lean proof verification for debate conclusions',
    showInUI: true,
  },
  MEMORY_EXPLORER: {
    enabled: true,
    label: 'Memory Explorer',
    status: 'beta',
    description: 'Browse agent memory tiers',
    showInUI: true,
  },
  TOURNAMENT_MODE: {
    enabled: true,
    label: 'Tournament Mode',
    status: 'beta',
    description: 'Multi-round agent tournaments',
    showInUI: true,
  },

  // Deprecated features
  CLI_AGENTS: {
    enabled: false,
    label: 'CLI Agents',
    status: 'deprecated',
    description: 'Legacy CLI-based agents (use API agents instead)',
    showInUI: false,
  },
  AGENT_BRIDGE: {
    enabled: false,
    label: 'Agent Bridge',
    status: 'alpha',
    description: 'Read-only bridge run inspection for experimental multi-agent handoffs',
    showInUI: false,
  },
} as const;

export type FeatureName = keyof typeof FEATURES;

/**
 * Check if a feature is enabled
 */
export function isFeatureEnabled(feature: FeatureName): boolean {
  const flag = FEATURES[feature];
  if (!flag) {
    logger.warn(`Unknown feature flag: ${feature}`);
    return false;
  }

  // Check for runtime override via localStorage (for testing)
  if (typeof window !== 'undefined') {
    const override = localStorage.getItem(`feature_${feature}`);
    if (override !== null) {
      return override === 'true';
    }
  }

  // Check for environment variable override
  if (typeof process !== 'undefined' && process.env) {
    const envKey = `NEXT_PUBLIC_FEATURE_${feature}`;
    const envValue = process.env[envKey];
    if (envValue !== undefined) {
      return envValue === 'true' || envValue === '1';
    }
  }

  return flag.enabled;
}

/**
 * Get feature flag details
 */
export function getFeatureFlag(feature: FeatureName): FeatureFlag | undefined {
  return FEATURES[feature];
}

/**
 * Get all features with a specific status
 */
export function getFeaturesByStatus(
  status: FeatureStatus,
): Array<{ name: FeatureName; flag: FeatureFlag }> {
  return Object.entries(FEATURES)
    .filter(([, flag]) => flag.status === status)
    .map(([name, flag]) => ({ name: name as FeatureName, flag }));
}

/**
 * Get all features that should be shown in UI
 */
export function getVisibleFeatures(): Array<{ name: FeatureName; flag: FeatureFlag }> {
  return Object.entries(FEATURES)
    .filter(([, flag]) => flag.showInUI)
    .map(([name, flag]) => ({ name: name as FeatureName, flag }));
}

/**
 * Enable a feature at runtime (persists to localStorage)
 */
export function enableFeature(feature: FeatureName): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(`feature_${feature}`, 'true');
  }
}

/**
 * Disable a feature at runtime (persists to localStorage)
 */
export function disableFeature(feature: FeatureName): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(`feature_${feature}`, 'false');
  }
}

/**
 * Reset a feature to its default state
 */
export function resetFeature(feature: FeatureName): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(`feature_${feature}`);
  }
}

/**
 * Reset all features to their default states
 */
export function resetAllFeatures(): void {
  if (typeof window !== 'undefined') {
    Object.keys(FEATURES).forEach((feature) => {
      localStorage.removeItem(`feature_${feature}`);
    });
  }
}
