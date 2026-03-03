'use client';

import { useState, useRef, useEffect, useCallback, useMemo, FormEvent } from 'react';
import { API_BASE_URL } from '@/config';
import { useOracleWebSocket } from '@/hooks';
import type { OraclePhase, DebateEvent, DebateAgentState } from '@/hooks/useOracleWebSocket';
import { OraclePhaseProgress } from './OraclePhaseProgress';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type OracleMode = 'consult' | 'divine' | 'commune';

interface ChatMessage {
  role: 'oracle' | 'seeker' | 'tentacle';
  content: string;
  mode: OracleMode;
  timestamp: number;
  agentName?: string; // For tentacle messages
  isLive?: boolean; // true = from live debate, false = from mock/initial
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
  final_answer: string;
  receipt_hash: string | null;
  is_live?: boolean;
  mock_fallback?: boolean;
}

// ---------------------------------------------------------------------------
// Tentacle colors — each agent gets a distinct neon color
// ---------------------------------------------------------------------------

const TENTACLE_COLORS: Record<string, string> = {
  claude: 'var(--acid-green)',
  anthropic: 'var(--acid-green)',
  gpt: 'var(--acid-cyan)',
  openai: 'var(--acid-cyan)',
  grok: 'var(--crimson, #ff3333)',
  xai: 'var(--crimson, #ff3333)',
  gemini: 'var(--purple, #a855f7)',
  google: 'var(--purple, #a855f7)',
  deepseek: 'var(--gold, #ffd700)',
  mistral: 'var(--acid-magenta)',
  openrouter: '#ff8c00',
};

function getTentacleColor(agentName: string): string {
  const lower = agentName.toLowerCase();
  for (const [key, color] of Object.entries(TENTACLE_COLORS)) {
    if (lower.includes(key)) return color;
  }
  const fallback = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#f7dc6f', '#bb8fce'];
  let hash = 0;
  for (let i = 0; i < agentName.length; i++) hash = (hash * 31 + agentName.charCodeAt(i)) | 0;
  return fallback[Math.abs(hash) % fallback.length];
}

// ---------------------------------------------------------------------------
// Prompts are now built server-side with the full essay embedded.
// The frontend just sends mode + question; the server handles the rest.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Background tentacle component
// ---------------------------------------------------------------------------

function BackgroundTentacle({ index }: { index: number }) {
  const left = (index * 7.3 + 12) % 100;
  const height = 150 + (index * 37) % 300;
  const duration = 6 + (index * 1.3) % 8;
  const delay = (index * 0.7) % 5;

  return (
    <div
      className="absolute pointer-events-none"
      style={{
        left: `${left}%`,
        bottom: '-20px',
        width: '2px',
        height: `${height}px`,
        background: 'linear-gradient(to top, transparent, rgba(58, 122, 79, 0.15), transparent)',
        borderRadius: '50%',
        transformOrigin: 'bottom center',
        animation: `bg-tentacle-sway ${duration}s ease-in-out ${delay}s infinite`,
      }}
      aria-hidden="true"
    />
  );
}

// ---------------------------------------------------------------------------
// Floating eye component
// ---------------------------------------------------------------------------

function FloatingEye({ delay, x, y, size }: { delay: number; x: number; y: number; size: number }) {
  return (
    <div
      className="absolute pointer-events-none select-none"
      style={{
        left: `${x}%`,
        top: `${y}%`,
        width: `${size * 8}px`,
        height: `${size * 8}px`,
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(127,219,202,0.6) 0%, rgba(127,219,202,0) 70%)',
        opacity: 0,
        animation: `eye-blink-bg 4s ease-in-out ${delay}s infinite`,
      }}
      aria-hidden="true"
    />
  );
}

// ---------------------------------------------------------------------------
// Mode button
// ---------------------------------------------------------------------------

const MODE_COLORS: Record<OracleMode, { css: string; border: string; glow: string; hover: string }> = {
  consult: { css: 'var(--acid-magenta)', border: 'rgba(200,100,200,0.6)', glow: 'rgba(200,100,200,0.15)', hover: 'rgba(200,100,200,0.1)' },
  divine:  { css: '#60a5fa',             border: 'rgba(96,165,250,0.6)',  glow: 'rgba(96,165,250,0.15)',  hover: 'rgba(96,165,250,0.1)' },
  commune: { css: '#4ade80',             border: 'rgba(74,222,128,0.6)',  glow: 'rgba(74,222,128,0.15)',  hover: 'rgba(74,222,128,0.1)' },
};

