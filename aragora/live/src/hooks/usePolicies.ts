'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '@/config';

const API_BASE = API_BASE_URL;

// ============================================================================
// Types
// ============================================================================

export interface PolicyRule {
  rule_id: string;
  name: string;
  description: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  enabled: boolean;
  custom_threshold?: number;
  metadata?: Record<string, unknown>;
}

export interface Policy {
  id: string;
  name: string;
  description: string;
  framework_id: string;
  workspace_id: string;
  vertical_id: string;
  level: 'mandatory' | 'recommended' | 'optional';
  enabled: boolean;
  rules: PolicyRule[];
  rules_count: number;
  created_at: string;
  updated_at: string;
  created_by?: string;
  metadata?: Record<string, unknown>;
}

export interface Violation {
  id: string;
  policy_id: string;
  rule_id: string;
  rule_name: string;
  framework_id: string;
  vertical_id: string;
  workspace_id: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  status: 'open' | 'investigating' | 'resolved' | 'false_positive';
  description: string;
  source: string;
  detected_at: string;
  resolved_at?: string;
  resolved_by?: string;
  resolution_notes?: string;
  metadata?: Record<string, unknown>;
}

export interface PolicyStats {
  policies: { total: number; enabled: number; disabled: number };
  violations: {
    total: number;
    open: number;
    by_severity: { critical: number; high: number; medium: number; low: number };
  };
  risk_score: number;
}

export interface CreatePolicyData {
  name: string;
  description?: string;
  framework_id: string;
  vertical_id: string;
  workspace_id?: string;
  level?: 'mandatory' | 'recommended' | 'optional';
  enabled?: boolean;
  rules?: Partial<PolicyRule>[];
  metadata?: Record<string, unknown>;
}

export interface UpdatePolicyData {
  name?: string;
  description?: string;
  level?: 'mandatory' | 'recommended' | 'optional';
  enabled?: boolean;
  rules?: Partial<PolicyRule>[];
  metadata?: Record<string, unknown>;
}

export interface PoliciesFilters {
  workspace_id?: string;
  vertical_id?: string;
  framework_id?: string;
  enabled_only?: boolean;
}

export interface ViolationsFilters {
  workspace_id?: string;
  vertical_id?: string;
  framework_id?: string;
  policy_id?: string;
  status?: Violation['status'];
  severity?: Violation['severity'];
}

interface UsePoliciesState {
  policies: Policy[];
  violations: Violation[];
  stats: PolicyStats | null;
  loading: boolean;
  error: string | null;
}

// ============================================================================
// Hook
// ============================================================================

export interface UsePoliciesOptions {
  /** Initial filters for policies */
  policyFilters?: PoliciesFilters;
  /** Initial filters for violations */
  violationFilters?: ViolationsFilters;
  /** Auto-load on mount */
  autoLoad?: boolean;
}

export interface UsePoliciesReturn extends UsePoliciesState {
  // Data helpers
  openViolations: Violation[];
  criticalViolations: Violation[];
  riskScore: number;

  // Load methods
  loadPolicies: (filters?: PoliciesFilters) => Promise<void>;
  loadViolations: (filters?: ViolationsFilters) => Promise<void>;
  loadStats: (workspaceId?: string) => Promise<void>;
  loadAll: () => Promise<void>;
  refetch: () => Promise<void>;

  // Policy CRUD
  createPolicy: (data: CreatePolicyData) => Promise<Policy | null>;
  updatePolicy: (id: string, data: UpdatePolicyData) => Promise<Policy | null>;
  deletePolicy: (id: string) => Promise<boolean>;
  togglePolicy: (id: string, enabled?: boolean) => Promise<boolean>;

  // Violation management
  updateViolationStatus: (
    id: string,
    status: Violation['status'],
    notes?: string,
  ) => Promise<Violation | null>;

  // Compliance check
  checkCompliance: (
    content: string,
    options?: {
      frameworks?: string[];
      min_severity?: string;
      store_violations?: boolean;
      workspace_id?: string;
      source?: string;
    },
  ) => Promise<{ compliant: boolean; score: number; issue_count: number; result: unknown } | null>;
}

