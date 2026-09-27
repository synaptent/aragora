'use client';

import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar } from 'recharts';
import { API_BASE_URL } from '@/config';

interface PatternData {
  date: string;
  issue_type: string;
  success_rate: number;
  pattern_count: number;
}

interface AgentData {
  agent: string;
  date: string;
  acceptance_rate: number;
  critique_quality: number;
  reputation_score: number;
}

interface DebateData {
  date: string;
  total_debates: number;
  consensus_rate: number;
  avg_confidence: number;
  avg_rounds: number;
  avg_duration: number;
}

interface EvolutionData {
  patterns: PatternData[];
  agents: AgentData[];
  debates: DebateData[];
}

export function LearningEvolution() {
  const [data, setData] = useState<EvolutionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'patterns' | 'agents' | 'debates'>('patterns');

  useEffect(() => {
    fetchEvolutionData();
  }, []);

  const fetchEvolutionData = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/learning/evolution`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const evolutionData = await response.json();
      setData(evolutionData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch evolution data');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-text-muted">Loading learning evolution...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-400 text-center">
          <div className="text-lg mb-2">Failed to load evolution data</div>
          <div className="text-sm">{error}</div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-text-muted">No evolution data available</div>
      </div>
    );
  }

  // Process data for charts
  type PatternChartPoint = { date: string; [issueType: string]: string | number };
  const patternChartData = data.patterns.reduce<PatternChartPoint[]>((acc, item) => {
    const existing = acc.find(d => d.date === item.date);
    if (existing) {
      existing[item.issue_type] = item.success_rate;
    } else {
      acc.push({
        date: item.date,
        [item.issue_type]: item.success_rate,
      });
    }
    return acc;
  }, []);

  type AgentChartPoint = { date: string; agent: string; reputation_score: number };
  const agentChartData = data.agents.reduce<AgentChartPoint[]>((acc, item) => {
    const existing = acc.find(d => d.date === item.date && d.agent === item.agent);
    if (!existing) {
      acc.push({
        date: item.date,
        agent: item.agent,
        reputation_score: item.reputation_score,
      });
    }
    return acc;
  }, []);

  const debateChartData = data.debates.map(item => ({
    ...item,
    date: new Date(item.date).toLocaleDateString(),
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-text">Learning Evolution</h2>
        <button
          onClick={fetchEvolutionData}
          className="px-3 py-1 bg-surface border border-border rounded text-sm text-text hover:bg-surface-hover"
        >
          Refresh
        </button>
      </div>

      {/* Tab Navigation */}
      <div className="flex space-x-1 bg-surface border border-border rounded p-1">
        {([
          { key: 'patterns', label: 'Pattern Success' },
          { key: 'agents', label: 'Agent Reputation' },
          { key: 'debates', label: 'Debate Outcomes' },
        ] as const).map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-1 rounded text-sm transition-colors ${
              activeTab === tab.key
                ? 'bg-accent text-bg font-medium'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Charts */}
      <div className="bg-surface border border-border rounded-lg p-4">
        {activeTab === 'patterns' && (
          <div>
            <h3 className="text-lg font-medium mb-4 text-text">Pattern Success Rates Over Time</h3>
            <ResponsiveContainer width="100%" height={400}>
              <LineChart data={patternChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" stroke="#9CA3AF" />
                <YAxis stroke="#9CA3AF" domain={[0, 1]} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1F2937',
                    border: '1px solid #374151',
                    borderRadius: '6px',
                  }}
                />
                <Legend />
                {/* Dynamic lines for each issue type */}
                {Array.from(new Set(data.patterns.map(p => p.issue_type))).map((type, index) => (
                  <Line
                    key={type}
                    type="monotone"
                    dataKey={type}
                    stroke={`hsl(${(index * 137.5) % 360}, 70%, 50%)`}
                    strokeWidth={2}
                    name={`${type} success rate`}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {activeTab === 'agents' && (
          <div>
            <h3 className="text-lg font-medium mb-4 text-text">Agent Reputation Evolution</h3>
            <ResponsiveContainer width="100%" height={400}>
              <LineChart data={agentChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" stroke="#9CA3AF" />
                <YAxis stroke="#9CA3AF" domain={[0, 1]} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1F2937',
                    border: '1px solid #374151',
                    borderRadius: '6px',
                  }}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="reputation_score"
                  stroke="#10B981"
                  strokeWidth={2}
                  name="Reputation Score"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {activeTab === 'debates' && (
          <div>
            <h3 className="text-lg font-medium mb-4 text-text">Debate Outcomes Over Time</h3>
            <ResponsiveContainer width="100%" height={400}>
              <BarChart data={debateChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" stroke="#9CA3AF" />
                <YAxis stroke="#9CA3AF" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1F2937',
                    border: '1px solid #374151',
                    borderRadius: '6px',
                  }}
                />
                <Legend />
                <Bar dataKey="total_debates" fill="#3B82F6" name="Total Debates" />
                <Bar dataKey="consensus_rate" fill="#10B981" name="Consensus Rate" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-surface border border-border rounded-lg p-4">
          <div className="text-text-muted text-sm">Total Patterns</div>
          <div className="text-2xl font-bold text-text">
            {data.patterns.length > 0 ? new Set(data.patterns.map(p => p.date + p.issue_type)).size : 0}
          </div>
        </div>
        <div className="bg-surface border border-border rounded-lg p-4">
          <div className="text-text-muted text-sm">Active Agents</div>
          <div className="text-2xl font-bold text-text">
            {new Set(data.agents.map(a => a.agent)).size}
          </div>
        </div>
        <div className="bg-surface border border-border rounded-lg p-4">
          <div className="text-text-muted text-sm">Total Debate Days</div>
          <div className="text-2xl font-bold text-text">
            {data.debates.length}
          </div>
        </div>
      </div>
    </div>
  );
}
