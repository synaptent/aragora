'use client';

import { useState, useCallback } from 'react';
import {
  usePromptEngine,
  type PipelineStage,
  type ClarifyingQuestion,
  type Specification,
  type ValidationResult,
  type RiskItem,
} from '@/hooks/usePromptEngine';

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const STAGES: { key: PipelineStage; label: string }[] = [
  { key: 'decompose', label: 'Decompose' },
  { key: 'interrogate', label: 'Interrogate' },
  { key: 'research', label: 'Research' },
  { key: 'specify', label: 'Specify' },
];

function PipelineProgress({ current, completed }: { current: PipelineStage; completed: string[] }) {
  return (
    <div className="flex items-center gap-1 font-mono text-xs">
      {STAGES.map((s, i) => {
        const done = completed.includes(s.key);
        const active = current === s.key;
        return (
          <span key={s.key} className="flex items-center gap-1">
            {i > 0 && <span className="text-acid-green/30">{'\u2192'}</span>}
            <span
              className={
                done
                  ? 'text-acid-green'
                  : active
                    ? 'text-acid-cyan animate-pulse'
                    : 'text-acid-green/30'
              }
            >
              {done ? '\u2713' : active ? '\u25B6' : '\u25CB'} {s.label}
            </span>
          </span>
        );
      })}
    </div>
  );
}

