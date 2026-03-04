'use client';

import { useEffect, useState, useCallback } from 'react';
import { logger } from '@/utils/logger';
import { useAuth } from '@/context/AuthContext';
import { API_BASE_URL } from '@/config';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const API_BASE = API_BASE_URL;

// API Explorer endpoint definitions
interface EndpointDef {
  method: 'GET' | 'POST' | 'DELETE';
  path: string;
  description: string;
  params?: Array<{ name: string; type: string; required?: boolean; default?: string }>;
  body?: string;
}

const API_ENDPOINTS: EndpointDef[] = [
  { method: 'GET', path: '/api/debates', description: 'List all debates' },
  { method: 'GET', path: '/api/debates/:id', description: 'Get debate by ID', params: [{ name: 'id', type: 'string', required: true }] },
  { method: 'POST', path: '/api/debates', description: 'Create new debate', body: '{\n  "topic": "Should AI be regulated?",\n  "agents": ["claude", "gpt4"],\n  "rounds": 3\n}' },
  { method: 'GET', path: '/api/agents', description: 'List available agents' },
  { method: 'GET', path: '/api/agent/:name/stats', description: 'Get agent statistics', params: [{ name: 'name', type: 'string', required: true, default: 'claude' }] },
  { method: 'GET', path: '/api/auth/me', description: 'Get current user info' },
  { method: 'GET', path: '/api/billing/usage', description: 'Get usage statistics' },
  { method: 'GET', path: '/api/leaderboard', description: 'Get agent leaderboard' },
];

interface ApiKeyInfo {
  prefix: string;
  created_at: string | null;
  expires_at: string | null;
  has_key: boolean;
}

interface UsageStats {
  total_requests: number;
  requests_today: number;
  requests_this_month: number;
  tokens_used: number;
  cost_usd: number;
}

interface DailyUsage {
  date: string;
  requests: number;
  tokens: number;
}

