"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import { getRuntimeBackendConfig } from "@/components/BackendSelector";
import { ThemeSelector } from "@/components/landing/ThemeSelector";

interface RecordedEvent {
  type: "proposal" | "critique" | "vote" | "consensus";
  agent: string;
  model: string;
  content: string;
  round: number;
  confidence?: number;
  vote?: "support" | "oppose" | "neutral";
}

interface RecordedDebate {
  id: string;
  topic: string;
  agents: string[];
  rounds: number;
  confidence: number;
  verdict: string;
  receiptHash: string;
  events: RecordedEvent[];
}

interface LiveDebateResult {
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
  share_url?: string;
  is_live?: boolean;
  mock_fallback?: boolean;
  mock_fallback_reason?: string;
}

const DEMO_TOPIC =
  "Should our startup adopt AI-powered code review as a mandatory step in our CI/CD pipeline?";

const EYEBROW_TEXT_STYLE = {
  fontSize: "12px",
  letterSpacing: "0.16em",
  lineHeight: "1.5",
} as const;

const LABEL_TEXT_STYLE = {
  fontSize: "12px",
  letterSpacing: "0.14em",
  lineHeight: "1.5",
} as const;

const LIVE_PROGRESS_STEPS = [
  "Submitting the canonical public demo question",
  "Collecting multi-agent positions from the playground backend",
  "Persisting a shareable debate result",
];

const PAGE_SHELL_MAX_WIDTH = "1240px";

const RECORDED_SAMPLE: RecordedDebate = {
  id: "demo_showcase_001",
  topic: DEMO_TOPIC,
  agents: ["claude-opus", "gpt-5", "gemini-pro", "mistral-large", "grok"],
  rounds: 2,
  confidence: 0.82,
  verdict:
    "Adopt AI code review as an advisory layer with human override, not a blocking gate. Start with security-critical paths only, expand based on measured false-positive rates.",
  receiptHash: "a7f3c91b2d4e8f06",
  events: [
    {
      type: "proposal",
      agent: "claude-opus",
      model: "Claude Opus 4.8",
      content:
        "Yes, adopt it as mandatory. AI code review catches security vulnerabilities that human reviewers miss 34% of the time. The key is treating it as a complement, not a replacement: flag issues for human judgment, not auto-reject.",
      round: 1,
      confidence: 0.85,
    },
    {
      type: "proposal",
      agent: "gpt-5",
      model: "GPT-5.4",
      content:
        "Mandatory is too strong. AI review tools have 15-25% false positive rates on complex codebases. Making it mandatory creates alert fatigue and slows velocity. Better as advisory with opt-in enforcement for security-critical paths.",
      round: 1,
      confidence: 0.78,
    },
    {
      type: "critique",
      agent: "gemini-pro",
      model: "Gemini 3.1 Pro",
      content:
        "Both proposals miss the cost dimension. AI review at scale costs $0.02-0.15 per PR. For a team doing 200 PRs/week, that is $200-1,500/month. The ROI depends on your current bug escape rate.",
      round: 1,
      confidence: 0.72,
    },
    {
      type: "critique",
      agent: "mistral-large",
      model: "Mistral Large",
      content:
        "The benchmark-based security claim does not map cleanly onto production code. AI reviewers are strongest on recurring patterns and weaker on business-logic failures.",
      round: 1,
      confidence: 0.76,
    },
    {
      type: "proposal",
      agent: "grok",
      model: "Grok 3",
      content:
        "The right framing is path-based enforcement. Security-critical code should require AI review. Lower-risk product code should stay advisory.",
      round: 2,
      confidence: 0.88,
    },
    {
      type: "vote",
      agent: "claude-opus",
      model: "Claude Opus 4.8",
      content:
        "I revise my position. Path-based mandatory review is the pragmatic middle ground.",
      round: 2,
      vote: "support",
      confidence: 0.84,
    },
    {
      type: "vote",
      agent: "gpt-5",
      model: "GPT-5.4",
      content:
        "Tiered enforcement addresses my velocity concern while maintaining security coverage.",
      round: 2,
      vote: "support",
      confidence: 0.81,
    },
    {
      type: "consensus",
      agent: "system",
      model: "Consensus Engine",
      content:
        "Consensus reached. Adopt AI code review as an advisory layer with mandatory enforcement on security-critical paths, then measure false-positive rate and ROI at 90 days.",
      round: 2,
      confidence: 0.82,
    },
  ],
};

const AGENT_ACCENTS = [
  "#15803d",
  "#2563eb",
  "#d97706",
  "#dc2626",
  "#7c3aed",
  "#0f766e",
];

function accentForAgent(agent: string): string {
  let hash = 0;
  for (const char of agent) {
    hash = (hash + char.charCodeAt(0)) % AGENT_ACCENTS.length;
  }
  return AGENT_ACCENTS[hash];
}

function formatAgentName(agent: string): string {
  const replacements: Record<string, string> = {
    claude: "Claude",
    "claude-opus": "Claude Opus 5",
    "claude-sonnet": "Claude Sonnet 4.6",
    gpt: "GPT",
    "gpt-5": "GPT-5.4",
    "gpt-4o": "GPT-4o",
    grok: "Grok 3",
    "grok-2": "Grok 2",
    gemini: "Gemini",
    "gemini-pro": "Gemini 3.1 Pro",
    mistral: "Mistral",
    "mistral-large": "Mistral Large",
    deepseek: "DeepSeek V3",
    system: "Consensus Engine",
  };

  const normalized = agent.trim().toLowerCase();
  if (replacements[normalized]) {
    return replacements[normalized];
  }

  return normalized
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => {
      if (part === "gpt") return "GPT";
      if (part === "ai") return "AI";
      if (/^\d/.test(part)) return part;
      return part.charAt(0).toUpperCase() + part.slice(1);
    })
    .join(" ");
}