function QuestionsPanel({
  questions,
  onAnswer,
}: {
  questions: ClarifyingQuestion[];
  onAnswer: (idx: number, answer: string) => void;
}) {
  if (questions.length === 0) return null;

  return (
    <div className="border border-acid-green/20 rounded p-4 space-y-4">
      <h3 className="text-acid-cyan font-mono text-sm uppercase tracking-wider">
        Clarifying Questions ({questions.length})
      </h3>
      {questions.map((q, i) => (
        <div key={i} className="space-y-2">
          <p className="text-acid-green font-mono text-sm">
            <span className="text-acid-cyan">Q{i + 1}:</span> {q.question}
          </p>
          <p className="text-acid-green/60 text-xs font-mono">{q.why_it_matters}</p>
          {q.options.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {q.options.map((opt, j) => (
                <button
                  key={j}
                  onClick={() => onAnswer(i, opt.label)}
                  className={`px-3 py-1 text-xs font-mono border rounded transition-colors ${
                    q.answer === opt.label
                      ? 'border-acid-cyan text-acid-cyan bg-acid-cyan/10'
                      : 'border-acid-green/30 text-acid-green hover:border-acid-green'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}
          {q.answer && (
            <p className="text-acid-green/80 text-xs font-mono">
              {'\u2713'} {q.answer}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const filled = Math.round(value * 10);
  const bar = '\u2588'.repeat(filled) + '\u2591'.repeat(10 - filled);
  return (
    <span className="font-mono text-xs">
      <span className={value >= 0.8 ? 'text-acid-green' : value >= 0.5 ? 'text-amber-400' : 'text-crimson'}>
        {bar}
      </span>{' '}
      {pct}%
    </span>
  );
}

function ValidationBadge({ validation }: { validation: ValidationResult }) {
  return (
    <div className="border border-acid-green/20 rounded p-3 space-y-2">
      <div className="flex items-center gap-2">
        <span
          className={`font-mono text-sm font-bold ${validation.passed ? 'text-acid-green' : 'text-crimson'}`}
        >
          {validation.passed ? '\u2713 PASSED' : '\u2717 FAILED'}
        </span>
        <ConfidenceBar value={validation.overall_confidence} />
      </div>
      {validation.dissenting_opinions.length > 0 && (
        <div className="space-y-1">
          {validation.dissenting_opinions.map((d, i) => (
            <p key={i} className="text-amber-400/80 text-xs font-mono">
              {'\u26A0'} {d}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function SpecificationView({ spec, validation }: { spec: Specification; validation: ValidationResult | null }) {
  return (
    <div className="border border-acid-green/20 rounded p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-acid-cyan font-mono text-sm uppercase tracking-wider">Specification</h3>
        <ConfidenceBar value={spec.confidence} />
      </div>

      <div>
        <h4 className="text-acid-green font-mono text-lg">{spec.title}</h4>
        {spec.estimated_effort && (
          <span className="text-acid-green/60 text-xs font-mono">Effort: {spec.estimated_effort}</span>
        )}
      </div>

      <Section title="Problem">{spec.problem_statement}</Section>
      <Section title="Solution">{spec.proposed_solution}</Section>

      {spec.implementation_plan.length > 0 && (
        <div>
          <SectionHeader>Implementation Plan</SectionHeader>
          <ol className="list-decimal list-inside space-y-1 text-acid-green/80 text-sm font-mono">
            {spec.implementation_plan.map((step, i) => (
              <li key={i}>{typeof step === 'string' ? step : JSON.stringify(step)}</li>
            ))}
          </ol>
        </div>
      )}

      {spec.risk_register.length > 0 && (
        <div>
          <SectionHeader>Risks</SectionHeader>
          <div className="space-y-2">
            {spec.risk_register.map((r: RiskItem, i: number) => (
              <div key={i} className="text-xs font-mono border-l-2 border-amber-400/30 pl-3">
                <span className="text-amber-400">{r.likelihood}/{r.impact}</span>{' '}
                <span className="text-acid-green/80">{r.description}</span>
                {r.mitigation && (
                  <p className="text-acid-green/60 mt-0.5">{'\u2192'} {r.mitigation}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {spec.success_criteria.length > 0 && (
        <div>
          <SectionHeader>Success Criteria</SectionHeader>
          <ul className="space-y-1">
            {spec.success_criteria.map((c, i) => (
              <li key={i} className="text-acid-green/80 text-sm font-mono">
                {'\u2713'} {typeof c === 'string' ? c : (c as { description: string }).description}
              </li>
            ))}
          </ul>
        </div>
      )}

      {validation && <ValidationBadge validation={validation} />}
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return <h4 className="text-acid-cyan/80 font-mono text-xs uppercase tracking-wider mb-1">{children}</h4>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  if (!children) return null;
  return (
    <div>
      <SectionHeader>{title}</SectionHeader>
      <p className="text-acid-green/80 text-sm font-mono whitespace-pre-wrap">{children}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type ProfileKey = 'founder' | 'cto' | 'business' | 'team';

const PROFILES: { key: ProfileKey; label: string }[] = [
  { key: 'founder', label: 'Founder' },
  { key: 'cto', label: 'CTO' },
  { key: 'business', label: 'Business' },
  { key: 'team', label: 'Team' },
];

export default function PromptEnginePage() {
  const engine = usePromptEngine();
  const [prompt, setPrompt] = useState('');
  const [profile, setProfile] = useState<ProfileKey>('founder');

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!prompt.trim() || engine.isRunning) return;
      engine.runPipeline(prompt.trim(), { profile });
    },
    [prompt, profile, engine],
  );

  const handleAnswer = useCallback(
    (idx: number, answer: string) => {
      engine.answerQuestions({ [idx]: answer });
    },
    [engine],
  );

  return (
    <div className="min-h-screen bg-bg p-4 md:p-8">
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h1 className="text-acid-green font-mono font-bold text-xl">[SPEC GENERATOR]</h1>
          {engine.currentStage !== 'idle' && (
            <button
              onClick={engine.reset}
              className="text-acid-green/60 hover:text-acid-green text-xs font-mono border border-acid-green/30 px-2 py-1 rounded transition-colors"
            >
              Reset
            </button>
          )}
        </div>
        <p className="text-acid-green/60 font-mono text-sm">
          Describe what you want to build. The engine decomposes your idea, asks clarifying
          questions, researches context, and produces a validated specification.
        </p>

        {/* Input form */}
        <form onSubmit={handleSubmit} className="space-y-3">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="I want to improve the onboarding flow..."
            rows={4}
            disabled={engine.isRunning}
            className="w-full bg-bg border border-acid-green/30 rounded p-3 text-acid-green font-mono text-sm placeholder:text-acid-green/30 focus:outline-none focus:border-acid-cyan resize-y disabled:opacity-50"
          />
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <label className="text-acid-green/60 font-mono text-xs">Profile:</label>
              <select
                value={profile}
                onChange={(e) => setProfile(e.target.value as ProfileKey)}
                disabled={engine.isRunning}
                className="bg-bg border border-acid-green/30 rounded px-2 py-1 text-acid-green font-mono text-xs focus:outline-none focus:border-acid-cyan disabled:opacity-50"
              >
                {PROFILES.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={!prompt.trim() || engine.isRunning}
              className="ml-auto px-4 py-2 bg-acid-green/10 border border-acid-green/30 text-acid-green font-mono text-sm rounded hover:bg-acid-green/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {engine.isRunning ? 'Running...' : 'Generate Specification \u2192'}
            </button>
          </div>
        </form>

        {/* Pipeline progress */}
        {engine.currentStage !== 'idle' && (
          <PipelineProgress current={engine.currentStage} completed={engine.stagesCompleted} />
        )}

        {/* Error */}
        {engine.error && (
          <div className="border border-crimson/30 rounded p-3 text-crimson font-mono text-sm">
            {'\u2717'} {engine.error}
          </div>
        )}

        {/* Intent summary */}
        {engine.intent && (
          <div className="border border-acid-green/20 rounded p-3 space-y-1">
            <h3 className="text-acid-cyan font-mono text-xs uppercase tracking-wider">Intent</h3>
            <p className="text-acid-green/80 text-sm font-mono">
              <span className="text-acid-cyan">{engine.intent.intent_type}</span>
              {engine.intent.summary && ` \u2014 ${engine.intent.summary}`}
            </p>
            {engine.intent.domains.length > 0 && (
              <p className="text-acid-green/50 text-xs font-mono">
                Domains: {engine.intent.domains.join(', ')}
              </p>
            )}
          </div>
        )}

        {/* Questions */}
        <QuestionsPanel questions={engine.questions} onAnswer={handleAnswer} />

        {/* Research summary */}
        {engine.research && (
          <div className="border border-acid-green/20 rounded p-3 space-y-1">
            <h3 className="text-acid-cyan font-mono text-xs uppercase tracking-wider">Research</h3>
            <p className="text-acid-green/80 text-sm font-mono whitespace-pre-wrap">
              {engine.research.summary}
            </p>
            {engine.research.recommendations.length > 0 && (
              <div className="mt-2 space-y-1">
                {engine.research.recommendations.map((r, i) => (
                  <p key={i} className="text-acid-green/60 text-xs font-mono">
                    {'\u2192'} {r}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Specification */}
        {engine.specification && (
          <SpecificationView spec={engine.specification} validation={engine.validation} />
        )}
      </div>
    </div>
  );
}
