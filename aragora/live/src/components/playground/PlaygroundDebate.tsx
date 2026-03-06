'use client';

import { useState, useEffect, useRef, useCallback } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentEntry {
  name: string;
  role: string;
  color: string;
  proposal: string;
}

interface CritiqueEntry {
  from: string;
  to: string;
  fromColor: string;
  text: string;
  severity: number;
}

interface VoteEntry {
  agent: string;
  color: string;
  choice: string;
  confidence: number;
  reasoning?: string;
}

interface ReceiptData {
  receipt_id: string;
  verdict: string;
  confidence: number;
  method: string;
  rounds: number;
  timestamp: string;
  hash: string;
}

interface DebateResult {
  id: string;
  topic: string;
  participants: string[];
  proposals: Record<string, string>;
  critiques: Array<{
    agent: string;
    target_agent: string;
    issues: string[];
    suggestions: string[];
    severity: number;
  }>;
  votes: Array<{
    agent: string;
    choice: string;
    confidence: number;
    reasoning: string;
  }>;
  receipt: {
    receipt_id: string;
    verdict: string;
    confidence: number;
    consensus: {
      reached: boolean;
      method: string;
      confidence: number;
    };
    rounds_used: number;
    timestamp: string;
    signature: string;
  };
  final_answer: string;
  confidence: number;
  consensus_reached: boolean;
  share_url?: string;
}

// ---------------------------------------------------------------------------
// Agent colors
// ---------------------------------------------------------------------------

const AGENT_COLORS = [
  'var(--acid-cyan)',
  'var(--acid-magenta)',
  'var(--acid-green)',
  '#f59e0b',
  '#a78bfa',
];

const ROLE_LABELS = ['Analyst', 'Contrarian', 'Synthesizer', 'Strategist', 'Auditor'];

function agentColor(index: number): string {
  return AGENT_COLORS[index % AGENT_COLORS.length];
}

function agentRole(index: number): string {
  return ROLE_LABELS[index % ROLE_LABELS.length];
}

// ---------------------------------------------------------------------------
// Demo data (used when no custom topic is provided)
// ---------------------------------------------------------------------------

const DEFAULT_TOPIC = 'Should we use microservices or a monolith for our new product?';

const EXAMPLE_TOPICS = [
  'Should we migrate our monolithic app to microservices?',
  'Is it better to build our own auth system or use Auth0?',
  'Should we raise prices 15% or expand to a new market first?',
  'Build vs buy: should we develop our own data warehouse?',
  'Should we switch from REST to GraphQL for our mobile API?',
];

const DEMO_AGENTS: AgentEntry[] = [
  {
    name: 'claude-analyst',
    role: 'Analyst',
    color: 'var(--acid-cyan)',
    proposal:
      'Start with a modular monolith. You get the deployment simplicity of a single artifact, ' +
      'but enforce module boundaries at the code level. When you have clear scaling bottlenecks ' +
      'after 6-12 months, extract only those modules into services. This avoids premature ' +
      'distributed-systems complexity (network partitions, eventual consistency, service discovery) ' +
      'while preserving the option to decompose later.',
  },
  {
    name: 'gpt-contrarian',
    role: 'Contrarian',
    color: 'var(--acid-magenta)',
    proposal:
      'Go microservices from day one. The "extract later" argument sounds reasonable but almost ' +
      'never happens in practice -- monolith boundaries rot within months, and the migration cost ' +
      'grows exponentially. If you design service contracts up front, your team can deploy and ' +
      'scale independently. The operational overhead of Kubernetes is a one-time cost; the ' +
      'organizational agility is permanent.',
  },
  {
    name: 'gemini-synthesizer',
    role: 'Synthesizer',
    color: 'var(--acid-green)',
    proposal:
      'Both positions contain valid tradeoffs. The key variable is team size: below 15 engineers, ' +
      'a modular monolith reduces coordination overhead. Above 25, independent deployability ' +
      'becomes critical. My recommendation: start with the modular monolith but invest in CI/CD ' +
      'pipelines and API contracts that make future extraction low-friction. Set a 6-month ' +
      'checkpoint to evaluate scaling pressure.',
  },
];

