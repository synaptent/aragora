'use client';

import { useState, useCallback, useEffect } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { DebateViewer } from '@/components/debate-viewer';
import { CruxPanel } from '@/components/CruxPanel';
import { AnalyticsPanel } from '@/components/AnalyticsPanel';
import { VoiceInput } from '@/components/VoiceInput';
import { RedTeamAnalysisPanel } from '@/components/RedTeamAnalysisPanel';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { ImpasseDetectionPanel } from '@/components/ImpasseDetectionPanel';
import { CalibrationPanel } from '@/components/CalibrationPanel';
import { ConsensusKnowledgeBase } from '@/components/ConsensusKnowledgeBase';
import { TrendingTopicsPanel } from '@/components/TrendingTopicsPanel';
import { MemoryInspector } from '@/components/MemoryInspector';
import { MetricsPanel } from '@/components/MetricsPanel';
import { BroadcastPanel } from '@/components/broadcast/BroadcastPanel';
import { EvidencePanel } from '@/components/EvidencePanel';
import { ForkVisualizer } from '@/components/fork-visualizer';
import { ExplainabilityPanel } from '@/components/ExplainabilityPanel';
import { BatchExplainabilityPanel } from '@/components/BatchExplainabilityPanel';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { useBackend } from '@/components/BackendSelector';
import { useDebateWebSocketStore } from '@/hooks/useDebateWebSocketStore';
import { DEFAULT_AGENTS } from '@/config';
import { fetchDebateClient, type SavedDebate } from './fetchDebate';

// ---------------------------------------------------------------------------
// Agent color palette — rotates through neon accents per agent
// ---------------------------------------------------------------------------
const AGENT_COLORS = [
  { border: 'var(--acid-green)', bg: 'rgba(57,255,20,0.06)', text: 'var(--acid-green)' },
  { border: 'var(--acid-cyan)', bg: 'rgba(0,255,255,0.06)', text: 'var(--acid-cyan)' },
  { border: 'var(--purple)', bg: 'rgba(191,0,255,0.06)', text: 'var(--purple)' },
  { border: 'var(--gold)', bg: 'rgba(255,215,0,0.06)', text: 'var(--gold)' },
  { border: 'var(--crimson)', bg: 'rgba(255,0,64,0.06)', text: 'var(--crimson)' },
];

function agentColor(index: number) {
  return AGENT_COLORS[index % AGENT_COLORS.length];
}

// ---------------------------------------------------------------------------
// Read-only saved-debate renderer
// ---------------------------------------------------------------------------

