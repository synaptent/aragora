'use client';

import React, { useCallback, useEffect, useState } from 'react';

// =============================================================================
// Types
// =============================================================================

interface Receipt {
  id: string;
  timestamp: string;
  verdict: 'PASS' | 'CONDITIONAL' | 'FAIL';
  topic: string;
  findings_count: number;
}

interface WorkflowStats {
  active: number;
  completed_today: number;
  failed: number;
  pending: number;
}

interface TeamMember {
  agent: string;
  elo: number;
  wins: number;
  losses: number;
  trend: 'up' | 'down' | 'stable';
}

interface ComplianceData {
  score: number;
  passed: number;
  failed: number;
  conditional: number;
  trend: number;
}

interface EnterpriseMetricsCardsProps {
  apiBase: string;
}

// =============================================================================
// Verdict Badge Component
// =============================================================================

function VerdictBadge({ verdict }: { verdict: Receipt['verdict'] }) {
  const colors = {
    PASS: 'bg-green-500/20 text-green-400 border-green-500/30',
    CONDITIONAL: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    FAIL: 'bg-red-500/20 text-red-400 border-red-500/30',
  };

  return (
    <span className={`px-2 py-0.5 text-xs font-theme-data border rounded ${colors[verdict]}`}>
      {verdict}
    </span>
  );
}

// =============================================================================
// Trend Indicator Component
// =============================================================================

function TrendIndicator({ trend, value }: { trend: 'up' | 'down' | 'stable'; value?: number }) {
  const icons = { up: '↑', down: '↓', stable: '→' };
  const colors = { up: 'text-green-400', down: 'text-red-400', stable: 'text-[var(--text-muted)]' };

  return (
    <span className={`font-theme-data ${colors[trend]}`}>
      {icons[trend]}
      {value !== undefined && (
        <span className="ml-1">
          {value > 0 ? '+' : ''}
          {value}%
        </span>
      )}
    </span>
  );
}

// =============================================================================
// Decision Audit Trail Card
// =============================================================================

function DecisionAuditCard({ apiBase }: { apiBase: string }) {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchReceipts = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`${apiBase}/api/gauntlet/results?limit=5`);
      if (!response.ok) throw new Error('Failed to fetch');
      const data = await response.json();
      // Map to Receipt format
      const mapped = (data.results || data || [])
        .slice(0, 5)
        .map((r: Record<string, unknown>) => ({
          id: r.id || r.debate_id || String(Math.random()),
          timestamp: r.timestamp || new Date().toISOString(),
          verdict: r.verdict || 'PASS',
          topic: r.topic || r.question || 'Unnamed Decision',
          findings_count: r.findings_count || (Array.isArray(r.findings) ? r.findings.length : 0),
        }));
      setReceipts(mapped);
      setError(null);
    } catch {
      setError('Could not load audit trail');
      // Show mock data for demo
      setReceipts([
        {
          id: '1',
          timestamp: new Date().toISOString(),
          verdict: 'PASS',
          topic: 'Q4 Budget Allocation',
          findings_count: 0,
        },
        {
          id: '2',
          timestamp: new Date(Date.now() - 3600000).toISOString(),
          verdict: 'CONDITIONAL',
          topic: 'Vendor Selection',
          findings_count: 2,
        },
        {
          id: '3',
          timestamp: new Date(Date.now() - 7200000).toISOString(),
          verdict: 'PASS',
          topic: 'Hiring Decision',
          findings_count: 0,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchReceipts();
  }, [fetchReceipts]);

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg overflow-hidden">
      <div className="p-3 border-b border-[var(--border)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">$</span>
          <h3 className="text-sm font-medium text-[var(--text)]">Decision Audit Trail</h3>
        </div>
        <button
          onClick={fetchReceipts}
          className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
        >
          ↻
        </button>
      </div>
      <div className="p-3 space-y-2 max-h-[200px] overflow-y-auto">
        {loading ? (
          <div className="text-xs text-[var(--text-muted)] text-center py-4">Loading...</div>
        ) : error && receipts.length === 0 ? (
          <div className="text-xs text-red-400 text-center py-4">{error}</div>
        ) : receipts.length === 0 ? (
          <div className="text-xs text-[var(--text-muted)] text-center py-4">
            No decisions recorded yet
          </div>
        ) : (
          receipts.map((receipt) => (
            <div
              key={receipt.id}
              className="flex items-center justify-between p-2 bg-[var(--bg)] rounded border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm text-[var(--text)] truncate">{receipt.topic}</div>
                <div className="text-xs text-[var(--text-muted)]">
                  {new Date(receipt.timestamp).toLocaleDateString()}
                </div>
              </div>
              <div className="flex items-center gap-2 ml-2">
                {receipt.findings_count > 0 && (
                  <span className="text-xs text-[var(--text-muted)]">
                    {receipt.findings_count} findings
                  </span>
                )}
                <VerdictBadge verdict={receipt.verdict} />
              </div>
            </div>
          ))
        )}
      </div>
      <a
        href="/receipts"
        className="block p-2 text-center text-xs font-theme-data text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors border-t border-[var(--border)]"
      >
        View All Receipts →
      </a>
    </div>
  );
}