function normalizeProposals(
  proposals: unknown,
  participants: string[],
): Record<string, string> {
  if (proposals && typeof proposals === "object" && !Array.isArray(proposals)) {
    return Object.fromEntries(
      Object.entries(proposals).map(([agent, value]) => [
        agent,
        String(value ?? ""),
      ]),
    );
  }

  if (Array.isArray(proposals)) {
    return Object.fromEntries(
      proposals.map((value, index) => [
        participants[index] ?? `agent_${index + 1}`,
        typeof value === "string" ? value : JSON.stringify(value),
      ]),
    );
  }

  return {};
}

function normalizeLiveDebateResult(data: unknown): LiveDebateResult | null {
  if (!data || typeof data !== "object") {
    return null;
  }

  const raw = data as Record<string, unknown>;
  const participants = Array.isArray(raw.participants)
    ? raw.participants.map((participant) => String(participant))
    : [];

  return {
    id: String(raw.id ?? ""),
    topic: String(raw.topic ?? DEMO_TOPIC),
    status: String(raw.status ?? "completed"),
    rounds_used: Number(raw.rounds_used ?? 1),
    consensus_reached: Boolean(raw.consensus_reached),
    confidence: Number(raw.confidence ?? 0),
    verdict: raw.verdict == null ? null : String(raw.verdict),
    duration_seconds: Number(raw.duration_seconds ?? 0),
    participants,
    proposals: normalizeProposals(raw.proposals, participants),
    final_answer: String(raw.final_answer ?? ""),
    receipt_hash: raw.receipt_hash == null ? null : String(raw.receipt_hash),
    share_url: raw.share_url == null ? undefined : String(raw.share_url),
    is_live: raw.is_live == null ? undefined : Boolean(raw.is_live),
    mock_fallback: Boolean(raw.mock_fallback),
    mock_fallback_reason:
      raw.mock_fallback_reason == null
        ? undefined
        : String(raw.mock_fallback_reason),
  };
}

function formatVerdict(result: LiveDebateResult): string {
  const directVerdict = result.final_answer.trim()
    ? result.final_answer.trim()
    : result.verdict
      ? result.verdict.replace(/_/g, " ")
      : "";

  if (!directVerdict) {
    return "No verdict returned.";
  }

  const synthesizedVerdict = buildVerdictFallback(result, directVerdict);
  return synthesizedVerdict ?? directVerdict;
}

function compactHash(value: string, leading = 16, trailing = 10): string {
  if (value.length <= leading + trailing + 1) {
    return value;
  }

  return `${value.slice(0, leading)}…${value.slice(-trailing)}`;
}

