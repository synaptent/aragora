'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAragoraClient } from '@/hooks/useAragoraClient';
import { LoadingSpinner } from './LoadingSpinner';
import { ApiError } from './ApiError';
import type { AgentHistory, AgentNetwork, AgentPerformance } from '@/lib/aragora-client';

interface AgentDetailPanelProps {
  agentId: string;
  onClose?: () => void;
}

type TabId = 'overview' | 'history' | 'network' | 'domains';

export function AgentDetailPanel({ agentId, onClose }: AgentDetailPanelProps) {
  const client = useAragoraClient();
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Data state
  const [performance, setPerformance] = useState<AgentPerformance | null>(null);
  const [history, setHistory] = useState<AgentHistory[]>([]);
  const [network, setNetwork] = useState<AgentNetwork | null>(null);
  const [domains, setDomains] = useState<Record<string, unknown>>({});

  const fetchData = useCallback(async () => {
    if (!client) return;
    setLoading(true);
    setError(null);

    try {
      const [perfRes, histRes, netRes, domRes] = await Promise.all([
        client.agentDetail.performance(agentId).catch((err) => {
          console.warn('[AgentDetailPanel] Failed to fetch agent performance:', err);
          return null;
        }),
        client.agentDetail.history(agentId, 20).catch((err) => {
          console.warn('[AgentDetailPanel] Failed to fetch agent history:', err);
          return { history: [] };
        }),
        client.agentDetail.network(agentId).catch((err) => {
          console.warn('[AgentDetailPanel] Failed to fetch agent network:', err);
          return null;
        }),
        client.agentDetail.domains(agentId).catch((err) => {
          console.warn('[AgentDetailPanel] Failed to fetch agent domains:', err);
          return { domains: {} };
        }),
      ]);

      if (perfRes?.performance) setPerformance(perfRes.performance);
      if (histRes?.history) setHistory(histRes.history);
      if (netRes) setNetwork(netRes);
      if (domRes?.domains) setDomains(domRes.domains);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load agent data');
    } finally {
      setLoading(false);
    }
  }, [client, agentId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const tabs: { id: TabId; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'history', label: 'History' },
    { id: 'network', label: 'Network' },
    { id: 'domains', label: 'Domains' },
  ];

  if (loading) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <LoadingSpinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <ApiError error={error} onRetry={fetchData} />
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-700 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold">
            {agentId.charAt(0).toUpperCase()}
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">{agentId}</h2>
            {performance && (
              <p className="text-sm text-slate-400">
                {performance.total_debates} debates • {(performance.win_rate * 100).toFixed(1)}% win
                rate
              </p>
            )}
          </div>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            ✕
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-700">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'text-blue-400 border-b-2 border-blue-400 bg-slate-800/50'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4">
        {activeTab === 'overview' && performance && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatCard label="Total Debates" value={performance.total_debates} />
              <StatCard label="Wins" value={performance.wins} color="text-green-400" />
              <StatCard label="Losses" value={performance.losses} color="text-red-400" />
              <StatCard label="Draws" value={performance.draws} color="text-yellow-400" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <StatCard label="Win Rate" value={`${(performance.win_rate * 100).toFixed(1)}%`} />
              <StatCard
                label="Avg ELO Gain"
                value={performance.avg_elo_gain.toFixed(1)}
                color={performance.avg_elo_gain >= 0 ? 'text-green-400' : 'text-red-400'}
              />
            </div>
          </div>
        )}

        {activeTab === 'history' && (
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {history.length === 0 ? (
              <p className="text-slate-400 text-center py-4">No debate history</p>
            ) : (
              history.map((h, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between p-3 bg-slate-800 rounded-lg"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{h.task}</p>
                    <p className="text-xs text-slate-400">{h.date}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span
                      className={`text-sm font-medium ${
                        h.outcome === 'win'
                          ? 'text-green-400'
                          : h.outcome === 'loss'
                            ? 'text-red-400'
                            : 'text-yellow-400'
                      }`}
                    >
                      {h.outcome.toUpperCase()}
                    </span>
                    <span
                      className={`text-xs ${h.elo_change >= 0 ? 'text-green-400' : 'text-red-400'}`}
                    >
                      {h.elo_change >= 0 ? '+' : ''}
                      {h.elo_change}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'network' && network && (
          <div className="grid md:grid-cols-2 gap-4">
            <div>
              <h3 className="text-sm font-medium text-slate-300 mb-2">Top Allies</h3>
              <div className="space-y-2">
                {network.allies.length === 0 ? (
                  <p className="text-slate-400 text-sm">No ally data</p>
                ) : (
                  network.allies.slice(0, 5).map((ally, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between p-2 bg-slate-800 rounded"
                    >
                      <span className="text-white">{ally.agent_id}</span>
                      <span className="text-green-400 text-sm">
                        +{ally.synergy_score.toFixed(1)}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
            <div>
              <h3 className="text-sm font-medium text-slate-300 mb-2">Top Rivals</h3>
              <div className="space-y-2">
                {network.rivals.length === 0 ? (
                  <p className="text-slate-400 text-sm">No rival data</p>
                ) : (
                  network.rivals.slice(0, 5).map((rival, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between p-2 bg-slate-800 rounded"
                    >
                      <span className="text-white">{rival.agent_id}</span>
                      <span className="text-red-400 text-sm">{rival.rivalry_score.toFixed(1)}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'domains' && (
          <div className="space-y-2">
            {Object.keys(domains).length === 0 ? (
              <p className="text-slate-400 text-center py-4">No domain data</p>
            ) : (
              Object.entries(domains).map(([domain, stats]) => {
                const s = stats as { wins?: number; losses?: number };
                const wins = s.wins || 0;
                const losses = s.losses || 0;
                const total = wins + losses;
                const winRate = total > 0 ? (wins / total) * 100 : 0;
                return (
                  <div
                    key={domain}
                    className="flex items-center justify-between p-3 bg-slate-800 rounded-lg"
                  >
                    <span className="text-white capitalize">{domain}</span>
                    <div className="flex items-center gap-4">
                      <span className="text-sm text-slate-400">
                        {wins}W / {losses}L
                      </span>
                      <span
                        className={`text-sm font-medium ${
                          winRate >= 50 ? 'text-green-400' : 'text-red-400'
                        }`}
                      >
                        {winRate.toFixed(0)}%
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  color = 'text-white',
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <div className="bg-slate-800 rounded-lg p-3">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      <p className={`text-xl font-semibold ${color}`}>{value}</p>
    </div>
  );
}

export default AgentDetailPanel;
