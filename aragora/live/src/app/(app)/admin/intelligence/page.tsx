'use client';

import { useState, useCallback } from 'react';
import {
  useSystemIntelligence,
  useAgentPerformance,
  useInstitutionalMemory,
  useImprovementQueue,
} from '@/hooks/useSystemIntelligence';

type TabId = 'learning' | 'agents' | 'memory' | 'queue';

const TABS: { id: TabId; label: string }[] = [
  { id: 'learning', label: 'Learning Insights' },
  { id: 'agents', label: 'Agent Performance' },
  { id: 'memory', label: 'Institutional Memory' },
  { id: 'queue', label: 'Improvement Queue' },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function LearningInsightsTab() {
  const { overview, isLoading } = useSystemIntelligence();

  if (isLoading) return <LoadingPlaceholder />;
  if (!overview) return <EmptyState message="No learning data available yet." />;

  return (
    <div className="space-y-6">
      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Cycles" value={overview.totalCycles} />
        <StatCard label="Success Rate" value={`${(overview.successRate * 100).toFixed(1)}%`} />
        <StatCard label="Active Agents" value={overview.activeAgents} />
        <StatCard label="Knowledge Items" value={overview.knowledgeItems} />
      </div>

      {/* Top agents */}
      <Card title="Top Agents by ELO">
        {overview.topAgents.length === 0 ? (
          <p className="text-sm text-gray-500">No agent data available.</p>
        ) : (
          <div className="space-y-2">
            {overview.topAgents.slice(0, 5).map((agent) => (
              <div
                key={agent.id}
                className="flex items-center justify-between px-3 py-2 bg-[var(--bg-tertiary)] rounded"
              >
                <span className="font-theme-data text-sm">{agent.id}</span>
                <div className="flex gap-4 text-xs text-gray-400">
                  <span>ELO: {agent.elo}</span>
                  <span>Wins: {agent.wins}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Recent improvements */}
      <Card title="Recent Improvements">
        {overview.recentImprovements.length === 0 ? (
          <p className="text-sm text-gray-500">No recent improvements.</p>
        ) : (
          <div className="space-y-2">
            {overview.recentImprovements.map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between px-3 py-2 bg-[var(--bg-tertiary)] rounded"
              >
                <span className="text-sm truncate max-w-[70%]">{item.goal}</span>
                <StatusBadge status={item.status} />
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function EloSparkline({
  points,
  width = 100,
  height = 24,
}: {
  points: { date: string; elo: number }[];
  width?: number;
  height?: number;
}) {
  if (points.length < 2) return null;

  const elos = points.map((p) => p.elo);
  const min = Math.min(...elos);
  const max = Math.max(...elos);
  const range = max - min || 1;
  const pad = 2;

  const pathPoints = points.map((p, i) => {
    const x = pad + (i / (points.length - 1)) * (width - 2 * pad);
    const y = height - pad - ((p.elo - min) / range) * (height - 2 * pad);
    return `${x},${y}`;
  });

  const trend = elos[elos.length - 1] - elos[0];
  const color = trend >= 0 ? 'var(--acid-green, #00ff41)' : '#f87171';

  return (
    <svg width={width} height={height} className="inline-block align-middle">
      <polyline
        points={pathPoints.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function AgentPerformanceTab() {
  const { agents, isLoading } = useAgentPerformance();

  if (isLoading) return <LoadingPlaceholder />;
  if (agents.length === 0) return <EmptyState message="No agent performance data." />;

  return (
    <div className="space-y-4">
      {/* ELO trend sparklines */}
      <Card title="ELO Trends">
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
          {agents.slice(0, 6).map((agent) => (
            <div
              key={agent.id}
              className="flex items-center gap-3 px-3 py-2 bg-[var(--bg-tertiary)] rounded"
            >
              <div className="flex-1 min-w-0">
                <div className="font-theme-data text-xs truncate">{agent.name}</div>
                <div className="text-[10px] text-gray-500">{agent.elo} ELO</div>
              </div>
              <EloSparkline points={agent.eloHistory} />
            </div>
          ))}
        </div>
        {agents.length > 6 && (
          <p className="text-xs text-gray-500 mt-2">
            Showing top 6 of {agents.length} agents.{' '}
            <a href="/agents/performance" className="text-[var(--acid-green)] hover:underline">
              View all
            </a>
          </p>
        )}
      </Card>

      {/* Agent table */}
      <Card title="Agent Details">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
                <th className="pb-2 pr-4">Agent</th>
                <th className="pb-2 pr-4">ELO</th>
                <th className="pb-2 pr-4">Trend</th>
                <th className="pb-2 pr-4">Win Rate</th>
                <th className="pb-2 pr-4">Calibration</th>
                <th className="pb-2">Domains</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr key={agent.id} className="border-b border-gray-800/50">
                  <td className="py-2 pr-4 font-theme-data">{agent.name}</td>
                  <td className="py-2 pr-4">{agent.elo}</td>
                  <td className="py-2 pr-4">
                    <EloSparkline points={agent.eloHistory} width={80} height={20} />
                  </td>
                  <td className="py-2 pr-4">{(agent.winRate * 100).toFixed(1)}%</td>
                  <td className="py-2 pr-4">{(agent.calibration * 100).toFixed(0)}%</td>
                  <td className="py-2">
                    <div className="flex gap-1 flex-wrap">
                      {agent.domains.slice(0, 3).map((d) => (
                        <span
                          key={d}
                          className="px-1.5 py-0.5 text-xs bg-[var(--acid-green)]/10 text-[var(--acid-green)] rounded"
                        >
                          {d}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function InstitutionalMemoryTab() {
  const { memory, isLoading } = useInstitutionalMemory();

  if (isLoading) return <LoadingPlaceholder />;
  if (!memory) return <EmptyState message="No institutional memory data." />;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <StatCard label="Total Injections" value={memory.totalInjections} />
        <StatCard label="Retrieval Count" value={memory.retrievalCount} />
      </div>

      <Card title="Top Patterns">
        {memory.topPatterns.length === 0 ? (
          <p className="text-sm text-gray-500">No patterns detected yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
                  <th className="pb-2 pr-4">Pattern</th>
                  <th className="pb-2 pr-4">Frequency</th>
                  <th className="pb-2">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {memory.topPatterns.map((p, i) => (
                  <tr key={i} className="border-b border-gray-800/50">
                    <td className="py-2 pr-4">{p.pattern}</td>
                    <td className="py-2 pr-4">{p.frequency}</td>
                    <td className="py-2">{(p.confidence * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Confidence Changes">
        {memory.confidenceChanges.length === 0 ? (
          <p className="text-sm text-gray-500">No confidence shifts recorded.</p>
        ) : (
          <div className="space-y-2">
            {memory.confidenceChanges.map((c, i) => (
              <div
                key={i}
                className="flex items-center justify-between px-3 py-2 bg-[var(--bg-tertiary)] rounded"
              >
                <span className="text-sm">{c.topic}</span>
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-gray-500">{(c.before * 100).toFixed(0)}%</span>
                  <span className="text-gray-600">&rarr;</span>
                  <span className={c.after > c.before ? 'text-green-400' : 'text-red-400'}>
                    {(c.after * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function ImprovementQueueTab() {
  const { items, queue, isLoading, addGoal, reorderItem, removeItem } = useImprovementQueue();
  const [newGoal, setNewGoal] = useState('');
  const [newPriority, setNewPriority] = useState(50);

  const handleAdd = useCallback(async () => {
    if (!newGoal.trim()) return;
    await addGoal(newGoal.trim(), newPriority);
    setNewGoal('');
    setNewPriority(50);
  }, [newGoal, newPriority, addGoal]);

  if (isLoading) return <LoadingPlaceholder />;

  return (
    <div className="space-y-6">
      {/* Add goal form */}
      <Card title="Submit Improvement Goal">
        <div className="flex gap-3">
          <input
            type="text"
            value={newGoal}
            onChange={(e) => setNewGoal(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            placeholder="Describe an improvement goal..."
            className="flex-1 px-3 py-2 bg-[var(--bg-tertiary)] border border-gray-700 rounded text-sm focus:outline-none focus:border-[var(--acid-green)]"
          />
          <input
            type="number"
            value={newPriority}
            onChange={(e) => setNewPriority(Number(e.target.value))}
            min={1}
            max={100}
            className="w-20 px-3 py-2 bg-[var(--bg-tertiary)] border border-gray-700 rounded text-sm text-center focus:outline-none focus:border-[var(--acid-green)]"
            title="Priority (1-100)"
          />
          <button
            onClick={handleAdd}
            disabled={!newGoal.trim()}
            className="px-4 py-2 bg-[var(--acid-green)]/20 text-[var(--acid-green)] border border-[var(--acid-green)]/30 rounded text-sm hover:bg-[var(--acid-green)]/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Add
          </button>
        </div>
      </Card>

      {/* Source breakdown */}
      {queue && Object.keys(queue.sourceBreakdown).length > 0 && (
        <div className="flex gap-3 flex-wrap">
          {Object.entries(queue.sourceBreakdown).map(([source, count]) => (
            <div key={source} className="px-3 py-1.5 bg-[var(--bg-tertiary)] rounded text-xs">
              <span className="text-gray-400">{source}:</span>{' '}
              <span className="font-theme-data">{count}</span>
            </div>
          ))}
          <div className="px-3 py-1.5 bg-[var(--bg-tertiary)] rounded text-xs">
            <span className="text-gray-400">Total:</span>{' '}
            <span className="font-theme-data">{queue.totalSize}</span>
          </div>
        </div>
      )}

      {/* Queue table */}
      <Card title="Queue Items">
        {items.length === 0 ? (
          <p className="text-sm text-gray-500">Queue is empty.</p>
        ) : (
          <div className="space-y-2">
            {items.map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between px-3 py-2 bg-[var(--bg-tertiary)] rounded group"
              >
                <div className="flex-1 min-w-0 mr-4">
                  <p className="text-sm truncate">{item.goal}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Source: {item.source} &middot; Priority: {item.priority}
                  </p>
                </div>
                <div className="flex gap-2 items-center opacity-60 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={() => reorderItem(item.id, Math.min(item.priority + 10, 100))}
                    className="px-2 py-1 text-xs bg-gray-800 rounded hover:bg-gray-700"
                    title="Increase priority"
                  >
                    &uarr;
                  </button>
                  <button
                    onClick={() => reorderItem(item.id, Math.max(item.priority - 10, 1))}
                    className="px-2 py-1 text-xs bg-gray-800 rounded hover:bg-gray-700"
                    title="Decrease priority"
                  >
                    &darr;
                  </button>
                  <button
                    onClick={() => removeItem(item.id)}
                    className="px-2 py-1 text-xs bg-red-900/30 text-red-400 rounded hover:bg-red-900/50"
                    title="Remove"
                  >
                    &times;
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="px-4 py-3 bg-[var(--bg-secondary)] border border-gray-800 rounded">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className="text-xl font-theme-data mt-1">{value}</p>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-[var(--bg-secondary)] border border-gray-800 rounded p-4">
      <h3 className="text-sm font-semibold text-gray-300 mb-3">{title}</h3>
      {children}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-yellow-900/30 text-yellow-400',
    completed: 'bg-green-900/30 text-green-400',
    failed: 'bg-red-900/30 text-red-400',
  };
  return (
    <span
      className={`px-2 py-0.5 text-xs rounded ${colors[status] ?? 'bg-gray-800 text-gray-400'}`}
    >
      {status}
    </span>
  );
}

function LoadingPlaceholder() {
  return (
    <div className="flex items-center justify-center h-48 text-sm text-gray-500">Loading...</div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-48 text-sm text-gray-500">{message}</div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function IntelligencePage() {
  const [activeTab, setActiveTab] = useState<TabId>('learning');

  return (
    <div className="relative min-h-screen p-6 space-y-6">
      <div className="relative z-10">
        <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-6">
          System Intelligence
        </h1>

        {/* Tab bar */}
        <div className="flex gap-1 mb-6 border-b border-gray-800">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 text-sm transition-colors ${
                activeTab === tab.id
                  ? 'text-[var(--acid-green)] border-b-2 border-[var(--acid-green)]'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === 'learning' && <LearningInsightsTab />}
        {activeTab === 'agents' && <AgentPerformanceTab />}
        {activeTab === 'memory' && <InstitutionalMemoryTab />}
        {activeTab === 'queue' && <ImprovementQueueTab />}
      </div>
    </div>
  );
}
