'use client';

import { useState, useCallback, useRef } from 'react';
import { API_BASE_URL } from '@/config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PromptIntent {
  raw_prompt: string;
  intent_type: string;
  domains: string[];
  ambiguities: Array<string | { description: string; impact: string }>;
  assumptions: Array<string | { description: string; confidence: number }>;
  scope_estimate: string;
  summary: string;
  decomposed_at: string;
}

export interface QuestionOption {
  label: string;
  description: string;
  tradeoffs?: string;
}

export interface ClarifyingQuestion {
  question: string;
  why_it_matters: string;
  options: QuestionOption[];
  default_option: string | null;
  impact_level: string;
  answer: string | null;
}

export interface ResearchReport {
  summary: string;
  current_state: string;
  codebase_findings: Record<string, unknown>[];
  past_decisions: Record<string, unknown>[];
  related_decisions: Record<string, unknown>[];
  evidence: Array<{ source: string; title: string; url?: string; relevance: number }>;
  competitive_analysis: string;
  recommendations: string[];
  researched_at: string;
}

export interface RiskItem {
  description: string;
  likelihood: string;
  impact: string;
  mitigation: string;
}

export interface Specification {
  title: string;
  problem_statement: string;
  proposed_solution: string;
  implementation_plan: string[];
  risk_register: RiskItem[];
  success_criteria: Array<string | { description: string; measurement: string; target: string }>;
  estimated_effort: string;
  status: string;
  alternatives_considered: string[];
  confidence: number;
  provenance_chain: Record<string, unknown>[];
  provenance: Record<string, unknown> | null;
  created_at: string;
}

export interface ValidationResult {
  role_results: Record<string, { passed: boolean; confidence: number; issues: string[] }>;
  overall_confidence: number;
  passed: boolean;
  dissenting_opinions: string[];
}

export interface PipelineOptions {
  profile?: 'founder' | 'cto' | 'business' | 'team';
  autonomy?: string;
  skipResearch?: boolean;
  skipInterrogation?: boolean;
  useWebSocket?: boolean;
}

export type PipelineStage = 'idle' | 'decompose' | 'interrogate' | 'research' | 'specify' | 'complete' | 'error';

export interface UsePromptEngineReturn {
  isRunning: boolean;
  currentStage: PipelineStage;
  intent: PromptIntent | null;
  questions: ClarifyingQuestion[];
  research: ResearchReport | null;
  specification: Specification | null;
  validation: ValidationResult | null;
  error: string | null;
  stagesCompleted: string[];

  runPipeline: (prompt: string, options?: PipelineOptions) => Promise<void>;
  decompose: (prompt: string) => Promise<PromptIntent | null>;
  answerQuestions: (answers: Record<number, string>) => void;
  reset: () => void;
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

const TOKENS_KEY = 'aragora_tokens';

function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(TOKENS_KEY);
  if (!stored) return null;
  try {
    return (JSON.parse(stored) as { access_token?: string }).access_token || null;
  } catch {
    return null;
  }
}

async function postApi<T>(path: string, body: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => 'Unknown error');
    throw new Error(text);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function usePromptEngine(): UsePromptEngineReturn {
  const [isRunning, setIsRunning] = useState(false);
  const [currentStage, setCurrentStage] = useState<PipelineStage>('idle');
  const [intent, setIntent] = useState<PromptIntent | null>(null);
  const [questions, setQuestions] = useState<ClarifyingQuestion[]>([]);
  const [research, setResearch] = useState<ResearchReport | null>(null);
  const [specification, setSpecification] = useState<Specification | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stagesCompleted, setStagesCompleted] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setIsRunning(false);
    setCurrentStage('idle');
    setIntent(null);
    setQuestions([]);
    setResearch(null);
    setSpecification(null);
    setValidation(null);
    setError(null);
    setStagesCompleted([]);
  }, []);

  const decompose = useCallback(async (prompt: string): Promise<PromptIntent | null> => {
    try {
      const res = await postApi<{ intent: PromptIntent }>('/api/prompt-engine/decompose', { prompt });
      setIntent(res.intent);
      return res.intent;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Decomposition failed');
      return null;
    }
  }, []);

  const answerQuestions = useCallback((answers: Record<number, string>) => {
    setQuestions(prev =>
      prev.map((q, i) => (i in answers ? { ...q, answer: answers[i] } : q))
    );
  }, []);

  const runPipeline = useCallback(async (prompt: string, options?: PipelineOptions) => {
    reset();
    setIsRunning(true);
    setCurrentStage('decompose');

    try {
      const res = await postApi<{
        specification: Specification;
        intent: PromptIntent;
        questions: ClarifyingQuestion[];
        research: ResearchReport | null;
        auto_approved: boolean;
        stages_completed: string[];
        validation: ValidationResult;
      }>('/api/prompt-engine/run', {
        prompt,
        profile: options?.profile ?? 'founder',
        autonomy: options?.autonomy,
        skip_research: options?.skipResearch ?? false,
        skip_interrogation: options?.skipInterrogation ?? false,
      });

      setIntent(res.intent);
      setCurrentStage('interrogate');
      setQuestions(res.questions);
      setCurrentStage('research');
      setResearch(res.research);
      setCurrentStage('specify');
      setSpecification(res.specification);
      setValidation(res.validation);
      setStagesCompleted(res.stages_completed);
      setCurrentStage('complete');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pipeline failed');
      setCurrentStage('error');
    } finally {
      setIsRunning(false);
    }
  }, [reset]);

  return {
    isRunning,
    currentStage,
    intent,
    questions,
    research,
    specification,
    validation,
    error,
    stagesCompleted,
    runPipeline,
    decompose,
    answerQuestions,
    reset,
  };
}
