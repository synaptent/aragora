/**
 * Onboarding hook: syncs frontend onboarding state with backend API.
 *
 * Wraps the Zustand onboardingStore and adds:
 * - Backend flow initialization (POST /api/v1/onboarding/flow)
 * - Step progression sync (PUT /api/v1/onboarding/flow/step)
 * - Template fetching from backend (GET /api/v1/onboarding/templates)
 * - First debate launch (POST /api/v1/onboarding/first-debate)
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetchSafe, apiGet, apiPost, apiPut } from '@/lib/api';
import {
  useOnboardingStore,
  type OnboardingStep,
  type SelectedTemplate,
} from '@/store/onboardingStore';

// ────────────────────────────────────────────────────────────────────────────
// Types matching backend StarterTemplate
// ────────────────────────────────────────────────────────────────────────────

interface BackendTemplate {
  id: string;
  name: string;
  description: string;
  use_cases: string[];
  agents_count: number;
  rounds: number;
  estimated_minutes: number;
  example_prompt: string;
  tags: string[];
  difficulty: string;
}

interface BackendFlowResponse {
  id: string;
  user_id: string;
  current_step: string;
  completed_steps: string[];
  use_case: string | null;
  selected_template_id: string | null;
  first_debate_id: string | null;
}

interface FirstDebateResponse {
  debate_id: string;
  receipt_id?: string;
  status: string;
}

// ────────────────────────────────────────────────────────────────────────────
// Hook
// ────────────────────────────────────────────────────────────────────────────

export function useOnboarding() {
  const store = useOnboardingStore();
  const [flowId, setFlowId] = useState<string | null>(null);
  const [templates, setTemplates] = useState<SelectedTemplate[]>([]);
  const [isLoadingTemplates, setIsLoadingTemplates] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const initRef = useRef(false);

  // ── Initialize backend flow on mount ──────────────────────────────────
  const initFlow = useCallback(async (useCase?: string) => {
    if (initRef.current) return;
    initRef.current = true;

    const { data } = await apiFetchSafe<BackendFlowResponse>('/api/v1/onboarding/flow', {
      method: 'POST',
      body: JSON.stringify({ use_case: useCase || 'general' }),
    });
    if (data?.id) {
      setFlowId(data.id);
    }
  }, []);

  // ── Fetch templates from backend ──────────────────────────────────────
  const fetchTemplates = useCallback(
    async (useCase?: string) => {
      setIsLoadingTemplates(true);
      try {
        const params = useCase ? `?use_case=${encodeURIComponent(useCase)}` : '';
        const result = await apiGet<{ templates: BackendTemplate[] } | BackendTemplate[]>(
          `/api/v1/onboarding/templates${params}`,
        );

        const raw = Array.isArray(result) ? result : (result.templates ?? []);
        const mapped: SelectedTemplate[] = raw.map((t) => ({
          id: t.id,
          name: t.name,
          description: t.description,
          agentsCount: t.agents_count,
          rounds: t.rounds,
          estimatedDurationMinutes: t.estimated_minutes,
        }));

        setTemplates(mapped);
        store.setAvailableTemplates(mapped);
        return mapped;
      } catch {
        // Backend unavailable — return empty (frontend can show fallback)
        return [];
      } finally {
        setIsLoadingTemplates(false);
      }
    },
    [store],
  );

  // ── Sync step progression to backend ──────────────────────────────────
  const syncStep = useCallback(
    async (nextStep: OnboardingStep) => {
      if (!flowId) return;
      setIsSyncing(true);
      try {
        await apiPut('/api/v1/onboarding/flow/step', { flow_id: flowId, next_step: nextStep });
      } catch {
        // Sync failure is non-blocking — local state is source of truth
      } finally {
        setIsSyncing(false);
      }
    },
    [flowId],
  );

  // ── Wrapped nextStep that also syncs ──────────────────────────────────
  const nextStep = useCallback(() => {
    store.nextStep();
    // Sync the *new* current step after the store update
    const next = useOnboardingStore.getState().currentStep;
    syncStep(next);
  }, [store, syncStep]);

  // ── Launch first debate via backend ───────────────────────────────────
  const launchFirstDebate = useCallback(
    async (templateId: string, customPrompt?: string) => {
      store.setDebateStatus('creating');

      try {
        const body: Record<string, string> = { template_id: templateId };
        if (flowId) body.flow_id = flowId;
        if (customPrompt) body.custom_prompt = customPrompt;

        const result = await apiPost<FirstDebateResponse>('/api/v1/onboarding/first-debate', body);

        if (result.debate_id) {
          store.setFirstDebateId(result.debate_id);
          if (result.receipt_id) {
            store.setFirstReceiptId(result.receipt_id);
          }
          store.setDebateStatus('completed');
          store.updateProgress({ firstDebateStarted: true, firstDebateCompleted: true });
          store.updateChecklist({ firstDebateRun: true });
          return result;
        } else {
          store.setDebateStatus('error');
          store.setDebateError('No debate ID returned');
          return null;
        }
      } catch (err) {
        store.setDebateStatus('error');
        store.setDebateError(err instanceof Error ? err.message : 'Failed to launch debate');
        return null;
      }
    },
    [flowId, store],
  );

  // ── Auto-fetch templates on mount ─────────────────────────────────────
  useEffect(() => {
    if (templates.length === 0 && !isLoadingTemplates) {
      fetchTemplates(store.useCase ?? undefined);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    // Store state (passthrough)
    ...store,

    // Backend-synced actions
    initFlow,
    fetchTemplates,
    nextStep, // overrides store.nextStep with sync
    launchFirstDebate,

    // Backend state
    flowId,
    templates,
    isLoadingTemplates,
    isSyncing,
  };
}
