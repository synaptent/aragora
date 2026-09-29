/** Shape of the debate JSON returned by the backend API. */
export interface SavedDebateMessage {
  role: string;
  content: string;
  agent?: string;
  round?: number;
  timestamp?: string;
}

export interface SavedDebate {
  id: string;
  topic: string;
  status: string;
  rounds_used?: number;
  consensus_reached: boolean;
  confidence: number;
  verdict: string | null;
  duration_seconds: number;
  participants: string[];
  proposals: Record<string, string>;
  critiques: Array<{ agent: string; target: string; text: string }>;
  votes: Array<{ agent: string; choice: string; confidence: number }>;
  final_answer: string;
  receipt_hash: string | null;
  result_mode?: string;
  result_warning?: string;
  messages?: SavedDebateMessage[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

function parseSavedDebate(payload: unknown): SavedDebate | null {
  if (!payload || typeof payload !== 'object') {
    return null;
  }

  const debate = payload as Record<string, unknown>;
  const id =
    typeof debate.id === 'string'
      ? debate.id
      : typeof debate.debate_id === 'string'
        ? debate.debate_id
        : null;
  const topic =
    typeof debate.topic === 'string'
      ? debate.topic
      : typeof debate.task === 'string'
        ? debate.task
        : typeof debate.question === 'string'
          ? debate.question
          : null;
  const status = typeof debate.status === 'string' ? debate.status : 'completed';
  const messages = normalizeMessages(debate.messages ?? debate.transcript);
  const participants = normalizeParticipants(debate.participants ?? debate.agents, messages);
  const proposals = normalizeProposals(debate.proposals, messages);
  const critiques = normalizeCritiques(debate.critiques);
  const votes = normalizeVotes(debate.votes);
  const finalAnswer =
    firstString(debate.final_answer, debate.conclusion, debate.winning_proposal, debate.verdict) ??
    '';
  const verdict = firstString(debate.verdict, debate.winning_proposal, debate.final_answer) ?? null;
  const receiptHash =
    debate.receipt_hash == null
      ? null
      : typeof debate.receipt_hash === 'string'
        ? debate.receipt_hash
        : null;
  const resultMode = typeof debate.result_mode === 'string' ? debate.result_mode : undefined;
  const resultWarning =
    typeof debate.result_warning === 'string' ? debate.result_warning : undefined;

  if (!id || !topic) {
    return null;
  }

  return {
    id,
    topic,
    status,
    rounds_used: normalizeRoundsUsed(debate.rounds_used ?? debate.rounds, messages),
    consensus_reached: normalizeConsensusReached(debate),
    confidence: normalizeConfidence(debate),
    verdict,
    duration_seconds: normalizeNumber(debate.duration_seconds),
    participants,
    proposals,
    critiques,
    votes,
    final_answer: finalAnswer,
    receipt_hash: receiptHash,
    ...(resultMode ? { result_mode: resultMode } : {}),
    ...(resultWarning ? { result_warning: resultWarning } : {}),
    messages: messages.length > 0 ? messages : undefined,
  };
}

function firstString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.length > 0) {
      return value;
    }
  }
  return null;
}

function normalizeNumber(value: unknown, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
}

function normalizeConsensusReached(payload: Record<string, unknown>): boolean {
  if (typeof payload.consensus_reached === 'boolean') {
    return payload.consensus_reached;
  }
  if (
    payload.consensus &&
    typeof payload.consensus === 'object' &&
    payload.consensus !== null &&
    typeof (payload.consensus as Record<string, unknown>).reached === 'boolean'
  ) {
    return Boolean((payload.consensus as Record<string, unknown>).reached);
  }
  return false;
}

function normalizeConfidence(payload: Record<string, unknown>): number {
  if (typeof payload.confidence === 'number') {
    return payload.confidence;
  }
  if (typeof payload.agreement === 'number') {
    return payload.agreement;
  }
  if (payload.consensus && typeof payload.consensus === 'object' && payload.consensus !== null) {
    const consensus = payload.consensus as Record<string, unknown>;
    return normalizeNumber(consensus.confidence ?? consensus.agreement);
  }
  return 0;
}

function normalizeRoundsUsed(value: unknown, messages: SavedDebateMessage[]): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.length;
  }
  return messages.reduce((maxRound, message) => {
    const round = typeof message.round === 'number' ? message.round : 0;
    return Math.max(maxRound, round);
  }, 0);
}