// =============================================================================
// Compliance Score Card
// =============================================================================

function ComplianceScoreCard({ apiBase }: { apiBase: string }) {
  const [compliance, setCompliance] = useState<ComplianceData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchCompliance = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`${apiBase}/api/gauntlet/results?limit=50`);
      if (!response.ok) throw new Error('Failed to fetch');
      const data = await response.json();
      const results = data.results || data || [];

      const passed = results.filter((r: { verdict: string }) => r.verdict === 'PASS').length;
      const failed = results.filter((r: { verdict: string }) => r.verdict === 'FAIL').length;
      const conditional = results.filter(
        (r: { verdict: string }) => r.verdict === 'CONDITIONAL',
      ).length;
      const total = results.length || 1;
      const score = Math.round((passed / total) * 100);

      setCompliance({
        score,
        passed,
        failed,
        conditional,
        trend: 5, // Placeholder - would calculate from historical data
      });
    } catch {
      // Show mock data
      setCompliance({ score: 87, passed: 42, failed: 3, conditional: 5, trend: 5 });
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchCompliance();
  }, [fetchCompliance]);

  const scoreColor = compliance
    ? compliance.score >= 80
      ? 'text-green-400'
      : compliance.score >= 60
        ? 'text-yellow-400'
        : 'text-red-400'
    : 'text-[var(--text-muted)]';

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg overflow-hidden">
      <div className="p-3 border-b border-[var(--border)] flex items-center gap-2">
        <span className="text-lg">✓</span>
        <h3 className="text-sm font-medium text-[var(--text)]">Compliance Score</h3>
      </div>
      <div className="p-4">
        {loading ? (
          <div className="text-xs text-[var(--text-muted)] text-center py-4">Loading...</div>
        ) : compliance ? (
          <div className="space-y-3">
            <div className="flex items-end justify-between">
              <div className={`text-4xl font-bold font-theme-data ${scoreColor}`}>
                {compliance.score}%
              </div>
              <TrendIndicator
                trend={compliance.trend >= 0 ? 'up' : 'down'}
                value={compliance.trend}
              />
            </div>

            {/* Progress bar */}
            <div className="h-2 bg-[var(--bg)] rounded-full overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ${
                  compliance.score >= 80
                    ? 'bg-green-500'
                    : compliance.score >= 60
                      ? 'bg-yellow-500'
                      : 'bg-red-500'
                }`}
                style={{ width: `${compliance.score}%` }}
              />
            </div>

            {/* Breakdown */}
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="p-2 bg-[var(--bg)] rounded">
                <div className="text-lg font-theme-data text-green-400">{compliance.passed}</div>
                <div className="text-xs text-[var(--text-muted)]">Passed</div>
              </div>
              <div className="p-2 bg-[var(--bg)] rounded">
                <div className="text-lg font-theme-data text-yellow-400">
                  {compliance.conditional}
                </div>
                <div className="text-xs text-[var(--text-muted)]">Conditional</div>
              </div>
              <div className="p-2 bg-[var(--bg)] rounded">
                <div className="text-lg font-theme-data text-red-400">{compliance.failed}</div>
                <div className="text-xs text-[var(--text-muted)]">Failed</div>
              </div>
            </div>
          </div>
        ) : (
          <div className="text-xs text-[var(--text-muted)] text-center py-4">
            No compliance data available
          </div>
        )}
      </div>
      <a
        href="/gauntlet"
        className="block p-2 text-center text-xs font-theme-data text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors border-t border-[var(--border)]"
      >
        Run Gauntlet →
      </a>
    </div>
  );
}

// =============================================================================
// Active Workflows Card
// =============================================================================

function ActiveWorkflowsCard({ apiBase }: { apiBase: string }) {
  const [stats, setStats] = useState<WorkflowStats | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchStats = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`${apiBase}/api/workflows/stats`);
      if (!response.ok) throw new Error('Failed to fetch');
      const data = await response.json();
      setStats({
        active: data.active || 0,
        completed_today: data.completed_today || data.completed || 0,
        failed: data.failed || 0,
        pending: data.pending || data.queued || 0,
      });
    } catch {
      // Show mock data
      setStats({ active: 3, completed_today: 12, failed: 0, pending: 5 });
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg overflow-hidden">
      <div className="p-3 border-b border-[var(--border)] flex items-center gap-2">
        <span className="text-lg">&gt;</span>
        <h3 className="text-sm font-medium text-[var(--text)]">Active Workflows</h3>
      </div>
      <div className="p-4">
        {loading ? (
          <div className="text-xs text-[var(--text-muted)] text-center py-4">Loading...</div>
        ) : stats ? (
          <div className="grid grid-cols-2 gap-3">
            <div className="p-3 bg-[var(--bg)] rounded-lg border border-[var(--acid-green)]/30">
              <div className="text-2xl font-bold font-theme-data text-[var(--acid-green)]">
                {stats.active}
              </div>
              <div className="text-xs text-[var(--text-muted)]">Running</div>
            </div>
            <div className="p-3 bg-[var(--bg)] rounded-lg">
              <div className="text-2xl font-bold font-theme-data text-[var(--text)]">
                {stats.pending}
              </div>
              <div className="text-xs text-[var(--text-muted)]">Pending</div>
            </div>
            <div className="p-3 bg-[var(--bg)] rounded-lg">
              <div className="text-2xl font-bold font-theme-data text-green-400">
                {stats.completed_today}
              </div>
              <div className="text-xs text-[var(--text-muted)]">Completed Today</div>
            </div>
            <div className="p-3 bg-[var(--bg)] rounded-lg">
              <div className="text-2xl font-bold font-theme-data text-red-400">{stats.failed}</div>
              <div className="text-xs text-[var(--text-muted)]">Failed</div>
            </div>
          </div>
        ) : (
          <div className="text-xs text-[var(--text-muted)] text-center py-4">
            No workflow data available
          </div>
        )}
      </div>
      <a
        href="/workflows"
        className="block p-2 text-center text-xs font-theme-data text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors border-t border-[var(--border)]"
      >
        Manage Workflows →
      </a>
    </div>
  );
}

// =============================================================================
// Team Performance Card
// =============================================================================

function TeamPerformanceCard({ apiBase }: { apiBase: string }) {
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTeam = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`${apiBase}/api/leaderboard-view?limit=5`);
      if (!response.ok) throw new Error('Failed to fetch');
      const data = await response.json();
      const mapped = (data.agents || data || [])
        .slice(0, 5)
        .map((a: Record<string, unknown>) => ({
          agent: a.agent || a.name || 'Unknown',
          elo: a.elo || a.rating || 1500,
          wins: a.wins || 0,
          losses: a.losses || 0,
          trend: (a.trend as TeamMember['trend']) || (Math.random() > 0.5 ? 'up' : 'stable'),
        }));
      setTeam(mapped);
    } catch {
      // Show mock data
      setTeam([
        { agent: 'Claude', elo: 1823, wins: 42, losses: 8, trend: 'up' },
        { agent: 'GPT-4', elo: 1756, wins: 38, losses: 12, trend: 'stable' },
        { agent: 'Gemini', elo: 1698, wins: 31, losses: 19, trend: 'up' },
        { agent: 'Grok', elo: 1642, wins: 28, losses: 22, trend: 'down' },
        { agent: 'Mistral', elo: 1589, wins: 24, losses: 26, trend: 'stable' },
      ]);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchTeam();
  }, [fetchTeam]);

  // Map agent names to colors
  const getAgentColor = (agent: string): string => {
    const colors: Record<string, string> = {
      claude: '#00ffff',
      gpt4: '#10b981',
      'gpt-4': '#10b981',
      gemini: '#a855f7',
      grok: '#ef4444',
      mistral: '#f59e0b',
    };
    return colors[agent.toLowerCase().replace(/[^a-z0-9]/g, '')] || '#6b7280';
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg overflow-hidden">
      <div className="p-3 border-b border-[var(--border)] flex items-center gap-2">
        <span className="text-lg">^</span>
        <h3 className="text-sm font-medium text-[var(--text)]">Team Performance</h3>
      </div>
      <div className="p-3 space-y-2 max-h-[200px] overflow-y-auto">
        {loading ? (
          <div className="text-xs text-[var(--text-muted)] text-center py-4">Loading...</div>
        ) : team.length === 0 ? (
          <div className="text-xs text-[var(--text-muted)] text-center py-4">
            No team data available
          </div>
        ) : (
          team.map((member, index) => (
            <div
              key={member.agent}
              className="flex items-center gap-3 p-2 bg-[var(--bg)] rounded border border-[var(--border)]"
            >
              <span className="text-sm font-theme-data text-[var(--text-muted)] w-4">
                {index + 1}
              </span>
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: getAgentColor(member.agent) }}
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-[var(--text)] truncate">{member.agent}</div>
              </div>
              <div className="text-sm font-theme-data text-[var(--acid-green)]">{member.elo}</div>
              <div className="text-xs text-[var(--text-muted)]">
                {member.wins}W/{member.losses}L
              </div>
              <TrendIndicator trend={member.trend} />
            </div>
          ))
        )}
      </div>
      <a
        href="/leaderboard"
        className="block p-2 text-center text-xs font-theme-data text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors border-t border-[var(--border)]"
      >
        Full Leaderboard →
      </a>
    </div>
  );
}

// =============================================================================
// Main Component
// =============================================================================

export function EnterpriseMetricsCards({ apiBase }: EnterpriseMetricsCardsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <DecisionAuditCard apiBase={apiBase} />
      <ComplianceScoreCard apiBase={apiBase} />
      <ActiveWorkflowsCard apiBase={apiBase} />
      <TeamPerformanceCard apiBase={apiBase} />
    </div>
  );
}

export default EnterpriseMetricsCards;
