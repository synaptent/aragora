'use client';

import { useState } from 'react';
import { API_BASE_URL } from '@/config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CritiqueResult {
  agent: string;
  target_agent: string;
  issues: string[];
  suggestions: string[];
  severity: number;
}

interface VoteResult {
  agent: string;
  choice: string;
  confidence: number;
  reasoning: string;
}

interface ReceiptResult {
  receipt_id: string;
  question: string;
  verdict: string;
  confidence: number;
  consensus: {
    reached: boolean;
    method: string;
    confidence: number;
    supporting_agents: string[];
    dissenting_agents: string[];
  };
  agents: string[];
  rounds_used: number;
  timestamp: string;
  signature: string | null;
  signature_algorithm: string | null;
}

interface DebateResponse {
  id: string;
  topic: string;
  status: string;
  rounds_used: number;
  consensus_reached: boolean;
  confidence: number;
  verdict: string | null;
  duration_seconds: number;
  participants: string[];
  proposals: Record<string, string>;
  critiques: CritiqueResult[];
  votes: VoteResult[];
  dissenting_views: string[];
  final_answer: string;
  receipt: ReceiptResult | null;
  receipt_hash: string | null;
}

// ---------------------------------------------------------------------------
// Agent color mapping
// ---------------------------------------------------------------------------

const AGENT_COLORS: Record<string, string> = {
  analyst: 'text-[var(--acid-cyan)]',
  critic: 'text-[var(--crimson)]',
  moderator: 'text-[var(--acid-green)]',
  contrarian: 'text-[var(--acid-yellow)]',
  synthesizer: 'text-[var(--acid-magenta)]',
};

