'use client';

import Link from 'next/link';
import { useEffect } from 'react';
import { useParams } from 'next/navigation';

import { BridgeRunDetail } from '@/components/autonomous/bridge/BridgeRunDetail';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useRightSidebar } from '@/context/RightSidebarContext';

export default function AgentBridgeRunDetailPage() {
  const params = useParams();
  const runId = Array.isArray(params.run_id) ? params.run_id[0] : params.run_id;
  const { setContext, clearContext } = useRightSidebar();

  useEffect(() => {
    setContext({
      title: 'Bridge Detail',
      subtitle: runId ?? 'Run detail',
      statsContent: (
        <div className="space-y-4">
          <div className="text-xs uppercase tracking-wider text-white/40">Panels</div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-white/50">Transcript</span>
              <span className="text-[var(--accent)]">Footer-aware</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/50">Events</span>
              <span className="text-cyan-300">Parse status</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/50">Metadata</span>
              <span className="text-white/60">run.json + sessions.json</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/50">Actions</span>
              <span className="text-amber-200">Write-gated</span>
            </div>
          </div>
        </div>
      ),
      actionsContent: (
        <div className="space-y-2">
          <a
            href="/autonomous/bridge"
            className="block w-full rounded bg-white/5 px-3 py-2 text-center text-sm transition-colors hover:bg-white/10"
          >
            All Bridge Runs
          </a>
        </div>
      ),
    });

    return () => clearContext();
  }, [clearContext, runId, setContext]);

  if (!runId || typeof runId !== 'string') {
    return null;
  }

  return (
    <div className="relative min-h-screen bg-black text-white">
      <Scanlines />
      <CRTVignette />

      <div className="relative z-10 p-6">
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <div className="text-sm text-white/50">
            <Link href="/autonomous/bridge" className="transition-colors hover:text-white">
              Agent Bridge
            </Link>
            <span className="mx-2 text-white/25">/</span>
            <span className="text-white/75">{runId}</span>
          </div>
        </div>

        <BridgeRunDetail runId={runId} />
      </div>
    </div>
  );
}