const DEMO_CRITIQUES: CritiqueEntry[] = [
  {
    from: 'gpt-contrarian',
    to: 'claude-analyst',
    fromColor: 'var(--acid-magenta)',
    text: 'The "extract later" pattern has a <20% success rate in orgs with >50 engineers. Your proposal lacks a concrete trigger for decomposition.',
    severity: 7.2,
  },
  {
    from: 'claude-analyst',
    to: 'gpt-contrarian',
    fromColor: 'var(--acid-cyan)',
    text: 'You assume Kubernetes operational cost is "one-time" but ignore ongoing incident management, service mesh maintenance, and distributed tracing overhead for a small team.',
    severity: 6.8,
  },
  {
    from: 'gemini-synthesizer',
    to: 'gpt-contrarian',
    fromColor: 'var(--acid-green)',
    text: 'Team size is the missing variable. Your proposal optimizes for scale that may never materialize, violating YAGNI.',
    severity: 5.5,
  },
];

const DEMO_VOTES: VoteEntry[] = [
  { agent: 'claude-analyst', color: 'var(--acid-cyan)', choice: 'gemini-synthesizer', confidence: 0.82 },
  { agent: 'gpt-contrarian', color: 'var(--acid-magenta)', choice: 'gemini-synthesizer', confidence: 0.61 },
  { agent: 'gemini-synthesizer', color: 'var(--acid-green)', choice: 'gemini-synthesizer', confidence: 0.91 },
];

const DEMO_RECEIPT: ReceiptData = {
  receipt_id: 'rcpt_pg_demo_4f8a1c',
  verdict: 'CONSENSUS REACHED',
  confidence: 0.87,
  method: 'weighted_majority',
  rounds: 2,
  timestamp: new Date().toISOString().split('T')[0],
  hash: 'sha256:e3b0c44298fc1c14...a495991b7852b855',
};

const DEMO_FINAL_ANSWER =
  'Start with a modular monolith and invest in API contracts for future extraction. ' +
  'Set a 6-month checkpoint keyed to team size (> 25 engineers) and scaling pressure ' +
  'as the decomposition trigger.';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function apiResultToDisplay(result: DebateResult) {
  const participants = result.participants || [];
  const colorMap = new Map<string, string>();
  participants.forEach((p, i) => colorMap.set(p, agentColor(i)));

  const agents: AgentEntry[] = participants.map((p, i) => ({
    name: p,
    role: agentRole(i),
    color: agentColor(i),
    proposal: result.proposals?.[p] ?? '',
  }));

  const critiques: CritiqueEntry[] = (result.critiques ?? []).map((c) => ({
    from: c.agent,
    to: c.target_agent,
    fromColor: colorMap.get(c.agent) ?? 'var(--acid-cyan)',
    text: [
      ...(c.issues ?? []),
      ...(c.suggestions ?? []).map((s) => `Suggestion: ${s}`),
    ].join(' '),
    severity: c.severity,
  }));

  const votes: VoteEntry[] = (result.votes ?? []).map((v) => ({
    agent: v.agent,
    color: colorMap.get(v.agent) ?? 'var(--acid-cyan)',
    choice: v.choice,
    confidence: v.confidence,
    reasoning: v.reasoning,
  }));

  const receipt: ReceiptData = {
    receipt_id: result.receipt?.receipt_id ?? result.id,
    verdict: result.consensus_reached ? 'CONSENSUS REACHED' : 'COMPLETED',
    confidence: result.confidence ?? 0,
    method: result.receipt?.consensus?.method ?? 'weighted_majority',
    rounds: result.receipt?.rounds_used ?? 2,
    timestamp: result.receipt?.timestamp?.split('T')[0] ?? new Date().toISOString().split('T')[0],
    hash: result.receipt?.signature ?? '',
  };

  return { agents, critiques, votes, receipt, finalAnswer: result.final_answer ?? '' };
}

