'use client';

import { useState } from 'react';
import { useInterrogation } from '@/hooks/useInterrogation';
import type {
  InterrogationStage,
  InterrogationQuestion,
  Requirement,
} from '@/hooks/useInterrogation';

const STAGES: InterrogationStage[] = [
  'idle',
  'decomposing',
  'questioning',
  'crystallizing',
  'complete',
];
const STAGE_LABELS: Record<InterrogationStage, string> = {
  idle: 'READY',
  decomposing: 'DECOMPOSING',
  questioning: 'QUESTIONING',
  crystallizing: 'CRYSTALLIZING',
  complete: 'SPEC READY',
};

function VaguenessBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  return (
    <div className="flex items-center gap-2 text-xs font-theme-data">
      <div className="flex-1 h-1.5 bg-[var(--surface)] border border-[var(--border)] rounded-sm overflow-hidden">
        <div
          className="h-full bg-[var(--acid-green)] transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[var(--acid-green)] w-8 text-right">{pct}%</span>
    </div>
  );
}

function QuestionCard({
  question,
  onAnswer,
}: {
  question: InterrogationQuestion;
  onAnswer: (text: string) => void;
}) {
  const [custom, setCustom] = useState('');

  return (
    <div className="border border-[var(--border)] bg-[var(--surface)] p-4 rounded space-y-3 shadow-[0_0_12px_rgba(0,255,65,0.08)]">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-theme-data text-[var(--text)]">{question.text}</p>
        <span className="text-[10px] font-theme-data text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 px-1.5 py-0.5 rounded shrink-0">
          P{question.priority}
        </span>
      </div>

      <p className="text-xs font-theme-data text-[var(--text-muted)] italic">Why: {question.why}</p>

      {question.context && (
        <p className="text-xs font-theme-data text-[var(--text-muted)]">
          Context: {question.context}
        </p>
      )}

      {question.options.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {question.options.map((opt) => (
            <button
              key={opt}
              onClick={() => onAnswer(opt)}
              className="text-xs font-theme-data px-3 py-1.5 border border-[var(--acid-green)]/40 text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 hover:border-[var(--acid-green)] rounded transition-colors"
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && custom.trim()) {
              onAnswer(custom.trim());
              setCustom('');
            }
          }}
          placeholder="Or type your own answer..."
          className="flex-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data px-3 py-1.5 rounded focus:outline-none focus:border-[var(--acid-green)] placeholder:text-[var(--text-muted)]"
        />
        <button
          onClick={() => {
            if (custom.trim()) {
              onAnswer(custom.trim());
              setCustom('');
            }
          }}
          disabled={!custom.trim()}
          className="text-xs font-theme-data px-3 py-1.5 bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 rounded hover:bg-[var(--acid-green)]/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          Submit
        </button>
      </div>
    </div>
  );
}

const LEVEL_COLORS: Record<Requirement['level'], string> = {
  must: 'text-[var(--acid-green)]',
  should: 'text-[var(--acid-cyan)]',
  could: 'text-yellow-400',
};

const LEVEL_BORDER: Record<Requirement['level'], string> = {
  must: 'border-[var(--acid-green)]/40',
  should: 'border-[var(--acid-cyan)]/40',
  could: 'border-yellow-400/40',
};

export default function InterrogatePage() {
  const {
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
  } = useInterrogation();

  const [prompt, setPrompt] = useState('');

  const currentQuestion: InterrogationQuestion | undefined = questions.find(
    (q) => !answers[q.text],
  );

  const answeredCount = Object.keys(answers).length;
  const totalQuestions = questions.length;

  const handleStart = () => {
    if (prompt.trim()) {
      start(prompt.trim());
    }
  };

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)] p-4 sm:p-8 font-theme-data">
      {/* Header */}
      <div className="max-w-3xl mx-auto mb-8">
        <h1 className="text-xl sm:text-2xl font-bold text-[var(--acid-green)] tracking-wider">
          INTERROGATION ENGINE
        </h1>
        <p className="text-xs text-[var(--text-muted)] mt-1">
          Vague prompt &rarr; structured spec &rarr; execution
        </p>
      </div>

      <div className="max-w-3xl mx-auto space-y-6">
        {/* Error display */}
        {error && (
          <div className="border border-red-500/40 bg-red-500/10 text-red-400 text-xs font-theme-data px-4 py-2 rounded">
            {error}
          </div>
        )}

        {/* === Section 1: Prompt Input === */}
        <section className="border border-[var(--border)] bg-[var(--surface)] p-4 rounded shadow-[0_0_12px_rgba(0,255,65,0.15)]">
          <label className="text-xs text-[var(--acid-cyan)] uppercase tracking-wider block mb-2">
            Prompt
          </label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && e.metaKey && stage === 'idle') handleStart();
            }}
            disabled={stage !== 'idle'}
            placeholder="Describe what you want to build, decide, or explore..."
            rows={3}
            className="w-full bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-sm font-theme-data px-3 py-2 rounded focus:outline-none focus:border-[var(--acid-green)] placeholder:text-[var(--text-muted)] resize-none disabled:opacity-50"
          />
          <div className="flex items-center justify-between mt-3">
            <span className="text-[10px] text-[var(--text-muted)]">
              {stage === 'idle' ? 'Cmd+Enter to submit' : ''}
            </span>
            <div className="flex gap-2">
              {stage !== 'idle' && (
                <button
                  onClick={reset}
                  className="text-xs font-theme-data px-4 py-1.5 border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)] hover:border-[var(--acid-green)]/40 rounded transition-colors"
                >
                  Reset
                </button>
              )}
              <button
                onClick={handleStart}
                disabled={!prompt.trim() || stage !== 'idle' || loading}
                className="text-xs font-theme-data px-4 py-1.5 bg-[var(--acid-green)] text-[var(--bg)] rounded hover:brightness-110 disabled:opacity-30 disabled:cursor-not-allowed transition-all shadow-[0_0_8px_rgba(0,255,65,0.3)]"
              >
                {loading && stage === 'decomposing' ? 'Decomposing...' : 'Interrogate'}
              </button>
            </div>
          </div>
        </section>

        {/* === Section 2: Dimensions === */}
        {stage !== 'idle' && dimensions.length > 0 && (
          <section className="border border-[var(--border)] bg-[var(--surface)] p-4 rounded">
            <h2 className="text-xs text-[var(--acid-cyan)] uppercase tracking-wider mb-3">
              Dimensions ({dimensions.length})
            </h2>
            <div className="space-y-3">
              {dimensions.map((dim) => (
                <div key={dim.name}>
                  <div className="flex items-baseline justify-between mb-1">
                    <span className="text-sm text-[var(--acid-green)]">{dim.name}</span>
                  </div>
                  <p className="text-xs text-[var(--text-muted)] mb-1">{dim.description}</p>
                  <VaguenessBar score={dim.vagueness_score} />
                </div>
              ))}
            </div>
          </section>
        )}

        {/* === Section 3: Questions === */}
        {stage === 'questioning' && currentQuestion && (
          <section>
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-xs text-[var(--acid-cyan)] uppercase tracking-wider">
                Question {answeredCount + 1} of {totalQuestions}
              </h2>
              <button
                onClick={crystallize}
                className="text-[10px] font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] underline underline-offset-2 transition-colors"
              >
                Skip remaining &rarr; crystallize
              </button>
            </div>
            <QuestionCard
              question={currentQuestion}
              onAnswer={(a) => answer(currentQuestion.text, a)}
            />
          </section>
        )}

        {/* All questions answered prompt */}
        {stage === 'questioning' && !currentQuestion && (
          <section className="border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/5 p-4 rounded text-center">
            <p className="text-sm text-[var(--acid-green)] mb-3">All questions answered.</p>
            <button
              onClick={crystallize}
              disabled={loading}
              className="text-xs font-theme-data px-6 py-2 bg-[var(--acid-green)] text-[var(--bg)] rounded hover:brightness-110 disabled:opacity-30 transition-all shadow-[0_0_12px_rgba(0,255,65,0.3)]"
            >
              {loading ? 'Crystallizing...' : 'Crystallize Spec'}
            </button>
          </section>
        )}

        {/* Crystallizing spinner */}
        {stage === 'crystallizing' && loading && (
          <section className="border border-[var(--border)] bg-[var(--surface)] p-6 rounded text-center">
            <div className="animate-pulse text-[var(--acid-green)] text-sm mb-1">
              Crystallizing spec...
            </div>
            <p className="text-[10px] text-[var(--text-muted)]">
              Synthesizing answers into structured specification
            </p>
          </section>
        )}

        {/* === Section 4: Spec Output === */}
        {stage === 'complete' && spec && (
          <section className="border border-[var(--acid-green)]/30 bg-[var(--surface)] p-4 rounded space-y-4 shadow-[0_0_12px_rgba(0,255,65,0.15)]">
            <h2 className="text-xs text-[var(--acid-cyan)] uppercase tracking-wider">
              Crystallized Spec
            </h2>

            <div>
              <h3 className="text-[10px] text-[var(--text-muted)] uppercase mb-1">
                Problem Statement
              </h3>
              <p className="text-sm text-[var(--text)]">{spec.problem_statement}</p>
            </div>

            {spec.requirements.length > 0 && (
              <div>
                <h3 className="text-[10px] text-[var(--text-muted)] uppercase mb-2">
                  Requirements
                </h3>
                <div className="space-y-1.5">
                  {spec.requirements.map((req, i) => (
                    <div
                      key={i}
                      className={`flex items-start gap-2 text-xs border-l-2 ${LEVEL_BORDER[req.level]} pl-3 py-1`}
                    >
                      <span
                        className={`font-bold uppercase text-[10px] w-12 shrink-0 ${LEVEL_COLORS[req.level]}`}
                      >
                        {req.level}
                      </span>
                      <span className="text-[var(--text)]">{req.description}</span>
                      <span className="text-[var(--text-muted)] text-[10px] ml-auto shrink-0">
                        [{req.dimension}]
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {spec.non_requirements.length > 0 && (
              <div>
                <h3 className="text-[10px] text-[var(--text-muted)] uppercase mb-1">
                  Non-Requirements
                </h3>
                <ul className="text-xs text-[var(--text-muted)] space-y-0.5 list-none">
                  {spec.non_requirements.map((nr, i) => (
                    <li key={i} className="before:content-['x_'] before:text-red-400">
                      {nr}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {spec.success_criteria.length > 0 && (
              <div>
                <h3 className="text-[10px] text-[var(--text-muted)] uppercase mb-1">
                  Success Criteria
                </h3>
                <ul className="text-xs text-[var(--acid-green)]/80 space-y-0.5 list-none">
                  {spec.success_criteria.map((sc, i) => (
                    <li key={i} className="before:content-['>>_']">
                      {sc}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {spec.risks.length > 0 && (
              <div>
                <h3 className="text-[10px] text-[var(--text-muted)] uppercase mb-1">Risks</h3>
                <ul className="text-xs text-yellow-400/80 space-y-0.5 list-none">
                  {spec.risks.map((r, i) => (
                    <li key={i} className="before:content-['!_']">
                      {r}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {spec.context_summary && (
              <div>
                <h3 className="text-[10px] text-[var(--text-muted)] uppercase mb-1">
                  Context Summary
                </h3>
                <p className="text-xs text-[var(--text-muted)]">{spec.context_summary}</p>
              </div>
            )}

            {/* Execute button */}
            <div className="pt-3 border-t border-[var(--border)] flex justify-end">
              <button className="text-xs font-theme-data px-6 py-2 bg-[var(--acid-green)] text-[var(--bg)] rounded hover:brightness-110 transition-all shadow-[0_0_12px_rgba(0,255,65,0.3)]">
                Execute via Pipeline &rarr;
              </button>
            </div>
          </section>
        )}

        {/* === Bottom: Stage Progress Bar === */}
        <div className="border border-[var(--border)] bg-[var(--surface)] px-4 py-3 rounded">
          <div className="flex items-center justify-between gap-1">
            {STAGES.map((s, i) => {
              const isActive = s === stage;
              const isPast = STAGES.indexOf(stage) > i;
              return (
                <div key={s} className="flex items-center gap-1 flex-1">
                  <div
                    className={`
                      h-1.5 flex-1 rounded-sm transition-colors duration-300
                      ${isPast ? 'bg-[var(--acid-green)]' : isActive ? 'bg-[var(--acid-green)]/50 animate-pulse' : 'bg-[var(--border)]'}
                    `}
                  />
                  {i < STAGES.length - 1 && <div className="w-1" />}
                </div>
              );
            })}
          </div>
          <div className="flex justify-between mt-1.5">
            {STAGES.map((s) => (
              <span
                key={s}
                className={`text-[9px] tracking-wider ${
                  s === stage ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'
                }`}
              >
                {STAGE_LABELS[s]}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
