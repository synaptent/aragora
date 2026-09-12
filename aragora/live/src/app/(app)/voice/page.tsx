'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { VoiceInput } from '@/components/ui/VoiceInput';
import { API_BASE_URL, DEFAULT_AGENTS } from '@/config';
import { usePWA } from '@/hooks/usePWA';

type VoiceState = 'idle' | 'listening' | 'processing' | 'confirming' | 'starting';

export default function VoicePage() {
  const router = useRouter();
  const { isInstallable, isOffline, promptInstall } = usePWA();
  const [state, setState] = useState<VoiceState>('idle');
  const [transcript, setTranscript] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [recentTopics, setRecentTopics] = useState<string[]>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('aragora-recent-voice-topics');
      return saved ? JSON.parse(saved) : [];
    }
    return [];
  });

  const handleTranscript = useCallback((text: string) => {
    setTranscript(text);
    setState('confirming');
  }, []);

  const handleRecordingStart = useCallback(() => {
    setState('listening');
    setError(null);
  }, []);

  const handleRecordingStop = useCallback(() => {
    setState('processing');
  }, []);

  const handleError = useCallback((err: string) => {
    setError(err);
    setState('idle');
  }, []);

  const startDebate = useCallback(
    async (topic: string) => {
      if (!topic.trim()) return;

      setState('starting');
      setError(null);

      try {
        const response = await fetch(`${API_BASE_URL}/api/debate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question: topic,
            agents: DEFAULT_AGENTS,
            rounds: 3,
            metadata: { source: 'voice', platform: 'mobile' },
          }),
        });

        const data = await response.json();

        if (data.success && data.debate_id) {
          // Save to recent topics
          const newRecent = [topic, ...recentTopics.filter((t) => t !== topic)].slice(0, 5);
          setRecentTopics(newRecent);
          localStorage.setItem('aragora-recent-voice-topics', JSON.stringify(newRecent));

          // Navigate to debate
          router.push(`/debate/${data.debate_id}`);
        } else {
          setError(data.error || 'Failed to start debate');
          setState('confirming');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to start debate');
        setState('confirming');
      }
    },
    [recentTopics, router],
  );

  const editTopic = useCallback(() => {
    setState('idle');
  }, []);

  const clearRecent = useCallback(() => {
    setRecentTopics([]);
    localStorage.removeItem('aragora-recent-voice-topics');
  }, []);

  return (
    <main className="min-h-screen bg-bg flex flex-col">
      {/* Header */}
      <header className="border-b border-border p-4">
        <div className="flex items-center justify-between">
          <Link href="/" className="text-[var(--accent)] font-theme-data font-bold">
            ARAGORA
          </Link>
          <Link href="/arena" className="text-xs font-theme-data text-text-muted hover:text-text">
            [TYPE INSTEAD]
          </Link>
        </div>
      </header>

      {/* Offline Indicator */}
      {isOffline && (
        <div className="bg-warning/20 border-b border-warning/30 px-4 py-2 text-center">
          <span className="text-warning text-sm font-theme-data">
            You&apos;re offline - Some features may be limited
          </span>
        </div>
      )}

      {/* Install Prompt */}
      {isInstallable && (
        <div className="bg-[var(--accent)]/10 border-b border-[var(--accent)]/30 px-4 py-2">
          <div className="flex items-center justify-between max-w-md mx-auto">
            <span className="text-sm text-text-muted">Install app for quick access</span>
            <button
              onClick={promptInstall}
              className="px-3 py-1 bg-[var(--accent)] text-bg text-xs font-theme-data font-bold rounded hover:bg-[var(--accent)]/80"
            >
              Install
            </button>
          </div>
        </div>
      )}

      {/* Main Content */}
      <div className="flex-1 flex flex-col items-center justify-center p-6">
        {/* Error Display */}
        {error && (
          <div className="w-full max-w-md mb-6 p-3 bg-warning/10 border border-warning/30 rounded-lg text-warning text-sm text-center">
            {error}
          </div>
        )}

        {/* Idle State - Ready to record */}
        {state === 'idle' && (
          <div className="text-center space-y-8">
            <div>
              <h1 className="text-2xl font-theme-data font-bold text-text mb-2">Voice Debate</h1>
              <p className="text-text-muted text-sm">Tap the microphone and speak your topic</p>
            </div>

            <VoiceInput
              onTranscript={handleTranscript}
              onRecordingStart={handleRecordingStart}
              onRecordingStop={handleRecordingStop}
              onError={handleError}
              className="mx-auto"
              showWaveform={true}
            />

            <p className="text-xs text-text-muted max-w-xs mx-auto">
              Example: &quot;Should companies adopt four-day work weeks?&quot;
            </p>

            {/* Recent Topics */}
            {recentTopics.length > 0 && (
              <div className="mt-8 w-full max-w-md">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
                    Recent Topics
                  </h3>
                  <button
                    onClick={clearRecent}
                    className="text-xs text-text-muted hover:text-warning"
                  >
                    Clear
                  </button>
                </div>
                <div className="space-y-2">
                  {recentTopics.map((topic, i) => (
                    <button
                      key={i}
                      onClick={() => {
                        setTranscript(topic);
                        setState('confirming');
                      }}
                      className="w-full text-left p-3 bg-surface border border-border rounded-lg text-sm text-text hover:border-[var(--accent)]/50 transition-colors"
                    >
                      {topic}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Listening State */}
        {state === 'listening' && (
          <div className="text-center space-y-6">
            <div className="relative">
              {/* Pulsing rings */}
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-32 h-32 rounded-full bg-[var(--accent)]/20 animate-ping" />
              </div>
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-24 h-24 rounded-full bg-[var(--accent)]/30 animate-pulse" />
              </div>
              <div className="relative z-10 w-20 h-20 mx-auto rounded-full bg-[var(--accent)] flex items-center justify-center">
                <span className="text-3xl">🎤</span>
              </div>
            </div>

            <div>
              <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">
                Listening...
              </h2>
              <p className="text-text-muted text-sm mt-2">Speak your debate topic</p>
            </div>

            <VoiceInput
              onTranscript={handleTranscript}
              onRecordingStart={handleRecordingStart}
              onRecordingStop={handleRecordingStop}
              onError={handleError}
              className="mx-auto"
              showWaveform={true}
            />
          </div>
        )}

        {/* Processing State */}
        {state === 'processing' && (
          <div className="text-center space-y-6">
            <div className="w-16 h-16 mx-auto border-4 border-[var(--accent)]/30 border-t-acid-green rounded-full animate-spin" />
            <h2 className="text-xl font-theme-data font-bold text-text">Transcribing...</h2>
          </div>
        )}

        {/* Confirming State - Show transcript */}
        {state === 'confirming' && transcript && (
          <div className="w-full max-w-md space-y-6">
            <div className="text-center">
              <h2 className="text-lg font-theme-data text-text-muted mb-4">Your topic:</h2>
              <div className="p-4 bg-surface border border-[var(--accent)]/30 rounded-lg">
                <p className="text-lg text-text">{transcript}</p>
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={editTopic}
                className="flex-1 px-4 py-3 bg-surface border border-border text-text font-theme-data hover:border-text-muted transition-colors rounded"
              >
                Try Again
              </button>
              <button
                onClick={() => startDebate(transcript)}
                className="flex-1 px-4 py-3 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors rounded"
              >
                Start Debate
              </button>
            </div>

            {/* Quick Edit */}
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-2">
                Or edit your topic:
              </label>
              <textarea
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
                className="w-full p-3 bg-bg border border-border rounded-lg text-text font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none resize-none"
                rows={2}
              />
            </div>
          </div>
        )}

        {/* Starting State */}
        {state === 'starting' && (
          <div className="text-center space-y-6">
            <div className="w-16 h-16 mx-auto border-4 border-[var(--accent)]/30 border-t-acid-green rounded-full animate-spin" />
            <div>
              <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">
                Starting Debate...
              </h2>
              <p className="text-text-muted text-sm mt-2">Assembling AI agents</p>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <footer className="border-t border-border p-4">
        <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
          <span>Voice-first debate</span>
          <Link href="/transcribe" className="hover:text-[var(--accent)]">
            [TRANSCRIBE FILES]
          </Link>
        </div>
      </footer>
    </main>
  );
}
