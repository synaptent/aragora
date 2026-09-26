'use client';

import { useState, useCallback } from 'react';

interface MultiAgentAnalysisProps {
  apiBase: string;
  userId: string;
  authToken?: string;
  email: {
    id: string;
    subject: string;
    body?: string;
    from_address: string;
    snippet?: string;
    date: string;
  };
  onComplete?: (result: DebateResult) => void;
}

interface DebateResult {
  message_id: string;
  priority: string;
  category: string;
  confidence: number;
  reasoning: string;
  action_items: string[];
  suggested_labels: string[];
  is_spam: boolean;
  is_phishing: boolean;
  sender_reputation: number | null;
  debate_id: string | null;
  duration_seconds: number;
}

export function MultiAgentAnalysis({
  apiBase,
  userId,
  authToken,
  email,
  onComplete,
}: MultiAgentAnalysisProps) {
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [result, setResult] = useState<DebateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<'fast' | 'thorough'>('fast');

  const runAnalysis = useCallback(async () => {
    setIsAnalyzing(true);
    setError(null);

    try {
      const response = await fetch(`${apiBase}/api/v1/email/prioritize`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          subject: email.subject,
          body: email.body || email.snippet || '',
          sender: email.from_address,
          received_at: email.date,
          message_id: email.id,
          user_id: userId,
          fast_mode: mode === 'fast',
          enable_pii_redaction: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`Analysis failed: ${response.statusText}`);
      }

      const data: DebateResult = await response.json();
      setResult(data);
      onComplete?.(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setIsAnalyzing(false);
    }
  }, [apiBase, authToken, email, userId, mode, onComplete]);

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'urgent':
        return 'text-red-400 border-red-500/40 bg-red-500/10';
      case 'high':
        return 'text-orange-400 border-orange-500/40 bg-orange-500/10';
      case 'normal':
        return 'text-yellow-400 border-yellow-500/40 bg-yellow-500/10';
      case 'low':
        return 'text-blue-400 border-blue-500/40 bg-blue-500/10';
      case 'spam':
        return 'text-gray-400 border-gray-500/40 bg-gray-500/10';
      default:
        return 'text-gray-400 border-gray-500/40 bg-gray-500/10';
    }
  };

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'action_required':
        return '!';
      case 'reply_needed':
        return 'R';
      case 'fyi':
        return 'i';
      case 'meeting':
        return 'M';
      case 'newsletter':
        return 'N';
      case 'promotional':
        return 'P';
      case 'social':
        return 'S';
      case 'spam':
        return 'X';
      case 'phishing':
        return '!X';
      default:
        return '?';
    }
  };

  return (
    <div className="border border-[var(--acid-cyan)]/30 bg-surface/50 rounded p-3 mt-3">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[var(--acid-cyan)] font-theme-data text-xs">Multi-Agent Analysis</h4>
        {!result && !isAnalyzing && (
          <div className="flex items-center gap-2">
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as 'fast' | 'thorough')}
              className="px-2 py-1 text-xs font-theme-data bg-bg border border-[var(--acid-cyan)]/30 text-text rounded"
            >
              <option value="fast">Fast (2 rounds)</option>
              <option value="thorough">Thorough (5 rounds)</option>
            </select>
            <button
              onClick={runAnalysis}
              className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/40 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/20 rounded"
            >
              Analyze
            </button>
          </div>
        )}
      </div>

      {isAnalyzing && (
        <div className="text-center py-4">
          <div className="animate-pulse text-[var(--acid-cyan)] text-sm font-theme-data mb-2">
            Running multi-agent debate...
          </div>
          <div className="text-text-muted text-xs">
            {mode === 'fast' ? '2 agents, 2 rounds' : '2 agents, 5 rounds'}
          </div>
        </div>
      )}

      {error && (
        <div className="text-red-400 text-xs font-theme-data py-2">
          {error}
          <button onClick={runAnalysis} className="ml-2 underline hover:no-underline">
            Retry
          </button>
        </div>
      )}

      {result && (
        <div className="space-y-3">
          {/* Priority & Category */}
          <div className="flex items-center gap-3">
            <span
              className={`px-2 py-1 text-xs font-theme-data rounded ${getPriorityColor(result.priority)}`}
            >
              {result.priority.toUpperCase()}
            </span>
            <span className="px-2 py-1 text-xs font-theme-data bg-purple-500/10 border border-purple-500/30 text-purple-400 rounded">
              {getCategoryIcon(result.category)} {result.category.replace('_', ' ')}
            </span>
            <span className="text-xs text-text-muted font-theme-data">
              {Math.round(result.confidence * 100)}% confidence
            </span>
          </div>

          {/* Reasoning */}
          <div>
            <span className="text-[var(--acid-cyan)] text-xs font-theme-data">Reasoning:</span>
            <p className="text-text-muted text-xs mt-1">{result.reasoning}</p>
          </div>

          {/* Action Items */}
          {result.action_items.length > 0 && (
            <div>
              <span className="text-[var(--acid-cyan)] text-xs font-theme-data">Action Items:</span>
              <ul className="mt-1 space-y-1">
                {result.action_items.map((item, i) => (
                  <li key={i} className="text-text-muted text-xs flex items-start gap-1">
                    <span className="text-[var(--accent)]">-</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Suggested Labels */}
          {result.suggested_labels.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[var(--acid-cyan)] text-xs font-theme-data">Labels:</span>
              {result.suggested_labels.map((label) => (
                <span
                  key={label}
                  className="px-1.5 py-0.5 text-xs bg-[var(--accent)]/10 border border-[var(--accent)]/20 text-[var(--accent)] rounded"
                >
                  {label}
                </span>
              ))}
            </div>
          )}

          {/* Security Indicators */}
          {(result.is_spam || result.is_phishing) && (
            <div className="flex items-center gap-2">
              {result.is_spam && (
                <span className="px-2 py-1 text-xs bg-gray-500/10 border border-gray-500/30 text-gray-400 rounded">
                  Spam Detected
                </span>
              )}
              {result.is_phishing && (
                <span className="px-2 py-1 text-xs bg-red-500/10 border border-red-500/30 text-red-400 rounded">
                  Phishing Warning
                </span>
              )}
            </div>
          )}

          {/* Meta Info */}
          <div className="text-text-muted text-xs font-theme-data pt-2 border-t border-[var(--acid-cyan)]/20">
            <span>Analysis took {result.duration_seconds.toFixed(2)}s</span>
            {result.sender_reputation !== null && (
              <span className="ml-4">
                Sender reputation: {Math.round(result.sender_reputation * 100)}%
              </span>
            )}
            {result.debate_id && (
              <span className="ml-4">Debate ID: {result.debate_id.slice(0, 8)}...</span>
            )}
          </div>

          {/* Re-analyze button */}
          <button
            onClick={() => {
              setResult(null);
              runAnalysis();
            }}
            className="text-xs text-[var(--acid-cyan)]/70 hover:text-[var(--acid-cyan)] underline"
          >
            Re-analyze
          </button>
        </div>
      )}
    </div>
  );
}