function normalizeMessages(value: unknown): SavedDebateMessage[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') {
      return [];
    }

    const record = item as Record<string, unknown>;
    const content = firstString(record.content, record.text, record.message);
    if (!content) {
      return [];
    }

    const role = firstString(record.role, record.kind, record.type) ?? 'agent';
    const agent = firstString(record.agent, record.name);
    const round = typeof record.round === 'number' ? record.round : undefined;
    const timestamp = typeof record.timestamp === 'string' ? record.timestamp : undefined;

    return [
      {
        role,
        content,
        ...(agent ? { agent } : {}),
        ...(round != null ? { round } : {}),
        ...(timestamp ? { timestamp } : {}),
      },
    ];
  });
}

function normalizeParticipants(value: unknown, messages: SavedDebateMessage[]): string[] {
  if (Array.isArray(value)) {
    return value.filter((participant): participant is string => typeof participant === 'string');
  }

  const agents = messages
    .map((message) => message.agent)
    .filter((agent): agent is string => typeof agent === 'string' && agent.length > 0);

  return Array.from(new Set(agents));
}

function normalizeProposals(
  value: unknown,
  messages: SavedDebateMessage[],
): Record<string, string> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).flatMap(([agent, content]) =>
        typeof content === 'string' ? [[agent, content]] : [],
      ),
    );
  }

  const grouped = new Map<string, string[]>();
  for (const message of messages) {
    if (!message.agent) {
      continue;
    }
    const existing = grouped.get(message.agent) ?? [];
    existing.push(message.content);
    grouped.set(message.agent, existing);
  }

  return Object.fromEntries(
    Array.from(grouped.entries()).map(([agent, content]) => [agent, content.join('\n\n')]),
  );
}

function normalizeCritiques(
  value: unknown,
): Array<{ agent: string; target: string; text: string }> {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') {
      return [];
    }

    const record = item as Record<string, unknown>;
    const agent = firstString(record.agent, record.author) ?? 'unknown';
    const target = firstString(record.target, record.target_agent, record.to_agent) ?? '';
    const text =
      firstString(record.text, record.summary) ??
      (Array.isArray(record.issues)
        ? record.issues.filter((issue): issue is string => typeof issue === 'string').join('\n')
        : null);

    if (!text) {
      return [];
    }

    return [{ agent, target, text }];
  });
}

function normalizeVotes(
  value: unknown,
): Array<{ agent: string; choice: string; confidence: number }> {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') {
      return [];
    }

    const record = item as Record<string, unknown>;
    const agent = firstString(record.agent, record.name);
    const choice = firstString(record.choice, record.vote, record.verdict);

    if (!agent || !choice) {
      return [];
    }

    return [{ agent, choice, confidence: normalizeNumber(record.confidence) }];
  });
}

async function fetchDebateFromCandidateUrls(
  debateId: string,
  init: RequestInit,
): Promise<SavedDebate | null> {
  const encodedDebateId = encodeURIComponent(debateId);
  const urls = [
    `${API_BASE}/api/v1/debates/public/${encodedDebateId}`,
    `${API_BASE}/api/v1/playground/debate/${encodedDebateId}`,
  ];

  for (const url of urls) {
    try {
      const res = await fetch(url, init);
      if (!res.ok) continue;
      const data = await res.json();
      const debate = parseSavedDebate(data?.data ?? data);
      if (debate) {
        return debate;
      }
    } catch {
      // Try the next candidate URL
    }
  }

  return null;
}

/**
 * Fetch a saved debate from the backend API (server-side).
 *
 * Tries the public viewer endpoint first (no auth required, checks shareability),
 * then falls back to the playground endpoint for backward compatibility.
 * Returns null when the debate cannot be fetched (not found, API down, etc.).
 */
export async function fetchDebate(debateId: string): Promise<SavedDebate | null> {
  return fetchDebateFromCandidateUrls(debateId, { next: { revalidate: 300 } });
}

/**
 * Fetch a saved debate from the browser runtime.
 *
 * Used by the standalone viewer as a fail-soft recovery path when the initial
 * server-side preload misses but the permalink still resolves publicly.
 */
export async function fetchDebateClient(debateId: string): Promise<SavedDebate | null> {
  return fetchDebateFromCandidateUrls(debateId, { cache: 'no-store' });
}
