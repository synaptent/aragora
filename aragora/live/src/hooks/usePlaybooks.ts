'use client';

import { useState, useCallback, useEffect } from 'react';
import { useApi } from './useApi';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PlaybookStep {
  name: string;
  action: string;
  config: Record<string, unknown>;
}

export interface ApprovalGate {
  name: string;
  description: string;
  required_role: string;
  auto_approve_if_consensus: boolean;
  timeout_hours: number;
}

export interface Playbook {
  id: string;
  name: string;
  description: string;
  category: string;
  template_name: string;
  vertical_profile: string | null;
  compliance_artifacts: string[];
  min_agents: number;
  max_agents: number;
  required_agent_types: string[];
  agent_selection_strategy: string;
  max_rounds: number;
  consensus_threshold: number;
  timeout_seconds: number;
  output_format: string;
  output_channels: string[];
  approval_gates: ApprovalGate[];
  steps: PlaybookStep[];
  tags: string[];
  version: string;
  metadata: Record<string, unknown>;
}

interface PlaybookListResponse {
  playbooks: Playbook[];
  count: number;
}

export interface PlaybookRunResult {
  run_id: string;
  playbook_id: string;
  playbook_name: string;
  input: string;
  context: Record<string, unknown>;
  status: string;
  created_at: string;
  steps: PlaybookStep[];
  config: {
    template_name: string;
    vertical_profile: string | null;
    min_agents: number;
    max_agents: number;
    max_rounds: number;
    consensus_threshold: number;
  };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function usePlaybooks() {
  const listApi = useApi<PlaybookListResponse>();
  const runApi = useApi<PlaybookRunResult>();

  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [selectedPlaybook, setSelectedPlaybook] = useState<Playbook | null>(null);

  // Fetch all playbooks, optionally filtered by category
  const fetchPlaybooks = useCallback(
    async (category?: string) => {
      const query = category ? `?category=${encodeURIComponent(category)}` : '';
      try {
        const result = await listApi.get(`/api/v1/playbooks${query}`);
        if (result?.playbooks) {
          setPlaybooks(result.playbooks);
        }
        return result;
      } catch {
        // Error state is managed by useApi
        return null;
      }
    },
    [listApi],
  );

  // Launch a playbook by ID
  const runPlaybook = useCallback(
    async (playbookId: string, input: string, context?: Record<string, unknown>) => {
      try {
        const result = await runApi.post(
          `/api/v1/playbooks/${encodeURIComponent(playbookId)}/run`,
          { input, context: context ?? {} },
        );
        return result;
      } catch {
        return null;
      }
    },
    [runApi],
  );

  // Fetch on mount
  useEffect(() => {
    fetchPlaybooks();
    // Only run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    playbooks,
    selectedPlaybook,
    setSelectedPlaybook,
    fetchPlaybooks,
    runPlaybook,
    loading: listApi.loading,
    launching: runApi.loading,
    error: listApi.error,
    launchError: runApi.error,
  };
}