// ---------------------------------------------------------------------------
// Typing animation hook
// ---------------------------------------------------------------------------

function useTypewriter(text: string, active: boolean, speed = 12): string {
  const [displayed, setDisplayed] = useState('');
  const indexRef = useRef(0);

  useEffect(() => {
    if (!active) return;
    setDisplayed('');
    indexRef.current = 0;

    const interval = setInterval(() => {
      indexRef.current += 1;
      if (indexRef.current >= text.length) {
        setDisplayed(text);
        clearInterval(interval);
      } else {
        setDisplayed(text.slice(0, indexRef.current));
      }
    }, speed);

    return () => clearInterval(interval);
  }, [text, active, speed]);

  return active ? displayed : '';
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Cursor({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return <span className="animate-pulse text-[var(--acid-green)]">_</span>;
}

function PhaseLabel({ label, active }: { label: string; active: boolean }) {
  return (
    <div className={`flex items-center gap-2 mb-4 ${active ? 'opacity-100' : 'opacity-40'} transition-opacity duration-500`}>
      <span className="text-xs font-mono text-[var(--acid-green)]">{'>>'}</span>
      <span className="text-sm font-mono font-bold text-[var(--acid-green)] uppercase tracking-wider">
        {label}
      </span>
      {active && (
        <span className="ml-2 w-2 h-2 rounded-full bg-[var(--acid-green)] animate-pulse" />
      )}
    </div>
  );
}

function AgentProposal({
  agent,
  text,
  typing,
}: {
  agent: AgentEntry;
  text: string;
  typing: boolean;
}) {
  return (
    <div className="border border-[var(--border)] bg-[var(--surface)]/30 p-4 mb-3">
      <div className="flex items-center gap-2 mb-2">
        <span
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: agent.color }}
        />
        <span className="text-xs font-mono font-bold" style={{ color: agent.color }}>
          {agent.name}
        </span>
        <span className="text-xs font-mono text-[var(--text-muted)]">
          [{agent.role}]
        </span>
      </div>
      <p className="text-xs font-mono text-[var(--text)] leading-relaxed whitespace-pre-wrap">
        {text}
        <Cursor visible={typing && text.length > 0 && text.length < agent.proposal.length} />
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

type Phase = 'idle' | 'topic' | 'proposals' | 'critiques' | 'votes' | 'receipt';

const PHASE_ORDER: Phase[] = ['topic', 'proposals', 'critiques', 'votes', 'receipt'];

export interface PlaygroundDebateProps {
  /** Called when the debate completes and the receipt is shown */
  onDebateComplete?: (info: { debateId: string; shareUrl: string }) => void;
}

export function PlaygroundDebate({ onDebateComplete }: PlaygroundDebateProps = {}) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [proposalIndex, setProposalIndex] = useState(-1);
  const [critiqueIndex, setCritiqueIndex] = useState(-1);
  const [voteIndex, setVoteIndex] = useState(-1);
  const [showReceipt, setShowReceipt] = useState(false);
  const [started, setStarted] = useState(false);
  const [customTopic, setCustomTopic] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [shareUrl, setShareUrl] = useState('');
  const [debateId, setDebateId] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);

  // Live API result state
  const [liveAgents, setLiveAgents] = useState<AgentEntry[]>([]);
  const [liveCritiques, setLiveCritiques] = useState<CritiqueEntry[]>([]);
  const [liveVotes, setLiveVotes] = useState<VoteEntry[]>([]);
  const [liveReceipt, setLiveReceipt] = useState<ReceiptData | null>(null);
  const [liveFinalAnswer, setLiveFinalAnswer] = useState('');
  const [isLive, setIsLive] = useState(false);

  // Pick data source based on mode
  const agents = isLive ? liveAgents : DEMO_AGENTS;
  const critiques = isLive ? liveCritiques : DEMO_CRITIQUES;
  const votes = isLive ? liveVotes : DEMO_VOTES;
  const receipt = isLive ? liveReceipt : DEMO_RECEIPT;
  const finalAnswer = isLive ? liveFinalAnswer : DEMO_FINAL_ANSWER;
  const topic = isLive ? customTopic : DEFAULT_TOPIC;

  // Auto-scroll to bottom as content appears
  const scrollToBottom = useCallback(() => {
    if (containerRef.current) {
      containerRef.current.scrollTo({
        top: containerRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, []);

  // Typing hooks (use first 3 agents for demo, all agents for live — hook count must be stable)
  const p0 = useTypewriter(agents[0]?.proposal ?? '', proposalIndex >= 0, 8);
  const p1 = useTypewriter(agents[1]?.proposal ?? '', proposalIndex >= 1, 8);
  const p2 = useTypewriter(agents[2]?.proposal ?? '', proposalIndex >= 2, 8);
  const p3 = useTypewriter(agents[3]?.proposal ?? '', proposalIndex >= 3, 8);
  const p4 = useTypewriter(agents[4]?.proposal ?? '', proposalIndex >= 4, 8);
  const allProposals = [p0, p1, p2, p3, p4];

  const startDebate = useCallback(async () => {
    const topicText = customTopic.trim();

    if (!topicText) {
      // Demo mode — use pre-scripted animation
      setIsLive(false);
      setStarted(true);
      return;
    }

    // Live mode — call the API
    setIsLive(true);
    setLoading(true);
    setError('');
    setShareUrl('');

    try {
      const res = await fetch('/api/v1/playground/debate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topicText, rounds: 2, agents: 3 }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (res.status === 429) {
          setError(`Rate limited. Try again in ${err.retry_after ?? 60} seconds.`);
        } else {
          setError(err.error ?? `Request failed (${res.status})`);
        }
        setLoading(false);
        return;
      }

      const data: DebateResult = await res.json();
      const display = apiResultToDisplay(data);

      setLiveAgents(display.agents);
      setLiveCritiques(display.critiques);
      setLiveVotes(display.votes);
      setLiveReceipt(display.receipt);
      setLiveFinalAnswer(display.finalAnswer);
      if (data.share_url) setShareUrl(data.share_url);
      setDebateId(data.id ?? display.receipt.receipt_id);

      setLoading(false);
      setStarted(true);
    } catch {
      setError('Failed to connect. The server may be offline.');
      setLoading(false);
    }
  }, [customTopic]);

  // Orchestrate the reveal sequence (works for both demo and live)
  useEffect(() => {
    if (!started) return;

    const timers: ReturnType<typeof setTimeout>[] = [];
    let t = 0;

    // Topic reveal
    timers.push(setTimeout(() => setPhase('topic'), (t += 300)));

    // Proposals phase — one per agent
    timers.push(setTimeout(() => { setPhase('proposals'); setProposalIndex(0); }, (t += 1200)));
    for (let i = 1; i < agents.length; i++) {
      const delay = isLive ? 800 : 3500;
      timers.push(setTimeout(() => setProposalIndex(i), (t += delay)));
    }

    // Critiques phase
    timers.push(setTimeout(() => { setPhase('critiques'); setCritiqueIndex(0); }, (t += (isLive ? 1000 : 4000))));
    for (let i = 1; i < critiques.length; i++) {
      timers.push(setTimeout(() => setCritiqueIndex(i), (t += (isLive ? 400 : 1500))));
    }

    // Votes phase
    timers.push(setTimeout(() => { setPhase('votes'); setVoteIndex(0); }, (t += (isLive ? 800 : 2000))));
    for (let i = 1; i < votes.length; i++) {
      timers.push(setTimeout(() => setVoteIndex(i), (t += (isLive ? 300 : 600))));
    }

    // Receipt phase
    timers.push(setTimeout(() => { setPhase('receipt'); setShowReceipt(true); }, (t += (isLive ? 800 : 1500))));

    return () => timers.forEach(clearTimeout);
  }, [started, agents.length, critiques.length, votes.length, isLive]);

  // Notify parent when debate completes (receipt shown)
  useEffect(() => {
    if (showReceipt && onDebateComplete) {
      const id = debateId || DEMO_RECEIPT.receipt_id;
      onDebateComplete({ debateId: id, shareUrl });
    }
  }, [showReceipt, onDebateComplete, debateId, shareUrl]);

  // Scroll on phase/content changes
  useEffect(() => { scrollToBottom(); }, [phase, proposalIndex, critiqueIndex, voteIndex, showReceipt, p0, p1, p2, scrollToBottom]);

  const phaseIdx = PHASE_ORDER.indexOf(phase);

  const handleReset = useCallback(() => {
    setPhase('idle');
    setProposalIndex(-1);
    setCritiqueIndex(-1);
    setVoteIndex(-1);
    setShowReceipt(false);
    setStarted(false);
    setIsLive(false);
    setError('');
    setShareUrl('');
    setDebateId('');
    setLiveAgents([]);
    setLiveCritiques([]);
    setLiveVotes([]);
    setLiveReceipt(null);
    setLiveFinalAnswer('');
  }, []);

  return (
    <div className="w-full max-w-3xl mx-auto">
      {/* Terminal header */}
      <div className="border border-[var(--acid-green)]/40 bg-[var(--surface)]/50">
        <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--acid-green)]/20 bg-[var(--bg)]">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full border border-[var(--acid-green)]/40" />
            <span className="w-3 h-3 rounded-full border border-[var(--acid-green)]/40" />
            <span className="w-3 h-3 rounded-full border border-[var(--acid-green)]/40" />
          </div>
          <span className="text-xs font-mono text-[var(--text-muted)]">
            aragora://playground{isLive ? '/live' : '/demo'}
          </span>
          <span className="text-xs font-mono text-[var(--acid-green)]">
            {isLive ? 'LIVE' : 'DEMO'}
          </span>
        </div>

        <div ref={containerRef} className="p-6 max-h-[600px] overflow-y-auto space-y-4">
          {/* Start state */}
          {!started && !loading && (
            <div className="py-6 space-y-5">
              <div className="text-center space-y-1">
                <p className="text-sm font-mono text-[var(--text-muted)]">
                  {'>'} Watch AI agents debate any decision with adversarial rigor
                </p>
                <p className="text-xs font-mono text-[var(--text-muted)]/60">
                  Enter your question below, or pick an example — or leave blank for a demo
                </p>
              </div>

              {/* Example topics */}
              <div className="flex flex-col gap-1.5">
                {EXAMPLE_TOPICS.map((t) => (
                  <button
                    key={t}
                    onClick={() => setCustomTopic(t)}
                    className="text-left px-3 py-2 text-xs font-mono border border-[var(--acid-cyan)]/20
                               text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                  >
                    {t}
                  </button>
                ))}
              </div>

              <div className="max-w-lg mx-auto space-y-3">
                <textarea
                  value={customTopic}
                  onChange={(e) => setCustomTopic(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      startDebate();
                    }
                  }}
                  placeholder="Or type your own question..."
                  className="w-full px-4 py-3 font-mono text-xs bg-[var(--bg)] border border-[var(--acid-green)]/30 text-[var(--text)] placeholder:text-[var(--text-muted)]/40 focus:border-[var(--acid-green)] focus:outline-none resize-none"
                  rows={2}
                  maxLength={500}
                />
                {error && (
                  <p className="text-xs font-mono text-[var(--crimson,#ef4444)]">{error}</p>
                )}
                <button
                  onClick={startDebate}
                  disabled={loading}
                  className="w-full py-3 font-mono text-sm font-bold bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors disabled:opacity-50"
                >
                  {customTopic.trim() ? 'RUN DEBATE' : 'START DEMO'}
                </button>
              </div>
            </div>
          )}

          {/* Loading state */}
          {loading && (
            <div className="py-10 space-y-5">
              {/* Animated agent assembly */}
              <div className="flex items-center justify-center gap-3">
                {['Strategic Analyst', "Devil's Advocate", 'Synthesizer'].map((name, i) => (
                  <div key={name} className="flex flex-col items-center gap-1">
                    <span
                      className="w-3 h-3 rounded-full animate-pulse"
                      style={{
                        backgroundColor: ['var(--acid-cyan)', 'var(--acid-magenta)', 'var(--acid-green)'][i],
                        animationDelay: `${i * 200}ms`,
                      }}
                    />
                    <span className="text-[10px] font-mono text-[var(--text-muted)]/60 text-center hidden sm:block">
                      {name}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-xs font-mono text-center text-[var(--text-muted)]">
                Running live debate with 3 AI agents...
              </p>
              <div className="h-1 bg-[var(--acid-green)]/10 overflow-hidden max-w-xs mx-auto">
                <div
                  className="h-full bg-[var(--acid-green)] animate-pulse"
                  style={{ width: '40%', animation: 'loading-bar 2s ease-in-out infinite' }}
                />
              </div>
              <p className="text-[10px] font-mono text-center text-[var(--text-muted)]/40">
                Usually 15-30 seconds
              </p>
            </div>
          )}

          {/* Topic */}
          {started && phaseIdx >= 0 && (
            <div className="border-l-2 border-[var(--acid-green)] pl-4">
              <span className="text-xs font-mono text-[var(--text-muted)]">TOPIC</span>
              <p className="text-sm font-mono text-[var(--text)] mt-1 font-bold">
                {topic}
              </p>
              <div className="flex items-center gap-3 mt-2 text-xs font-mono text-[var(--text-muted)]">
                <span>{agents.length} agents</span>
                <span>|</span>
                <span>2 rounds</span>
                <span>|</span>
                <span>weighted majority</span>
              </div>
            </div>
          )}

          {/* Proposals */}
          {started && phaseIdx >= 1 && (
            <div>
              <PhaseLabel label="Round 1: Proposals" active={phase === 'proposals'} />
              {agents.map((agent, i) => {
                if (proposalIndex < i) return null;
                return (
                  <AgentProposal
                    key={agent.name}
                    agent={agent}
                    text={allProposals[i] ?? ''}
                    typing={proposalIndex === i}
                  />
                );
              })}
            </div>
          )}

          {/* Critiques */}
          {started && phaseIdx >= 2 && (
            <div>
              <PhaseLabel label="Round 2: Critiques" active={phase === 'critiques'} />
              {critiques.map((critique, i) => {
                if (critiqueIndex < i) return null;
                return (
                  <div
                    key={i}
                    className="border-l-2 border-[var(--border)] pl-3 mb-3 animate-in fade-in duration-300"
                  >
                    <div className="text-xs font-mono mb-1">
                      <span style={{ color: critique.fromColor }}>{critique.from}</span>
                      <span className="text-[var(--text-muted)]">{' -> '}</span>
                      <span className="text-[var(--text-muted)]">{critique.to}</span>
                      <span className="text-[var(--crimson,#ef4444)] ml-2">
                        severity {critique.severity}/10
                      </span>
                    </div>
                    <p className="text-xs font-mono text-[var(--text-muted)] leading-relaxed">
                      {critique.text}
                    </p>
                  </div>
                );
              })}
            </div>
          )}

          {/* Votes */}
          {started && phaseIdx >= 3 && (
            <div>
              <PhaseLabel label="Voting" active={phase === 'votes'} />
              <div className="space-y-2">
                {votes.map((vote, i) => {
                  if (voteIndex < i) return null;
                  return (
                    <div key={i} className="flex items-center gap-2 text-xs font-mono">
                      <span style={{ color: vote.color }}>{vote.agent}</span>
                      <span className="text-[var(--text-muted)]">voted for</span>
                      <span className="text-[var(--acid-green)] font-bold">{vote.choice}</span>
                      <span className="text-[var(--text-muted)]">
                        ({Math.round(vote.confidence * 100)}%)
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Receipt */}
          {started && showReceipt && receipt && (
            <div>
              <PhaseLabel label="Decision Receipt" active={phase === 'receipt'} />
              <div className="border border-[var(--acid-green)]/30 bg-[var(--bg)] p-4">
                <div className="flex items-center justify-between mb-4">
                  <span className="px-3 py-1 text-sm font-mono font-bold bg-[var(--acid-green)]/20 text-[var(--acid-green)] border border-[var(--acid-green)]/30">
                    {receipt.verdict}
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-[var(--text-muted)]">CONFIDENCE</span>
                    <div className="w-24 h-2 bg-[var(--bg)] border border-[var(--acid-green)]/20 overflow-hidden">
                      <div
                        className="h-full bg-[var(--acid-green)] transition-all duration-1000"
                        style={{ width: `${Math.round(receipt.confidence * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono text-[var(--acid-green)]">
                      {Math.round(receipt.confidence * 100)}%
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                  <div>
                    <span className="text-[var(--text-muted)]">Receipt ID: </span>
                    <span className="text-[var(--acid-cyan)]">{receipt.receipt_id}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Method: </span>
                    <span className="text-[var(--text)]">{receipt.method}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Rounds: </span>
                    <span className="text-[var(--text)]">{receipt.rounds}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Date: </span>
                    <span className="text-[var(--text)]">{receipt.timestamp}</span>
                  </div>
                  <div className="col-span-2">
                    <span className="text-[var(--text-muted)]">Hash: </span>
                    <span className="text-[var(--text-muted)]/70">
                      {receipt.hash ? `${receipt.hash.slice(0, 32)}...` : 'N/A'}
                    </span>
                  </div>
                </div>

                {finalAnswer && (
                  <div className="mt-4 pt-3 border-t border-[var(--acid-green)]/20">
                    <p className="text-xs font-mono text-[var(--text)] leading-relaxed">
                      <span className="text-[var(--acid-green)] font-bold">Verdict: </span>
                      {finalAnswer}
                    </p>
                  </div>
                )}

                {/* Share + Try Again buttons */}
                <div className="mt-4 pt-3 border-t border-[var(--acid-green)]/20 space-y-2">
                  {shareUrl ? (
                    <button
                      onClick={() => {
                        const url = `${window.location.origin}${shareUrl}`;
                        navigator.clipboard
                          .writeText(url)
                          .catch(() => {});
                      }}
                      className="w-full py-2 text-xs font-mono font-bold border border-[var(--acid-green)] text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors"
                    >
                      SHARE THIS DEBATE
                    </button>
                  ) : (
                    <button
                      onClick={() => {
                        navigator.clipboard
                          .writeText(`${window.location.origin}/playground`)
                          .catch(() => {});
                      }}
                      className="w-full py-2 text-xs font-mono font-bold border border-[var(--acid-green)]/50 text-[var(--acid-green)]/70 hover:border-[var(--acid-green)] hover:text-[var(--acid-green)] transition-colors"
                    >
                      SHARE ARAGORA PLAYGROUND
                    </button>
                  )}
                  <button
                    onClick={handleReset}
                    className="w-full py-2 text-xs font-mono border border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--acid-green)]/30 hover:text-[var(--text)] transition-colors"
                  >
                    TRY ANOTHER QUESTION
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