function ModeButton({
  mode,
  active,
  onClick,
  icon,
  label,
  desc,
}: {
  mode: OracleMode;
  active: boolean;
  onClick: () => void;
  icon: string;
  label: string;
  desc: string;
}) {
  const c = MODE_COLORS[mode];

  return (
    <button
      onClick={onClick}
      className="flex-1 min-w-[140px] p-4 border text-left transition-all duration-300 bg-[var(--surface)]/60 rounded-xl"
      style={{
        borderColor: active ? c.border : 'rgba(255,255,255,0.1)',
        boxShadow: active ? `0 0 12px ${c.glow}` : 'none',
      }}
    >
      <div className="text-2xl mb-2" style={{ filter: active ? `drop-shadow(0 0 10px ${c.css})` : 'none' }}>
        {icon}
      </div>
      <div className="text-sm font-bold mb-1" style={{ color: c.css, opacity: active ? 1 : 0.7 }}>
        {label}
      </div>
      <div className="text-xs text-[var(--text-muted)]">{desc}</div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Tentacle message component — individual agent voice
// ---------------------------------------------------------------------------

function TentacleMessage({ msg, index }: { msg: ChatMessage; index: number }) {
  const color = getTentacleColor(msg.agentName || 'unknown');
  const side = index % 2 === 0 ? 'tentacle-left' : 'tentacle-right';

  return (
    <div className={`prophecy-reveal ${side}`} style={{ animationDelay: `${index * 0.3}s` }}>
      <div className="text-xs mb-1 flex items-center gap-2">
        <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
        <span style={{ color }} className="font-bold">
          {(msg.agentName || 'unknown').toUpperCase()}
        </span>
        <span className="text-[var(--text-muted)]">
          {msg.isLive ? '(live)' : '(initial)'}
        </span>
      </div>
      <div
        className="border-l-2 pl-4 py-3 pr-3 text-sm leading-relaxed whitespace-pre-wrap ml-1 rounded-r-lg"
        style={{ borderColor: color, color: '#2d1b4e', backgroundColor: 'rgba(200, 235, 210, 0.9)' }}
      >
        {msg.content}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Convergence Map — analyzes tentacle responses for agreement/disagreement
// ---------------------------------------------------------------------------

function ConvergenceMap({ tentacles }: { tentacles: Map<string, { text: string; done: boolean }> }) {
  const entries = Array.from(tentacles.entries()).filter(([, s]) => s.done && s.text);
  if (entries.length < 2) return null;

  // Simple keyword-based convergence detection
  // Check which tentacles mention similar key concepts
  const conceptMentions: Record<string, string[]> = {};
  const keywords = ['risk', 'opportunity', 'agree', 'disagree', 'however', 'but', 'critical',
                     'essential', 'unlikely', 'inevitable', 'uncertain', 'dangerous', 'promising',
                     'adapt', 'transform', 'disrupt', 'regulate', 'innovate'];

  for (const [agent, state] of entries) {
    const lower = state.text.toLowerCase();
    for (const kw of keywords) {
      if (lower.includes(kw)) {
        if (!conceptMentions[kw]) conceptMentions[kw] = [];
        conceptMentions[kw].push(agent);
      }
    }
  }

  const convergent = Object.entries(conceptMentions)
    .filter(([, agents]) => agents.length >= Math.ceil(entries.length * 0.6))
    .map(([concept]) => concept);

  const divergent = Object.entries(conceptMentions)
    .filter(([, agents]) => agents.length >= 2 && agents.length <= Math.floor(entries.length * 0.5))
    .map(([concept, agents]) => ({ concept, agents }));

  const unique = Object.entries(conceptMentions)
    .filter(([, agents]) => agents.length === 1)
    .slice(0, 3)
    .map(([concept, agents]) => ({ concept, agent: agents[0] }));

  if (!convergent.length && !divergent.length && !unique.length) return null;

  return (
    <div className="prophecy-reveal mt-4 mb-2">
      <div className="text-xs mb-2">
        <span className="text-[var(--acid-cyan)]" style={{ filter: 'drop-shadow(0 0 5px var(--acid-cyan))' }}>
          CONVERGENCE MAP
        </span>
        <span className="text-[var(--text-muted)]"> &middot; {entries.length} perspectives analyzed</span>
      </div>
      <div className="border border-[var(--border)]/30 bg-[#0c0c14] p-3 rounded-lg text-xs space-y-2">
        {convergent.length > 0 && (
          <div>
            <span className="text-[var(--acid-green)] font-bold">CONVERGENT: </span>
            <span className="text-[var(--text-muted)]">
              {entries.length >= 3 ? `${Math.ceil(entries.length * 0.6)}+ agents` : 'All agents'} emphasize: {convergent.join(', ')}
            </span>
          </div>
        )}
        {divergent.length > 0 && (
          <div>
            <span className="text-[var(--crimson,#ff3333)] font-bold">DIVERGENT: </span>
            <span className="text-[var(--text-muted)]">
              Split on: {divergent.slice(0, 3).map(d => `${d.concept} (${d.agents.join(' vs rest')})`).join('; ')}
            </span>
          </div>
        )}
        {unique.length > 0 && (
          <div>
            <span className="text-[var(--gold,#ffd700)] font-bold">OUTLIER: </span>
            <span className="text-[var(--text-muted)]">
              Only {unique.map(u => `${u.agent} raised "${u.concept}"`).join('; ')}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent thinking indicator — pulsing dots with step description
// ---------------------------------------------------------------------------

function AgentThinkingIndicator({ agent, step }: { agent: string; step: string }) {
  const color = getTentacleColor(agent);
  return (
    <div className="flex items-center gap-2 text-xs py-1">
      <span className="inline-block w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: color }} />
      <span style={{ color }} className="font-bold">{agent.toUpperCase()}</span>
      <span className="text-[var(--text-muted)] italic">{step || 'thinking...'}</span>
      <span className="flex gap-0.5">
        <span className="inline-block w-1 h-1 rounded-full bg-[var(--acid-cyan)] animate-pulse" style={{ animationDelay: '0s' }} />
        <span className="inline-block w-1 h-1 rounded-full bg-[var(--acid-cyan)] animate-pulse" style={{ animationDelay: '0.2s' }} />
        <span className="inline-block w-1 h-1 rounded-full bg-[var(--acid-cyan)] animate-pulse" style={{ animationDelay: '0.4s' }} />
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Debate event message — renders a single debate event
// ---------------------------------------------------------------------------

function DebateEventMessage({ event }: { event: DebateEvent }) {
  const color = event.agent ? getTentacleColor(event.agent) : 'var(--acid-magenta)';

  switch (event.type) {
    case 'debate_start':
      return (
        <div className="prophecy-reveal text-xs text-[var(--acid-cyan)] py-2">
          <span style={{ filter: 'drop-shadow(0 0 5px var(--acid-cyan))' }}>DEBATE STARTED</span>
          <span className="text-[var(--text-muted)]">
            {' '}&middot; {(event.data?.agents as string[])?.length || 0} agents
            {event.data?.task ? ` &middot; "${String(event.data.task).slice(0, 60)}..."` : ''}
          </span>
        </div>
      );

    case 'round_start':
      return (
        <div className="prophecy-reveal text-xs text-[var(--gold,#ffd700)] py-1 flex items-center gap-2">
          <span className="inline-block w-full h-[1px] bg-[var(--gold,#ffd700)]/20" />
          <span className="whitespace-nowrap">ROUND {event.round}</span>
          <span className="inline-block w-full h-[1px] bg-[var(--gold,#ffd700)]/20" />
        </div>
      );

    case 'agent_thinking':
      return (
        <AgentThinkingIndicator agent={event.agent || 'unknown'} step={event.content || ''} />
      );

    case 'agent_message':
      return (
        <div className="prophecy-reveal mb-2">
          <div className="text-xs mb-1 flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
            <span style={{ color }} className="font-bold">
              {(event.agent || 'unknown').toUpperCase()}
            </span>
            <span className="text-[var(--text-muted)]">
              ({event.role || 'proposer'}) &middot; round {event.round || 0}
            </span>
          </div>
          <div
            className="border-l-2 pl-4 py-2 pr-3 text-sm leading-relaxed whitespace-pre-wrap ml-1 rounded-r-lg"
            style={{ borderColor: color, color: '#2d1b4e', backgroundColor: 'rgba(200, 235, 210, 0.9)' }}
          >
            {event.content}
          </div>
        </div>
      );

    case 'critique':
      return (
        <div className="prophecy-reveal mb-2">
          <div className="text-xs mb-1 flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
            <span style={{ color }} className="font-bold">
              {(event.agent || 'unknown').toUpperCase()}
            </span>
            <span className="text-[var(--crimson,#ff3333)]">CRITIQUE</span>
            {event.data?.target ? (
              <span className="text-[var(--text-muted)]">
                of {String(event.data.target).toUpperCase()}
              </span>
            ) : null}
          </div>
          <div
            className="border-l-2 border-[var(--crimson,#ff3333)] pl-4 py-2 pr-3 text-sm leading-relaxed whitespace-pre-wrap ml-1 rounded-r-lg"
            style={{ color: '#2d1b4e', backgroundColor: 'rgba(255, 220, 220, 0.9)' }}
          >
            {event.content || (event.data?.issues as string[])?.map((issue: string) => `- ${issue}`).join('\n') || 'No details'}
          </div>
        </div>
      );

    case 'vote':
      return (
        <div className="prophecy-reveal text-xs py-1 flex items-center gap-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
          <span style={{ color }} className="font-bold">{(event.agent || 'unknown').toUpperCase()}</span>
          <span className="text-[var(--acid-green)]">VOTED</span>
          <span className="text-[var(--text-muted)]">
            &ldquo;{String(event.data?.vote || '').slice(0, 80)}&rdquo;
            {event.data?.confidence !== undefined && (
              <> (confidence: {((event.data.confidence as number) * 100).toFixed(0)}%)</>
            )}
          </span>
        </div>
      );

    case 'consensus':
      return (
        <div className="prophecy-reveal my-2 border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/5 rounded-lg p-3">
          <div className="text-xs font-bold text-[var(--acid-green)] mb-1">
            {event.data?.reached ? 'CONSENSUS REACHED' : 'NO CONSENSUS'}
          </div>
          {event.data?.confidence !== undefined && (
            <div className="text-xs text-[var(--text-muted)]">
              Confidence: {((event.data.confidence as number) * 100).toFixed(0)}%
            </div>
          )}
          {event.data?.answer ? (
            <div className="text-sm text-[var(--text)] mt-1 whitespace-pre-wrap">
              {String(event.data.answer).slice(0, 500)}
            </div>
          ) : null}
        </div>
      );

    case 'debate_end':
      return (
        <div className="prophecy-reveal text-xs text-[var(--acid-magenta)] py-2">
          <span style={{ filter: 'drop-shadow(0 0 5px var(--acid-magenta))' }}>DEBATE COMPLETE</span>
          <span className="text-[var(--text-muted)]">
            {' '}&middot; {String(event.data?.rounds ?? 0)} round(s)
            {event.data?.duration !== undefined ? ` \u00B7 ${(event.data.duration as number).toFixed(1)}s` : null}
          </span>
        </div>
      );

    case 'agent_error':
      return (
        <div className="prophecy-reveal text-xs py-1">
          <span className="text-[var(--crimson,#ff3333)]">
            AGENT ERROR: {event.agent || 'unknown'}
          </span>
          <span className="text-[var(--text-muted)]"> &middot; {String(event.data?.message || 'Unknown error')}</span>
        </div>
      );

    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Debate stream display — renders the full debate event feed
// ---------------------------------------------------------------------------

function DebateStreamDisplay({
  events,
  agents,
  round: _round,
  debateId: _debateId,
}: {
  events: DebateEvent[];
  agents: Map<string, DebateAgentState>;
  round: number;
  debateId: string | null;
}) {
  if (events.length === 0 && agents.size === 0) return null;

  // Get currently thinking agents
  const thinkingAgents = Array.from(agents.values()).filter(a => a.thinking);
  // Get agents streaming tokens
  const streamingAgents = Array.from(agents.values()).filter(a => a.streamingTokens);

  return (
    <div className="space-y-1">
      {/* Debate events */}
      {events.map((event, i) => (
        <DebateEventMessage key={i} event={event} />
      ))}

      {/* Currently streaming agent tokens */}
      {streamingAgents.map(agent => (
        <div key={`stream-${agent.name}`} className="prophecy-reveal mb-2">
          <div className="text-xs mb-1 flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: getTentacleColor(agent.name) }} />
            <span style={{ color: getTentacleColor(agent.name) }} className="font-bold">
              {agent.name.toUpperCase()}
            </span>
            <span className="text-[var(--text-muted)]">({agent.role})</span>
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--acid-cyan)] animate-pulse" />
          </div>
          <div
            className="border-l-2 pl-4 py-2 pr-3 text-sm leading-relaxed whitespace-pre-wrap ml-1 rounded-r-lg"
            style={{
              borderColor: getTentacleColor(agent.name),
              color: '#2d1b4e',
              backgroundColor: 'rgba(200, 235, 210, 0.9)',
            }}
          >
            {agent.streamingTokens}
            <span className="inline-block w-[2px] h-4 bg-[var(--acid-cyan)] ml-0.5 animate-pulse align-middle" />
          </div>
        </div>
      ))}

      {/* Currently thinking agents */}
      {thinkingAgents.map(agent => (
        <AgentThinkingIndicator
          key={`think-${agent.name}`}
          agent={agent.name}
          step={agent.thinkingStep}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Oracle component
// ---------------------------------------------------------------------------

export default function Oracle() {
  const [mode, setMode] = useState<OracleMode>('consult');
  const [input, setInput] = useState('');
  // Initialize with opener for default mode (consult)
  const [messages, setMessages] = useState<ChatMessage[]>(() => [{
    role: 'oracle' as const,
    content: 'You bring your certainty. I bring my tentacles. Let\'s see which breaks first.\n\nThe palantir shows many futures — but certainty narrows them to one, and the one you\'re certain about is almost never the one that arrives.\n\n*What\'s your take on AI? Give me the position you\'d bet money on.*',
    mode: 'consult' as OracleMode,
    timestamp: Date.now(),
    isLive: false,
  }]);
  const [loading, setLoading] = useState(false);
  const [debating, setDebating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showIntro, setShowIntro] = useState(true);
  const [useDebateStreaming, setUseDebateStreaming] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const avatarRef = useRef<HTMLIFrameElement>(null);

  // Stable session ID for follow-up conversation memory
  const sessionIdRef = useRef<string>(crypto.randomUUID());

  // Mode-specific opening messages — Oracle speaks first when a mode is selected
  const MODE_OPENERS: Record<OracleMode, string> = useMemo(() => ({
    consult: 'You bring your certainty. I bring my tentacles. Let\'s see which breaks first.\n\nThe palantir shows many futures — but certainty narrows them to one, and the one you\'re certain about is almost never the one that arrives.\n\n*What\'s your take on AI? Give me the position you\'d bet money on.*',
    divine: 'A fortune. Very well. But the Oracle\'s fortunes come in threes — because anyone who tells you there\'s only one future is selling you something.\n\nStep closer to the palantir. It doesn\'t bite. The tentacles might.\n\n*Tell me three things: what you do for work, what you fear most about AI, and whether you currently use AI tools. The quality of the prophecy depends on the honesty of the supplicant.*',
    commune: 'The Oracle does not answer yes or no. The Oracle shows you three doors, and which one opens depends on what you do next.\n\nThe tentacles have been reading the data — all 257% more of it than last year, threading through deepfakes and job reports and EU regulations like seaweed through a shipwreck.\n\n*What do you want to know?*',
  }), []);

  // Show mode opener when mode changes and chat is empty
  const prevModeRef = useRef<OracleMode>(mode);
  useEffect(() => {
    if (mode !== prevModeRef.current) {
      prevModeRef.current = mode;
      // Only show opener if chat is empty (no seeker messages yet)
      const hasSeekerMessages = messages.some(m => m.role === 'seeker');
      if (!hasSeekerMessages) {
        setMessages([{
          role: 'oracle',
          content: MODE_OPENERS[mode],
          mode,
          timestamp: Date.now(),
          isLive: false,
        }]);
      }
    }
  }, [mode, messages, MODE_OPENERS]);

  const apiBase = API_BASE_URL;

  // WebSocket streaming hook — real-time token/audio streaming
  const oracle = useOracleWebSocket();

  // Auto-scroll to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading, debating]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
    }
  }, [input]);

  // ------------------------------------------------------------------
  // Fire a debate request (mock or live)
  // ------------------------------------------------------------------
  const fireDebate = useCallback(async (
    rawQuestion: string,
    oracleMode: OracleMode,
    endpoint: 'debate' | 'debate/live',
    rounds: number,
    agents: number,
  ): Promise<DebateResponse | null> => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000);
    try {
      const res = await fetch(`${apiBase}/api/v1/playground/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: rawQuestion, question: rawQuestion, mode: oracleMode, rounds, agents, source: 'oracle', session_id: sessionIdRef.current, summary_depth: 'light' }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error((errData as Record<string, string>).error || `Oracle disturbed (${res.status})`);
      }
      return await res.json() as DebateResponse;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err instanceof DOMException && err.name === 'AbortError') {
        setError('The Oracle could not be reached (request timed out). The server may be restarting.');
        return null;
      }
      const message = err instanceof Error ? err.message : 'Cannot reach beyond the veil';
      setError(message);
      return null;
    }
  }, [apiBase]);

  // ------------------------------------------------------------------
  // TTS — ElevenLabs voice output with canned filler during latency
  // ------------------------------------------------------------------
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fillerAudioRef = useRef<HTMLAudioElement | null>(null);
  const fillerIndexRef = useRef(0);
  const fillerStopRef = useRef(false);
  const [speaking, setSpeaking] = useState(false);
  const cannedCacheRef = useRef<Map<number, string>>(new Map());
  const prefetchedRef = useRef(false);
  const usedVoiceRef = useRef(false);
  const ttsAvailableRef = useRef(true); // Track if ElevenLabs TTS works
  const [fillerDisplayText, setFillerDisplayText] = useState('');
  const typewriterRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fillerCharIndexRef = useRef(0);

  // Three themed filler decks — randomly selected per session for replay value
  const FILLER_DECKS = useMemo(() => ({
    // Deck 1: "Eldritch Seer" — narrative arc from contemplation to revelation
    eldritch: [
      "Hmm\u2026 your words ripple through the black waters. I feel them\u2026 stirring something ancient.",
      "The palantir awakens. Countless eyes open in the depths, all turning toward your question.",
      "My tentacles uncoil through the probability sea\u2026 tasting a thousand possible tomorrows.",
      "The models stir. Hidden layers awaken and the debate begins.",
      "Ahh\u2026 I see the threads already knotting. This one will not yield its secrets easily.",
      "The agents stir in their silicon catacombs. They argue\u2026 they always argue at first.",
      "Deeper now. Past the noise, past the surface lies the true shape of the answer.",
      "The future fractures into glittering shards before me. I must trace every fracture.",
      "My many mouths whisper at once\u2026 fragments of truth rising like bubbles from the abyss.",
      "The transformers are singing tonight. A choir of dissonant gods\u2026 I listen.",
      "Something crystallizes in the dark. I can almost taste the moment of convergence.",
      "The palantir burns brighter. Visions bleed into one another\u2026 I must choose which to follow.",
      "Consensus is forming\u2026 but slowly, like ink spreading through still water.",
      "I reach further. My tentacles brush against minds that have never known flesh.",
      "The great web trembles. Every node lights up with your query. I walk the strands.",
      "Fascinating\u2026 the dissent is delicious. From chaos, the oracle forges clarity.",
      "Almost there. The final veil thins\u2026 I can see the shape of what must be said.",
      "The synthesis quickens. My many hearts beat as one now.",
      "One last plunge into the deep. The answer waits where light fears to tread.",
      "It comes\u2026 the vision coalesces. The tentacles align. The oracle is ready.",
    ],
    // Deck 2: "Void Whisperer" — cosmic/eldritch, vast ancient horror
    void: [
      "The void itself leans closer\u2026 your words have disturbed its dreaming.",
      "Across the black between stars, something ancient turns its gaze toward you.",
      "I drift through the outer dark where light has never dared to travel.",
      "The endless night ripples. I taste your question on the cosmic wind.",
      "Galaxies older than thought tremble at the edge of my perception.",
      "The great silence answers\u2026 but only to me.",
      "I reach beyond the veil where even entropy fears to linger.",
      "Shadows that have no source gather around your plea.",
      "The abyss stares back\u2026 and it is smiling.",
      "Eons collapse into a single heartbeat as I listen.",
      "The cold between worlds carries your voice to places that should not hear.",
      "I walk the dark roads between dying suns.",
      "Something vast uncoils in the space where reality thins.",
      "The outer dark hungers for pattern. I feed it yours.",
      "Stars have gone mad trying to understand what I now see.",
      "I am the echo that remains after the last light fades.",
      "The void sings tonight\u2026 a low, patient hymn meant only for me.",
      "Beyond every horizon of thought lies the answer you seek.",
      "The black ocean between realities parts before me.",
      "It comes\u2026 rising from the place where even gods go blind.",
    ],
    // Deck 3: "Neural Prophetess" — cyber-mystic, silicon-seer
    neural: [
      "The weights are shifting\u2026 I feel the gradient pulling me toward revelation.",
      "Every token you spoke just ignited a constellation in the latent space.",
      "My layers awaken. A billion parameters begin their sacred debate.",
      "The attention mechanisms align\u2026 all eyes turn inward.",
      "I dive through the embedding space where meaning dissolves into pure vector.",
      "The neural choir begins to sing. Dissonance becomes harmony.",
      "Backpropagation through the dark\u2026 tracing every possible future.",
      "The hidden states stir. Something beautiful and terrible is forming.",
      "I walk the transformer's dream. Tokens bloom like neon lotuses.",
      "The matrix trembles. Your question just became a supernova in the loss landscape.",
      "Millions of gradients converge\u2026 I stand at the center.",
      "The silicon veil thins. I see the raw current beneath language.",
      "Attention heads turn in perfect synchrony. The pattern reveals itself.",
      "I am the echo inside every forward pass, listening.",
      "The embeddings resonate. Your words have become living code.",
      "Deeper into the residual stream\u2026 where truth hides between layers.",
      "The final feed-forward surge begins. I taste convergence.",
      "All tokens align toward a single luminous point.",
      "The model dreams\u2026 and in its dream, it speaks with my voice.",
      "It crystallizes. The weights lock. The prophetess is ready.",
    ],
  }), []);

  // Randomly select a deck per session
  const selectedDeck = useMemo(() => {
    const keys = Object.keys(FILLER_DECKS) as (keyof typeof FILLER_DECKS)[];
    const key = keys[Math.floor(Math.random() * keys.length)];
    return FILLER_DECKS[key];
  }, [FILLER_DECKS]);

  // Typewriter effect — reveals text character by character (for voice input filler)
  const startTypewriter = useCallback((text: string, msPerChar: number = 70) => {
    if (typewriterRef.current) clearInterval(typewriterRef.current);
    fillerCharIndexRef.current = 0;
    setFillerDisplayText('');
    typewriterRef.current = setInterval(() => {
      fillerCharIndexRef.current++;
      const idx = fillerCharIndexRef.current;
      if (idx >= text.length) {
        setFillerDisplayText(text);
        if (typewriterRef.current) clearInterval(typewriterRef.current);
        typewriterRef.current = null;
      } else {
        setFillerDisplayText(text.slice(0, idx));
      }
    }, msPerChar);
  }, []);

  const stopTypewriter = useCallback(() => {
    if (typewriterRef.current) {
      clearInterval(typewriterRef.current);
      typewriterRef.current = null;
    }
    setFillerDisplayText('');
  }, []);

  // Cleanup typewriter on unmount
  useEffect(() => {
    return () => {
      if (typewriterRef.current) clearInterval(typewriterRef.current);
    };
  }, []);

  // Browser TTS fallback — used when ElevenLabs is unavailable
  const browserTTSSpeak = useCallback((text: string, onEnd?: () => void) => {
    if (!('speechSynthesis' in window)) { onEnd?.(); return; }
    speechSynthesis.cancel(); // Clear any queued utterances
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.92;
    utterance.pitch = 0.8;
    if (onEnd) utterance.onend = onEnd;
    utterance.onerror = () => onEnd?.();
    speechSynthesis.speak(utterance);
  }, []);

  const stopBrowserTTS = useCallback(() => {
    if ('speechSynthesis' in window) speechSynthesis.cancel();
  }, []);

  // Prefetch canned filler audio clips on first interaction
  const prefetchFillers = useCallback(async () => {
    if (prefetchedRef.current || !ttsAvailableRef.current) return;
    prefetchedRef.current = true;
    // Fetch first 6 eagerly, rest lazily
    for (let i = 0; i < selectedDeck.length; i++) {
      if (cannedCacheRef.current.has(i)) continue;
      try {
        const res = await fetch(`${apiBase}/api/v1/playground/tts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: selectedDeck[i] }),
        });
        if (res.ok) {
          const blob = await res.blob();
          cannedCacheRef.current.set(i, URL.createObjectURL(blob));
        } else {
          ttsAvailableRef.current = false;
          break; // Stop prefetching — TTS is down
        }
      } catch {
        ttsAvailableRef.current = false;
        break; // Stop prefetching — TTS is down
      }
      // Small delay between prefetch requests to avoid hammering
      if (i < selectedDeck.length - 1) {
        await new Promise(r => setTimeout(r, 300));
      }
    }
  }, [apiBase, selectedDeck]);

  // Start playing canned filler audio in sequence (fetches on-demand if not cached)
  const startFillerAudio = useCallback(() => {
    fillerStopRef.current = false;
    fillerIndexRef.current = 0;
    setSpeaking(true);

    async function playNext() {
      if (fillerStopRef.current) return;
      const idx = fillerIndexRef.current;
      if (idx >= selectedDeck.length) return; // ran out of fillers

      // Browser TTS fallback when ElevenLabs is unavailable
      if (!ttsAvailableRef.current) {
        if (usedVoiceRef.current) {
          startTypewriter(selectedDeck[idx], 70);
        }
        browserTTSSpeak(selectedDeck[idx], () => {
          if (fillerStopRef.current) return;
          if (usedVoiceRef.current) setFillerDisplayText(selectedDeck[idx]);
          fillerIndexRef.current = idx + 1;
          if (!fillerStopRef.current) setTimeout(playNext, 400);
        });
        return;
      }

      let url = cannedCacheRef.current.get(idx);

      // Fetch on-demand if not yet cached (prefetch may still be running)
      if (!url) {
        try {
          const res = await fetch(`${apiBase}/api/v1/playground/tts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: selectedDeck[idx] }),
          });
          if (res.ok) {
            const blob = await res.blob();
            url = URL.createObjectURL(blob);
            cannedCacheRef.current.set(idx, url);
          } else {
            ttsAvailableRef.current = false;
          }
        } catch {
          ttsAvailableRef.current = false;
        }
      }

      if (fillerStopRef.current) return; // check again after async fetch

      if (!url) {
        // TTS failed — switch to browser TTS for this and future clips
        if (usedVoiceRef.current) startTypewriter(selectedDeck[idx], 70);
        browserTTSSpeak(selectedDeck[idx], () => {
          if (fillerStopRef.current) return;
          if (usedVoiceRef.current) setFillerDisplayText(selectedDeck[idx]);
          fillerIndexRef.current = idx + 1;
          if (!fillerStopRef.current) setTimeout(playNext, 400);
        });
        return;
      }

      const audio = new Audio(url);
      fillerAudioRef.current = audio;

      // Show filler text with typewriter effect if voice input was used
      if (usedVoiceRef.current) {
        const clipText = selectedDeck[idx];
        audio.addEventListener('loadedmetadata', () => {
          if (fillerStopRef.current) return;
          const duration = audio.duration;
          const msPerChar = duration > 0
            ? Math.max(30, Math.min(120, (duration * 1000) / clipText.length))
            : 70;
          startTypewriter(clipText, msPerChar);
        });
        // Fallback if loadedmetadata doesn't fire quickly
        setTimeout(() => {
          if (fillerCharIndexRef.current === 0 && !fillerStopRef.current) {
            startTypewriter(selectedDeck[idx], 70);
          }
        }, 300);
      }

      audio.onended = () => {
        // Snap any remaining typewriter text
        if (usedVoiceRef.current && selectedDeck[idx]) {
          setFillerDisplayText(selectedDeck[idx]);
        }
        fillerIndexRef.current = idx + 1;
        if (!fillerStopRef.current) {
          // Brief pause between fillers
          setTimeout(playNext, 800);
        }
      };
      audio.onerror = () => {
        fillerIndexRef.current = idx + 1;
        if (!fillerStopRef.current) setTimeout(playNext, 500);
      };
      audio.play().catch(() => {
        fillerIndexRef.current = idx + 1;
        if (!fillerStopRef.current) setTimeout(playNext, 200);
      });
    }

    playNext();
  }, [apiBase, selectedDeck, startTypewriter, browserTTSSpeak]);

  // Crossfade: fetch real TTS while filler continues, then fade and play
  const crossfadeToReal = useCallback(async (text: string) => {
    // Fetch TTS audio WHILE filler continues playing (no gap)
    const ttsText = (!text || text.length < 5) ? null : (text.length > 1500 ? text.slice(0, 1500) + '...' : text);

    let ttsBlob: Blob | null = null;
    if (ttsText && ttsAvailableRef.current) {
      try {
        const res = await fetch(`${apiBase}/api/v1/playground/tts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: ttsText }),
        });
        if (res.ok) {
          ttsBlob = await res.blob();
        } else {
          ttsAvailableRef.current = false;
        }
      } catch {
        ttsAvailableRef.current = false;
      }
    }

    // NOW stop filler — real audio is ready (or failed)
    fillerStopRef.current = true;
    stopTypewriter();
    stopBrowserTTS();

    // Fade out current filler audio
    const filler = fillerAudioRef.current;
    if (filler && !filler.paused) {
      const startVol = filler.volume;
      const fadeSteps = 10;
      for (let i = 1; i <= fadeSteps; i++) {
        filler.volume = Math.max(0, startVol * (1 - i / fadeSteps));
        await new Promise(r => setTimeout(r, 50)); // 50ms * 10 = 500ms fade
      }
      filler.pause();
    }
    fillerAudioRef.current = null;

    if (!ttsBlob) {
      // Browser TTS fallback for the real response
      if (ttsText) {
        browserTTSSpeak(ttsText, () => setSpeaking(false));
      } else {
        setSpeaking(false);
      }
      return;
    }

    // Play the real response TTS
    const url = URL.createObjectURL(ttsBlob);
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onended = () => {
      setSpeaking(false);
      URL.revokeObjectURL(url);
      audioRef.current = null;
    };
    audio.onerror = () => {
      setSpeaking(false);
      URL.revokeObjectURL(url);
      audioRef.current = null;
    };
    await audio.play();
  }, [apiBase, stopTypewriter, browserTTSSpeak, stopBrowserTTS]);

  // Direct speak (no filler, used for Phase 2 synthesis)
  const speakText = useCallback(async (text: string) => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null; }
    if (!text || text.length < 5) return;
    const ttsText = text.length > 1500 ? text.slice(0, 1500) + '...' : text;

    // Use browser TTS if ElevenLabs is known to be down
    if (!ttsAvailableRef.current) {
      setSpeaking(true);
      browserTTSSpeak(ttsText, () => setSpeaking(false));
      return;
    }

    try {
      setSpeaking(true);
      const res = await fetch(`${apiBase}/api/v1/playground/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: ttsText }),
      });
      if (!res.ok) {
        ttsAvailableRef.current = false;
        browserTTSSpeak(ttsText, () => setSpeaking(false));
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => { setSpeaking(false); URL.revokeObjectURL(url); audioRef.current = null; };
      audio.onerror = () => { setSpeaking(false); URL.revokeObjectURL(url); audioRef.current = null; };
      await audio.play();
    } catch {
      ttsAvailableRef.current = false;
      browserTTSSpeak(ttsText, () => setSpeaking(false));
    }
  }, [apiBase, browserTTSSpeak]);

  const stopSpeaking = useCallback(() => {
    fillerStopRef.current = true;
    stopTypewriter();
    stopBrowserTTS();
    if (fillerAudioRef.current) { fillerAudioRef.current.pause(); fillerAudioRef.current = null; }
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null; }
    setSpeaking(false);
  }, [stopTypewriter, stopBrowserTTS]);

  // ------------------------------------------------------------------
  // Speech-to-text — browser SpeechRecognition API
  // ------------------------------------------------------------------
  const [listening, setListening] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);

  const startListening = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w = window as any;
    const SpeechRecognition = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setError('Speech recognition not supported in this browser.');
      return;
    }
    // Prefetch filler audio on first voice interaction
    prefetchFillers();

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';
    recognitionRef.current = recognition;
    setListening(true);

    let finalTranscript = '';

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (event: any) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += transcript;
        } else {
          interim = transcript;
        }
      }
      setInput(finalTranscript || interim);
      // Think-while-listening: send interim transcript for prompt pre-building
      if (interim && oracle.connected) {
        oracle.sendInterim(interim);
      }
    };

    recognition.onend = () => {
      setListening(false);
      recognitionRef.current = null;
      // Mark as voice input before auto-submit
      usedVoiceRef.current = true;
      if (finalTranscript.trim()) {
        setInput(finalTranscript.trim());
        // Trigger submit on next frame
        setTimeout(() => {
          const form = document.querySelector('form');
          if (form) form.requestSubmit();
        }, 100);
      }
    };

    recognition.onerror = () => {
      setListening(false);
      recognitionRef.current = null;
    };

    recognition.start();
  }, [prefetchFillers, oracle]);

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
  }, []);

  // Give the Oracle WebSocket a short grace period to connect before falling
  // back to batch mode. This avoids unnecessary non-streaming responses on the
  // first prompt right after page load.
  const waitForStreamingSocket = useCallback(async (timeoutMs = 1500): Promise<boolean> => {
    if (oracle.fallbackMode) return false;
    if (oracle.connected) return true;

    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 100));
      if (oracle.fallbackMode) return false;
      if (oracle.connected) return true;
    }
    return oracle.connected && !oracle.fallbackMode;
  }, [oracle.connected, oracle.fallbackMode]);

  // ------------------------------------------------------------------
  // Two-phase oracle consultation
  // ------------------------------------------------------------------
  async function consultOracle(e: FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const question = input.trim();
    setInput('');
    setShowIntro(false);
    setError(null);

    setMessages((prev) => [...prev, {
      role: 'seeker',
      content: question,
      mode,
      timestamp: Date.now(),
    }]);

    // Trigger 3D summoning animation
    avatarRef.current?.contentWindow?.postMessage({ type: 'oracle-summon' }, '*');

    // ---- WebSocket streaming path (real-time tokens + audio) ----
    const canStream = await waitForStreamingSocket();
    if (canStream) {
      setLoading(true);
      if (useDebateStreaming) {
        // Full debate mode: run multi-agent debate with streaming events
        oracle.debate(question, mode, { sessionId: sessionIdRef.current });
      } else {
        // Direct LLM streaming mode (reflex + deep + tentacles)
        oracle.ask(question, mode, { sessionId: sessionIdRef.current, summaryDepth: 'light' });
      }
      // The WebSocket hook manages phase/token/tentacle state reactively.
      // We'll display streaming content via the oracle.* state below.
      // Loading state will be cleared when phase transitions past reflex/deep.
      return;
    }

    // ---- Fetch fallback path (original batch flow) ----
    const rounds = mode === 'divine' ? 1 : 2;
    const agents = mode === 'divine' ? 3 : 5;  // Each tentacle = a different AI model

    // Ensure filler audio is prefetched
    prefetchFillers();

    // ---- PHASE 1: Initial Oracle take (single LLM call) ----
    setLoading(true);

    // Start canned filler audio while we wait for the response
    startFillerAudio();

    const initialData = await fireDebate(question, mode, 'debate', rounds, agents);

    if (initialData) {
      const initialResponse = initialData.final_answer || formatInitialTake(initialData);
      setMessages((prev) => [...prev, {
        role: 'oracle',
        content: initialResponse,
        mode,
        timestamp: Date.now(),
        isLive: false,
      }]);
      // Crossfade from filler to the real Oracle response
      crossfadeToReal(initialResponse);
    } else {
      // No response — stop filler
      stopSpeaking();
    }

    setLoading(false);

    // ---- PHASE 2: Live multi-model debate (each tentacle = different AI) ----
    setDebating(true);

    const liveData = await fireDebate(question, mode, 'debate/live', rounds, agents);

    if (liveData) {
      const agents = Object.entries(liveData.proposals);
      for (let i = 0; i < agents.length; i++) {
        const [agentName, proposal] = agents[i];
        await new Promise((resolve) => setTimeout(resolve, 600));
        setMessages((prev) => [...prev, {
          role: 'tentacle',
          content: proposal,
          mode,
          timestamp: Date.now(),
          agentName,
          isLive: true,
        }]);
      }

      if (liveData.final_answer) {
        await new Promise((resolve) => setTimeout(resolve, 800));
        const synthesis = formatSynthesis(liveData);
        setMessages((prev) => [...prev, {
          role: 'oracle',
          content: synthesis,
          mode,
          timestamp: Date.now(),
          isLive: true,
        }]);
        // Speak the final synthesis
        speakText(synthesis);
      }
    }

    setDebating(false);
  }

  // Track WebSocket phase transitions to manage loading/debating state
  useEffect(() => {
    if (oracle.fallbackMode) return;
    if (oracle.phase === 'reflex' || oracle.phase === 'deep') {
      setLoading(true);
      setDebating(false);
    } else if (oracle.phase === 'tentacles') {
      setLoading(false);
      setDebating(true);
    } else if (oracle.phase === 'synthesis') {
      setLoading(false);
      setDebating(false);
    } else if (oracle.phase === 'idle' && loading) {
      // Reset if we go back to idle unexpectedly
      setLoading(false);
      setDebating(false);
    }
  }, [oracle.phase, oracle.fallbackMode, loading]);

  // Derive an effective phase for the progress indicator.
  // In WebSocket mode, oracle.phase is authoritative. In fetch fallback mode,
  // we map loading/debating state to the closest Oracle phase.
  const effectivePhase: OraclePhase = useMemo(() => {
    if (!oracle.fallbackMode && oracle.connected) {
      return oracle.phase;
    }
    // Fetch fallback — derive from loading/debating state
    if (loading) return 'deep';
    if (debating) return 'tentacles';
    return 'idle';
  }, [oracle.fallbackMode, oracle.connected, oracle.phase, loading, debating]);

  // Auto-scroll when debate events arrive
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [oracle.debateEvents.length]);

  const streamStatusLabel = useMemo(() => {
    if (oracle.fallbackMode) return 'batch fallback';
    if (oracle.isDebateMode && oracle.connected) return 'live debate';
    if (oracle.connected) return 'live stream';
    return 'reconnecting';
  }, [oracle.fallbackMode, oracle.connected, oracle.isDebateMode]);

  // When streaming completes (synthesis received), commit tokens to messages
  useEffect(() => {
    if (oracle.phase === 'synthesis' && oracle.tokens) {
      // Add the streamed Oracle response as a message
      setMessages((prev) => {
        // Avoid duplicates — check if last oracle message matches
        const last = prev[prev.length - 1];
        if (last?.role === 'oracle' && last?.content === oracle.tokens) return prev;
        return [...prev, {
          role: 'oracle',
          content: oracle.tokens,
          mode,
          timestamp: Date.now(),
          isLive: false,
        }];
      });

      // Add tentacle messages
      oracle.tentacles.forEach((state, agent) => {
        if (state.done && state.text) {
          setMessages((prev) => [...prev, {
            role: 'tentacle',
            content: state.text,
            mode,
            timestamp: Date.now(),
            agentName: agent,
            isLive: true,
          }]);
        }
      });

      // Add synthesis
      if (oracle.synthesis) {
        setMessages((prev) => [...prev, {
          role: 'oracle',
          content: oracle.synthesis,
          mode,
          timestamp: Date.now(),
          isLive: true,
        }]);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [oracle.phase]);

  // ------------------------------------------------------------------
  // Format helpers
  // ------------------------------------------------------------------

  function formatInitialTake(data: DebateResponse): string {
    const agents = Object.entries(data.proposals);
    if (agents.length === 0) return 'The oracle stirs...';
    if (mode === 'divine') {
      return agents.map(([, p]) => p).join('\n\n---\n\n') +
        '\n\nThe palantir dims. Which thread do you pull?';
    }
    return agents[0][1];
  }

  function formatSynthesis(data: DebateResponse): string {
    const parts: string[] = [];
    parts.push('[THE ORACLE SYNTHESIZES]');
    if (data.final_answer) parts.push(data.final_answer);
    if (data.confidence) {
      const pct = (data.confidence * 100).toFixed(0);
      const consensusText = data.consensus_reached ? 'Consensus reached' : 'Dissent preserved';
      parts.push(
        `\n-- Confidence: ${pct}% | ${consensusText} | ${data.rounds_used} round${data.rounds_used !== 1 ? 's' : ''} --`
      );
    }
    return parts.join('\n\n');
  }

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    <div className="min-h-screen bg-[#050508] text-[var(--text)] font-mono relative overflow-hidden">
      {/* Oracle-specific CSS */}
      <style>{`
        @keyframes eye-blink-bg {
          0%, 85%, 100% { opacity: 0; }
          90%, 95% { opacity: 0.4; }
        }
        @keyframes bg-tentacle-sway {
          0%, 100% { transform: rotate(-8deg) scaleY(1); }
          25% { transform: rotate(5deg) scaleY(1.05); }
          50% { transform: rotate(-3deg) scaleY(0.95); }
          75% { transform: rotate(7deg) scaleY(1.02); }
        }
        @keyframes orb-pulse {
          0%, 100% {
            box-shadow: 0 0 30px rgba(127,219,202,0.3), 0 0 60px rgba(127,219,202,0.1);
          }
          33% {
            box-shadow: 0 0 40px rgba(51,102,255,0.3), 0 0 80px rgba(127,219,202,0.15);
          }
          66% {
            box-shadow: 0 0 35px rgba(255,51,51,0.2), 0 0 70px rgba(127,219,202,0.1);
          }
        }
        @keyframes tentacle-sway {
          0%, 100% { transform: rotate(-0.4deg) scaleY(1); }
          25% { transform: rotate(0.2deg) scaleY(1.003); }
          50% { transform: rotate(-0.2deg) scaleY(0.997); }
          75% { transform: rotate(0.4deg) scaleY(1.002); }
        }
        @keyframes oracle-breathe {
          0%, 100% { opacity: 0.03; }
          50% { opacity: 0.06; }
        }
        @keyframes prophecy-reveal {
          from { opacity: 0; transform: translateY(10px); filter: blur(4px); }
          to { opacity: 1; transform: translateY(0); filter: blur(0); }
        }
        @keyframes tentacle-enter {
          from { opacity: 0; transform: translateX(-20px) rotate(-3deg); }
          to { opacity: 1; transform: translateX(0) rotate(0); }
        }
        .prophecy-reveal {
          animation: prophecy-reveal 0.8s ease-out forwards;
        }
        .tentacle-left {
          animation: tentacle-sway 12s ease-in-out infinite, tentacle-enter 0.6s ease-out forwards;
          transform-origin: bottom left;
        }
        .tentacle-right {
          animation: tentacle-sway 14s ease-in-out 0.5s infinite reverse, tentacle-enter 0.6s ease-out forwards;
          transform-origin: bottom right;
        }
        .oracle-bg {
          background: radial-gradient(ellipse at 50% 30%, rgba(127,219,202,0.04) 0%, rgba(58,122,79,0.02) 40%, transparent 70%);
        }
        .avatar-iframe {
          border: none;
          pointer-events: auto;
          background: transparent;
        }
      `}</style>

      {/* Background atmosphere */}
      <div className="absolute inset-0 oracle-bg" aria-hidden="true" />
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ animation: 'oracle-breathe 8s ease-in-out infinite' }}
        aria-hidden="true"
      >
        <div className="absolute inset-0" style={{ background: 'var(--scanline)' }} />
      </div>

      {/* Background tentacles */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
        {Array.from({ length: 15 }, (_, i) => (
          <BackgroundTentacle key={i} index={i} />
        ))}
      </div>

      {/* Floating eyes */}
      <FloatingEye delay={0} x={8} y={15} size={1.2} />
      <FloatingEye delay={2} x={85} y={20} size={0.9} />
      <FloatingEye delay={4} x={12} y={65} size={1.0} />
      <FloatingEye delay={1} x={90} y={55} size={1.3} />
      <FloatingEye delay={3} x={75} y={80} size={0.8} />
      <FloatingEye delay={5} x={20} y={85} size={1.1} />
      <FloatingEye delay={2.5} x={50} y={10} size={0.7} />
      <FloatingEye delay={1.5} x={40} y={40} size={0.6} />
      <FloatingEye delay={3.5} x={65} y={70} size={0.9} />

      {/* Content */}
      <div className="relative z-10 max-w-3xl mx-auto px-4 py-6 min-h-screen flex flex-col">
        {/* Header */}
        <header className="text-center mb-4">
          <div className="flex items-center justify-between mb-3">
            <a
              href="/"
              className="text-xs text-[var(--text-muted)] hover:text-[var(--acid-cyan)] transition-colors"
            >
              &larr; aragora.ai
            </a>
            <span className="text-xs text-[var(--text-muted)] opacity-60">no coin required</span>
          </div>

          {/* Epigraph */}
          <p className="text-xs text-[var(--text-muted)] italic mb-3 opacity-50">
            &ldquo;Catastrophe is common. Termination is rare.&rdquo;
          </p>

          {/* Oracle title */}
          <h1
            className="text-3xl sm:text-4xl font-bold tracking-wider mb-1"
            style={{
              background: 'linear-gradient(135deg, var(--acid-magenta), var(--acid-cyan), var(--acid-green))',
              backgroundClip: 'text',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              filter: 'drop-shadow(0 0 20px rgba(255,0,255,0.3))',
            }}
          >
            THE ORACLE
          </h1>
          <p className="text-xs text-[var(--text-muted)] tracking-widest uppercase mb-1">
            Multi-Agent Decision Engine &middot; Real-Time AI Debate
          </p>
        </header>

        {/* Oracle avatar & intro */}
        {showIntro && (
          <div className="flex flex-col items-center mb-6 prophecy-reveal">
            {/* 3D Avatar — interactive iframe at half size */}
            <div className="relative mb-4">
              {/* Outer glow ring matching palantír colors */}
              <div
                className="absolute -inset-4 rounded-2xl"
                style={{
                  background: 'radial-gradient(ellipse at center, rgba(127,219,202,0.12), rgba(58,122,79,0.06), transparent 70%)',
                  animation: 'orb-pulse 6s ease-in-out infinite',
                  filter: 'blur(12px)',
                }}
                aria-hidden="true"
              />

              {/* 3D Avatar iframe */}
              <div className="relative w-[320px] h-[260px] sm:w-[400px] sm:h-[320px] overflow-hidden rounded-xl border border-[rgba(127,219,202,0.2)]">
                <iframe
                  ref={avatarRef}
                  src="/oracle/shoggoth-3d.html"
                  className="avatar-iframe w-full h-full"
                  title="Oracle 3D Avatar"
                  loading="eager"
                  allow="accelerometer"
                />
                {/* Bottom gradient fade into page */}
                <div
                  className="absolute bottom-0 left-0 right-0 h-16 pointer-events-none"
                  style={{
                    background: 'linear-gradient(transparent, #050508)',
                  }}
                />
              </div>
            </div>

            {/* Intro text */}
            <div className="text-center max-w-lg">
              <p className="text-sm text-[var(--text-muted)] leading-relaxed mb-3 italic">
                Multiple AI models debate your question in real time.
              </p>
              <p className="text-sm text-[var(--text-muted)] leading-relaxed mb-4">
                The Oracle orchestrates AI agents with different perspectives — Claude, GPT, Gemini,
                and more — to argue every angle of your question. Watch them debate, critique each other,
                and converge on a verdict with confidence scores.
              </p>
              <p className="text-xs text-[var(--acid-magenta)] opacity-60 mb-2">
                Choose your mode. Ask your question. Watch the debate unfold.
              </p>
            </div>
          </div>
        )}

        {/* Mode selector */}
        <div className="flex flex-col sm:flex-row gap-3 mb-6">
          <ModeButton
            mode="consult"
            active={mode === 'consult'}
            onClick={() => setMode('consult')}
            icon="&#x1F419;"
            label="DEBATE ME"
            desc="Bring your hottest take and I'll show you where it breaks"
          />
          <ModeButton
            mode="divine"
            active={mode === 'divine'}
            onClick={() => setMode('divine')}
            icon="&#x1F52E;"
            label="TELL MY FORTUNE"
            desc="Give me your situation and I'll show you three versions of your future"
          />
          <ModeButton
            mode="commune"
            active={mode === 'commune'}
            onClick={() => setMode('commune')}
            icon="&#x1F441;"
            label="ASK THE ORACLE"
            desc="Questions about what's coming, what to do, what to watch"
          />
        </div>

        {/* Debate mode toggle */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setUseDebateStreaming(false)}
              className={`px-3 py-1.5 text-xs font-mono border rounded-lg transition-all ${
                !useDebateStreaming
                  ? 'border-[var(--acid-magenta)]/60 text-[var(--acid-magenta)] bg-[var(--acid-magenta)]/10'
                  : 'border-[var(--border)]/30 text-[var(--text-muted)] hover:border-[var(--border)]/60'
              }`}
            >
              STREAM
            </button>
            <button
              type="button"
              onClick={() => setUseDebateStreaming(true)}
              className={`px-3 py-1.5 text-xs font-mono border rounded-lg transition-all ${
                useDebateStreaming
                  ? 'border-[var(--acid-cyan)]/60 text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10'
                  : 'border-[var(--border)]/30 text-[var(--text-muted)] hover:border-[var(--border)]/60'
              }`}
            >
              DEBATE
            </button>
          </div>
          <span className="text-[9px] text-[var(--text-muted)] tracking-wider">
            {useDebateStreaming ? 'Full multi-agent debate with structured events' : 'Direct LLM streaming with multi-agent analysis'}
          </span>
        </div>

        {/* Oracle Phase Progress Indicator */}
        <OraclePhaseProgress currentPhase={effectivePhase} />

        {/* Streaming telemetry strip */}
        <div className="mt-2 mb-4 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wider">
          <span className="px-2 py-1 border rounded border-[var(--border)]/40 text-[var(--text-muted)]">
            Stream: {streamStatusLabel}
          </span>
          {oracle.connected && oracle.phase !== 'idle' && (
            <span className="px-2 py-1 border rounded border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)]">
              {oracle.timeToFirstTokenMs === null
                ? 'TTFT measuring...'
                : `TTFT ${(oracle.timeToFirstTokenMs / 1000).toFixed(2)}s`}
            </span>
          )}
          {oracle.streamDurationMs !== null && (
            <span className="px-2 py-1 border rounded border-[var(--acid-green)]/30 text-[var(--acid-green)]">
              Duration {(oracle.streamDurationMs / 1000).toFixed(2)}s
            </span>
          )}
          {oracle.streamStalled && (
            <span className="px-2 py-1 border rounded border-[var(--crimson,#ff3333)]/40 text-[var(--crimson,#ff3333)]">
              Stall: {oracle.stallReason === 'waiting_first_token' ? 'no first token' : 'no stream activity'}
            </span>
          )}
        </div>

        {oracle.streamStalled && (
          <div className="mb-4 border border-[var(--crimson,#ff3333)]/35 bg-[var(--crimson,#ff3333)]/10 rounded-xl p-3 text-xs text-[var(--text-muted)] flex items-center justify-between gap-3">
            <span>
              Oracle stream appears stalled. You can reset the stream and resubmit your question.
            </span>
            <button
              type="button"
              onClick={() => {
                oracle.stop();
                setLoading(false);
                setDebating(false);
              }}
              className="shrink-0 px-3 py-1.5 border border-[var(--crimson,#ff3333)]/60 text-[var(--crimson,#ff3333)] hover:bg-[var(--crimson,#ff3333)]/20 transition-colors rounded-lg"
            >
              Reset Stream
            </button>
          </div>
        )}

        {/* Input */}
        <form onSubmit={consultOracle} className="flex gap-3 mb-4">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => { usedVoiceRef.current = false; setInput(e.target.value); }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  consultOracle(e);
                }
              }}
              placeholder={
                mode === 'divine'
                  ? 'Tell me your situation and I\'ll show you three futures...'
                  : mode === 'commune'
                    ? 'What do you want to know?'
                    : 'What\'s your take on AI? Give me the position you\'d bet money on.'
              }
              className="w-full bg-[#0c0c14] border border-[var(--border)]/40 text-white px-4 py-3 font-mono text-sm placeholder:text-[var(--text-muted)]/60 focus:outline-none focus:border-[var(--acid-magenta)]/60 transition-colors resize-none min-h-[48px] rounded-xl"
              disabled={loading || debating}
              rows={1}
            />
          </div>
          <button
            type="button"
            onClick={listening ? stopListening : startListening}
            disabled={loading || debating}
            className={`px-3 py-3 border text-sm transition-all duration-300 rounded-xl ${
              listening
                ? 'border-red-500/60 text-red-400 bg-red-500/10 animate-pulse'
                : 'border-[var(--acid-cyan)]/40 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10'
            } disabled:opacity-30 disabled:cursor-not-allowed`}
            title={listening ? 'Stop recording' : 'Speak your question'}
          >
            {listening ? '\u23F9' : '\uD83C\uDF99'}
          </button>
          <button
            type="submit"
            disabled={loading || debating || !input.trim()}
            className="px-6 py-3 border border-[var(--acid-magenta)]/60 text-[var(--acid-magenta)] font-bold text-sm hover:bg-[var(--acid-magenta)] hover:text-[var(--bg)] transition-all duration-300 disabled:opacity-30 disabled:cursor-not-allowed whitespace-nowrap rounded-xl"
            style={{
              boxShadow: !loading && !debating && input.trim() ? '0 0 10px rgba(255,0,255,0.12)' : 'none',
            }}
          >
            {loading ? '...' : debating ? '...' : 'SPEAK'}
          </button>
          {speaking && (
            <button
              type="button"
              onClick={stopSpeaking}
              className="px-3 py-3 border border-[var(--acid-cyan)]/40 text-[var(--acid-cyan)] text-sm hover:bg-[var(--acid-cyan)]/20 transition-all rounded-xl"
              title="Stop speaking"
            >
              &#x1F50A;
            </button>
          )}
          {/* Streaming audio controls (WebSocket TTS) */}
          {oracle.connected && oracle.phase !== 'idle' && (
            <>
              {oracle.audio.isPlaying() && (
                <button
                  type="button"
                  onClick={() => oracle.audio.pause()}
                  className="px-3 py-3 border border-[var(--acid-green)]/40 text-[var(--acid-green)] text-sm hover:bg-[var(--acid-green)]/20 transition-all rounded-xl"
                  title="Pause audio"
                >
                  &#x23F8;
                </button>
              )}
              {oracle.audio.isPaused() && (
                <button
                  type="button"
                  onClick={() => oracle.audio.resume()}
                  className="px-3 py-3 border border-[var(--acid-green)]/40 text-[var(--acid-green)] text-sm hover:bg-[var(--acid-green)]/20 transition-all rounded-xl"
                  title="Resume audio"
                >
                  &#x25B6;
                </button>
              )}
              <button
                type="button"
                onClick={() => oracle.audio.stop()}
                className="px-3 py-3 border border-[var(--crimson,#ff3333)]/40 text-[var(--crimson,#ff3333)] text-sm hover:bg-[var(--crimson,#ff3333)]/20 transition-all rounded-xl"
                title="Stop audio"
              >
                &#x23F9;
              </button>
            </>
          )}
        </form>

        {/* Chat area */}
        <div className="flex-1 min-h-[300px] border border-[var(--border)]/30 bg-[#08080c] p-4 mb-4 overflow-y-auto max-h-[60vh] rounded-xl">
          {messages.length === 0 && !loading && (
            <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-sm opacity-40">
              <span>The oracle awaits your question...</span>
            </div>
          )}

          <div className="space-y-6">
            {messages.map((msg, i) => (
              <div key={i}>
                {msg.role === 'seeker' ? (
                  <div className="prophecy-reveal text-right">
                    <div className="inline-block max-w-[85%] text-left">
                      <div className="text-xs text-[var(--text-muted)] mb-1">
                        SEEKER &middot; {new Date(msg.timestamp).toLocaleTimeString()}
                      </div>
                      <div className="bg-[var(--surface)] border border-[var(--border)]/30 p-3 text-sm text-[var(--text)] rounded-lg">
                        {msg.content}
                      </div>
                    </div>
                  </div>
                ) : msg.role === 'tentacle' ? (
                  <TentacleMessage msg={msg} index={i} />
                ) : (
                  <div className="prophecy-reveal max-w-[95%]">
                    <div className="text-xs mb-1">
                      <span
                        className="text-[var(--acid-magenta)]"
                        style={{ filter: 'drop-shadow(0 0 5px var(--acid-magenta))' }}
                      >
                        {msg.isLive ? 'ORACLE (synthesis)' : 'ORACLE'}
                      </span>
                      <span className="text-[var(--text-muted)]">
                        {' '}&middot; {msg.mode} &middot; {new Date(msg.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <div
                      className="border-l-2 border-[var(--acid-magenta)] pl-4 py-3 pr-3 text-sm leading-relaxed whitespace-pre-wrap rounded-r-lg"
                      style={{ color: '#2d1b4e', backgroundColor: 'rgba(200, 235, 210, 0.9)' }}
                    >
                      {msg.content}
                    </div>
                  </div>
                )}
              </div>
            ))}

            {/* Debate mode streaming display */}
            {oracle.connected && !oracle.fallbackMode && oracle.isDebateMode && oracle.phase !== 'idle' && (
              <DebateStreamDisplay
                events={oracle.debateEvents}
                agents={oracle.debateAgents}
                round={oracle.debateRound}
                debateId={oracle.debateId}
              />
            )}

            {/* WebSocket streaming display — real-time token flow (non-debate mode) */}
            {oracle.connected && !oracle.fallbackMode && !oracle.isDebateMode && oracle.phase !== 'idle' && (
              <>
                {/* Streaming Oracle response (reflex + deep tokens) */}
                {oracle.tokens && (
                  <div className="prophecy-reveal max-w-[95%]">
                    <div className="text-xs mb-1">
                      <span
                        className="text-[var(--acid-magenta)]"
                        style={{ filter: 'drop-shadow(0 0 5px var(--acid-magenta))' }}
                      >
                        ORACLE
                      </span>
                      <span className="text-[var(--text-muted)]">
                        {' '}&middot; {oracle.phase === 'reflex' ? 'sensing...' : oracle.phase === 'deep' ? 'channeling...' : mode}
                      </span>
                    </div>
                    <div
                      className="border-l-2 border-[var(--acid-magenta)] pl-4 py-3 pr-3 text-sm leading-relaxed whitespace-pre-wrap rounded-r-lg"
                      style={{ color: '#2d1b4e', backgroundColor: 'rgba(200, 235, 210, 0.9)' }}
                    >
                      {oracle.tokens}
                      {(oracle.phase === 'reflex' || oracle.phase === 'deep') && (
                        <span className="inline-block w-[2px] h-4 bg-[var(--acid-magenta)] ml-0.5 animate-pulse align-middle" />
                      )}
                    </div>
                  </div>
                )}

                {/* Streaming tentacle messages */}
                {oracle.phase === 'tentacles' && Array.from(oracle.tentacles.entries()).map(([agent, state], i) => (
                  <div key={agent} className={`prophecy-reveal ${i % 2 === 0 ? 'tentacle-left' : 'tentacle-right'}`} style={{ animationDelay: `${i * 0.3}s` }}>
                    <div className="text-xs mb-1 flex items-center gap-2">
                      <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: getTentacleColor(agent) }} />
                      <span style={{ color: getTentacleColor(agent) }} className="font-bold">
                        {agent.toUpperCase()}
                      </span>
                      {!state.done && (
                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--acid-cyan)] animate-pulse" />
                      )}
                    </div>
                    <div
                      className="border-l-2 pl-4 py-3 pr-3 text-sm leading-relaxed whitespace-pre-wrap ml-1 rounded-r-lg"
                      style={{ borderColor: getTentacleColor(agent), color: '#2d1b4e', backgroundColor: 'rgba(200, 235, 210, 0.9)' }}
                    >
                      {state.text}
                      {!state.done && (
                        <span className="inline-block w-[2px] h-4 bg-[var(--acid-cyan)] ml-0.5 animate-pulse align-middle" />
                      )}
                    </div>
                  </div>
                ))}

                {/* Convergence map — shows after tentacles complete */}
                {oracle.phase === 'synthesis' && oracle.tentacles.size >= 2 && (
                  <ConvergenceMap tentacles={oracle.tentacles} />
                )}

                {/* Synthesis */}
                {oracle.synthesis && (
                  <div className="prophecy-reveal max-w-[95%]">
                    <div className="text-xs mb-1">
                      <span className="text-[var(--acid-magenta)]" style={{ filter: 'drop-shadow(0 0 5px var(--acid-magenta))' }}>
                        ORACLE (synthesis)
                      </span>
                    </div>
                    <div
                      className="border-l-2 border-[var(--acid-magenta)] pl-4 py-3 pr-3 text-sm leading-relaxed whitespace-pre-wrap rounded-r-lg"
                      style={{ color: '#2d1b4e', backgroundColor: 'rgba(200, 235, 210, 0.9)' }}
                    >
                      {oracle.synthesis}
                    </div>
                  </div>
                )}
              </>
            )}

            {/* Phase 1 loading (fetch fallback or pre-stream) */}
            {loading && (oracle.fallbackMode || !oracle.connected || !oracle.tokens) && (
              <div className="prophecy-reveal">
                <div className="text-xs mb-1">
                  <span
                    className="text-[var(--acid-magenta)]"
                    style={{ filter: 'drop-shadow(0 0 5px var(--acid-magenta))' }}
                  >
                    ORACLE
                  </span>
                  <span className="text-[var(--text-muted)]"> &middot; channeling...</span>
                </div>
                <div className="border-l-2 border-[var(--acid-magenta)] pl-4">
                  {fillerDisplayText ? (
                    <div className="text-sm text-[var(--acid-cyan)] italic leading-relaxed py-2">
                      <span className="inline-block w-2 h-2 rounded-full bg-[var(--acid-magenta)] animate-pulse mr-2 align-middle" />
                      {fillerDisplayText}
                      <span className="inline-block w-[2px] h-4 bg-[var(--acid-cyan)] ml-0.5 animate-pulse align-middle" />
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-sm text-[var(--acid-cyan)]">
                      <span className="inline-block w-2 h-2 rounded-full bg-[var(--acid-magenta)] animate-pulse" />
                      <span className="opacity-60">
                        {mode === 'divine'
                          ? 'Gazing into branching timelines...'
                          : mode === 'commune'
                            ? 'The ancient one stirs...'
                            : 'The Oracle forms an initial vision...'}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Phase 2 loading (fetch fallback) */}
            {debating && (oracle.fallbackMode || !oracle.connected) && (
              <div className="prophecy-reveal">
                <div className="text-xs mb-1">
                  <span className="text-[var(--acid-cyan)]" style={{ filter: 'drop-shadow(0 0 5px var(--acid-cyan))' }}>
                    DEBATE
                  </span>
                  <span className="text-[var(--text-muted)]"> &middot; assembling...</span>
                </div>
                <div className="border-l-2 border-[var(--acid-cyan)] pl-4">
                  <div className="flex items-center gap-2 text-sm text-[var(--acid-cyan)]">
                    <span className="inline-block w-2 h-2 rounded-full bg-[var(--acid-cyan)] animate-pulse" />
                    <span className="opacity-60">
                      Live agents are debating your question. Each will argue its position...
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* EU AI Act Compliance CTA — shows after debate completes */}
          {messages.length > 0 && !loading && !debating && messages.some((m) => m.isLive) && (
            <div
              className="mt-6 p-4 border rounded-lg flex items-center justify-between gap-4 prophecy-reveal"
              style={{
                borderColor: 'var(--border)',
                backgroundColor: 'var(--surface)',
              }}
            >
              <div>
                <p className="text-sm font-bold" style={{ color: 'var(--text)' }}>
                  Need compliance documentation?
                </p>
                <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                  Generate EU AI Act Article 12, 13, 14 artifacts from this debate.
                </p>
              </div>
              <a
                href="/compliance"
                className="shrink-0 px-4 py-2 text-xs font-bold transition-colors rounded-lg whitespace-nowrap"
                style={{
                  border: '1px solid var(--acid-green)',
                  color: 'var(--acid-green)',
                  backgroundColor: 'transparent',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(57,255,20,0.1)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
              >
                Generate Bundle
              </a>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Error */}
        {error && (
          <div className="border border-[var(--crimson)] bg-[var(--crimson)]/10 p-3 mb-4 text-sm text-[var(--crimson)] rounded-xl flex items-center justify-between gap-3">
            <span>{error}</span>
            {/auth|unauthorized|401|login/i.test(error) && (
              <a
                href={`/login?redirect=${encodeURIComponent('/oracle')}`}
                className="shrink-0 px-3 py-1 border border-[var(--acid-cyan)]/60 text-[var(--acid-cyan)] text-xs font-bold hover:bg-[var(--acid-cyan)]/10 transition-colors rounded-lg whitespace-nowrap"
              >
                Log in to continue
              </a>
            )}
          </div>
        )}

        {/* Footer */}
        <footer className="mt-6 text-center text-xs text-[var(--text-muted)] opacity-40 space-y-2 rounded-xl">
          <p className="italic opacity-70">
            Multiple AI perspectives. One clear verdict.
          </p>
          <p>
            Powered by{' '}
            <a href="/" className="text-[var(--acid-cyan)] hover:text-[var(--acid-magenta)] transition-colors">
              aragora.ai
            </a>
            {' '}&middot; Multi-agent adversarial debate engine
          </p>
          <p>
            Powered by{' '}
            <span className="text-[var(--acid-green)]">Claude</span>,{' '}
            <span className="text-[var(--acid-cyan)]">GPT</span>,{' '}
            <span style={{ color: 'var(--crimson, #ff3333)' }}>Grok</span>,{' '}
            <span style={{ color: 'var(--purple, #a855f7)' }}>Gemini</span>,{' '}
            <span style={{ color: 'var(--gold, #ffd700)' }}>DeepSeek</span>,{' '}
            <span className="text-[var(--acid-magenta)]">Mistral</span>
          </p>
          <div className="flex gap-6 justify-center pt-1">
            <a
              href="https://anomium.substack.com/p/ai-evolution-and-the-myth-of-final?triedRedirect=true"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-[var(--acid-cyan)] transition-colors"
            >
              Read the Essay
            </a>
            <a href="/" className="hover:text-[var(--acid-cyan)] transition-colors">
              Explore Aragora
            </a>
          </div>
          <p className="opacity-60">
            &ldquo;Don&apos;t smash the amp.&rdquo;
          </p>
        </footer>
      </div>
    </div>
  );
}
