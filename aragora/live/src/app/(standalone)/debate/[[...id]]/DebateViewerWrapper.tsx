'use client';

import { useState, useCallback } from 'react';
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
import type { SavedDebate } from './fetchDebate';

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
        <header className="border-b border-acid-green/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/landing/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <ThemeToggle />
          </div>
        </header>

        <div className="container mx-auto px-4 py-8 max-w-4xl">
          {/* Status Banner for non-completed debates */}
          {isInProgress && (
            <div className="mb-6 p-4 border border-[var(--acid-cyan)]/40 bg-[var(--acid-cyan)]/5 font-mono text-sm text-[var(--acid-cyan)] text-center">
              {'>'} DEBATE IN PROGRESS -- RESULTS MAY UPDATE
            </div>
          )}
          {isFailed && (
            <div className="mb-6 p-4 border border-[var(--crimson)]/40 bg-[var(--crimson)]/5 font-mono text-sm text-[var(--crimson)] text-center">
              {'>'} DEBATE FAILED -- PARTIAL RESULTS SHOWN BELOW
            </div>
          )}

          {/* Topic */}
          <h1 className="text-2xl md:text-3xl font-mono font-bold text-[var(--acid-green)] mb-2 leading-tight">
            {debate.topic}
          </h1>

          {/* Meta row */}
          <div className="flex flex-wrap items-center gap-4 mb-8 text-xs font-mono text-[var(--text-muted)]">
            <span>{debate.participants.length} AGENTS</span>
            {debate.duration_seconds > 0 && (
              <span>{debate.duration_seconds.toFixed(1)}s</span>
            )}
            {debate.consensus_reached && (
              <span className="text-[var(--acid-green)]">CONSENSUS</span>
            )}
            {!debate.consensus_reached && debate.status === 'completed' && (
              <span className="text-[var(--gold)]">NO CONSENSUS</span>
            )}
          </div>

          {/* ---- Verdict Card ---- */}
          {debate.verdict && (
            <div className="mb-8 border border-[var(--acid-green)]/30 bg-[var(--surface)]">
              <div className="p-4 border-b border-[var(--acid-green)]/20">
                <div className="flex items-center justify-between mb-3">
                  <span className="px-3 py-1 text-sm font-mono font-bold bg-[var(--acid-green)]/20 text-[var(--acid-green)] border border-[var(--acid-green)]/30 uppercase">
                    VERDICT
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-[var(--text-muted)]">
                      CONFIDENCE
                    </span>
                    <div className="w-24 h-2 bg-[var(--bg)] border border-[var(--acid-green)]/20 overflow-hidden">
                      <div
                        className="h-full bg-[var(--acid-green)] transition-all duration-500"
                        style={{ width: `${confidencePercent}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono text-[var(--acid-green)]">
                      {confidencePercent}%
                    </span>
                  </div>
                </div>
                <p className="text-sm font-mono text-[var(--text)] leading-relaxed">
                  {debate.verdict}
                </p>
              </div>

              {/* Final answer / synthesis */}
              {debate.final_answer && (
                <div className="p-4 border-b border-[var(--acid-green)]/20">
                  <span className="text-xs font-mono text-[var(--text-muted)] uppercase tracking-wider block mb-2">
                    Synthesis
                  </span>
                  <p className="text-sm font-mono text-[var(--text)] leading-relaxed whitespace-pre-wrap">
                    {debate.final_answer.length > 800
                      ? debate.final_answer.slice(0, 800) + '...'
                      : debate.final_answer}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* ---- Agent Position Cards ---- */}
          {debate.participants.length > 0 && debate.proposals && (
            <div className="mb-8">
              <h2 className="text-xs font-mono text-[var(--text-muted)] uppercase tracking-wider mb-4">
                Agent Positions
              </h2>
              <div className="space-y-3">
                {debate.participants.map((agent, i) => {
                  const color = agentColor(i);
                  const raw = debate.proposals[agent] ?? '';
                  const excerpt =
                    raw.length > 500 ? raw.slice(0, 500) + '...' : raw;
                  return (
                    <div
                      key={agent}
                      className="p-4 bg-[var(--bg)]/50"
                      style={{
                        borderLeft: `3px solid ${color.border}`,
                        backgroundColor: color.bg,
                      }}
                    >
                      <span
                        className="text-xs font-mono font-bold uppercase tracking-wider"
                        style={{ color: color.text }}
                      >
                        {agent}
                      </span>
                      {excerpt && (
                        <p className="mt-2 text-sm font-mono text-[var(--text)] leading-relaxed whitespace-pre-wrap">
                          {excerpt}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ---- Vote Breakdown ---- */}
          {debate.votes && debate.votes.length > 0 && (
            <div className="mb-8 border border-[var(--acid-green)]/20 bg-[var(--surface)]">
              <div className="p-4">
                <h2 className="text-xs font-mono text-[var(--text-muted)] uppercase tracking-wider mb-4">
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
                            className="text-xs font-mono font-bold uppercase"
                            style={{ color: color.text }}
                          >
                            {vote.agent}
                          </span>
                          <span className="text-xs font-mono text-[var(--text-muted)]">
                            {voteConf}%
                          </span>
                        </div>
                        <p className="text-xs font-mono text-[var(--text)]">
                          {vote.choice}
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
              <span className="text-xs font-mono text-[var(--acid-green)]">
                &#10003;
              </span>
              <div className="min-w-0">
                <span className="text-xs font-mono text-[var(--text-muted)]">
                  SHA-256 DECISION RECEIPT
                </span>
                <p
                  className="text-xs font-mono text-[var(--text-muted)]/60 truncate"
                  title={debate.receipt_hash}
                >
                  {debate.receipt_hash}
                </p>
              </div>
            </div>
          )}

          {/* ---- Share & CTA ---- */}
          <div className="flex flex-col sm:flex-row gap-3 mb-8">
            <button
              onClick={handleCopyLink}
              className="flex-1 py-3 font-mono font-bold text-sm border border-[var(--acid-green)] text-[var(--acid-green)]
                         hover:bg-[var(--acid-green)]/10 transition-colors"
            >
              {copied ? 'LINK COPIED!' : 'SHARE THIS DEBATE'}
            </button>
            <Link
              href={`/try${debate.topic ? `?topic=${encodeURIComponent(debate.topic.slice(0, 200))}` : ''}`}
              className="flex-1 py-3 text-center font-mono font-bold text-sm bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors"
            >
              RUN YOUR OWN DEBATE →
            </Link>
          </div>

          {/* Footer */}
          <div className="text-center py-8 border-t border-[var(--border)]">
            <Link
              href="/landing/"
              className="text-xs font-mono text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
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

export function DebateViewerWrapper({
  savedDebate,
}: {
  savedDebate?: SavedDebate | null;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [showDeepAnalysis, setShowDeepAnalysis] = useState(false);
  const { config } = useBackend();

  // Extract debate ID from pathname: /debate/abc123 -> abc123
  const pathSegments = (pathname ?? '').split('/').filter(Boolean);
  const debateId = pathSegments[1] || null; // ['debate', 'abc123'] -> 'abc123'

  // Handle starting a debate from a trending topic
  const handleStartDebateFromTrend = useCallback(async (topic: string, source: string) => {
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
  }, [config.api, router]);

  // Live debates start with 'adhoc_' - hide analysis during streaming for better UX
  const isLiveDebate = debateId?.startsWith('adhoc_') ?? false;

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
  if (savedDebate) {
    return <SavedDebateView debate={savedDebate} />;
  }

  // No ID provided - show message
  if (!debateId) {
    return (
      <>
        <Scanlines opacity={0.02} />
        <CRTVignette />
        <main className="min-h-screen bg-bg text-text relative z-10">
          <header className="border-b border-acid-green/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
            <div className="container mx-auto px-4 py-3 flex items-center justify-between">
              <Link href="/landing/">
                <AsciiBannerCompact connected={true} />
              </Link>
              <ThemeToggle />
            </div>
          </header>
          <div className="container mx-auto px-4 py-20 text-center">
            <div className="text-acid-green font-mono text-xl mb-4">{'>'} NO DEBATE ID PROVIDED</div>
            <Link href="/landing/" className="text-acid-cyan hover:text-acid-green transition-colors font-mono">
              [RETURN HOME]
            </Link>
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
            className="w-full py-3 border border-acid-green/30 bg-surface hover:bg-surface/80 transition-colors font-mono text-sm text-acid-green"
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
            className="w-full py-2 mt-4 border border-acid-cyan/30 bg-surface hover:bg-surface/80 transition-colors font-mono text-xs text-acid-cyan"
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
                <TrendingTopicsPanel apiBase={config.api} onStartDebate={handleStartDebateFromTrend} />
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
