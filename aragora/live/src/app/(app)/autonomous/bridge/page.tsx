'use client';

import Link from 'next/link';
import { useEffect } from 'react';

import { BridgeRunList } from '@/components/autonomous/bridge/BridgeRunList';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useRightSidebar } from '@/context/RightSidebarContext';

export default function AgentBridgeRunsPage() {
  const { setContext, clearContext } = useRightSidebar();

  useEffect(() => {
    setContext({
      title: 'Agent Bridge',
      subtitle: 'Operator-gated broker state',
      statsContent: (
        <div className="space-y-4">
          <div className="text-xs uppercase tracking-wider text-white/40">Mode</div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-white/50">Surface</span>
              <span className="text-[var(--accent)]">Read + gated write</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/50">Transport</span>
              <span className="text-cyan-300">HTTP polling</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/50">Write gate</span>
              <span className="text-amber-200">ARAGORA_FEATURE_AGENT_BRIDGE_WRITE</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/50">Broker store</span>
              <span className="text-white/60">.aragora/agent_bridge</span>
            </div>
          </div>
        </div>
      ),
      actionsContent: (
        <div className="space-y-2">
          <a
            href="/autonomous"
            className="block w-full rounded bg-white/5 px-3 py-2 text-center text-sm transition-colors hover:bg-white/10"
          >
            Autonomous Home
          </a>
        </div>
      ),
    });

    return () => clearContext();
  }, [clearContext, setContext]);

  return (
    <div className="relative min-h-screen bg-black text-white">
      <Scanlines />
      <CRTVignette />

      <div className="relative z-10 p-6">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mb-2 text-xs uppercase tracking-[0.25em] text-white/35">
              Autonomous Bridge
            </div>
            <h1 className="text-3xl font-bold text-white">Agent Bridge Runs</h1>
            <p className="mt-2 max-w-3xl text-sm text-white/55">
              Inspect persistent bridge runs, role-keyed session state, and operator-gated one-step
              dispatch controls for local harness cross-check loops.
            </p>
          </div>

          <Link
            href="/autonomous"
            className="rounded border border-white/10 px-3 py-2 text-sm text-white/60 transition-colors hover:border-white/20 hover:text-white"
          >
            Back to Autonomous
          </Link>
        </div>

        <BridgeRunList />
      </div>
    </div>
  );
}
