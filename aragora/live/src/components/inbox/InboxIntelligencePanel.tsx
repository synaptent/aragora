'use client';

import { useState, useEffect, useCallback } from 'react';

interface SpamAnalysis {
  email_id: string;
  is_spam: boolean;
  spam_score: number;
  risk_level: 'safe' | 'low' | 'medium' | 'high' | 'critical';
  category: string;
  confidence: number;
  signals: Array<{ name: string; score: number; weight: number; details: string }>;
  reasons: string[];
}

interface PhishingAnalysis {
  email_id: string;
  is_phishing: boolean;
  phishing_score: number;
  confidence: number;
  indicators: string[];
  targeted_brand: string | null;
  credential_harvesting_detected: boolean;
  login_page_mimicry: boolean;
}

interface EmailThread {
  thread_id: string;
  subject: string;
  participants: string[];
  message_count: number;
  unread_count: number;
  first_message_date: string;
  last_message_date: string;
  labels: string[];
}

interface ThreadSummary {
  thread_id: string;
  summary: string;
  key_points: string[];
  action_items: string[];
  sentiment: string;
  urgency: string;
}

interface InboxIntelligencePanelProps {
  apiBase: string;
}

type TabType = 'spam' | 'phishing' | 'threads' | 'summary';

export function InboxIntelligencePanel({ apiBase }: InboxIntelligencePanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState<TabType>('spam');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Test email input
  const [testEmail, setTestEmail] = useState({ sender: '', subject: '', body: '' });

  // Results
  const [spamResult, setSpamResult] = useState<SpamAnalysis | null>(null);
  const [phishingResult, setPhishingResult] = useState<PhishingAnalysis | null>(null);
  const [threads, setThreads] = useState<EmailThread[]>([]);
  const [selectedThread, setSelectedThread] = useState<EmailThread | null>(null);
  const [threadSummary, setThreadSummary] = useState<ThreadSummary | null>(null);

  const analyzeSpam = useCallback(async () => {
    if (!testEmail.sender || !testEmail.subject) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/inbox/analyze-spam`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email_id: `test-${Date.now()}`,
          sender: testEmail.sender,
          subject: testEmail.subject,
          body_text: testEmail.body,
        }),
      });
      if (!response.ok) throw new Error('Spam analysis failed');
      const data = await response.json();
      setSpamResult(data.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }, [apiBase, testEmail]);

  const analyzePhishing = useCallback(async () => {
    if (!testEmail.sender || !testEmail.subject) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/inbox/analyze-phishing`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email_id: `test-${Date.now()}`,
          sender: testEmail.sender,
          subject: testEmail.subject,
          body_text: testEmail.body,
        }),
      });
      if (!response.ok) throw new Error('Phishing analysis failed');
      const data = await response.json();
      setPhishingResult(data.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }, [apiBase, testEmail]);

  const fetchThreads = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/inbox/threads?limit=10`);
      if (!response.ok) throw new Error('Failed to fetch threads');
      const data = await response.json();
      setThreads(data.threads || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch threads');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  const fetchThreadSummary = useCallback(
    async (threadId: string) => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${apiBase}/api/inbox/threads/${threadId}/summary`);
        if (!response.ok) throw new Error('Failed to fetch summary');
        const data = await response.json();
        setThreadSummary(data.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch summary');
      } finally {
        setLoading(false);
      }
    },
    [apiBase],
  );

  useEffect(() => {
    if (expanded && activeTab === 'threads') {
      fetchThreads();
    }
  }, [expanded, activeTab, fetchThreads]);

  const getRiskColor = (level: SpamAnalysis['risk_level']) => {
    switch (level) {
      case 'critical':
        return 'text-red-500 border-red-500/50 bg-red-500/10';
      case 'high':
        return 'text-orange-500 border-orange-500/50 bg-orange-500/10';
      case 'medium':
        return 'text-yellow-500 border-yellow-500/50 bg-yellow-500/10';
      case 'low':
        return 'text-blue-400 border-blue-400/50 bg-blue-400/10';
      case 'safe':
        return 'text-[var(--accent)] border-[var(--accent)]/50 bg-[var(--accent)]/10';
      default:
        return 'text-text-muted';
    }
  };

  const getUrgencyColor = (urgency: string) => {
    switch (urgency) {
      case 'urgent':
        return 'text-red-500';
      case 'high':
        return 'text-orange-500';
      case 'normal':
        return 'text-text-muted';
      case 'low':
        return 'text-[var(--accent)]';
      default:
        return 'text-text-muted';
    }
  };

  return (
    <div className="panel" style={{ padding: 0 }}>
      {/* Header */}
      <button onClick={() => setExpanded(!expanded)} className="panel-collapsible-header w-full">
        <div className="flex items-center gap-2">
          <span className="text-purple-400 font-theme-data text-sm">[INBOX INTEL]</span>
          <span className="text-text-muted text-xs">Spam detection & threading</span>
        </div>
        <span className="panel-toggle">{expanded ? '[-]' : '[+]'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {/* Tabs */}
          <div className="flex flex-wrap gap-1 border-b border-purple-400/20 pb-2">
            {(['spam', 'phishing', 'threads', 'summary'] as TabType[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-2 py-1 text-xs font-theme-data transition-colors whitespace-nowrap ${
                  activeTab === tab
                    ? 'bg-purple-400 text-bg'
                    : 'text-text-muted hover:text-purple-400'
                }`}
              >
                {tab.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Test Email Input (for spam/phishing tabs) */}
          {(activeTab === 'spam' || activeTab === 'phishing') && (
            <div className="space-y-2">
              <input
                type="text"
                placeholder="Sender email..."
                value={testEmail.sender}
                onChange={(e) => setTestEmail({ ...testEmail, sender: e.target.value })}
                className="w-full bg-bg border border-purple-400/30 px-2 py-1 text-xs font-theme-data text-text focus:border-purple-400 focus:outline-none"
              />
              <input
                type="text"
                placeholder="Subject line..."
                value={testEmail.subject}
                onChange={(e) => setTestEmail({ ...testEmail, subject: e.target.value })}
                className="w-full bg-bg border border-purple-400/30 px-2 py-1 text-xs font-theme-data text-text focus:border-purple-400 focus:outline-none"
              />
              <textarea
                placeholder="Email body (optional)..."
                value={testEmail.body}
                onChange={(e) => setTestEmail({ ...testEmail, body: e.target.value })}
                rows={3}
                className="w-full bg-bg border border-purple-400/30 px-2 py-1 text-xs font-theme-data text-text focus:border-purple-400 focus:outline-none resize-none"
              />
              <button
                onClick={activeTab === 'spam' ? analyzeSpam : analyzePhishing}
                disabled={!testEmail.sender || !testEmail.subject || loading}
                className="w-full px-3 py-1 bg-purple-400/20 text-purple-400 text-xs font-theme-data hover:bg-purple-400/30 disabled:opacity-50"
              >
                {loading ? 'ANALYZING...' : `ANALYZE ${activeTab.toUpperCase()}`}
              </button>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="text-warning text-xs text-center py-2 border border-warning/30 bg-warning/5">
              {error}
            </div>
          )}

          {/* Content */}
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {activeTab === 'spam' && spamResult && (
              <div className="space-y-3">
                {/* Verdict */}
                <div
                  className={`border p-3 text-center ${
                    spamResult.is_spam
                      ? 'border-red-500/50 bg-red-500/10'
                      : 'border-[var(--accent)]/50 bg-[var(--accent)]/10'
                  }`}
                >
                  <div
                    className={`text-2xl font-theme-data font-bold ${
                      spamResult.is_spam ? 'text-red-500' : 'text-[var(--accent)]'
                    }`}
                  >
                    {spamResult.is_spam ? 'SPAM DETECTED' : 'LIKELY SAFE'}
                  </div>
                  <div className="text-text-muted text-xs mt-1">
                    Score: {(spamResult.spam_score * 100).toFixed(0)}% | Confidence:{' '}
                    {(spamResult.confidence * 100).toFixed(0)}%
                  </div>
                </div>

                {/* Risk Level & Category */}
                <div className="flex gap-2">
                  <div
                    className={`flex-1 border p-2 text-center ${getRiskColor(spamResult.risk_level)}`}
                  >
                    <div className="text-[10px] text-text-muted uppercase">Risk Level</div>
                    <div className="font-theme-data uppercase">{spamResult.risk_level}</div>
                  </div>
                  <div className="flex-1 border border-text-muted/30 bg-surface p-2 text-center">
                    <div className="text-[10px] text-text-muted uppercase">Category</div>
                    <div className="font-theme-data text-purple-400">{spamResult.category}</div>
                  </div>
                </div>

                {/* Signals */}
                {spamResult.signals.length > 0 && (
                  <div className="border border-text-muted/20 bg-surface p-2 text-xs">
                    <div className="text-text-muted mb-2">Detection Signals</div>
                    <div className="space-y-1">
                      {spamResult.signals.map((signal, i) => (
                        <div key={i} className="flex items-center gap-2">
                          <div className="flex-1 font-theme-data text-[10px]">{signal.name}</div>
                          <div className="w-20 h-1.5 bg-bg rounded-full overflow-hidden">
                            <div
                              className={`h-full ${signal.score > 0.7 ? 'bg-red-500' : signal.score > 0.4 ? 'bg-yellow-500' : 'bg-[var(--accent)]'}`}
                              style={{ width: `${signal.score * 100}%` }}
                            />
                          </div>
                          <div className="w-8 text-right text-text-muted">
                            {(signal.score * 100).toFixed(0)}%
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Reasons */}
                {spamResult.reasons.length > 0 && (
                  <div className="border border-warning/30 bg-warning/5 p-2 text-xs">
                    <div className="text-warning mb-1">Detected Patterns</div>
                    {spamResult.reasons.map((reason, i) => (
                      <div key={i} className="text-text-muted">
                        • {reason}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTab === 'phishing' && phishingResult && (
              <div className="space-y-3">
                {/* Verdict */}
                <div
                  className={`border p-3 text-center ${
                    phishingResult.is_phishing
                      ? 'border-red-500/50 bg-red-500/10'
                      : 'border-[var(--accent)]/50 bg-[var(--accent)]/10'
                  }`}
                >
                  <div
                    className={`text-2xl font-theme-data font-bold ${
                      phishingResult.is_phishing ? 'text-red-500' : 'text-[var(--accent)]'
                    }`}
                  >
                    {phishingResult.is_phishing ? 'PHISHING DETECTED' : 'NOT PHISHING'}
                  </div>
                  <div className="text-text-muted text-xs mt-1">
                    Score: {(phishingResult.phishing_score * 100).toFixed(0)}% | Confidence:{' '}
                    {(phishingResult.confidence * 100).toFixed(0)}%
                  </div>
                </div>

                {/* Threat Indicators */}
                <div className="grid grid-cols-2 gap-2">
                  <div
                    className={`border p-2 text-center ${
                      phishingResult.credential_harvesting_detected
                        ? 'border-red-500/50 bg-red-500/10 text-red-500'
                        : 'border-[var(--accent)]/50 bg-[var(--accent)]/10 text-[var(--accent)]'
                    }`}
                  >
                    <div className="text-[10px] uppercase">Credential Harvesting</div>
                    <div className="font-theme-data">
                      {phishingResult.credential_harvesting_detected ? 'DETECTED' : 'CLEAR'}
                    </div>
                  </div>
                  <div
                    className={`border p-2 text-center ${
                      phishingResult.login_page_mimicry
                        ? 'border-red-500/50 bg-red-500/10 text-red-500'
                        : 'border-[var(--accent)]/50 bg-[var(--accent)]/10 text-[var(--accent)]'
                    }`}
                  >
                    <div className="text-[10px] uppercase">Login Mimicry</div>
                    <div className="font-theme-data">
                      {phishingResult.login_page_mimicry ? 'DETECTED' : 'CLEAR'}
                    </div>
                  </div>
                </div>

                {/* Targeted Brand */}
                {phishingResult.targeted_brand && (
                  <div className="border border-warning/50 bg-warning/10 p-2 text-xs">
                    <div className="text-warning">Impersonating Brand</div>
                    <div className="font-theme-data text-warning text-lg uppercase">
                      {phishingResult.targeted_brand}
                    </div>
                  </div>
                )}

                {/* Indicators */}
                {phishingResult.indicators.length > 0 && (
                  <div className="border border-text-muted/20 bg-surface p-2 text-xs">
                    <div className="text-text-muted mb-1">Phishing Indicators</div>
                    {phishingResult.indicators.map((indicator, i) => (
                      <div key={i} className="text-warning/80">
                        • {indicator}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTab === 'threads' &&
              (threads.length > 0 ? (
                <div className="space-y-1">
                  {threads.map((thread) => (
                    <button
                      key={thread.thread_id}
                      onClick={() => {
                        setSelectedThread(thread);
                        setActiveTab('summary');
                        fetchThreadSummary(thread.thread_id);
                      }}
                      className="w-full border border-purple-400/30 bg-surface p-2 text-xs text-left hover:border-purple-400/60 transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-theme-data text-purple-400 truncate max-w-[70%]">
                          {thread.subject}
                        </span>
                        <span className="text-text-muted">{thread.message_count} msgs</span>
                      </div>
                      <div className="flex items-center justify-between mt-1 text-text-muted/60">
                        <span className="truncate max-w-[60%]">
                          {thread.participants.slice(0, 2).join(', ')}
                          {thread.participants.length > 2 ? '...' : ''}
                        </span>
                        {thread.unread_count > 0 && (
                          <span className="bg-purple-400 text-bg text-[10px] px-1 rounded">
                            {thread.unread_count} new
                          </span>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="text-text-muted text-xs text-center py-4">
                  {loading ? 'Loading threads...' : 'No threads available'}
                </div>
              ))}

            {activeTab === 'summary' &&
              (threadSummary ? (
                <div className="space-y-3">
                  {/* Thread Header */}
                  {selectedThread && (
                    <div className="border border-purple-400/30 bg-purple-400/10 p-2 text-xs">
                      <div className="font-theme-data text-purple-400">
                        {selectedThread.subject}
                      </div>
                      <div className="text-text-muted mt-1">
                        {selectedThread.message_count} messages |{' '}
                        {selectedThread.participants.length} participants
                      </div>
                    </div>
                  )}

                  {/* Summary */}
                  <div className="border border-text-muted/20 bg-surface p-2 text-xs">
                    <div className="text-text-muted mb-1">Summary</div>
                    <div className="text-text">{threadSummary.summary}</div>
                  </div>

                  {/* Urgency & Sentiment */}
                  <div className="flex gap-2">
                    <div
                      className={`flex-1 border border-text-muted/20 bg-surface p-2 text-center ${getUrgencyColor(threadSummary.urgency)}`}
                    >
                      <div className="text-[10px] text-text-muted uppercase">Urgency</div>
                      <div className="font-theme-data uppercase">{threadSummary.urgency}</div>
                    </div>
                    <div className="flex-1 border border-text-muted/20 bg-surface p-2 text-center">
                      <div className="text-[10px] text-text-muted uppercase">Sentiment</div>
                      <div className="font-theme-data text-purple-400">
                        {threadSummary.sentiment}
                      </div>
                    </div>
                  </div>

                  {/* Key Points */}
                  {threadSummary.key_points.length > 0 && (
                    <div className="border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 p-2 text-xs">
                      <div className="text-[var(--acid-cyan)] mb-1">Key Points</div>
                      {threadSummary.key_points.map((point, i) => (
                        <div key={i} className="text-text-muted">
                          • {point}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Action Items */}
                  {threadSummary.action_items.length > 0 && (
                    <div className="border border-warning/30 bg-warning/5 p-2 text-xs">
                      <div className="text-warning mb-1">Action Items</div>
                      {threadSummary.action_items.map((item, i) => (
                        <div key={i} className="text-text-muted flex items-start gap-1">
                          <span className="text-warning">□</span>
                          <span>{item}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Back Button */}
                  <button
                    onClick={() => setActiveTab('threads')}
                    className="w-full text-xs text-text-muted hover:text-purple-400 py-1"
                  >
                    ← Back to threads
                  </button>
                </div>
              ) : selectedThread ? (
                <div className="text-text-muted text-xs text-center py-4 animate-pulse">
                  Generating summary...
                </div>
              ) : (
                <div className="text-text-muted text-xs text-center py-4">
                  Select a thread to view summary
                </div>
              ))}

            {/* Initial states */}
            {activeTab === 'spam' && !spamResult && !loading && (
              <div className="text-text-muted text-xs text-center py-4">
                Enter email details above to analyze for spam
              </div>
            )}
            {activeTab === 'phishing' && !phishingResult && !loading && (
              <div className="text-text-muted text-xs text-center py-4">
                Enter email details above to check for phishing
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