function SavedDebateView({ debate }: { debate: SavedDebate }) {
  const [copied, setCopied] = useState(false);
  const confidencePercent = Math.round(debate.confidence * 100);

  const isInProgress = debate.status === 'in_progress' || debate.status === 'running';
  const isFailed = debate.status === 'failed' || debate.status === 'error';
  const previewOnly =
    debate.result_mode === 'preview' ||
    (debate.verdict === 'needs_review' &&
      debate.critiques.length === 0 &&
      debate.votes.length === 0);

  const shareUrl =
    typeof window !== 'undefined'
      ? `${window.location.origin}/debate/${debate.id}`
      : `/debate/${debate.id}`;

  const handleCopyLink = async () => {
    if (typeof navigator === 'undefined') return;
    if (navigator.share) {
      try {
        await navigator.share({
          title: 'Aragora Debate',
          text: `I stress-tested "${debate.topic}" with AI agents on Aragora.`,
          url: shareUrl,
        });
        return;
      } catch {
        // fall through to clipboard
      }
    }
    if (navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(shareUrl);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {
        // silently ignore
      }
    }
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />
      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/landing/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <ThemeToggle />
          </div>
        </header>

        <div className="container mx-auto px-4 py-8 max-w-5xl">
          {/* Status Banner for non-completed debates */}
          {isInProgress && (
            <div className="mb-6 p-4 border border-[var(--acid-cyan)]/40 bg-[var(--acid-cyan)]/5 font-theme-data text-sm text-[var(--acid-cyan)] text-center">
              {'>'} DEBATE IN PROGRESS -- RESULTS MAY UPDATE
            </div>
          )}
          {isFailed && (
            <div className="mb-6 p-4 border border-[var(--crimson)]/40 bg-[var(--crimson)]/5 font-theme-data text-sm text-[var(--crimson)] text-center">
              {'>'} DEBATE FAILED -- PARTIAL RESULTS SHOWN BELOW
            </div>
          )}
          {previewOnly && (
            <div className="mb-6 p-4 border border-[var(--gold)]/40 bg-[var(--gold)]/5 font-theme-data text-sm text-[var(--gold)]">
              <div className="font-bold mb-1">{'>'} LANDING PREVIEW</div>
              <p className="text-xs leading-relaxed text-[var(--text-muted)]">
                {debate.result_warning ||
                  'This page shows a fast landing-page preview of parallel model outputs, not a full consensus proof.'}
              </p>
            </div>
          )}

          {/* Topic */}
          <h1 className="text-2xl md:text-3xl font-theme-data font-bold text-[var(--acid-green)] mb-2 leading-tight">
            {debate.topic}
          </h1>

          {/* Meta row */}
          <div className="flex flex-wrap items-center gap-4 mb-8 text-xs font-theme-data text-[var(--text-muted)]">
            <span>{debate.participants.length} AGENTS</span>
            {typeof debate.rounds_used === 'number' && debate.rounds_used > 0 && (
              <span>{debate.rounds_used} ROUNDS</span>
            )}
            {debate.duration_seconds > 0 && <span>{debate.duration_seconds.toFixed(1)}s</span>}
            {previewOnly && <span className="text-[var(--gold)]">PREVIEW ONLY</span>}
            {!previewOnly && debate.consensus_reached && (
              <span className="text-[var(--acid-green)]">CONSENSUS</span>
            )}
            {!previewOnly && !debate.consensus_reached && debate.status === 'completed' && (
              <span className="text-[var(--gold)]">NO CONSENSUS</span>
            )}
          </div>

          {/* ---- Verdict Card ---- */}
          {debate.verdict && (
            <div className="mb-8 border border-[var(--acid-green)]/30 bg-[var(--surface)]">
              <div className="p-4 border-b border-[var(--acid-green)]/20">
                <div className="flex items-center justify-between mb-3">
                  <span className="px-3 py-1 text-sm font-theme-data font-bold bg-[var(--acid-green)]/20 text-[var(--acid-green)] border border-[var(--acid-green)]/30 uppercase">
                    VERDICT
                  </span>
                  {previewOnly ? (
                    <span className="text-xs font-theme-data text-[var(--gold)]">PREVIEW ONLY</span>
                  ) : (
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-theme-data text-[var(--text-muted)]">
                        CONFIDENCE
                      </span>
                      <div className="w-24 h-2 bg-[var(--bg)] border border-[var(--acid-green)]/20 overflow-hidden">
                        <div
                          className="h-full bg-[var(--acid-green)] transition-all duration-500"
                          style={{ width: `${confidencePercent}%` }}
                        />
                      </div>
                      <span className="text-xs font-theme-data text-[var(--acid-green)]">
                        {confidencePercent}%
                      </span>
                    </div>
                  )}
                </div>
                <p className="text-sm font-theme-data text-[var(--text)] leading-relaxed">
                  {debate.verdict}
                </p>
              </div>

              {/* Final answer / synthesis */}
              {debate.final_answer && (
                <div className="p-4 border-b border-[var(--acid-green)]/20">
                  <span className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider block mb-2">
                    Synthesis
                  </span>
                  <p className="text-sm font-theme-data text-[var(--text)] leading-relaxed whitespace-pre-wrap">
                    {debate.final_answer}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* ---- Agent Position Cards ---- */}
          {debate.participants.length > 0 && debate.proposals && (
            <div className="mb-8">
              <h2 className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider mb-4">
                Agent Positions
              </h2>
              <div className="space-y-3">
                {debate.participants.map((agent, i) => {
                  const color = agentColor(i);
                  const proposal = debate.proposals[agent] ?? '';
                  return (
                    <div
                      key={agent}
                      className="p-4 bg-[var(--bg)]/50"
                      style={{ borderLeft: `3px solid ${color.border}`, backgroundColor: color.bg }}
                    >
                      <span
                        className="text-xs font-theme-data font-bold uppercase tracking-wider"
                        style={{ color: color.text }}
                      >
                        {agent}
                      </span>
                      {proposal && (
                        <p className="mt-2 text-sm font-theme-data text-[var(--text)] leading-relaxed whitespace-pre-wrap">
                          {proposal}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ---- Critiques ---- */}
          {debate.critiques.length > 0 && (
            <div className="mb-8 border border-[var(--crimson)]/20 bg-[var(--surface)]">
              <div className="p-4">
                <h2 className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider mb-4">
                  Critiques
                </h2>
                <div className="space-y-3">
                  {debate.critiques.map((critique, index) => (
                    <div
                      key={`${critique.agent}-${critique.target}-${index}`}
                      className="p-4 bg-[var(--bg)]/50 border border-[var(--border)]"
                    >
                      <div className="flex flex-wrap items-center gap-2 mb-2 text-xs font-theme-data uppercase">
                        <span className="text-[var(--crimson)]">{critique.agent}</span>
                        {critique.target && (
                          <span className="text-[var(--text-muted)]">
                            critiques {critique.target}
                          </span>
                        )}
                      </div>
                      <p className="text-sm font-theme-data text-[var(--text)] leading-relaxed whitespace-pre-wrap">
                        {critique.text}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ---- Vote Breakdown ---- */}
          {debate.votes && debate.votes.length > 0 && (
            <div className="mb-8 border border-[var(--acid-green)]/20 bg-[var(--surface)]">
              <div className="p-4">
                <h2 className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider mb-4">
                  Vote Breakdown
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {debate.votes.map((vote, i) => {
                    const color = agentColor(
                      debate.participants.indexOf(vote.agent) >= 0
                        ? debate.participants.indexOf(vote.agent)
                        : i,
                    );
                    const voteConf = Math.round(vote.confidence * 100);
                    return (
                      <div
                        key={`${vote.agent}-${i}`}
                        className="p-3 bg-[var(--bg)]/50 border border-[var(--border)]"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span
                            className="text-xs font-theme-data font-bold uppercase"
                            style={{ color: color.text }}
                          >
                            {vote.agent}
                          </span>
                          <span className="text-xs font-theme-data text-[var(--text-muted)]">
                            {voteConf}%
                          </span>
                        </div>
                        <p className="text-xs font-theme-data text-[var(--text)]">{vote.choice}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* ---- Transcript ---- */}
          {debate.messages && debate.messages.length > 0 && (
            <div className="mb-8 border border-[var(--acid-cyan)]/20 bg-[var(--surface)]">
              <div className="p-4">
                <h2 className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider mb-4">
                  Full Transcript
                </h2>
                <div className="space-y-3">
                  {debate.messages.map((message, index) => {
                    const speaker = message.agent || message.role || `message-${index + 1}`;
                    return (
                      <div
                        key={`${speaker}-${index}`}
                        className="p-4 bg-[var(--bg)]/50 border border-[var(--border)]"
                      >
                        <div className="flex flex-wrap items-center gap-2 mb-2 text-xs font-theme-data uppercase">
                          <span className="text-[var(--acid-cyan)]">{speaker}</span>
                          {typeof message.round === 'number' && (
                            <span className="text-[var(--text-muted)]">round {message.round}</span>
                          )}
                        </div>
                        <p className="text-sm font-theme-data text-[var(--text)] leading-relaxed whitespace-pre-wrap">
                          {message.content}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* ---- Receipt Hash ---- */}
          {debate.receipt_hash && (
            <div className="mb-8 flex items-center gap-3 p-4 bg-[var(--surface)] border border-[var(--acid-green)]/20">
              <span className="text-xs font-theme-data text-[var(--acid-green)]">&#10003;</span>
              <div className="min-w-0">
                <span className="text-xs font-theme-data text-[var(--text-muted)]">
                  SHA-256 DECISION RECEIPT
                </span>
                <p
                  className="text-xs font-theme-data text-[var(--text-muted)]/60 truncate"
                  title={debate.receipt_hash}
                >
                  {debate.receipt_hash}
                </p>
              </div>
            </div>
          )}

          {/* ---- Share & CTA ---- */}
          <div className="flex flex-col gap-3 mb-8">
            <Link
              href={`/try${debate.topic ? `?topic=${encodeURIComponent(debate.topic.slice(0, 200))}` : ''}`}
              className="w-full py-4 text-center font-theme-data font-bold text-sm bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors"
            >
              START YOUR OWN DEBATE
            </Link>
            <div className="flex flex-col sm:flex-row gap-3">
              <button
                onClick={handleCopyLink}
                className="flex-1 py-3 font-theme-data font-bold text-sm border border-[var(--acid-green)] text-[var(--acid-green)]
                           hover:bg-[var(--acid-green)]/10 transition-colors"
              >
                {copied ? 'LINK COPIED!' : 'SHARE THIS DEBATE'}
              </button>
              <Link
                href="/landing/"
                className="flex-1 py-3 text-center font-theme-data font-bold text-sm border border-[var(--border)] text-[var(--text-muted)]
                           hover:border-[var(--acid-green)]/30 hover:text-[var(--text)] transition-colors"
              >
                BACK TO ARAGORA
              </Link>
            </div>
          </div>

          {/* Footer */}
          <div className="text-center py-8 border-t border-[var(--border)]">
            <Link
              href="/landing/"
              className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
            >
              ARAGORA // DECISION INTEGRITY PLATFORM
            </Link>
          </div>
        </div>
      </main>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main wrapper — shows saved debate view OR live/interactive debate view
// ---------------------------------------------------------------------------

export function DebateViewerWrapper({ savedDebate }: { savedDebate?: SavedDebate | null }) {
  const router = useRouter();
  const pathname = usePathname();
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [showDeepAnalysis, setShowDeepAnalysis] = useState(false);
  const [resolvedSavedDebate, setResolvedSavedDebate] = useState<SavedDebate | null>(
    savedDebate ?? null,
  );
  const [isResolvingSavedDebate, setIsResolvingSavedDebate] = useState(false);
  const { config } = useBackend();

  // Extract debate ID from pathname: /debate/abc123 -> abc123
  const pathSegments = (pathname ?? '').split('/').filter(Boolean);
  const debateId = pathSegments[1] || null; // ['debate', 'abc123'] -> 'abc123'

  // Handle starting a debate from a trending topic
  const handleStartDebateFromTrend = useCallback(
    async (topic: string, source: string) => {
      try {
        const response = await fetch(`${config.api}/api/debate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question: topic,
            agents: DEFAULT_AGENTS,
            rounds: 3,
            metadata: { source, from_trending: true },
          }),
        });

        const data = await response.json();
        if (data.success && data.debate_id) {
          router.push(`/debate/${data.debate_id}`);
        }
      } catch {
        // Silently handle errors - could add toast notification
      }
    },
    [config.api, router],
  );

  // Live debates start with 'adhoc_' - hide analysis during streaming for better UX
  const isLiveDebate = debateId?.startsWith('adhoc_') ?? false;

  useEffect(() => {
    if (savedDebate) {
      setResolvedSavedDebate(savedDebate);
      return;
    }

    if (!debateId || isLiveDebate) {
      setResolvedSavedDebate(null);
      setIsResolvingSavedDebate(false);
      return;
    }

    let cancelled = false;
    setIsResolvingSavedDebate(true);

    const resolveSavedDebate = async () => {
      const debate = await fetchDebateClient(debateId);
      if (!cancelled) {
        setResolvedSavedDebate(debate);
        setIsResolvingSavedDebate(false);
      }
    };

    void resolveSavedDebate();

    return () => {
      cancelled = true;
    };
  }, [debateId, isLiveDebate, savedDebate]);

  // Get WebSocket actions for voice input integration
  // Note: This creates a separate connection for voice suggestions
  // DebateViewer has its own connection for main debate events
  // Must be called before early returns to satisfy hooks rules
  const { sendSuggestion } = useDebateWebSocketStore({
    debateId: debateId || '',
    wsUrl: config.ws,
    enabled: isLiveDebate && !!debateId,
  });

  // ---- Saved (read-only) debate from server-side fetch ----
  if (resolvedSavedDebate) {
    return <SavedDebateView debate={resolvedSavedDebate} />;
  }

  // No ID provided - show CTA to start a debate
  if (!debateId) {
    return (
      <>
        <Scanlines opacity={0.02} />
        <CRTVignette />
        <main className="min-h-screen bg-bg text-text relative z-10">
          <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
            <div className="container mx-auto px-4 py-3 flex items-center justify-between">
              <Link href="/landing/">
                <AsciiBannerCompact connected={true} />
              </Link>
              <ThemeToggle />
            </div>
          </header>
          <div className="container mx-auto px-4 py-20 text-center max-w-lg">
            <div className="text-[var(--accent)] font-theme-data text-xl mb-4">
              {'>'} ARAGORA DEBATE VIEWER
            </div>
            <p className="text-text-muted font-theme-data text-sm mb-8">
              Watch AI agents debate decisions with adversarial rigor and deliver audit-ready
              verdicts.
            </p>
            <div className="flex flex-col gap-3">
              <Link
                href="/try"
                className="py-4 font-theme-data font-bold text-sm bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors"
              >
                START YOUR OWN DEBATE
              </Link>
              <Link
                href="/landing/"
                className="py-3 font-theme-data text-sm border border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--acid-green)]/30 hover:text-[var(--text)] transition-colors"
              >
                BACK TO ARAGORA
              </Link>
            </div>
          </div>
        </main>
      </>
    );
  }

  if (isResolvingSavedDebate && !isLiveDebate) {
    return (
      <>
        <Scanlines opacity={0.02} />
        <CRTVignette />
        <main className="min-h-screen bg-bg text-text relative z-10">
          <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
            <div className="container mx-auto px-4 py-3 flex items-center justify-between">
              <Link href="/landing/">
                <AsciiBannerCompact connected={true} />
              </Link>
              <ThemeToggle />
            </div>
          </header>
          <div className="container mx-auto px-4 py-20 text-center max-w-lg">
            <div className="text-[var(--accent)] font-theme-data animate-pulse">
              {'>'} LOADING DEBATE...
            </div>
          </div>
        </main>
      </>
    );
  }

  return (
    <div className="min-h-screen bg-bg">
      {/* Main Debate Viewer */}
      <PanelErrorBoundary panelName="Debate Viewer">
        <DebateViewer debateId={debateId} wsUrl={config.ws} />
      </PanelErrorBoundary>

      {/* Voice Input Panel - visible for live debates */}
      {isLiveDebate && (
        <div className="container mx-auto px-4 py-4">
          <PanelErrorBoundary panelName="Voice Input">
            <VoiceInput
              debateId={debateId}
              apiBase={config.api}
              sendSuggestion={sendSuggestion}
              autoSubmitSuggestion={false}
            />
          </PanelErrorBoundary>
        </div>
      )}

      {/* Analysis Panels Toggle - hidden during live debates for maximum viewport space */}
      {!isLiveDebate && (
        <div className="container mx-auto px-4 py-4">
          <button
            onClick={() => setShowAnalysis(!showAnalysis)}
            className="w-full py-3 border border-[var(--accent)]/30 bg-surface hover:bg-surface/80 transition-colors font-theme-data text-sm text-[var(--accent)]"
          >
            {showAnalysis ? '[-] HIDE ANALYSIS PANELS' : '[+] SHOW ANALYSIS PANELS'}
          </button>
        </div>
      )}

      {/* Collapsible Analysis Section - only for archived debates */}
      {!isLiveDebate && showAnalysis && (
        <div className="container mx-auto px-4 pb-8">
          {/* Explainability Panel - Full Width */}
          <div className="mb-4">
            <PanelErrorBoundary panelName="Decision Explainability">
              <ExplainabilityPanel debateId={debateId} />
            </PanelErrorBoundary>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Crux Analysis Panel */}
            <div className="lg:col-span-1">
              <PanelErrorBoundary panelName="Crux Analysis">
                <CruxPanel debateId={debateId} apiBase={config.api} />
              </PanelErrorBoundary>
            </div>

            {/* Analytics Panel (with Graph Stats) */}
            <div className="lg:col-span-1">
              <PanelErrorBoundary panelName="Analytics">
                <AnalyticsPanel apiBase={config.api} loopId={debateId} />
              </PanelErrorBoundary>
            </div>

            {/* Red Team Analysis Panel */}
            <div className="lg:col-span-1">
              <PanelErrorBoundary panelName="Red Team Analysis">
                <RedTeamAnalysisPanel debateId={debateId} apiBase={config.api} />
              </PanelErrorBoundary>
            </div>
          </div>

          {/* Evidence, Broadcast, and Fork Panels */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-4">
            <PanelErrorBoundary panelName="Evidence">
              <EvidencePanel debateId={debateId} />
            </PanelErrorBoundary>
            <PanelErrorBoundary panelName="Broadcast">
              <BroadcastPanel debateId={debateId} debateTitle={`Debate ${debateId}`} />
            </PanelErrorBoundary>
            <PanelErrorBoundary panelName="Fork Explorer">
              <ForkVisualizer debateId={debateId} />
            </PanelErrorBoundary>
          </div>

          {/* Deep Analysis Toggle */}
          <button
            onClick={() => setShowDeepAnalysis(!showDeepAnalysis)}
            className="w-full py-2 mt-4 border border-[var(--acid-cyan)]/30 bg-surface hover:bg-surface/80 transition-colors font-theme-data text-xs text-[var(--acid-cyan)]"
          >
            {showDeepAnalysis ? '[-] HIDE DEEP ANALYSIS' : '[+] SHOW DEEP ANALYSIS'}
          </button>

          {/* Deep Analysis Panels */}
          {showDeepAnalysis && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-4">
              <PanelErrorBoundary panelName="Impasse Detection">
                <ImpasseDetectionPanel debateId={debateId} apiBase={config.api} />
              </PanelErrorBoundary>
              <PanelErrorBoundary panelName="Calibration">
                <CalibrationPanel apiBase={config.api} />
              </PanelErrorBoundary>
              <PanelErrorBoundary panelName="Consensus Knowledge">
                <ConsensusKnowledgeBase apiBase={config.api} />
              </PanelErrorBoundary>
              <PanelErrorBoundary panelName="Trending Topics">
                <TrendingTopicsPanel
                  apiBase={config.api}
                  onStartDebate={handleStartDebateFromTrend}
                />
              </PanelErrorBoundary>
              <PanelErrorBoundary panelName="Memory Inspector">
                <MemoryInspector apiBase={config.api} />
              </PanelErrorBoundary>
              <PanelErrorBoundary panelName="Metrics">
                <MetricsPanel apiBase={config.api} />
              </PanelErrorBoundary>
            </div>
          )}

          {/* Batch Explainability - Full Width */}
          {showDeepAnalysis && (
            <div className="mt-4">
              <PanelErrorBoundary panelName="Batch Explainability">
                <BatchExplainabilityPanel apiBase={config.api} />
              </PanelErrorBoundary>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