function cleanPreviewText(text: string): string {
  return text
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[(.*?)\]\((.*?)\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^["'“”]+|["'“”]+$/g, "");
}

function containsMarkdownSyntax(text: string): boolean {
  return /(^|\n)\s*#{1,6}\s+|(^|\n)\s*[-*+]\s+|(^|\n)\s*\d+\.\s+|\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\[[^\]]+\]\([^)]+\)/m.test(
    text,
  );
}

function normalizeComparableText(text: string): string {
  return cleanPreviewText(text)
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function tokenOverlapRatio(a: string, b: string): number {
  const aTokens = new Set(a.split(" ").filter(Boolean));
  const bTokens = new Set(b.split(" ").filter(Boolean));
  if (aTokens.size === 0 || bTokens.size === 0) {
    return 0;
  }

  let overlap = 0;
  for (const token of aTokens) {
    if (bTokens.has(token)) {
      overlap += 1;
    }
  }

  return overlap / Math.max(aTokens.size, bTokens.size);
}

function lowerFirst(text: string): string {
  if (!text) {
    return text;
  }
  return text.charAt(0).toLowerCase() + text.slice(1);
}

function splitIntoSentences(text: string): string[] {
  return cleanPreviewText(text)
    .split(/(?<=[.!?])\s+(?=[A-Z0-9])/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

function trimInsight(text: string, maxLength = 170): string {
  if (text.length <= maxLength) {
    return text;
  }

  const trimmed = text.slice(0, maxLength);
  const boundary = trimmed.lastIndexOf(" ");
  return `${trimmed.slice(0, boundary > 0 ? boundary : maxLength).trim()}…`;
}

function buildVerdictFallback(
  result: LiveDebateResult,
  directVerdict: string,
): string | null {
  const normalizedVerdict = normalizeComparableText(directVerdict);
  if (!normalizedVerdict) {
    return null;
  }

  const proposalEntries = Object.entries(result.proposals).filter(([, value]) =>
    normalizeComparableText(value),
  );

  if (proposalEntries.length < 2) {
    return null;
  }

  const echoesProposal = proposalEntries.some(([, proposal]) => {
    const normalizedProposal = normalizeComparableText(proposal);
    if (!normalizedProposal) {
      return false;
    }

    if (normalizedVerdict === normalizedProposal) {
      return true;
    }

    const shorter = Math.min(normalizedVerdict.length, normalizedProposal.length);
    const longer = Math.max(normalizedVerdict.length, normalizedProposal.length);

    return (
      shorter / longer > 0.72 &&
      tokenOverlapRatio(normalizedVerdict, normalizedProposal) > 0.82
    );
  });

  if (!echoesProposal) {
    return null;
  }

  const debateLead = result.consensus_reached
    ? `The returned agents reached a ${Math.round(result.confidence * 100)}% confidence consensus after ${result.rounds_used} round${result.rounds_used === 1 ? "" : "s"}, but they emphasized different tradeoffs.`
    : "The returned agents surfaced competing positions without a clean consensus.";

  const positionHighlights = proposalEntries
    .slice(0, 3)
    .map(([agent, proposal]) => {
      const firstSentence =
        splitIntoSentences(proposal)[0] || cleanPreviewText(proposal);
      return `${formatAgentName(agent)} argued that ${lowerFirst(trimInsight(firstSentence, 130))}`;
    })
    .join(" ");

  return `${debateLead} ${positionHighlights}`.trim();
}

function pickInsight(
  sentences: string[],
  used: Set<number>,
  patterns: RegExp[],
): string | null {
  const index = sentences.findIndex(
    (sentence, sentenceIndex) =>
      !used.has(sentenceIndex) &&
      patterns.some((pattern) => pattern.test(sentence)),
  );

  if (index === -1) {
    return null;
  }

  used.add(index);
  return sentences[index];
}

function buildDecisionSnapshot(summary: string): {
  recommendation: string;
  rationale: string;
  caution: string;
  nextStep: string;
} {
  if (/^The returned agents (reached|surfaced)/i.test(summary.trim())) {
    const sentences = splitIntoSentences(summary);
    return {
      recommendation: trimInsight(
        sentences[0] || "The returned agents reached a conditional consensus.",
        220,
      ),
      rationale: trimInsight(
        sentences[1] ||
          "The strongest support for the recommendation is captured in the agent positions below.",
      ),
      caution: trimInsight(
        "The returned agents still emphasize different tradeoffs, so the rollout should stay measured and reversible.",
      ),
      nextStep: "Compare the agent positions below before turning this into policy.",
    };
  }

  const sentences = splitIntoSentences(summary);
  const used = new Set<number>();

  const recommendation =
    sentences[0]?.replace(/^As the [^,]+,\s*/i, "").trim() ||
    "Review the full verdict below.";
  if (sentences[0]) {
    used.add(0);
  }

  const rationale =
    pickInsight(sentences, used, [
      /benefit/i,
      /improv/i,
      /reduce/i,
      /quality/i,
      /security/i,
      /velocity/i,
      /impact/i,
      /value/i,
    ]) ||
    sentences.find((_, index) => !used.has(index)) ||
    "The case for the recommendation is in the full verdict below.";

  const caution =
    pickInsight(sentences, used, [
      /however/i,
      /but/i,
      /risk/i,
      /uncertaint/i,
      /cost/i,
      /friction/i,
      /latency/i,
      /false positive/i,
      /trade-?off/i,
      /pushback/i,
    ]) ||
    "The decision still depends on rollout tradeoffs, costs, and human review.";

  const nextStep =
    pickInsight(sentences, used, [
      /start/i,
      /pilot/i,
      /rollout/i,
      /measure/i,
      /monitor/i,
      /review/i,
      /phase/i,
      /prioriti/i,
      /recommend/i,
    ]) ||
    "Compare the agent positions below before turning this into policy.";

  const normalizedRationale = normalizeComparableText(rationale);
  let distinctCaution = caution;
  if (normalizeComparableText(caution) === normalizedRationale) {
    distinctCaution =
      pickInsight(sentences, used, [
        /however/i,
        /but/i,
        /risk/i,
        /uncertaint/i,
        /cost/i,
        /friction/i,
        /latency/i,
        /false positive/i,
        /trade-?off/i,
        /pushback/i,
      ]) ||
      "The recommendation still depends on rollout risk, cost control, and human review discipline.";
  }

  let distinctNextStep = nextStep;
  const normalizedNextStep = normalizeComparableText(nextStep);
  if (
    normalizedNextStep === normalizedRationale ||
    normalizedNextStep === normalizeComparableText(distinctCaution)
  ) {
    distinctNextStep =
      "Compare the agent positions below before turning this into policy.";
  }

  return {
    recommendation: trimInsight(recommendation, 220),
    rationale: trimInsight(rationale),
    caution: trimInsight(distinctCaution),
    nextStep: trimInsight(distinctNextStep),
  };
}

function MarkdownBody({
  text,
  className,
}: {
  text: string;
  className: string;
}) {
  return (
    <div className={className}>
      <ReactMarkdown
        components={{
          h1: ({ children }) => (
            <h4 className="mb-3 text-[1.05em] font-semibold leading-7">
              {children}
            </h4>
          ),
          h2: ({ children }) => (
            <h4 className="mb-3 text-[1.05em] font-semibold leading-7">
              {children}
            </h4>
          ),
          h3: ({ children }) => (
            <h4 className="mb-3 text-[1.02em] font-semibold leading-7">
              {children}
            </h4>
          ),
          p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
          ul: ({ children }) => (
            <ul className="mb-3 list-disc space-y-2 pl-5 last:mb-0">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-3 list-decimal space-y-2 pl-5 last:mb-0">
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="pl-1">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          code: ({ children }) => (
            <code className="rounded bg-[var(--surface-elevated)] px-1.5 py-0.5 text-[0.95em]">
              {children}
            </code>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function StatusBadge({
  label,
  tone,
}: {
  label: string;
  tone: "live" | "fallback" | "sample";
}) {
  const styles = {
    live: "border-[var(--acid-green)]/40 bg-[var(--acid-green)]/10 text-[var(--acid-green)]",
    fallback: "border-amber-500/25 bg-amber-500/8 text-amber-700",
    sample: "border-sky-500/20 bg-sky-500/8 text-sky-700",
  }[tone];

  return (
    <span
      className={`inline-flex items-center rounded-full border font-semibold uppercase ${styles}`}
      style={{ ...EYEBROW_TEXT_STYLE, padding: "8px 14px" }}
    >
      {label}
    </span>
  );
}

function AgentRoster({ agents }: { agents: string[] }) {
  return (
    <div className="flex flex-wrap gap-3">
      {agents.map((agent) => {
        const accent = accentForAgent(agent);
        return (
          <div
            key={agent}
            className="rounded-full border text-[15px] font-semibold tracking-[0.04em] shadow-[var(--shadow-panel)]"
            style={{
              borderColor: `${accent}26`,
              color: accent,
              backgroundColor: `${accent}10`,
              padding: "10px 16px",
            }}
          >
            {formatAgentName(agent)}
          </div>
        );
      })}
    </div>
  );
}

function ConsensusBar({ confidence }: { confidence: number }) {
  const clamped = Math.max(0, Math.min(confidence, 1));

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-[13px] font-medium text-[var(--text-muted)]">
        <span className="uppercase tracking-[0.12em]">
          Consensus confidence
        </span>
        <span className="rounded-full bg-[var(--surface-elevated)] px-3.5 py-1.5 font-semibold text-[var(--acid-green)] shadow-[var(--shadow-panel)]">
          {Math.round(clamped * 100)}%
        </span>
      </div>
      <div
        className="overflow-hidden rounded-full border border-[var(--border)] bg-[var(--surface-elevated)]"
        style={{ height: "14px" }}
      >
        <div
          className="h-full bg-[var(--acid-green)]"
          style={{ width: `${clamped * 100}%` }}
        />
      </div>
    </div>
  );
}

function SnapshotCard({
  label,
  value,
  accentClass,
  className = "",
}: {
  label: string;
  value: string;
  accentClass: string;
  className?: string;
}) {
  return (
    <div
      className={`h-full rounded-[18px] border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-panel)] ${className}`}
      style={{
        padding: "24px",
        display: "flex",
        flexDirection: "column",
        gap: "12px",
      }}
    >
      <div
        className={`font-semibold uppercase ${accentClass}`}
        style={LABEL_TEXT_STYLE}
      >
        {label}
      </div>
      <p className="text-[15px] leading-7 text-[var(--text)] text-pretty">
        {value}
      </p>
    </div>
  );
}

function DecisionSnapshot({
  summary,
  tone,
}: {
  summary: string;
  tone: "live" | "sample";
}) {
  const snapshot = buildDecisionSnapshot(summary);
  const accentClass =
    tone === "live" ? "text-[var(--acid-green)]" : "text-sky-700";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "32px",
      }}
    >
      <h3
        className={`font-semibold uppercase ${accentClass}`}
        style={EYEBROW_TEXT_STYLE}
      >
        Decision snapshot
      </h3>
      <div className="grid items-stretch gap-4 md:grid-cols-2">
        <SnapshotCard
          label="Recommendation"
          value={snapshot.recommendation}
          accentClass={accentClass}
          className="md:col-span-2"
        />
        <SnapshotCard
          label="Why"
          value={snapshot.rationale}
          accentClass={accentClass}
          className="md:min-h-[260px]"
        />
        <SnapshotCard
          label="Main caution"
          value={snapshot.caution}
          accentClass={accentClass}
          className="md:min-h-[260px]"
        />
        <SnapshotCard
          label="Next step"
          value={snapshot.nextStep}
          accentClass={accentClass}
          className="md:col-span-2"
        />
      </div>
    </div>
  );
}

function DetailRow({
  label,
  value,
  mono = false,
  title,
  compact = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  title?: string;
  compact?: boolean;
}) {
  return (
    <div
      className="rounded-[14px] bg-[var(--surface)] shadow-[var(--shadow-panel)]"
      style={{
        padding: compact ? "9px 13px" : "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: compact ? "3px" : "6px",
      }}
    >
      <dt
        className="font-semibold uppercase text-[var(--text-muted)]"
        style={LABEL_TEXT_STYLE}
      >
        {label}
      </dt>
      <dd
        className={
          mono
            ? "break-all font-theme-data text-[12px] leading-5 text-[var(--text)]"
            : "text-sm font-medium leading-6 text-[var(--text)]"
        }
        title={title ?? value}
      >
        {value}
      </dd>
    </div>
  );
}

function ResultStateChip({ tone }: { tone: "live" | "fallback" }) {
  const isLive = tone === "live";

  return (
    <span
      className={`rounded-full text-[14px] font-medium shadow-[var(--shadow-panel)] ${
        isLive
          ? "bg-[var(--surface)] text-[var(--acid-green)]"
          : "bg-amber-50 text-amber-700"
      }`}
      style={{ padding: "10px 16px" }}
    >
      {isLive
        ? "Backend returned a live debate"
        : "Backend did not return a fresh live debate"}
    </span>
  );
}

function ExpandableText({
  text,
  collapsedLines,
  className,
  buttonLabel,
  surfaceTone,
  renderMarkdown = false,
}: {
  text: string;
  collapsedLines: number;
  className: string;
  buttonLabel: string;
  surfaceTone: "surface" | "elevated";
  renderMarkdown?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const shouldCollapse = text.trim().length > collapsedLines * 110;
  const surfaceColor =
    surfaceTone === "surface" ? "var(--surface)" : "var(--surface-elevated)";
  const shouldRenderMarkdown = renderMarkdown && containsMarkdownSyntax(text);
  const previewText = shouldRenderMarkdown ? cleanPreviewText(text) : text;
  const buttonBorderColor =
    surfaceTone === "surface"
      ? "color-mix(in srgb, var(--border) 68%, transparent)"
      : "color-mix(in srgb, var(--border) 60%, transparent)";

  return (
    <div className="space-y-3">
      <div className="relative">
        {shouldRenderMarkdown && (expanded || !shouldCollapse) ? (
          <MarkdownBody text={text} className={className} />
        ) : (
          <p
            className={className}
            style={
              !expanded && shouldCollapse
                ? {
                    display: "-webkit-box",
                    WebkitBoxOrient: "vertical",
                    WebkitLineClamp: collapsedLines,
                    overflow: "hidden",
                  }
                : undefined
            }
          >
            {previewText}
          </p>
        )}
        {!expanded && shouldCollapse ? (
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 h-16"
            style={{
              background: `linear-gradient(to top, ${surfaceColor} 0%, color-mix(in srgb, ${surfaceColor} 92%, transparent) 58%, transparent 100%)`,
            }}
          />
        ) : null}
      </div>
      {shouldCollapse ? (
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          className="inline-flex items-center gap-2 rounded-full border bg-transparent text-[13px] font-medium text-[var(--text-muted)] transition-colors hover:text-[var(--acid-green)]"
          style={{ padding: "8px 14px", borderColor: buttonBorderColor }}
        >
          <span>{expanded ? "Show less" : buttonLabel}</span>
          <span
            aria-hidden="true"
            className={`text-base leading-none ${expanded ? "rotate-180" : ""}`}
          >
            ↓
          </span>
        </button>
      ) : null}
    </div>
  );
}

function LiveResultCard({
  result,
  runStartedAt,
}: {
  result: LiveDebateResult;
  runStartedAt: string | null;
}) {
  const resultTone =
    result.mock_fallback || result.is_live === false ? "fallback" : "live";
  const resultLabel =
    resultTone === "live" ? "Live-backed result" : "Simulated fallback";
  const summary = formatVerdict(result);
  const shareHref = result.share_url ?? `/debate/${result.id}`;
  const proposalEntries = Object.entries(result.proposals).slice(0, 3);

  return (
    <section
      className="space-y-8 rounded-[20px] border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-elevated)]"
      style={{ padding: "40px" }}
    >
      <div
        className="grid gap-8 lg:grid-cols-[minmax(0,1.36fr)_336px] xl:grid-cols-[minmax(0,1.46fr)_384px]"
        style={{ gap: "44px" }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "32px" }}>
          <div
            className="border-b border-[var(--border)]"
            style={{
              paddingBottom: "32px",
              display: "flex",
              flexDirection: "column",
              gap: "18px",
            }}
          >
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div
                style={{ display: "flex", flexDirection: "column", gap: "14px" }}
              >
                <div
                  className="font-semibold uppercase text-[var(--text-muted)]"
                  style={EYEBROW_TEXT_STYLE}
                >
                  {resultTone === "live" ? "Fresh response" : "Fallback response"}
                </div>
                <StatusBadge label={resultLabel} tone={resultTone} />
              </div>
              <ResultStateChip tone={resultTone} />
            </div>
            <div className="space-y-2">
              <p className="max-w-3xl text-[21px] font-semibold leading-9 text-[var(--text)] text-balance">
                {result.topic}
              </p>
              <p className="max-w-2xl text-sm leading-7 text-[var(--text-muted)] text-pretty">
                {resultTone === "live"
                  ? "Fresh result from the public playground backend."
                  : `The backend returned a non-live fallback${result.mock_fallback_reason ? `: ${result.mock_fallback_reason}` : "."}`}
              </p>
            </div>
          </div>
          <div
            className="rounded-[18px] border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[var(--shadow-panel)]"
            style={{
              padding: "36px",
              display: "flex",
              flexDirection: "column",
              gap: "36px",
            }}
          >
            <DecisionSnapshot summary={summary} tone="live" />
            <div
              className="border-t border-[var(--border)]"
              style={{ paddingTop: "48px" }}
            >
              <h3
                className="font-semibold uppercase text-[var(--acid-green)]"
                style={EYEBROW_TEXT_STYLE}
              >
                Full verdict
              </h3>
              <div style={{ marginTop: "28px" }}>
                <ExpandableText
                  text={summary}
                  collapsedLines={4}
                  buttonLabel="Read full verdict"
                  surfaceTone="elevated"
                  renderMarkdown
                  className="max-w-2xl text-[17px] leading-8 text-[var(--text)] text-pretty"
                />
              </div>
            </div>
          </div>

          {proposalEntries.length > 0 && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "24px",
                paddingBottom: "16px",
              }}
            >
              <h3
                className="font-semibold uppercase text-[var(--acid-green)]"
                style={EYEBROW_TEXT_STYLE}
              >
                Agent positions
              </h3>
              <div className="grid grid-cols-1 gap-5">
                {proposalEntries.map(([agent, proposal]) => {
                  const accent = accentForAgent(agent);
                  return (
                    <div
                      key={agent}
                      className="rounded-[18px] border bg-[var(--surface)] shadow-[var(--shadow-panel)]"
                      style={{
                        borderColor: `${accent}28`,
                        boxShadow: `inset 4px 0 0 ${accent}`,
                        padding: "32px",
                        paddingLeft: "40px",
                        display: "flex",
                        flexDirection: "column",
                        gap: "16px",
                      }}
                    >
                      <div className="flex flex-wrap items-baseline gap-3">
                        <div
                          className="text-lg font-bold uppercase tracking-[0.08em]"
                          style={{ color: accent }}
                        >
                          {formatAgentName(agent)}
                        </div>
                      </div>
                      <ExpandableText
                        text={proposal}
                        collapsedLines={4}
                        buttonLabel="Read full position"
                        surfaceTone="surface"
                        renderMarkdown
                        className="max-w-2xl text-[15px] leading-7 text-[var(--text)] text-pretty"
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <aside className="space-y-5 lg:sticky lg:top-6 lg:self-start">
          <div
            className="rounded-[18px] border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[var(--shadow-panel)]"
            style={{
              padding: "28px",
              display: "flex",
              flexDirection: "column",
              gap: "16px",
            }}
          >
            <h3
              className="font-semibold uppercase text-[var(--acid-green)]"
              style={EYEBROW_TEXT_STYLE}
            >
              Run details
            </h3>
            <dl
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "12px",
              }}
            >
              <DetailRow
                label="Runtime"
                value={`${result.duration_seconds.toFixed(1)}s`}
              />
              <DetailRow
                label="Started"
                value={runStartedAt ?? "Just now"}
              />
              <DetailRow
                label="Status"
                value={`${result.status} after ${result.rounds_used} round${result.rounds_used === 1 ? "" : "s"}`}
              />
            </dl>
            <div
              className="border-t border-[var(--border)]"
              style={{
                paddingTop: "14px",
                display: "flex",
                flexDirection: "column",
                gap: "8px",
              }}
            >
              <div
                className="font-semibold uppercase text-[var(--text-muted)]"
                style={LABEL_TEXT_STYLE}
              >
                Result record
              </div>
              <dl
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "8px",
                }}
              >
                <DetailRow
                  label="Result ID"
                  value={compactHash(result.id, 12, 6)}
                  title={result.id}
                  mono
                  compact
                />
                {result.receipt_hash ? (
                  <DetailRow
                    label="Receipt"
                    value={compactHash(result.receipt_hash)}
                    title={result.receipt_hash}
                    mono
                    compact
                  />
                ) : null}
              </dl>
            </div>
          </div>

          <div
            className="rounded-[18px] border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[var(--shadow-panel)]"
            style={{
              padding: "28px",
              display: "flex",
              flexDirection: "column",
              gap: "16px",
            }}
          >
            <h3
              className="font-semibold uppercase text-[var(--acid-green)]"
              style={EYEBROW_TEXT_STYLE}
            >
              Returned agents
            </h3>
            <AgentRoster agents={result.participants} />
          </div>

          <div
            className="rounded-[18px] border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[var(--shadow-panel)]"
            style={{
              padding: "28px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
            }}
          >
            <ConsensusBar confidence={result.confidence} />
          </div>

          <div
            className="rounded-[18px] border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[var(--shadow-panel)]"
            style={{
              padding: "28px",
              display: "flex",
              flexDirection: "column",
              gap: "16px",
            }}
          >
            <h3
              className="font-semibold uppercase text-[var(--acid-green)]"
              style={EYEBROW_TEXT_STYLE}
            >
              Next action
            </h3>
            <p className="text-sm leading-7 text-[var(--text-muted)]">
              Open the shareable result, or take the same prompt into /try for
              a deeper run.
            </p>
            <div className="flex flex-col gap-4">
              <Link
                href={shareHref}
                className="rounded-full bg-[var(--acid-green)] px-6 py-3 text-center text-[15px] font-semibold transition-opacity hover:opacity-90"
                style={{ color: "#ffffff" }}
              >
                View Shareable Result
              </Link>
              <Link
                href={`/try?topic=${encodeURIComponent(result.topic)}`}
                className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-6 py-3 text-center text-[15px] font-medium text-[var(--text-muted)] transition-colors hover:border-[var(--acid-green)]/50 hover:text-[var(--acid-green)]"
              >
                Ask This in /try
              </Link>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

function RecordedSampleCard({ sample }: { sample: RecordedDebate }) {
  return (
    <section
      className="rounded-[20px] border border-sky-500/18 bg-[var(--surface)] shadow-[var(--shadow-elevated)]"
      style={{ padding: "40px" }}
    >
      <div
        className="grid gap-8 lg:grid-cols-[minmax(0,1.36fr)_336px] xl:grid-cols-[minmax(0,1.46fr)_384px]"
        style={{ gap: "44px" }}
      >
        <div className="space-y-6">
          <div className="space-y-2 border-b border-[var(--border)] pb-6">
            <StatusBadge label="Recorded sample" tone="sample" />
            <p className="max-w-2xl text-sm leading-7 text-[var(--text-muted)]">
              This is a captured example for zero-latency browsing. It is
              illustrative only and is never presented as a fresh run.
            </p>
          </div>

          <div
            className="rounded-[18px] border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[var(--shadow-panel)]"
            style={{
              padding: "36px",
              display: "flex",
              flexDirection: "column",
              gap: "36px",
            }}
          >
            <DecisionSnapshot summary={sample.verdict} tone="sample" />
            <div
              className="border-t border-[var(--border)]"
              style={{ paddingTop: "48px" }}
            >
              <h3
                className="font-semibold uppercase text-sky-700"
                style={EYEBROW_TEXT_STYLE}
              >
                Recorded verdict
              </h3>
              <div style={{ marginTop: "28px" }}>
                <ExpandableText
                  text={sample.verdict}
                  collapsedLines={4}
                  buttonLabel="Read full verdict"
                  surfaceTone="elevated"
                  renderMarkdown
                  className="max-w-2xl text-[17px] leading-8 text-[var(--text)] text-pretty"
                />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-5">
            {sample.events.map((event, index) => {
              const accent = accentForAgent(event.agent);
              const badgeColor =
                event.type === "proposal"
                  ? "text-blue-400"
                  : event.type === "critique"
                    ? "text-red-400"
                    : event.type === "vote"
                      ? "text-green-400"
                      : "text-[var(--acid-green)]";

              return (
                <div
                  key={`${event.agent}-${index}`}
                  className="border bg-[var(--surface)] rounded-[18px] shadow-sm"
                  style={{
                    borderColor: `${accent}28`,
                    boxShadow: `inset 4px 0 0 ${accent}`,
                    padding: "30px",
                    paddingLeft: "36px",
                    display: "flex",
                    flexDirection: "column",
                    gap: "14px",
                  }}
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <span
                        className="text-lg font-bold uppercase tracking-[0.08em]"
                        style={{ color: accent }}
                      >
                        {event.model}
                      </span>
                      <span
                        className={`rounded-full uppercase font-semibold ${badgeColor} bg-current/5`}
                        style={{ ...LABEL_TEXT_STYLE, padding: "6px 14px" }}
                      >
                        {event.type}
                      </span>
                    </div>
                    <div className="rounded-full bg-[var(--surface-elevated)] px-4 py-1.5 text-sm text-[var(--text-muted)] shadow-[var(--shadow-panel)]">
                      Round {event.round}
                      {event.confidence !== undefined
                        ? ` · ${Math.round(event.confidence * 100)}%`
                        : ""}
                    </div>
                  </div>
                  <ExpandableText
                    text={event.content}
                    collapsedLines={3}
                    buttonLabel="Read full entry"
                    surfaceTone="surface"
                    renderMarkdown
                    className="max-w-2xl text-[15px] leading-7 text-[var(--text)] text-pretty"
                  />
                  {event.vote && (
                    <div className="text-sm font-semibold text-[var(--acid-green)]">
                      Vote: {event.vote}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <aside className="space-y-5 lg:sticky lg:top-6 lg:self-start">
          <div
            className="rounded-[18px] border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[var(--shadow-panel)]"
            style={{
              padding: "28px",
              display: "flex",
              flexDirection: "column",
              gap: "16px",
            }}
          >
            <h3
              className="font-semibold uppercase text-sky-700"
              style={EYEBROW_TEXT_STYLE}
            >
              Sample details
            </h3>
            <dl
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "12px",
              }}
            >
              <DetailRow
                label="Rounds"
                value={`${sample.rounds} recorded round${sample.rounds === 1 ? "" : "s"}`}
              />
            </dl>
            <div
              className="border-t border-[var(--border)]"
              style={{
                paddingTop: "14px",
                display: "flex",
                flexDirection: "column",
                gap: "8px",
              }}
            >
              <div
                className="font-semibold uppercase text-[var(--text-muted)]"
                style={LABEL_TEXT_STYLE}
              >
                Sample record
              </div>
              <dl
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "8px",
                }}
              >
                <DetailRow
                  label="Debate ID"
                  value={compactHash(sample.id, 12, 6)}
                  title={sample.id}
                  mono
                  compact
                />
                <DetailRow
                  label="Receipt"
                  value={compactHash(sample.receiptHash)}
                  title={sample.receiptHash}
                  mono
                  compact
                />
              </dl>
            </div>
          </div>

          <div
            className="rounded-[18px] border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[var(--shadow-panel)]"
            style={{
              padding: "28px",
              display: "flex",
              flexDirection: "column",
              gap: "16px",
            }}
          >
            <h3
              className="font-semibold uppercase text-sky-700"
              style={EYEBROW_TEXT_STYLE}
            >
              Sample agents
            </h3>
            <AgentRoster agents={sample.agents} />
          </div>

          <div
            className="rounded-[18px] border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[var(--shadow-panel)]"
            style={{
              padding: "28px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
            }}
          >
            <ConsensusBar confidence={sample.confidence} />
          </div>
        </aside>
      </div>
    </section>
  );
}

export default function PublicDemoPage() {
  const [result, setResult] = useState<LiveDebateResult | null>(null);
  const [sampleFallbackMessage, setSampleFallbackMessage] = useState<
    string | null
  >(null);
  const [isLoading, setIsLoading] = useState(true);
  const [progressStep, setProgressStep] = useState(0);
  const [showRecordedSample, setShowRecordedSample] = useState(false);
  const [runStartedAt, setRunStartedAt] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const autoStartedRef = useRef(false);

  const runLiveDemo = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsLoading(true);
    setSampleFallbackMessage(null);
    setResult(null);
    setProgressStep(0);

    const startedAt = new Date().toLocaleTimeString();
    setRunStartedAt(startedAt);

    const timers = LIVE_PROGRESS_STEPS.map((_, index) =>
      window.setTimeout(() => setProgressStep(index), index * 1800),
    );
    const clearTimers = () =>
      timers.forEach((timer) => window.clearTimeout(timer));

    try {
      const { config } = getRuntimeBackendConfig();
      const response = await fetch(`${config.api}/api/v1/playground/debate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: DEMO_TOPIC,
          question: DEMO_TOPIC,
          rounds: 2,
          agents: 3,
          source: "demo",
        }),
        signal: controller.signal,
      });

      if (response.status === 429) {
        const data = await response.json().catch(() => null);
        const retryAfter =
          typeof data?.retry_after === "number" ? data.retry_after : 60;
        setSampleFallbackMessage(
          `The live proof surface is rate-limited right now, so this page is showing the labeled recorded sample instead. Retry in about ${retryAfter} seconds for a fresh run.`,
        );
        return;
      }

      if (!response.ok) {
        const data = await response.json().catch(() => null);
        const message =
          typeof data?.error === "string"
            ? data.error
            : `The live proof surface returned HTTP ${response.status}.`;
        setSampleFallbackMessage(
          `${message} Showing the labeled recorded sample instead of a live result.`,
        );
        return;
      }

      const parsed = normalizeLiveDebateResult(await response.json());
      if (!parsed) {
        setSampleFallbackMessage(
          "The live proof surface returned an unexpected payload, so this page is showing the labeled recorded sample instead.",
        );
        return;
      }

      setResult(parsed);
    } catch (fetchError) {
      if (fetchError instanceof Error && fetchError.name === "AbortError") {
        return;
      }
      setSampleFallbackMessage(
        "Could not reach the playground backend for a fresh run, so this page is showing the labeled recorded sample instead.",
      );
    } finally {
      clearTimers();
      setProgressStep(LIVE_PROGRESS_STEPS.length - 1);
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (autoStartedRef.current) {
      return;
    }
    autoStartedRef.current = true;
    void runLiveDemo();

    return () => {
      abortRef.current?.abort();
    };
  }, [runLiveDemo]);

  const recordedSamplePinned =
    sampleFallbackMessage !== null ||
    result?.mock_fallback === true ||
    result?.is_live === false;
  const recordedSampleVisible = showRecordedSample || recordedSamplePinned;

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(21,128,61,0.08),_transparent_32%),var(--bg)] text-[var(--text)]">
      <nav className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--surface)]/92 backdrop-blur">
        <div
          className="mx-auto flex items-center justify-between"
          style={{
            maxWidth: PAGE_SHELL_MAX_WIDTH,
            padding: "14px 40px",
            gap: "20px",
          }}
        >
          <Link
            href="/landing"
            className="text-sm font-semibold tracking-[0.14em] text-[var(--acid-green)] transition-opacity hover:opacity-80"
          >
            ARAGORA
          </Link>
          <div className="flex items-center gap-3.5">
            <ThemeSelector />
            <Link
              href="/try"
              className="rounded-full border border-[var(--border)] text-[15px] font-medium text-[var(--text-muted)] transition-colors hover:border-[var(--acid-green)]/50 hover:text-[var(--acid-green)]"
              style={{ padding: "10px 16px" }}
            >
              /try beta
            </Link>
            <Link
              href="/signup"
              className="rounded-full bg-[var(--acid-green)] text-[15px] font-semibold transition-opacity hover:opacity-90"
              style={{ color: "#ffffff", padding: "10px 18px" }}
            >
              Get started free
            </Link>
          </div>
        </div>
      </nav>

      <div
        className="mx-auto flex flex-col"
        style={{
          maxWidth: PAGE_SHELL_MAX_WIDTH,
          padding: "20px 40px 36px",
          gap: "26px",
        }}
      >
        <header className="mx-auto w-full max-w-[720px] space-y-1 text-center">
          <h1 className="text-3xl font-bold tracking-tight text-[var(--acid-green)] sm:text-4xl text-balance">
            Live Demo
          </h1>
          <p className="mx-auto max-w-2xl text-base leading-7 text-[var(--text-muted)] text-pretty">
            Watch AI agents debate a real question. Want to ask your own?{" "}
            <Link
              href="/try/"
              className="font-semibold text-[var(--acid-green)] hover:underline"
            >
              Try it free
            </Link>
            .
          </p>
        </header>

        <section
          className="rounded-[22px] border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-elevated)]"
          style={{ padding: "40px" }}
        >
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
            <div className="space-y-2">
              <div
                className="font-semibold uppercase text-[var(--acid-green)]"
                style={EYEBROW_TEXT_STYLE}
              >
                Canonical question
              </div>
              <p className="max-w-[780px] text-[20px] font-semibold leading-8 text-[var(--text)] text-balance">
                {DEMO_TOPIC}
              </p>
            </div>
            <div
              className="flex flex-wrap gap-3 lg:justify-end"
              style={{ maxWidth: "470px" }}
            >
              <button
                onClick={() => void runLiveDemo()}
                disabled={isLoading}
                className="rounded-full bg-[var(--acid-green)] text-[15px] font-semibold transition-opacity hover:opacity-90 disabled:opacity-50"
                style={{ color: "#ffffff", padding: "12px 22px" }}
              >
                {isLoading ? "Running..." : "Run Live"}
              </button>
              <Link
                href={`/try?topic=${encodeURIComponent(DEMO_TOPIC)}`}
                className="rounded-full border border-[var(--border)] text-[15px] font-medium text-[var(--text-muted)] transition-colors hover:border-[var(--acid-green)]/50 hover:text-[var(--acid-green)]"
                style={{ padding: "12px 20px" }}
              >
                Ask Your Own Question
              </Link>
              <button
                onClick={() => setShowRecordedSample((current) => !current)}
                disabled={recordedSamplePinned}
                className="rounded-full border bg-transparent text-[13px] font-medium tracking-[0.01em] text-[var(--text-muted)] transition-colors hover:text-sky-700"
                style={{
                  padding: "10px 16px",
                  borderColor: "color-mix(in srgb, var(--border) 68%, transparent)",
                }}
              >
                {recordedSamplePinned
                  ? "Sample Shown"
                  : showRecordedSample
                    ? "Hide Sample"
                    : "Show Recorded Sample"}
              </button>
            </div>
          </div>
        </section>

        {isLoading && (
          <section
            className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-elevated)]"
            style={{
              padding: "36px",
              display: "flex",
              flexDirection: "column",
              gap: "20px",
            }}
          >
            <StatusBadge label="Running live proof" tone="live" />
            <div
              className="rounded-[18px] border border-[var(--border)] bg-[var(--surface-elevated)]"
              style={{
                padding: "24px",
                display: "flex",
                flexDirection: "column",
                gap: "14px",
              }}
            >
              {LIVE_PROGRESS_STEPS.map((step, index) => (
                <div
                  key={step}
                  className="transition-opacity"
                  style={{
                    opacity: index <= progressStep ? 1 : 0.35,
                    padding: "4px 0",
                    display: "grid",
                    gridTemplateColumns: "12px minmax(0,1fr)",
                    columnGap: "14px",
                    alignItems: "start",
                  }}
                >
                  <span
                    className="h-3 w-3 shrink-0 rounded-full bg-[var(--acid-green)]"
                    style={{ marginTop: "10px" }}
                    aria-hidden="true"
                  />
                  <span
                    className={
                      index <= progressStep
                        ? "text-[var(--text)]"
                        : "text-[var(--text-muted)]"
                    }
                    style={{
                      fontSize: "15px",
                      lineHeight: "1.9",
                    }}
                  >
                    {step}
                  </span>
                </div>
              ))}
            </div>
            <p className="max-w-3xl text-sm leading-7 text-[var(--text-muted)]">
              This surface only claims a live proof when the backend explicitly
              returns a live result.
            </p>
          </section>
        )}

        {sampleFallbackMessage && (
          <section
            className="rounded-[20px] border border-sky-500/20 bg-sky-500/5 shadow-[var(--shadow-elevated)]"
            style={{
              padding: "36px",
              display: "flex",
              flexDirection: "column",
              gap: "20px",
            }}
          >
            <StatusBadge label="Showing recorded sample" tone="sample" />
            <p className="max-w-3xl text-sm leading-7 text-sky-900">
              {sampleFallbackMessage}
            </p>
            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => void runLiveDemo()}
                disabled={isLoading}
                className="rounded-full bg-sky-700 text-[15px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                style={{ padding: "12px 20px" }}
              >
                Retry Live Run
              </button>
              <Link
                href="/try"
                className="rounded-full border border-sky-500/30 text-[15px] font-medium text-sky-800 transition-colors hover:bg-sky-500/8"
                style={{ padding: "12px 20px" }}
              >
                Open /try Instead
              </Link>
            </div>
          </section>
        )}

        {result && !isLoading && (
          <LiveResultCard result={result} runStartedAt={runStartedAt} />
        )}

        {recordedSampleVisible && <RecordedSampleCard sample={RECORDED_SAMPLE} />}
      </div>
    </main>
  );
}
