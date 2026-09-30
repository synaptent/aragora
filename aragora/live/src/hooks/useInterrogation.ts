'use client';

import { useState, useCallback } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export interface Dimension {
  name: string;
  description: string;
  vagueness_score: number;
}

export interface InterrogationQuestion {
  text: string;
  why: string;
  options: string[];
  context: string;
  priority: number;
}

export interface Requirement {
  description: string;
  level: 'must' | 'should' | 'could';
  dimension: string;
}

export interface Spec {
  problem_statement: string;
  requirements: Requirement[];
  non_requirements: string[];
  success_criteria: string[];
  risks: string[];
  context_summary: string;
}

export type InterrogationStage =
  'idle' | 'decomposing' | 'questioning' | 'crystallizing' | 'complete';

export function useInterrogation() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [dimensions, setDimensions] = useState<Dimension[]>([]);
  const [questions, setQuestions] = useState<InterrogationQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [spec, setSpec] = useState<Spec | null>(null);
  const [stage, setStage] = useState<InterrogationStage>('idle');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const start = useCallback(async (prompt: string) => {
    setStage('decomposing');
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/interrogation/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      });
      if (!res.ok) throw new Error('Failed to start');
      const json = await res.json();
      const data = json.data;
      setSessionId(data.session_id);
      setDimensions(data.dimensions);
      setQuestions(data.questions);
      setStage(data.questions.length > 0 ? 'questioning' : 'crystallizing');
    } catch {
      setError('Failed to start interrogation');
      setStage('idle');
    } finally {
      setLoading(false);
    }
  }, []);

  const answer = useCallback(
    async (questionText: string, answerText: string) => {
      if (!sessionId) return;
      setAnswers((prev) => ({ ...prev, [questionText]: answerText }));
      try {
        const res = await fetch(`${API_BASE}/api/v1/interrogation/answer`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessionId,
            question: questionText,
            answer: answerText,
          }),
        });
        if (!res.ok) throw new Error('Failed to answer');
        const json = await res.json();
        if (json.data.is_complete) {
          setStage('crystallizing');
        }
      } catch {
        setError('Failed to submit answer');
      }
    },
    [sessionId],
  );

  const crystallize = useCallback(async () => {
    if (!sessionId) return;
    setStage('crystallizing');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/interrogation/crystallize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      });
      if (!res.ok) throw new Error('Failed to crystallize');
      const json = await res.json();
      setSpec(json.data.spec);
      setStage('complete');
    } catch {
      setError('Failed to crystallize spec');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const reset = useCallback(() => {
    setSessionId(null);
    setDimensions([]);
    setQuestions([]);
    setAnswers({});
    setSpec(null);
    setStage('idle');
    setError(null);
    setLoading(false);
  }, []);

  return {
    sessionId,
    dimensions,
    questions,
    answers,
    spec,
    stage,
    error,
    loading,
    start,
    answer,
    crystallize,
    reset,
  };
}