function agentColor(name: string): string {
  return AGENT_COLORS[name] || 'text-[var(--acid-cyan)]';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Playground() {
  const [topic, setTopic] = useState('');
  const [rounds, setRounds] = useState(2);
  const [agents, setAgents] = useState(3);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DebateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const apiBase = API_BASE_URL;

  async function runDebate() {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch(`${apiBase}/api/v1/playground/debate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topic || undefined, rounds, agents }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || `Request failed (${res.status})`);
        return;
      }

      setResult(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Network error';
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)] font-theme-data">
      {/* Header */}
      <header className="border-b border-[var(--border)] px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl text-[var(--acid-green)] font-bold">aragora playground</h1>
            <p className="text-xs text-[var(--text-muted)] mt-1">
              Run a multi-agent adversarial debate -- no signup, no API keys
            </p>
          </div>
          <a
            href="/"
            className="text-xs text-[var(--acid-cyan)] hover:text-[var(--acid-green)] transition-colors"
          >
            Back to Dashboard
          </a>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8">
        {/* Input Section */}
        <section className="border border-[var(--border)] p-6 mb-8">
          <label htmlFor="topic-input" className="block text-sm text-[var(--acid-cyan)] mb-2">
            Debate Topic
          </label>
          <input
            id="topic-input"
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="Should we use microservices or a monolith?"
            className="w-full bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] px-4 py-3 font-theme-data text-sm placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)] transition-colors"
            disabled={loading}
          />

          {/* Settings row */}
          <div className="flex items-center gap-6 mt-4">
            <div>
              <label htmlFor="rounds-select" className="text-xs text-[var(--text-muted)] mr-2">
                Rounds:
              </label>
              <select
                id="rounds-select"
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
                disabled={loading}
                className="bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] px-2 py-1 text-sm font-theme-data focus:outline-none focus:border-[var(--acid-green)]"
              >
                <option value={1}>1</option>
                <option value={2}>2</option>
              </select>
            </div>
            <div>
              <label htmlFor="agents-select" className="text-xs text-[var(--text-muted)] mr-2">
                Agents:
              </label>
              <select
                id="agents-select"
                value={agents}
                onChange={(e) => setAgents(Number(e.target.value))}
                disabled={loading}
                className="bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] px-2 py-1 text-sm font-theme-data focus:outline-none focus:border-[var(--acid-green)]"
              >
                <option value={2}>2</option>
                <option value={3}>3</option>
                <option value={4}>4</option>
                <option value={5}>5</option>
              </select>
            </div>
          </div>

          {/* Run button */}
          <button
            onClick={runDebate}
            disabled={loading}
            className="mt-6 px-8 py-3 bg-[var(--acid-green)] text-[var(--bg)] font-bold text-sm hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Running debate...' : 'Run Debate'}
          </button>
        </section>

        {/* Loading spinner */}
        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="flex items-center gap-3 text-[var(--acid-green)]">
              <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              <span className="text-sm">Agents are debating...</span>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="border border-[var(--crimson)] bg-[var(--crimson)]/10 p-4 mb-8">
            <p className="text-sm text-[var(--crimson)]">{error}</p>
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-6">
            {/* Summary bar */}
            <section className="border border-[var(--border)] p-4 flex flex-wrap gap-4 items-center text-sm">
              <span
                className={
                  result.consensus_reached ? 'text-[var(--acid-green)]' : 'text-[var(--warning)]'
                }
              >
                {result.consensus_reached ? 'Consensus Reached' : 'No Consensus'}
              </span>
              <span className="text-[var(--text-muted)]">|</span>
              <span className="text-[var(--text-muted)]">
                Confidence: {(result.confidence * 100).toFixed(0)}%
              </span>
              <span className="text-[var(--text-muted)]">|</span>
              <span className="text-[var(--text-muted)]">
                {result.rounds_used} round{result.rounds_used !== 1 ? 's' : ''}
              </span>
              <span className="text-[var(--text-muted)]">|</span>
              <span className="text-[var(--text-muted)]">{result.duration_seconds}s</span>
              {result.verdict && (
                <>
                  <span className="text-[var(--text-muted)]">|</span>
                  <span className="text-[var(--acid-cyan)]">
                    {result.verdict.replace(/_/g, ' ')}
                  </span>
                </>
              )}
            </section>

            {/* Proposals */}
            <section className="border border-[var(--border)] p-4">
              <h2 className="text-sm text-[var(--acid-green)] mb-4 font-bold">Proposals</h2>
              <div className="space-y-4">
                {Object.entries(result.proposals).map(([agent, content]) => (
                  <div key={agent}>
                    <h3 className={`text-sm font-bold mb-1 ${agentColor(agent)}`}>{agent}</h3>
                    <p className="text-xs text-[var(--text-muted)] whitespace-pre-wrap leading-relaxed">
                      {content}
                    </p>
                  </div>
                ))}
              </div>
            </section>

            {/* Critiques */}
            {result.critiques.length > 0 && (
              <section className="border border-[var(--border)] p-4">
                <h2 className="text-sm text-[var(--acid-green)] mb-4 font-bold">Critiques</h2>
                <div className="space-y-3">
                  {result.critiques.map((c, i) => (
                    <div key={i} className="border-l-2 border-[var(--border)] pl-3">
                      <div className="text-xs mb-1">
                        <span className={agentColor(c.agent)}>{c.agent}</span>
                        <span className="text-[var(--text-muted)]"> on </span>
                        <span className={agentColor(c.target_agent)}>{c.target_agent}</span>
                        <span className="text-[var(--text-muted)] ml-2">
                          severity {c.severity.toFixed(1)}/10
                        </span>
                      </div>
                      <ul className="text-xs text-[var(--text-muted)] space-y-0.5">
                        {c.issues.map((issue, j) => (
                          <li key={j} className="flex items-start gap-1">
                            <span className="text-[var(--crimson)]">-</span>
                            {issue}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Votes */}
            {result.votes.length > 0 && (
              <section className="border border-[var(--border)] p-4">
                <h2 className="text-sm text-[var(--acid-green)] mb-4 font-bold">Votes</h2>
                <div className="space-y-2">
                  {result.votes.map((v, i) => (
                    <div key={i} className="text-xs flex items-center gap-2">
                      <span className={agentColor(v.agent)}>{v.agent}</span>
                      <span className="text-[var(--text-muted)]">voted for</span>
                      <span className={`font-bold ${agentColor(v.choice)}`}>{v.choice}</span>
                      <span className="text-[var(--text-muted)]">
                        ({(v.confidence * 100).toFixed(0)}%)
                      </span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Dissenting views */}
            {result.dissenting_views.length > 0 && (
              <section className="border border-[var(--warning)]/30 bg-[var(--warning)]/5 p-4">
                <h2 className="text-sm text-[var(--warning)] mb-2 font-bold">Dissenting Views</h2>
                <ul className="text-xs text-[var(--text-muted)] space-y-1">
                  {result.dissenting_views.map((d, i) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
              </section>
            )}

            {/* Receipt */}
            {result.receipt && (
              <section className="border border-[var(--acid-green)]/30 p-4">
                <h2 className="text-sm text-[var(--acid-green)] mb-3 font-bold">
                  Decision Receipt
                </h2>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-[var(--text-muted)]">Receipt ID: </span>
                    <span className="text-[var(--acid-cyan)]">{result.receipt.receipt_id}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Verdict: </span>
                    <span className="text-[var(--acid-green)]">
                      {result.receipt.verdict.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Method: </span>
                    <span>{result.receipt.consensus.method}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Timestamp: </span>
                    <span>{result.receipt.timestamp}</span>
                  </div>
                </div>
                {result.receipt_hash && (
                  <div className="mt-3 text-xs">
                    <span className="text-[var(--text-muted)]">Hash: </span>
                    <code className="text-[var(--acid-green)]/70 break-all">
                      {result.receipt_hash}
                    </code>
                  </div>
                )}
              </section>
            )}
          </div>
        )}

        {/* Return to landing after debate completes */}
        {result && (
          <div className="mt-8 py-6 border-t border-[var(--border)] text-center space-y-3">
            <p className="text-sm text-[var(--text-muted)]">
              Want deeper analysis with real AI models?
            </p>
            <div className="flex items-center justify-center gap-4">
              <a
                href="/login"
                className="px-6 py-3 bg-[var(--acid-green)] text-[var(--bg)] font-bold text-sm hover:opacity-90 transition-opacity"
              >
                SIGN IN FOR REAL MODELS
              </a>
              <a
                href="/"
                className="px-6 py-3 border border-[var(--border)] text-[var(--text-muted)] text-sm hover:text-[var(--acid-green)] hover:border-[var(--acid-green)] transition-colors"
              >
                BACK TO LANDING
              </a>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-[var(--border)] px-6 py-4 mt-8">
        <div className="max-w-4xl mx-auto text-center text-xs text-[var(--text-muted)]">
          <p>
            Powered by <span className="text-[var(--acid-green)]">aragora-debate</span> with
            MockAgents. No real LLM calls are made.
          </p>
        </div>
      </footer>
    </div>
  );
}
