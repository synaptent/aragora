'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { useApi } from '@/hooks/useApi';
import { useBackend } from '@/components/BackendSelector';
import { usePolicies } from '@/hooks/usePolicies';
import { ComplianceFrameworkList, type ComplianceFramework } from './ComplianceFrameworkList';
import { ViolationTracker, type ComplianceViolation } from './ViolationTracker';
import { RiskOverview } from './RiskOverview';

export type PolicyTab = 'overview' | 'frameworks' | 'violations' | 'risk';

export interface PolicyDashboardProps {
  defaultTab?: PolicyTab;
  className?: string;
  onFrameworkSelect?: (framework: ComplianceFramework) => void;
  onViolationSelect?: (violation: ComplianceViolation) => void;
}

export function PolicyDashboard({
  defaultTab = 'overview',
  className = '',
  onFrameworkSelect,
  onViolationSelect,
}: PolicyDashboardProps) {
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  // Use the policies hook for violations and stats
  const {
    violations: policyViolations,
    loading: violationsLoading,
    riskScore,
    openViolations,
    criticalViolations,
  } = usePolicies({ autoLoad: true });

  const [activeTab, setActiveTab] = useState<PolicyTab>(defaultTab);
  const [frameworks, setFrameworks] = useState<ComplianceFramework[]>([]);
  const [frameworksLoading, setFrameworksLoading] = useState(true);
  const [selectedVertical, setSelectedVertical] = useState<string | null>(null);

  // Map policy violations to ComplianceViolation format for ViolationTracker
  const violations: ComplianceViolation[] = useMemo(
    () =>
      policyViolations.map((v) => ({
        id: v.id,
        rule_id: v.rule_id,
        rule_name: v.rule_name,
        framework_id: v.framework_id,
        vertical_id: v.vertical_id,
        severity: v.severity,
        status: v.status,
        description: v.description,
        source: v.source,
        detected_at: v.detected_at,
        resolved_at: v.resolved_at,
      })),
    [policyViolations],
  );

  // Available verticals
  const verticals = useMemo(
    () => [
      { id: 'software', name: 'Software Engineering' },
      { id: 'legal', name: 'Legal' },
      { id: 'healthcare', name: 'Healthcare' },
      { id: 'accounting', name: 'Accounting & Finance' },
      { id: 'research', name: 'Research' },
    ],
    [],
  );

  // Load frameworks from verticals API
  const loadFrameworks = useCallback(async () => {
    setFrameworksLoading(true);
    try {
      const allFrameworks: ComplianceFramework[] = [];

      for (const vertical of verticals) {
        try {
          const response = (await api.get(`/api/verticals/${vertical.id}/compliance`)) as {
            compliance_frameworks: Array<{
              framework_id: string;
              name: string;
              description: string;
              level: 'mandatory' | 'recommended' | 'optional';
              rules?: Array<{ rule_id: string }>;
              enabled?: boolean;
            }>;
          };

          (response.compliance_frameworks || []).forEach((fw) => {
            allFrameworks.push({
              framework_id: fw.framework_id,
              name: fw.name,
              description: fw.description,
              level: fw.level,
              vertical_id: vertical.id,
              rules_count: fw.rules?.length || 0,
              enabled: fw.enabled ?? true,
            });
          });
        } catch {
          // Skip verticals that fail - will be empty
        }
      }

      setFrameworks(allFrameworks);
    } catch {
      setFrameworks([]);
    } finally {
      setFrameworksLoading(false);
    }
  }, [api, verticals]);

  // Load frameworks on mount
  useEffect(() => {
    loadFrameworks();
  }, [loadFrameworks]);

  // Combined loading state
  const loading = frameworksLoading || violationsLoading;

  // Stats - use values from the hook for violations
  const stats = useMemo(
    () => ({
      totalFrameworks: frameworks.length,
      enabledFrameworks: frameworks.filter((f) => f.enabled).length,
      totalRules: frameworks.reduce((acc, f) => acc + f.rules_count, 0),
      openViolations: openViolations.length,
      criticalViolations: criticalViolations.length,
      riskScore,
    }),
    [frameworks, openViolations, criticalViolations, riskScore],
  );

  const tabs: Array<{ id: PolicyTab; label: string; badge?: number }> = [
    { id: 'overview', label: 'Overview' },
    { id: 'frameworks', label: 'Frameworks', badge: stats.enabledFrameworks },
    { id: 'violations', label: 'Violations', badge: stats.openViolations },
    {
      id: 'risk',
      label: 'Risk',
      badge: stats.criticalViolations > 0 ? stats.criticalViolations : undefined,
    },
  ];

  return (
    <div className={`bg-surface border border-border rounded-lg overflow-hidden ${className}`}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-bg">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-theme-data font-bold text-[var(--accent)]">
            POLICY & COMPLIANCE
          </h2>
          <span className="text-xs text-text-muted font-theme-data">
            [{stats.totalFrameworks} FRAMEWORKS]
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-xs font-theme-data uppercase flex items-center gap-2 ${
              activeTab === tab.id
                ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-bg'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab.label}
            {tab.badge !== undefined && (
              <span
                className={`px-1.5 py-0.5 rounded text-xs ${
                  tab.id === 'violations' && tab.badge > 0
                    ? 'bg-yellow-900/30 text-yellow-400'
                    : tab.id === 'risk' && tab.badge > 0
                      ? 'bg-red-900/30 text-red-400'
                      : 'bg-surface text-text-muted'
                }`}
              >
                {tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-5 gap-4 p-4 border-b border-border bg-bg">
        <div className="text-center">
          <div className="text-xl font-theme-data text-[var(--accent)]">
            {stats.totalFrameworks}
          </div>
          <div className="text-xs text-text-muted">Frameworks</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-theme-data text-[var(--acid-cyan)]">{stats.totalRules}</div>
          <div className="text-xs text-text-muted">Rules</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-theme-data text-yellow-400">{stats.openViolations}</div>
          <div className="text-xs text-text-muted">Open Issues</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-theme-data text-red-400">{stats.criticalViolations}</div>
          <div className="text-xs text-text-muted">Critical</div>
        </div>
        <div className="text-center">
          <div
            className={`text-xl font-theme-data ${
              stats.riskScore > 70
                ? 'text-red-400'
                : stats.riskScore > 40
                  ? 'text-yellow-400'
                  : 'text-green-400'
            }`}
          >
            {stats.riskScore}
          </div>
          <div className="text-xs text-text-muted">Risk Score</div>
        </div>
      </div>

      {/* Content */}
      <div className="p-4">
        {loading ? (
          <div className="text-center py-8 text-text-muted font-theme-data">Loading...</div>
        ) : (
          <>
            {activeTab === 'overview' && (
              <RiskOverview frameworks={frameworks} violations={violations} verticals={verticals} />
            )}
            {activeTab === 'frameworks' && (
              <ComplianceFrameworkList
                frameworks={frameworks}
                onSelectFramework={onFrameworkSelect}
                verticals={verticals}
                selectedVertical={selectedVertical}
                onVerticalChange={setSelectedVertical}
              />
            )}
            {activeTab === 'violations' && (
              <ViolationTracker
                violations={violations}
                onSelectViolation={onViolationSelect}
                verticals={verticals}
                selectedVertical={selectedVertical}
                onVerticalChange={setSelectedVertical}
              />
            )}
            {activeTab === 'risk' && (
              <RiskOverview
                frameworks={frameworks}
                violations={violations}
                verticals={verticals}
                showDetails
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
