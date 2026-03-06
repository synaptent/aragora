'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { PlaygroundDebate } from '@/components/playground/PlaygroundDebate';
import { PostDebatePrompt } from '@/components/playground/PostDebatePrompt';
import { EndpointSelector, ENDPOINTS } from '@/components/playground/EndpointSelector';
import type { Endpoint } from '@/components/playground/EndpointSelector';
import { RequestBuilder } from '@/components/playground/RequestBuilder';
import { ResponseViewer } from '@/components/playground/ResponseViewer';
import { WebSocketViewer } from '@/components/playground/WebSocketViewer';

type Tab = 'debate' | 'api' | 'websocket';

interface ResponseState {
  status: number | null;
  data: unknown;
  error: string | null;
  duration: number;
  headers: Record<string, string>;
}

export default function PlaygroundPage() {
  const [tab, setTab] = useState<Tab>('debate');
  const [selectedEndpoint, setSelectedEndpoint] = useState<Endpoint>(ENDPOINTS[0]);
  const [response, setResponse] = useState<ResponseState>({
    status: null,
    data: null,
    error: null,
    duration: 0,
    headers: {},
  });

  // Post-debate conversion prompt state
  const [debateComplete, setDebateComplete] = useState(false);
  const [completedDebateId, setCompletedDebateId] = useState('');
  const [completedShareUrl, setCompletedShareUrl] = useState('');

  const handleDebateComplete = useCallback(
    (info: { debateId: string; shareUrl: string }) => {
      setCompletedDebateId(info.debateId);
      setCompletedShareUrl(info.shareUrl);
      setDebateComplete(true);
    },
    [],
  );

  const handleResponse = useCallback((res: ResponseState) => {
    setResponse(res);
  }, []);

  return (
    <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] flex flex-col">
      {/* Nav */}
      <nav className="border-b border-[var(--border)] bg-[var(--surface)]/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link
            href="/landing"
            className="font-mono text-[var(--acid-green)] font-bold text-sm tracking-wider"
          >
            ARAGORA
          </Link>
          <div className="flex items-center gap-1">
            {(['debate', 'api', 'websocket'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-1.5 text-xs font-mono font-bold transition-colors ${
                  tab === t
                    ? 'bg-[var(--acid-green)] text-[var(--bg)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--acid-green)]'
                }`}
              >
                {t === 'debate' ? 'DEBATE DEMO' : t === 'api' ? 'REST API' : 'WEBSOCKET'}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="/docs"
              className="text-xs font-mono text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
            >
              API DOCS
            </Link>
            <Link
              href="/signup"
              className="text-xs font-mono px-3 py-1.5 bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors font-bold"
            >
              SIGN UP FREE
            </Link>
          </div>
        </div>
      </nav>

      {/* Debate Demo Tab */}
      {tab === 'debate' && (
        <>
          <section className="py-12 sm:py-16 px-4">
            <div className="max-w-3xl mx-auto text-center mb-10">
              <h1 className="font-mono text-2xl sm:text-3xl text-[var(--text)] mb-4 leading-tight">
                See a debate in action.{' '}
                <span className="text-[var(--acid-green)]">No signup required.</span>
              </h1>
              <p className="font-mono text-sm text-[var(--text-muted)] max-w-xl mx-auto leading-relaxed">
                Watch 3 AI agents argue an architecture decision, critique each other, vote, and
                produce an audit-ready decision receipt.
              </p>
            </div>
            <PlaygroundDebate onDebateComplete={handleDebateComplete} />
            <div style={{ marginTop: '32px' }}>
              <PostDebatePrompt
                debateId={completedDebateId}
                shareUrl={completedShareUrl}
                visible={debateComplete}
              />
            </div>
          </section>

          <section className="py-12 px-4 border-t border-[var(--border)]">
            <div className="max-w-3xl mx-auto">
              <h2 className="font-mono text-lg text-center text-[var(--acid-green)] mb-8">
                {'>'} WHY DEBATE BEATS A SINGLE LLM
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {[
                  {
                    title: 'ADVERSARIAL',
                    desc: "Agents are structurally incentivized to find flaws in each other's reasoning.",
                  },
                  {
                    title: 'MULTI-MODEL',
                    desc: 'Claude, GPT, Gemini, Mistral -- diverse architectures reduce shared blind spots.',
                  },
                  {
                    title: 'AUDITABLE',
                    desc: 'Every claim is linked to evidence. Dissenting views are preserved, never hidden.',
                  },
                ].map((item) => (
                  <div
                    key={item.title}
                    className="border border-[var(--acid-green)]/30 bg-[var(--surface)]/30 p-5"
                  >
                    <h3 className="font-mono text-sm text-[var(--acid-green)] mb-2">
                      {item.title}
                    </h3>
                    <p className="font-mono text-xs text-[var(--text-muted)] leading-relaxed">
                      {item.desc}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="py-16 px-4 border-t border-[var(--acid-green)]/30 bg-[var(--surface)]/30">
            <div className="max-w-2xl mx-auto text-center space-y-6">
              <h2 className="font-mono text-xl text-[var(--text)]">
                Ready to vet your own decisions?
              </h2>
              <p className="font-mono text-sm text-[var(--text-muted)]">
                Free tier includes 10 debates/month with real AI models.
              </p>
              <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                <Link
                  href="/signup"
                  className="px-8 py-3 font-mono text-sm font-bold bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors"
                >
                  CREATE FREE ACCOUNT
                </Link>
                <Link
                  href="/landing"
                  className="px-8 py-3 font-mono text-sm border border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--acid-green)] hover:text-[var(--acid-green)] transition-colors"
                >
                  BACK TO HOME
                </Link>
              </div>
            </div>
          </section>
        </>
      )}

      {/* REST API Tab */}
      {tab === 'api' && (
        <div className="flex flex-1 overflow-hidden" style={{ height: 'calc(100vh - 49px)' }}>
          {/* Left: Endpoint selector */}
          <div className="w-64 border-r border-[var(--border)] shrink-0">
            <EndpointSelector selected={selectedEndpoint} onSelect={setSelectedEndpoint} />
          </div>

          {/* Right: Request + Response split */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Top: Request builder */}
            <div className="border-b border-[var(--border)] overflow-y-auto max-h-[50%]">
              <RequestBuilder endpoint={selectedEndpoint} onResponse={handleResponse} />
            </div>

            {/* Bottom: Response viewer */}
            <div className="flex-1 overflow-hidden">
              <ResponseViewer {...response} />
            </div>
          </div>
        </div>
      )}

      {/* WebSocket Tab */}
      {tab === 'websocket' && (
        <div className="flex-1" style={{ height: 'calc(100vh - 49px)' }}>
          <WebSocketViewer />
        </div>
      )}
    </main>
  );
}
