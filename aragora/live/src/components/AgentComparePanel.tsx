'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { API_BASE_URL } from '../config';
import { useAuth } from '@/context/AuthContext';
import { TrustBadge, type CalibrationData } from '@/components/TrustBadge';

interface AgentProfile {
  name: string;
  rating: number;
  rank: number;
  wins: number;
  losses: number;
  win_rate: number;
  consistency_score?: number;
  calibration_score?: number;
  calibration?: CalibrationData | null;
  domains?: string[];
}

interface ComparisonResult {
  agents: AgentProfile[];
  head_to_head?: { matches: number; agent1_wins: number; agent2_wins: number; draws: number };
}

interface AgentComparePanelProps {
  initialAgents?: string[];
  availableAgents?: string[];
}

export function AgentComparePanel({
  initialAgents = [],
  availableAgents = [],
}: AgentComparePanelProps) {
  const { isAuthenticated, isLoading: authLoading, tokens } = useAuth();
  const [agent1, setAgent1] = useState(initialAgents[0] || '');
  const [agent2, setAgent2] = useState(initialAgents[1] || '');
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agents, setAgents] = useState<string[]>(availableAgents);
  const initialFetchDone = useRef(false);

  // Use centralized config
  const apiBase = API_BASE_URL;

  // Fetch available agents if not provided (only when authenticated) - fetch once only
  useEffect(() => {
    // Skip if auth is loading or user is not authenticated
    if (authLoading) return;
    if (!isAuthenticated) return;
    if (availableAgents.length > 0) return;
    if (initialFetchDone.current) return;

    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (tokens?.access_token) {
      headers['Authorization'] = `Bearer ${tokens.access_token}`;
    }

    fetch(`${apiBase}/api/rankings`, { headers })
      .then((res) => {
        // Don't retry on rate limit - gracefully handle
        if (res.status === 429) return { rankings: [] };
        return res.json();
      })
      .then((data) => {
        const agentNames = (data.rankings || []).map((r: { name: string }) => r.name);
        setAgents(agentNames);
        // Set defaults only on initial fetch
        if (agentNames.length > 0) setAgent1(agentNames[0]);
        if (agentNames.length > 1) setAgent2(agentNames[1]);
        initialFetchDone.current = true;
      })
      .catch(() => {});
  }, [apiBase, availableAgents, authLoading, isAuthenticated, tokens?.access_token]); // Remove agent1, agent2 from deps

  const fetchComparison = useCallback(async () => {
    if (!agent1 || !agent2 || agent1 === agent2) return;
    if (!isAuthenticated) return;

    try {
      setLoading(true);
      setError(null);

      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }

      const response = await fetch(
        `${apiBase}/api/agent/compare?agents=${encodeURIComponent(agent1)}&agents=${encodeURIComponent(agent2)}`,
        { headers },
      );

      if (!response.ok) {
        throw new Error(`Comparison failed: ${response.status}`);
      }

      const data = await response.json();
      setComparison(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Comparison failed');
    } finally {
      setLoading(false);
    }
  }, [apiBase, agent1, agent2, isAuthenticated, tokens?.access_token]);

  useEffect(() => {
    if (agent1 && agent2 && agent1 !== agent2) {
      fetchComparison();
    }
  }, [agent1, agent2, fetchComparison]);

  const getWinRateColor = (rate: number) => {
    if (rate >= 0.6) return 'text-green-400';
    if (rate >= 0.4) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getRatingDiff = () => {
    if (!comparison || comparison.agents.length < 2) return null;
    const rating0 = Number(comparison.agents[0]?.rating) || 0;
    const rating1 = Number(comparison.agents[1]?.rating) || 0;
    if (isNaN(rating0) || isNaN(rating1)) return null;
    return rating0 - rating1;
  };

  return (
    <div className="bg-white dark:bg-zinc-800 rounded-lg border border-zinc-200 dark:border-zinc-700 p-4">
      <h3 className="text-lg font-semibold text-white mb-4">Agent Comparison</h3>

      {/* Agent Selection */}
      <div className="flex flex-col md:flex-row gap-4 mb-6">
        <div className="flex-1">
          <label
            htmlFor="compare-agent-1"
            className="block text-sm text-zinc-500 dark:text-zinc-400 mb-1"
          >
            Agent 1
          </label>
          <select
            id="compare-agent-1"
            value={agent1}
            onChange={(e) => setAgent1(e.target.value)}
            aria-label="Select first agent for comparison"
            className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-300 dark:border-zinc-600 rounded px-3 py-2 text-white"
          >
            <option value="">Select agent...</option>
            {agents.map((agent) => (
              <option key={agent} value={agent} disabled={agent === agent2}>
                {agent}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-end pb-2">
          <span className="text-zinc-400 dark:text-zinc-500 text-xl">vs</span>
        </div>
        <div className="flex-1">
          <label
            htmlFor="compare-agent-2"
            className="block text-sm text-zinc-500 dark:text-zinc-400 mb-1"
          >
            Agent 2
          </label>
          <select
            id="compare-agent-2"
            value={agent2}
            onChange={(e) => setAgent2(e.target.value)}
            aria-label="Select second agent for comparison"
            className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-300 dark:border-zinc-600 rounded px-3 py-2 text-white"
          >
            <option value="">Select agent...</option>
            {agents.map((agent) => (
              <option key={agent} value={agent} disabled={agent === agent1}>
                {agent}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-900/50 border border-red-700 rounded text-red-200 text-sm">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex justify-center py-8">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
        </div>
      )}

      {comparison && comparison.agents.length === 2 && !loading && (
        <div className="space-y-4">
          {/* Rating Comparison */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-center">
            <div className="bg-zinc-50 dark:bg-zinc-900 rounded p-3">
              <div className="text-2xl font-bold text-blue-400">
                {(Number(comparison.agents[0]?.rating) || 0).toFixed(0)}
              </div>
              <div className="text-xs text-zinc-500 dark:text-zinc-400">ELO Rating</div>
            </div>
            <div className="flex items-center justify-center">
              {getRatingDiff() !== null && (
                <span className={getRatingDiff()! > 0 ? 'text-green-400' : 'text-red-400'}>
                  {getRatingDiff()! > 0 ? '+' : ''}
                  {getRatingDiff()!.toFixed(0)}
                </span>
              )}
            </div>
            <div className="bg-zinc-50 dark:bg-zinc-900 rounded p-3">
              <div className="text-2xl font-bold text-purple-400">
                {(Number(comparison.agents[1]?.rating) || 0).toFixed(0)}
              </div>
              <div className="text-xs text-zinc-500 dark:text-zinc-400">ELO Rating</div>
            </div>
          </div>

          {/* Stats Comparison Table */}
          <div className="bg-zinc-50 dark:bg-zinc-900 rounded overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 dark:border-zinc-700">
                  <th className="py-2 px-3 text-left text-blue-400">
                    {agent1}{' '}
                    <TrustBadge calibration={comparison.agents[0]?.calibration} size="sm" />
                  </th>
                  <th className="py-2 px-3 text-center text-zinc-500 dark:text-zinc-400">Stat</th>
                  <th className="py-2 px-3 text-right text-purple-400">
                    {agent2}{' '}
                    <TrustBadge calibration={comparison.agents[1]?.calibration} size="sm" />
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-zinc-200 dark:border-zinc-700">
                  <td className="py-2 px-3 text-white">{comparison.agents[0].wins}</td>
                  <td className="py-2 px-3 text-center text-zinc-500 dark:text-zinc-400">Wins</td>
                  <td className="py-2 px-3 text-right text-white">{comparison.agents[1].wins}</td>
                </tr>
                <tr className="border-b border-zinc-200 dark:border-zinc-700">
                  <td className="py-2 px-3 text-white">{comparison.agents[0].losses}</td>
                  <td className="py-2 px-3 text-center text-zinc-500 dark:text-zinc-400">Losses</td>
                  <td className="py-2 px-3 text-right text-white">{comparison.agents[1].losses}</td>
                </tr>
                <tr className="border-b border-zinc-200 dark:border-zinc-700">
                  <td
                    className={`py-2 px-3 ${getWinRateColor(comparison.agents[0]?.win_rate ?? 0)}`}
                  >
                    {((Number(comparison.agents[0]?.win_rate) || 0) * 100).toFixed(1)}%
                  </td>
                  <td className="py-2 px-3 text-center text-zinc-500 dark:text-zinc-400">
                    Win Rate
                  </td>
                  <td
                    className={`py-2 px-3 text-right ${getWinRateColor(comparison.agents[1]?.win_rate ?? 0)}`}
                  >
                    {((Number(comparison.agents[1]?.win_rate) || 0) * 100).toFixed(1)}%
                  </td>
                </tr>
                <tr className="border-b border-zinc-200 dark:border-zinc-700">
                  <td className="py-2 px-3 text-white">#{comparison.agents[0].rank}</td>
                  <td className="py-2 px-3 text-center text-zinc-500 dark:text-zinc-400">Rank</td>
                  <td className="py-2 px-3 text-right text-white">#{comparison.agents[1].rank}</td>
                </tr>
                {comparison.agents[0].consistency_score !== undefined && (
                  <tr className="border-b border-zinc-200 dark:border-zinc-700">
                    <td className="py-2 px-3 text-white">
                      {((Number(comparison.agents[0].consistency_score) || 0) * 100).toFixed(0)}%
                    </td>
                    <td className="py-2 px-3 text-center text-zinc-500 dark:text-zinc-400">
                      Consistency
                    </td>
                    <td className="py-2 px-3 text-right text-white">
                      {comparison.agents[1].consistency_score !== undefined
                        ? `${((Number(comparison.agents[1].consistency_score) || 0) * 100).toFixed(0)}%`
                        : '-'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Head-to-Head */}
          {comparison.head_to_head && comparison.head_to_head.matches > 0 && (
            <div className="bg-zinc-50 dark:bg-zinc-900 rounded p-4">
              <h4 className="text-sm font-medium text-zinc-600 dark:text-zinc-300 mb-3">
                Head-to-Head Record
              </h4>
              <div className="flex items-center justify-between">
                <div className="text-center">
                  <div className="text-2xl font-bold text-green-400">
                    {comparison.head_to_head.agent1_wins}
                  </div>
                  <div className="text-xs text-zinc-500 dark:text-zinc-400">Wins</div>
                </div>
                <div className="text-center">
                  <div className="text-lg text-zinc-400 dark:text-zinc-500">
                    {comparison.head_to_head.matches} matches
                  </div>
                  {comparison.head_to_head.draws > 0 && (
                    <div className="text-xs text-zinc-500 dark:text-zinc-400">
                      {comparison.head_to_head.draws} draws
                    </div>
                  )}
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-green-400">
                    {comparison.head_to_head.agent2_wins}
                  </div>
                  <div className="text-xs text-zinc-500 dark:text-zinc-400">Wins</div>
                </div>
              </div>
            </div>
          )}

          {/* Domain Overlap */}
          {comparison.agents[0].domains && comparison.agents[1].domains && (
            <div className="bg-zinc-50 dark:bg-zinc-900 rounded p-4">
              <h4 className="text-sm font-medium text-zinc-600 dark:text-zinc-300 mb-3">
                Domain Expertise
              </h4>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-zinc-500 dark:text-zinc-400 mb-2">{agent1}</div>
                  <div className="flex flex-wrap gap-1">
                    {comparison.agents[0].domains.slice(0, 5).map((domain, i) => (
                      <span
                        key={i}
                        className="px-2 py-0.5 bg-blue-900/50 text-blue-300 text-xs rounded"
                      >
                        {domain}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-zinc-500 dark:text-zinc-400 mb-2">{agent2}</div>
                  <div className="flex flex-wrap gap-1">
                    {comparison.agents[1].domains.slice(0, 5).map((domain, i) => (
                      <span
                        key={i}
                        className="px-2 py-0.5 bg-purple-900/50 text-purple-300 text-xs rounded"
                      >
                        {domain}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {!comparison && !loading && agent1 && agent2 && agent1 !== agent2 && (
        <div className="text-center py-8 text-zinc-500 dark:text-zinc-400">
          No comparison data available
        </div>
      )}

      {agent1 === agent2 && agent1 && (
        <div className="text-center py-8 text-zinc-500 dark:text-zinc-400">
          Please select two different agents to compare
        </div>
      )}
    </div>
  );
}
