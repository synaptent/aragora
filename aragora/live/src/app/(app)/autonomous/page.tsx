'use client';

import { useEffect } from 'react';
import { useRightSidebar } from '@/context/RightSidebarContext';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AutonomousDashboard } from '@/components/autonomous';
import { API_BASE_URL } from '@/config';
import { isFeatureEnabled } from '@/lib/featureFlags';

export default function AutonomousPage() {
  const { setContext, clearContext } = useRightSidebar();
  const agentBridgeEnabled = isFeatureEnabled('AGENT_BRIDGE');

  // Set up right sidebar
  useEffect(() => {
    setContext({
      title: 'Autonomous Operations',
      subtitle: 'Self-improving system management',
      statsContent: (
        <div className="space-y-4">
          <div className="text-xs text-white/40 uppercase tracking-wider">Overview</div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-white/50">Approval Flow</span>
              <span className="text-[var(--accent)]">Human-in-loop</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/50">Alerts</span>
              <span className="text-yellow-500">Monitored</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/50">Triggers</span>
              <span className="text-[var(--acid-cyan)]">Scheduled</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/50">Learning</span>
              <span className="text-purple-400">Continuous</span>
            </div>
          </div>
        </div>
      ),
      actionsContent: (
        <div className="space-y-2">
          <a
            href="/nomic-control"
            className="block w-full px-3 py-2 text-sm bg-white/5 hover:bg-white/10 rounded transition-colors text-center"
          >
            Nomic Control Panel
          </a>
          <a
            href="/analytics"
            className="block w-full px-3 py-2 text-sm bg-white/5 hover:bg-white/10 rounded transition-colors text-center"
          >
            View Analytics
          </a>
          {agentBridgeEnabled ? (
            <a
              href="/autonomous/bridge"
              className="block w-full px-3 py-2 text-sm bg-white/5 hover:bg-white/10 rounded transition-colors text-center"
            >
              Agent Bridge
            </a>
          ) : null}
        </div>
      ),
    });

    return () => clearContext();
  }, [setContext, clearContext, agentBridgeEnabled]);

  return (
    <div className="relative min-h-screen bg-black text-white">
      <Scanlines />
      <CRTVignette />

      <div className="relative z-10 p-6">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-white mb-2">Autonomous Operations</h1>
              <p className="text-white/50">
                Self-improving system with human-in-the-loop oversight. Manage approvals, alerts,
                scheduled triggers, and continuous learning.
              </p>
            </div>
            {agentBridgeEnabled ? (
              <a
                href="/autonomous/bridge"
                className="rounded border border-white/10 px-3 py-2 text-sm text-white/60 transition-colors hover:border-white/20 hover:text-white"
              >
                Open Agent Bridge
              </a>
            ) : null}
          </div>
        </div>

        {/* Main Dashboard */}
        <AutonomousDashboard apiBase={API_BASE_URL} />
      </div>
    </div>
  );
}
