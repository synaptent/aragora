'use client';

import { useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

interface DemoResult {
  topic: string;
  consensus_reached: boolean;
  confidence: number;
  verdict: string;
  participants: string[];
  receipt_hash?: string;
}

export default function PublicDemoPage() {
  const [topic, setTopic] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DemoResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runDemo = async () => {
    if (!topic.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/demo/adversarial`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topic.trim(), agent_count: 3, rounds: 2 }),
      });
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const data = await res.json();
      setResult(data?.data ?? data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-start px-4 py-16">
      <div className="w-full max-w-2xl space-y-8">
        <div className="text-center space-y-3">
          <h1 className="text-4xl font-bold tracking-tight">Live Debate Demo</h1>
          <p className="text-gray-400 text-lg">
            Watch 3 AI agents debate your question and reach consensus in real time.
          </p>
        </div>

        <div className="space-y-3">
          <textarea
            className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-white placeholder-gray-500 resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500"
            rows={3}
            placeholder="e.g. Should we rewrite this service in Rust?"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            disabled={loading}
          />
          <button
            onClick={runDemo}
            disabled={loading || !topic.trim()}
            className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-xl transition-colors"
          >
            {loading ? 'Agents are debating...' : 'Start Debate'}
          </button>
        </div>

        {error && (
          <div className="bg-red-900/40 border border-red-700 rounded-xl px-4 py-3 text-red-300">
            {error}
          </div>
        )}

        {result && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-400">Consensus</span>
              <span className={`font-semibold ${result.consensus_reached ? 'text-green-400' : 'text-yellow-400'}`}>
                {result.consensus_reached ? 'Reached' : 'Not reached'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-400">Confidence</span>
              <span className="font-mono">{(result.confidence * 100).toFixed(0)}%</span>
            </div>
            {result.verdict && (
              <div className="border-t border-gray-800 pt-4">
                <p className="text-sm text-gray-400 mb-1">Verdict</p>
                <p className="text-white">{result.verdict}</p>
              </div>
            )}
            <div className="flex items-center justify-between text-xs text-gray-500">
              <span>{result.participants?.length ?? 0} agents</span>
              {result.receipt_hash && (
                <span className="font-mono">#{result.receipt_hash.slice(0, 12)}</span>
              )}
            </div>
            <div className="border-t border-gray-800 pt-4 text-center">
              <a
                href="/signup"
                className="text-indigo-400 hover:text-indigo-300 text-sm font-medium"
              >
                Save debates and get full receipts — sign up free →
              </a>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