export default function DeveloperPortal() {
  const { isAuthenticated, tokens } = useAuth();
  const [apiKeyInfo, setApiKeyInfo] = useState<ApiKeyInfo | null>(null);
  const [newApiKey, setNewApiKey] = useState<string | null>(null);
  const [usageStats, setUsageStats] = useState<UsageStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [copied, setCopied] = useState(false);
  const accessToken = tokens?.access_token;

  // API Explorer state
  const [selectedEndpoint, setSelectedEndpoint] = useState<EndpointDef>(API_ENDPOINTS[0]);
  const [endpointParams, setEndpointParams] = useState<Record<string, string>>({});
  const [requestBody, setRequestBody] = useState<string>('');
  const [explorerResponse, setExplorerResponse] = useState<string | null>(null);
  const [explorerLoading, setExplorerLoading] = useState(false);
  const [explorerError, setExplorerError] = useState<string | null>(null);

  // Usage graph state
  const [dailyUsage, setDailyUsage] = useState<DailyUsage[]>([]);
  const [usageGraphView, setUsageGraphView] = useState<'requests' | 'tokens'>('requests');

  const fetchApiKeyInfo = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
        },
      });
      if (res.ok) {
        const data = await res.json();
        const user = data.user;
        setApiKeyInfo({
          prefix: user.api_key_prefix || null,
          created_at: user.api_key_created_at || null,
          expires_at: user.api_key_expires_at || null,
          has_key: !!user.api_key_prefix,
        });
      }
    } catch (err) {
      logger.error('Failed to fetch API key info:', err);
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  const fetchUsageStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/billing/usage`, {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setUsageStats({
          total_requests: data.usage?.total_api_calls || 0,
          requests_today: data.usage?.api_calls_today || 0,
          requests_this_month: data.usage?.debates_used || 0,
          tokens_used: data.usage?.tokens_used || 0,
          cost_usd: data.usage?.estimated_cost_usd || 0,
        });

        // Build daily usage from API data (or zeros if not provided)
        const daily: DailyUsage[] = [];
        const today = new Date();
        for (let i = 6; i >= 0; i--) {
          const date = new Date(today);
          date.setDate(date.getDate() - i);
          daily.push({
            date: date.toLocaleDateString('en-US', { weekday: 'short' }),
            requests: data.usage?.daily_requests?.[i] || 0,
            tokens: data.usage?.daily_tokens?.[i] || 0,
          });
        }
        setDailyUsage(daily);
      }
    } catch (err) {
      logger.error('Failed to fetch usage stats:', err);
    }
  }, [accessToken]);

  useEffect(() => {
    if (isAuthenticated && accessToken) {
      fetchApiKeyInfo();
      fetchUsageStats();
    } else {
      setLoading(false);
    }
  }, [isAuthenticated, accessToken, fetchApiKeyInfo, fetchUsageStats]);

  const generateApiKey = async () => {
    setGenerating(true);
    setError(null);
    setNewApiKey(null);
    try {
      const res = await fetch(`${API_BASE}/api/auth/api-key`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
      });
      const data = await res.json();
      if (res.ok) {
        setNewApiKey(data.api_key);
        setApiKeyInfo({
          prefix: data.prefix,
          created_at: new Date().toISOString(),
          expires_at: data.expires_at,
          has_key: true,
        });
      } else {
        setError(data.error || 'Failed to generate API key');
      }
    } catch {
      setError('Network error. Please try again.');
    } finally {
      setGenerating(false);
    }
  };

  const revokeApiKey = async () => {
    if (!confirm('Are you sure you want to revoke your API key? This cannot be undone.')) {
      return;
    }
    setRevoking(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/auth/api-key`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
        },
      });
      if (res.ok) {
        setApiKeyInfo({
          prefix: '',
          created_at: null,
          expires_at: null,
          has_key: false,
        });
        setNewApiKey(null);
      } else {
        const data = await res.json();
        setError(data.error || 'Failed to revoke API key');
      }
    } catch {
      setError('Network error. Please try again.');
    } finally {
      setRevoking(false);
    }
  };

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      logger.error('Failed to copy:', err);
    }
  };

  // API Explorer functions
  const selectEndpoint = (endpoint: EndpointDef) => {
    setSelectedEndpoint(endpoint);
    setExplorerResponse(null);
    setExplorerError(null);
    // Set default params
    const defaults: Record<string, string> = {};
    endpoint.params?.forEach(p => {
      if (p.default) defaults[p.name] = p.default;
    });
    setEndpointParams(defaults);
    setRequestBody(endpoint.body || '');
  };

  const executeRequest = async () => {
    setExplorerLoading(true);
    setExplorerError(null);
    setExplorerResponse(null);

    try {
      // Build URL with params
      let url = `${API_BASE}${selectedEndpoint.path}`;
      selectedEndpoint.params?.forEach(p => {
        url = url.replace(`:${p.name}`, endpointParams[p.name] || '');
      });

      const options: RequestInit = {
        method: selectedEndpoint.method,
        headers: {
          'Authorization': `Bearer ${newApiKey || accessToken}`,
          'Content-Type': 'application/json',
        },
      };

      if (selectedEndpoint.method === 'POST' && requestBody) {
        options.body = requestBody;
      }

      const res = await fetch(url, options);
      const data = await res.json();
      setExplorerResponse(JSON.stringify(data, null, 2));
    } catch (err) {
      setExplorerError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setExplorerLoading(false);
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-background p-8">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-2xl font-mono text-acid-green mb-4">DEVELOPER PORTAL</h1>
          <p className="text-text-muted font-mono">Please log in to access the developer portal.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background p-8">
      <PanelErrorBoundary panelName="Developer Portal">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-2xl font-mono text-acid-green mb-2">DEVELOPER PORTAL</h1>
          <p className="text-text-muted font-mono text-sm mb-8">
            Manage your API keys and monitor usage
          </p>

        {/* API Key Management */}
        <div className="border border-acid-green/30 bg-surface/30 p-6 mb-6">
          <h2 className="text-lg font-mono text-acid-cyan mb-4">API KEY</h2>

          {loading ? (
            <div className="text-xs font-mono text-text-muted">Loading...</div>
          ) : apiKeyInfo?.has_key ? (
            <div className="space-y-4">
              {/* Current Key Info */}
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-mono">
                  <span className="text-text-muted">Key Prefix</span>
                  <span className="text-acid-green">{apiKeyInfo.prefix}...</span>
                </div>
                {apiKeyInfo.created_at && (
                  <div className="flex justify-between text-xs font-mono">
                    <span className="text-text-muted">Created</span>
                    <span className="text-text">{new Date(apiKeyInfo.created_at).toLocaleDateString()}</span>
                  </div>
                )}
                {apiKeyInfo.expires_at && (
                  <div className="flex justify-between text-xs font-mono">
                    <span className="text-text-muted">Expires</span>
                    <span className="text-text">{new Date(apiKeyInfo.expires_at).toLocaleDateString()}</span>
                  </div>
                )}
              </div>

              {/* New Key Display */}
              {newApiKey && (
                <div className="border border-warning/50 bg-warning/10 p-4">
                  <div className="text-xs font-mono text-warning mb-2">
                    Save this key now - it will not be shown again!
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 text-xs font-mono bg-background p-2 border border-acid-green/20 text-acid-green break-all">
                      {newApiKey}
                    </code>
                    <button
                      onClick={() => copyToClipboard(newApiKey)}
                      className="px-3 py-2 text-xs font-mono border border-acid-green/50 text-acid-green hover:bg-acid-green/10 transition-colors"
                    >
                      {copied ? 'COPIED!' : 'COPY'}
                    </button>
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-2 pt-2">
                <button
                  onClick={generateApiKey}
                  disabled={generating}
                  className="px-4 py-2 text-xs font-mono border border-acid-cyan/50 text-acid-cyan hover:bg-acid-cyan/10 transition-colors disabled:opacity-50"
                >
                  {generating ? 'GENERATING...' : 'REGENERATE KEY'}
                </button>
                <button
                  onClick={revokeApiKey}
                  disabled={revoking}
                  className="px-4 py-2 text-xs font-mono border border-warning/50 text-warning hover:bg-warning/10 transition-colors disabled:opacity-50"
                >
                  {revoking ? 'REVOKING...' : 'REVOKE KEY'}
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-xs font-mono text-text-muted">
                You don&apos;t have an API key yet. Generate one to access the Aragora API.
              </p>
              <button
                onClick={generateApiKey}
                disabled={generating}
                className="px-4 py-2 text-xs font-mono border border-acid-green/50 text-acid-green hover:bg-acid-green/10 transition-colors disabled:opacity-50"
              >
                {generating ? 'GENERATING...' : 'GENERATE API KEY'}
              </button>
            </div>
          )}

          {error && (
            <div className="mt-4 text-xs font-mono text-warning">{error}</div>
          )}
        </div>

        {/* Usage Statistics */}
        <div className="border border-acid-green/30 bg-surface/30 p-6 mb-6">
          <h2 className="text-lg font-mono text-acid-cyan mb-4">USAGE STATISTICS</h2>

          {usageStats ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-4">
              <div className="border border-acid-green/20 p-3">
                <div className="text-xs font-mono text-text-muted mb-1">DEBATES</div>
                <div className="text-xl font-mono text-acid-green">{usageStats.requests_this_month}</div>
              </div>
              <div className="border border-acid-green/20 p-3">
                <div className="text-xs font-mono text-text-muted mb-1">TOKENS USED</div>
                <div className="text-xl font-mono text-acid-green">{usageStats.tokens_used.toLocaleString()}</div>
              </div>
              <div className="border border-acid-green/20 p-3">
                <div className="text-xs font-mono text-text-muted mb-1">API CALLS</div>
                <div className="text-xl font-mono text-acid-green">{usageStats.total_requests}</div>
              </div>
              <div className="border border-acid-green/20 p-3">
                <div className="text-xs font-mono text-text-muted mb-1">EST. COST</div>
                <div className="text-xl font-mono text-acid-cyan">${usageStats.cost_usd.toFixed(2)}</div>
              </div>
            </div>
          ) : (
            <div className="text-xs font-mono text-text-muted">Loading usage data...</div>
          )}

          {/* Usage Graph */}
          {dailyUsage.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-mono text-text">7-DAY USAGE</h3>
                <div className="flex gap-2">
                  <button
                    onClick={() => setUsageGraphView('requests')}
                    className={`px-2 py-1 text-xs font-mono border transition-colors ${
                      usageGraphView === 'requests'
                        ? 'border-acid-green bg-acid-green/20 text-acid-green'
                        : 'border-border text-text-muted hover:text-text'
                    }`}
                  >
                    REQUESTS
                  </button>
                  <button
                    onClick={() => setUsageGraphView('tokens')}
                    className={`px-2 py-1 text-xs font-mono border transition-colors ${
                      usageGraphView === 'tokens'
                        ? 'border-acid-cyan bg-acid-cyan/20 text-acid-cyan'
                        : 'border-border text-text-muted hover:text-text'
                    }`}
                  >
                    TOKENS
                  </button>
                </div>
              </div>
              <div className="flex items-end gap-2 h-32">
                {dailyUsage.map((day, idx) => {
                  const value = usageGraphView === 'requests' ? day.requests : day.tokens;
                  const maxValue = Math.max(...dailyUsage.map(d => usageGraphView === 'requests' ? d.requests : d.tokens));
                  const heightPercent = maxValue > 0 ? (value / maxValue) * 100 : 0;
                  const barColor = usageGraphView === 'requests' ? 'bg-acid-green' : 'bg-acid-cyan';
                  return (
                    <div key={idx} className="flex-1 flex flex-col items-center gap-1">
                      <span className="text-[10px] font-mono text-text-muted">
                        {value.toLocaleString()}
                      </span>
                      <div
                        className={`w-full ${barColor} transition-all duration-300 rounded-t`}
                        style={{ height: `${heightPercent}%`, minHeight: heightPercent > 0 ? '4px' : '0' }}
                      />
                      <span className="text-[10px] font-mono text-text-muted">{day.date}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* API Explorer */}
        <div className="border border-acid-green/30 bg-surface/30 p-6 mb-6">
          <h2 className="text-lg font-mono text-acid-cyan mb-4">API EXPLORER</h2>
          <p className="text-xs font-mono text-text-muted mb-4">
            Test API endpoints directly from your browser
          </p>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Endpoint Selection */}
            <div className="space-y-4">
              <div>
                <label className="text-xs font-mono text-text-muted block mb-2">ENDPOINT</label>
                <select
                  value={`${selectedEndpoint.method} ${selectedEndpoint.path}`}
                  onChange={(e) => {
                    const [method, ...pathParts] = e.target.value.split(' ');
                    const path = pathParts.join(' ');
                    const endpoint = API_ENDPOINTS.find(ep => ep.method === method && ep.path === path);
                    if (endpoint) selectEndpoint(endpoint);
                  }}
                  className="w-full bg-background border border-acid-green/30 text-text text-xs font-mono p-2 focus:outline-none focus:border-acid-green"
                >
                  {API_ENDPOINTS.map((ep, idx) => (
                    <option key={idx} value={`${ep.method} ${ep.path}`}>
                      {ep.method} {ep.path} - {ep.description}
                    </option>
                  ))}
                </select>
              </div>

              {/* Path Parameters */}
              {selectedEndpoint.params && selectedEndpoint.params.length > 0 && (
                <div className="space-y-2">
                  <label className="text-xs font-mono text-text-muted block">PARAMETERS</label>
                  {selectedEndpoint.params.map((param) => (
                    <div key={param.name} className="flex items-center gap-2">
                      <span className="text-xs font-mono text-acid-green w-20">{param.name}:</span>
                      <input
                        type="text"
                        value={endpointParams[param.name] || ''}
                        onChange={(e) => setEndpointParams({ ...endpointParams, [param.name]: e.target.value })}
                        placeholder={param.required ? 'required' : 'optional'}
                        aria-label={`Parameter: ${param.name}`}
                        className="flex-1 bg-background border border-acid-green/30 text-text text-xs font-mono p-2 focus:outline-none focus:border-acid-green"
                      />
                    </div>
                  ))}
                </div>
              )}

              {/* Request Body */}
              {selectedEndpoint.method === 'POST' && (
                <div>
                  <label htmlFor="request-body" className="text-xs font-mono text-text-muted block mb-2">REQUEST BODY</label>
                  <textarea
                    id="request-body"
                    value={requestBody}
                    onChange={(e) => setRequestBody(e.target.value)}
                    rows={6}
                    aria-label="Request body JSON"
                    className="w-full bg-background border border-acid-green/30 text-acid-green text-xs font-mono p-2 focus:outline-none focus:border-acid-green resize-none"
                  />
                </div>
              )}

              <button
                onClick={executeRequest}
                disabled={explorerLoading || !accessToken}
                className="px-4 py-2 text-xs font-mono border border-acid-green/50 text-acid-green hover:bg-acid-green/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {explorerLoading ? 'SENDING...' : 'SEND REQUEST'}
              </button>
            </div>

            {/* Response Panel */}
            <div>
              <label className="text-xs font-mono text-text-muted block mb-2">RESPONSE</label>
              <div className="bg-background border border-acid-green/20 p-3 h-64 overflow-auto">
                {explorerError && (
                  <pre className="text-xs font-mono text-warning whitespace-pre-wrap">{explorerError}</pre>
                )}
                {explorerResponse && (
                  <pre className="text-xs font-mono text-acid-green whitespace-pre-wrap">{explorerResponse}</pre>
                )}
                {!explorerError && !explorerResponse && (
                  <span className="text-xs font-mono text-text-muted">
                    Response will appear here...
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Quick Start Guide */}
        <div className="border border-acid-green/30 bg-surface/30 p-6 mb-6">
          <h2 className="text-lg font-mono text-acid-cyan mb-4">QUICK START</h2>

          <div className="space-y-6">
            {/* Zero-dependency debate */}
            <div>
              <h3 className="text-sm font-mono text-text mb-2">Run a Debate (no server needed)</h3>
              <pre className="text-xs font-mono bg-background p-3 border border-acid-green/20 text-acid-green overflow-x-auto">
{`pip install aragora-debate`}
              </pre>
              <pre className="text-xs font-mono bg-background p-3 mt-2 border border-acid-green/20 text-acid-green overflow-x-auto whitespace-pre">
{`from aragora_debate import Debate, create_agent
import asyncio

async def main():
    debate = Debate(topic="Should we use K8s or VMs?", rounds=2)
    debate.add_agent(create_agent("mock", name="analyst",
        proposal="K8s enables auto-scaling and self-healing."))
    debate.add_agent(create_agent("mock", name="skeptic",
        proposal="VMs are simpler; our team lacks K8s expertise."))
    result = await debate.run()
    print(f"Consensus: {result.consensus_reached}")

asyncio.run(main())`}
              </pre>
              <p className="text-[10px] font-mono text-text-muted mt-1">
                Zero dependencies. No API keys. Works offline. Add real LLMs with{' '}
                <code className="text-acid-green">pip install aragora-debate[anthropic]</code>
              </p>
            </div>

            {/* API Authentication */}
            <div>
              <h3 className="text-sm font-mono text-text mb-2">REST API (requires server)</h3>
              <pre className="text-xs font-mono bg-background p-3 border border-acid-green/20 text-acid-green overflow-x-auto">
{`curl -X POST ${API_BASE}/api/debates \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"topic": "Should AI be regulated?", "agents": ["claude", "gpt4"], "rounds": 3}'`}
              </pre>
            </div>

            {/* SDK install */}
            <div>
              <h3 className="text-sm font-mono text-text mb-2">SDK Installation</h3>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-text-muted">Debate engine:</span>
                  <code className="text-xs font-mono bg-background px-2 py-1 border border-acid-green/20 text-acid-green">
                    pip install aragora-debate
                  </code>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-text-muted">Python SDK:</span>
                  <code className="text-xs font-mono bg-background px-2 py-1 border border-acid-green/20 text-acid-green">
                    pip install aragora-sdk
                  </code>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-text-muted">TypeScript:</span>
                  <code className="text-xs font-mono bg-background px-2 py-1 border border-acid-green/20 text-acid-green">
                    npm install @aragora/sdk
                  </code>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Documentation Links */}
        <div className="border border-acid-green/30 bg-surface/30 p-6">
          <h2 className="text-lg font-mono text-acid-cyan mb-4">DOCUMENTATION</h2>
          <div className="flex flex-wrap gap-4">
            <a
              href="https://github.com/synaptent/aragora/blob/main/docs/api/API_REFERENCE.md"
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 text-xs font-mono border border-acid-green/50 text-acid-green hover:bg-acid-green/10 transition-colors"
            >
              API REFERENCE
            </a>
            <a
              href="https://github.com/synaptent/aragora/blob/main/docs/SDK_GUIDE.md"
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 text-xs font-mono border border-acid-green/50 text-acid-green hover:bg-acid-green/10 transition-colors"
            >
              SDK GUIDE
            </a>
            <a
              href="https://github.com/synaptent/aragora/blob/main/docs/START_HERE.md"
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 text-xs font-mono border border-acid-green/50 text-acid-green hover:bg-acid-green/10 transition-colors"
            >
              START HERE
            </a>
            <a
              href="https://github.com/synaptent/aragora/tree/main/examples"
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 text-xs font-mono border border-acid-green/50 text-acid-green hover:bg-acid-green/10 transition-colors"
            >
              EXAMPLES
            </a>
          </div>
        </div>
        </div>
      </PanelErrorBoundary>
    </div>
  );
}