/**
 * Hook for managing compliance policies and violations.
 *
 * @example
 * ```tsx
 * const {
 *   policies,
 *   violations,
 *   stats,
 *   loading,
 *   createPolicy,
 *   updateViolationStatus,
 * } = usePolicies({ autoLoad: true });
 *
 * // Create a new policy
 * const policy = await createPolicy({
 *   name: 'GDPR Compliance',
 *   framework_id: 'gdpr',
 *   vertical_id: 'legal',
 * });
 *
 * // Resolve a violation
 * await updateViolationStatus(violation.id, 'resolved', 'Fixed in PR #123');
 * ```
 */
export function usePolicies(options: UsePoliciesOptions = {}): UsePoliciesReturn {
  const { policyFilters, violationFilters, autoLoad = true } = options;

  const [state, setState] = useState<UsePoliciesState>({
    policies: [],
    violations: [],
    stats: null,
    loading: true,
    error: null,
  });

  // =========================================================================
  // Load methods
  // =========================================================================

  const loadPolicies = useCallback(
    async (filters?: PoliciesFilters) => {
      setState((s) => ({ ...s, loading: true, error: null }));

      try {
        const params = new URLSearchParams();
        const f = filters || policyFilters || {};
        if (f.workspace_id) params.set('workspace_id', f.workspace_id);
        if (f.vertical_id) params.set('vertical_id', f.vertical_id);
        if (f.framework_id) params.set('framework_id', f.framework_id);
        if (f.enabled_only) params.set('enabled_only', 'true');

        const query = params.toString();
        const url = `${API_BASE}/api/policies${query ? `?${query}` : ''}`;

        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        setState((s) => ({ ...s, policies: data.policies || [], loading: false }));
      } catch (e) {
        setState((s) => ({
          ...s,
          loading: false,
          error: e instanceof Error ? e.message : 'Failed to load policies',
        }));
      }
    },
    [policyFilters],
  );

  const loadViolations = useCallback(
    async (filters?: ViolationsFilters) => {
      setState((s) => ({ ...s, loading: true, error: null }));

      try {
        const params = new URLSearchParams();
        const f = filters || violationFilters || {};
        if (f.workspace_id) params.set('workspace_id', f.workspace_id);
        if (f.vertical_id) params.set('vertical_id', f.vertical_id);
        if (f.framework_id) params.set('framework_id', f.framework_id);
        if (f.policy_id) params.set('policy_id', f.policy_id);
        if (f.status) params.set('status', f.status);
        if (f.severity) params.set('severity', f.severity);

        const query = params.toString();
        const url = `${API_BASE}/api/compliance/violations${query ? `?${query}` : ''}`;

        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        setState((s) => ({ ...s, violations: data.violations || [], loading: false }));
      } catch (e) {
        setState((s) => ({
          ...s,
          loading: false,
          error: e instanceof Error ? e.message : 'Failed to load violations',
        }));
      }
    },
    [violationFilters],
  );

  const loadStats = useCallback(async (workspaceId?: string) => {
    try {
      const params = workspaceId ? `?workspace_id=${workspaceId}` : '';
      const response = await fetch(`${API_BASE}/api/compliance/stats${params}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      setState((s) => ({ ...s, stats: data }));
    } catch {
      // Stats are optional, don't set error
    }
  }, []);

  const loadAll = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    await Promise.all([loadPolicies(), loadViolations(), loadStats()]);
    setState((s) => ({ ...s, loading: false }));
  }, [loadPolicies, loadViolations, loadStats]);

  const refetch = loadAll;

  // =========================================================================
  // Policy CRUD
  // =========================================================================

  const createPolicy = useCallback(async (data: CreatePolicyData): Promise<Policy | null> => {
    try {
      const response = await fetch(`${API_BASE}/api/policies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${response.status}`);
      }

      const result = await response.json();
      const policy = result.policy as Policy;

      // Update local state
      setState((s) => ({ ...s, policies: [...s.policies, policy] }));

      return policy;
    } catch (e) {
      setState((s) => ({
        ...s,
        error: e instanceof Error ? e.message : 'Failed to create policy',
      }));
      return null;
    }
  }, []);

  const updatePolicy = useCallback(
    async (id: string, data: UpdatePolicyData): Promise<Policy | null> => {
      try {
        const response = await fetch(`${API_BASE}/api/policies/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${response.status}`);
        }

        const result = await response.json();
        const policy = result.policy as Policy;

        // Update local state
        setState((s) => ({ ...s, policies: s.policies.map((p) => (p.id === id ? policy : p)) }));

        return policy;
      } catch (e) {
        setState((s) => ({
          ...s,
          error: e instanceof Error ? e.message : 'Failed to update policy',
        }));
        return null;
      }
    },
    [],
  );

  const deletePolicy = useCallback(async (id: string): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE}/api/policies/${id}`, { method: 'DELETE' });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${response.status}`);
      }

      // Update local state
      setState((s) => ({ ...s, policies: s.policies.filter((p) => p.id !== id) }));

      return true;
    } catch (e) {
      setState((s) => ({
        ...s,
        error: e instanceof Error ? e.message : 'Failed to delete policy',
      }));
      return false;
    }
  }, []);

  const togglePolicy = useCallback(async (id: string, enabled?: boolean): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE}/api/policies/${id}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${response.status}`);
      }

      const result = await response.json();

      // Update local state
      setState((s) => ({
        ...s,
        policies: s.policies.map((p) => (p.id === id ? { ...p, enabled: result.enabled } : p)),
      }));

      return true;
    } catch (e) {
      setState((s) => ({
        ...s,
        error: e instanceof Error ? e.message : 'Failed to toggle policy',
      }));
      return false;
    }
  }, []);

  // =========================================================================
  // Violation management
  // =========================================================================

  const updateViolationStatus = useCallback(
    async (id: string, status: Violation['status'], notes?: string): Promise<Violation | null> => {
      try {
        const response = await fetch(`${API_BASE}/api/compliance/violations/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status, resolution_notes: notes }),
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${response.status}`);
        }

        const result = await response.json();
        const violation = result.violation as Violation;

        // Update local state
        setState((s) => ({
          ...s,
          violations: s.violations.map((v) => (v.id === id ? violation : v)),
        }));

        return violation;
      } catch (e) {
        setState((s) => ({
          ...s,
          error: e instanceof Error ? e.message : 'Failed to update violation',
        }));
        return null;
      }
    },
    [],
  );

  // =========================================================================
  // Compliance check
  // =========================================================================

  const checkCompliance = useCallback(
    async (
      content: string,
      options?: {
        frameworks?: string[];
        min_severity?: string;
        store_violations?: boolean;
        workspace_id?: string;
        source?: string;
      },
    ) => {
      try {
        const response = await fetch(`${API_BASE}/api/compliance/check`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content, ...options }),
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${response.status}`);
        }

        const result = await response.json();

        // Refresh violations if storing
        if (options?.store_violations) {
          loadViolations();
        }

        return result;
      } catch (e) {
        setState((s) => ({
          ...s,
          error: e instanceof Error ? e.message : 'Failed to check compliance',
        }));
        return null;
      }
    },
    [loadViolations],
  );

  // =========================================================================
  // Auto-load
  // =========================================================================

  useEffect(() => {
    if (autoLoad) {
      loadAll();
    }
  }, [autoLoad, loadAll]);

  // =========================================================================
  // Computed values
  // =========================================================================

  const openViolations = useMemo(
    () => state.violations.filter((v) => v.status === 'open' || v.status === 'investigating'),
    [state.violations],
  );

  const criticalViolations = useMemo(
    () => openViolations.filter((v) => v.severity === 'critical'),
    [openViolations],
  );

  const riskScore = useMemo(() => {
    if (state.stats?.risk_score !== undefined) return state.stats.risk_score;

    // Calculate from violations
    return Math.min(
      100,
      openViolations.reduce((acc, v) => {
        const weights = { critical: 25, high: 10, medium: 5, low: 2 };
        return acc + (weights[v.severity] || 0);
      }, 0),
    );
  }, [state.stats, openViolations]);

  return {
    ...state,
    openViolations,
    criticalViolations,
    riskScore,
    loadPolicies,
    loadViolations,
    loadStats,
    loadAll,
    refetch,
    createPolicy,
    updatePolicy,
    deletePolicy,
    togglePolicy,
    updateViolationStatus,
    checkCompliance,
  };
}

export default usePolicies;
