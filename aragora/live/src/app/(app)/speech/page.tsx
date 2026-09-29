'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AudioRecorder } from '@/components/AudioRecorder';
import { TranscriptionViewer, TranscriptionResult } from '@/components/TranscriptionViewer';
import { useBackend } from '@/components/BackendSelector';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { logger } from '@/utils/logger';
import { DEFAULT_AGENTS } from '@/config';

type TranscriptionState = 'idle' | 'uploading' | 'transcribing' | 'complete' | 'error';

interface STTProvider {
  name: string;
  display_name: string;
  model: string;
  available: boolean;
  formats: string[];
  max_size_mb: number;
  features: string[];
  is_default: boolean;
}

interface PodcastEpisode {
  debate_id: string;
  task: string;
  agents: string[];
  audio_url: string;
  duration_seconds: number;
  file_size_bytes: number;
  generated_at: string;
}

export default function SpeechPage() {
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [activeTab, setActiveTab] = useState<'transcribe' | 'url' | 'providers' | 'podcasts'>(
    'transcribe',
  );
  const [state, setState] = useState<TranscriptionState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TranscriptionResult | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [audioFile, setAudioFile] = useState<File | Blob | null>(null);
  const [language, setLanguage] = useState<string>('');
  const [prompt, setPrompt] = useState<string>('');
  const [selectedProvider, setSelectedProvider] = useState<string>('');

  // URL transcription state
  const [audioUrl, setAudioUrl] = useState<string>('');
  const [urlTranscribing, setUrlTranscribing] = useState(false);

  // Providers state
  const [providers, setProviders] = useState<STTProvider[]>([]);
  const [providersLoading, setProvidersLoading] = useState(false);

  // Podcast episodes state
  const [episodes, setEpisodes] = useState<PodcastEpisode[]>([]);
  const [episodesLoading, setEpisodesLoading] = useState(false);

  const fetchProviders = useCallback(async () => {
    setProvidersLoading(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/speech/providers`);
      if (res.ok) {
        const data = await res.json();
        setProviders(data.providers || []);
        const defaultProvider = data.providers?.find((p: STTProvider) => p.is_default);
        if (defaultProvider && !selectedProvider) {
          setSelectedProvider(defaultProvider.name);
        }
      }
    } catch (err) {
      logger.error('Failed to fetch providers:', err);
    } finally {
      setProvidersLoading(false);
    }
  }, [backendConfig.api, selectedProvider]);

  const fetchEpisodes = useCallback(async () => {
    setEpisodesLoading(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/podcast/episodes?limit=20`);
      if (res.ok) {
        const data = await res.json();
        setEpisodes(data.episodes || []);
      }
    } catch (err) {
      logger.error('Failed to fetch episodes:', err);
    } finally {
      setEpisodesLoading(false);
    }
  }, [backendConfig.api]);

  // Fetch providers on mount
  useEffect(() => {
    if (activeTab === 'providers' || activeTab === 'transcribe') {
      fetchProviders();
    }
  }, [activeTab, fetchProviders]);

  // Fetch podcast episodes
  useEffect(() => {
    if (activeTab === 'podcasts') {
      fetchEpisodes();
    }
  }, [activeTab, fetchEpisodes]);

  const handleRecordingComplete = useCallback((blob: Blob, _duration: number) => {
    setAudioFile(blob);
    setError(null);
  }, []);

  const handleRecordingError = useCallback((err: string) => {
    setError(err);
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // Validate file type
      const validTypes = [
        'audio/mpeg',
        'audio/mp3',
        'audio/wav',
        'audio/webm',
        'audio/m4a',
        'audio/x-m4a',
        'audio/ogg',
        'audio/flac',
      ];
      if (!validTypes.includes(file.type) && !file.name.match(/\.(mp3|wav|webm|m4a|ogg|flac)$/i)) {
        setError('Unsupported audio format. Please use MP3, WAV, WebM, M4A, OGG, or FLAC.');
        return;
      }

      // Validate file size (25MB max)
      if (file.size > 25 * 1024 * 1024) {
        setError('File too large. Maximum size is 25MB.');
        return;
      }

      setAudioFile(file);
      setError(null);
    }
  }, []);

  // Handle URL transcription
  const handleUrlTranscribe = useCallback(async () => {
    if (!audioUrl.trim()) {
      setError('Please enter an audio URL');
      return;
    }

    setUrlTranscribing(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch(`${backendConfig.api}/api/speech/transcribe-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: audioUrl,
          language: language || undefined,
          prompt: prompt || undefined,
          provider: selectedProvider || undefined,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || `Transcription failed: ${res.status}`);
      }

      setResult(data);
      setState('complete');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'URL transcription failed');
    } finally {
      setUrlTranscribing(false);
    }
  }, [audioUrl, backendConfig.api, language, prompt, selectedProvider]);

  const handleTranscribe = useCallback(async () => {
    if (!audioFile) {
      setError('No audio file selected');
      return;
    }

    setState('uploading');
    setError(null);
    setUploadProgress(0);

    try {
      const formData = new FormData();
      formData.append(
        'file',
        audioFile,
        audioFile instanceof File ? audioFile.name : 'recording.webm',
      );

      // Build query params
      const params = new URLSearchParams();
      if (language) params.append('language', language);
      if (prompt) params.append('prompt', prompt);
      if (selectedProvider) params.append('provider', selectedProvider);
      params.append('timestamps', 'true');

      const url = `${backendConfig.api}/api/speech/transcribe?${params.toString()}`;

      setState('transcribing');

      const response = await fetch(url, { method: 'POST', body: formData });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || `Transcription failed: ${response.status}`);
      }

      setResult(data);
      setState('complete');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Transcription failed');
      setState('error');
    }
  }, [audioFile, backendConfig.api, language, prompt, selectedProvider]);

  const handleCreateDebate = useCallback(
    async (text: string) => {
      try {
        const response = await fetch(`${backendConfig.api}/api/debate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question: text,
            agents: DEFAULT_AGENTS,
            rounds: 3,
            metadata: { source: 'voice_transcription' },
          }),
        });

        const data = await response.json();

        if (data.success && data.debate_id) {
          router.push(`/debate/${data.debate_id}`);
        } else {
          setError(data.error || 'Failed to create debate');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to create debate');
      }
    },
    [backendConfig.api, router],
  );

  const handleReset = useCallback(() => {
    setState('idle');
    setResult(null);
    setAudioFile(null);
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Title */}
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">{'>'} SPEECH</h1>
            <p className="text-text-muted font-theme-data text-sm">
              Transcribe audio to text, browse podcast episodes, and manage speech providers.
            </p>
          </div>

          {/* Tab Navigation */}
          <div className="flex gap-2 mb-6">
            <button
              onClick={() => setActiveTab('transcribe')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'transcribe'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [TRANSCRIBE]
            </button>
            <button
              onClick={() => setActiveTab('url')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'url'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [URL]
            </button>
            <button
              onClick={() => setActiveTab('podcasts')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'podcasts'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [PODCASTS]
            </button>
            <button
              onClick={() => setActiveTab('providers')}
              className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                activeTab === 'providers'
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                  : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
              }`}
            >
              [PROVIDERS]
            </button>
          </div>

          {/* Error Banner */}
          {error && (
            <div className="mb-6 p-3 border border-warning/30 bg-warning/10">
              <div className="flex items-center justify-between">
                <span className="text-warning font-theme-data text-sm">{error}</span>
                <button
                  onClick={() => setError(null)}
                  className="text-warning hover:text-warning/80"
                >
                  ×
                </button>
              </div>
            </div>
          )}

          {/* Transcribe Tab */}
          {activeTab === 'transcribe' && (
            <>
              {state === 'complete' && result ? (
                <div className="space-y-4">
                  <TranscriptionViewer result={result} onCreateDebate={handleCreateDebate} />
                  <div className="flex justify-center">
                    <button
                      onClick={handleReset}
                      className="px-4 py-2 border border-[var(--accent)]/30 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/10 transition-colors"
                    >
                      [TRANSCRIBE ANOTHER]
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-6">
                  {/* Recording Section */}
                  <section className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                    <h2 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                      Record Audio
                    </h2>
                    <AudioRecorder
                      onRecordingComplete={handleRecordingComplete}
                      onError={handleRecordingError}
                      maxDuration={300}
                    />
                  </section>

                  {/* Upload Section */}
                  <section className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                    <h2 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                      Upload Audio File
                    </h2>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".mp3,.wav,.webm,.m4a,.ogg,.flac,audio/*"
                      onChange={handleFileSelect}
                      className="hidden"
                      id="audio-upload"
                    />
                    <label
                      htmlFor="audio-upload"
                      className="block p-6 border-2 border-dashed border-[var(--accent)]/30 hover:border-[var(--accent)]/50 cursor-pointer transition-colors text-center"
                    >
                      <div className="text-[var(--accent)] font-theme-data text-sm mb-2">
                        Click to select audio file
                      </div>
                      <div className="text-text-muted font-theme-data text-xs">
                        MP3, WAV, WebM, M4A, OGG, FLAC (max 25MB)
                      </div>
                    </label>
                  </section>

                  {/* Selected File Display */}
                  {audioFile && (
                    <div className="p-3 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded">
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="text-[var(--acid-cyan)] font-theme-data text-xs">
                            {audioFile instanceof File ? audioFile.name : 'Recording'}
                          </span>
                          <span className="text-text-muted font-theme-data text-xs ml-2">
                            ({(audioFile.size / 1024 / 1024).toFixed(2)} MB)
                          </span>
                        </div>
                        <button
                          onClick={handleReset}
                          className="text-text-muted hover:text-warning font-theme-data text-xs"
                        >
                          [REMOVE]
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Options */}
                  <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                      <label className="block font-theme-data text-xs text-text-muted mb-2">
                        Language
                      </label>
                      <select
                        value={language}
                        onChange={(e) => setLanguage(e.target.value)}
                        className="w-full p-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] rounded"
                      >
                        <option value="">Auto-detect</option>
                        <option value="en">English</option>
                        <option value="es">Spanish</option>
                        <option value="fr">French</option>
                        <option value="de">German</option>
                        <option value="ja">Japanese</option>
                        <option value="zh">Chinese</option>
                      </select>
                    </div>
                    <div>
                      <label className="block font-theme-data text-xs text-text-muted mb-2">
                        Provider
                      </label>
                      <select
                        value={selectedProvider}
                        onChange={(e) => setSelectedProvider(e.target.value)}
                        className="w-full p-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] rounded"
                      >
                        {providers.map((p) => (
                          <option key={p.name} value={p.name} disabled={!p.available}>
                            {p.display_name} {p.is_default ? '(Default)' : ''}{' '}
                            {!p.available ? '(Unavailable)' : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block font-theme-data text-xs text-text-muted mb-2">
                        Prompt (optional)
                      </label>
                      <input
                        type="text"
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        placeholder="Technical terms..."
                        className="w-full p-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] rounded"
                      />
                    </div>
                  </section>

                  {/* Transcribe Button */}
                  <div className="flex justify-center">
                    <button
                      onClick={handleTranscribe}
                      disabled={!audioFile || state === 'uploading' || state === 'transcribing'}
                      className={`px-6 py-3 font-theme-data text-sm transition-colors rounded ${
                        !audioFile || state === 'uploading' || state === 'transcribing'
                          ? 'bg-surface border border-[var(--accent)]/20 text-text-muted cursor-not-allowed'
                          : 'bg-[var(--accent)]/20 border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/30'
                      }`}
                    >
                      {state === 'uploading' && '[UPLOADING...]'}
                      {state === 'transcribing' && '[TRANSCRIBING...]'}
                      {(state === 'idle' || state === 'error') && '[TRANSCRIBE AUDIO]'}
                    </button>
                  </div>

                  {/* Progress */}
                  {(state === 'uploading' || state === 'transcribing') && (
                    <div className="text-center">
                      <div className="h-1 bg-surface rounded overflow-hidden max-w-md mx-auto">
                        <div
                          className="h-full bg-[var(--accent)] transition-all duration-300"
                          style={{
                            width: state === 'uploading' ? `${uploadProgress}%` : '100%',
                            animation: state === 'transcribing' ? 'pulse 1.5s infinite' : 'none',
                          }}
                        />
                      </div>
                      <p className="text-text-muted font-theme-data text-xs mt-2">
                        {state === 'uploading' && 'Uploading...'}
                        {state === 'transcribing' && 'Processing with Whisper...'}
                      </p>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {/* URL Tab */}
          {activeTab === 'url' && (
            <div className="space-y-6">
              <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                <h2 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-4">
                  Transcribe from URL
                </h2>
                <p className="text-text-muted font-theme-data text-xs mb-4">
                  Enter a direct URL to an audio file. Supports MP3, WAV, and other common formats.
                </p>

                <div className="space-y-4">
                  <div>
                    <label className="block font-theme-data text-xs text-text-muted mb-2">
                      Audio URL
                    </label>
                    <input
                      type="url"
                      value={audioUrl}
                      onChange={(e) => setAudioUrl(e.target.value)}
                      placeholder="https://example.com/audio.mp3"
                      className="w-full p-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] rounded"
                    />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block font-theme-data text-xs text-text-muted mb-2">
                        Language
                      </label>
                      <select
                        value={language}
                        onChange={(e) => setLanguage(e.target.value)}
                        className="w-full p-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] rounded"
                      >
                        <option value="">Auto-detect</option>
                        <option value="en">English</option>
                        <option value="es">Spanish</option>
                        <option value="fr">French</option>
                        <option value="de">German</option>
                      </select>
                    </div>
                    <div>
                      <label className="block font-theme-data text-xs text-text-muted mb-2">
                        Provider
                      </label>
                      <select
                        value={selectedProvider}
                        onChange={(e) => setSelectedProvider(e.target.value)}
                        className="w-full p-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] rounded"
                      >
                        {providers.map((p) => (
                          <option key={p.name} value={p.name} disabled={!p.available}>
                            {p.display_name}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="flex justify-center">
                    <button
                      onClick={handleUrlTranscribe}
                      disabled={!audioUrl.trim() || urlTranscribing}
                      className={`px-6 py-3 font-theme-data text-sm transition-colors rounded ${
                        !audioUrl.trim() || urlTranscribing
                          ? 'bg-surface border border-[var(--accent)]/20 text-text-muted cursor-not-allowed'
                          : 'bg-[var(--accent)]/20 border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/30'
                      }`}
                    >
                      {urlTranscribing ? '[TRANSCRIBING...]' : '[TRANSCRIBE URL]'}
                    </button>
                  </div>
                </div>
              </div>

              {result && (
                <div className="space-y-4">
                  <TranscriptionViewer result={result} onCreateDebate={handleCreateDebate} />
                </div>
              )}
            </div>
          )}

          {/* Podcasts Tab */}
          {activeTab === 'podcasts' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="font-theme-data text-text">Generated Podcast Episodes</h2>
                <div className="flex gap-2">
                  <button
                    onClick={fetchEpisodes}
                    disabled={episodesLoading}
                    className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                  >
                    {episodesLoading ? '[LOADING...]' : '[REFRESH]'}
                  </button>
                  <Link
                    href="/api/podcast/feed.xml"
                    target="_blank"
                    className="px-3 py-1 text-xs font-theme-data border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                  >
                    [RSS FEED]
                  </Link>
                </div>
              </div>

              {episodesLoading ? (
                <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
                  Loading episodes...
                </div>
              ) : episodes.length === 0 ? (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="font-theme-data text-text-muted mb-4">
                    No podcast episodes generated yet.
                  </p>
                  <p className="font-theme-data text-xs text-text-muted">
                    Generate podcasts from debates using the broadcast feature.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {episodes.map((episode) => (
                    <div
                      key={episode.debate_id}
                      className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30"
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <h3 className="font-theme-data text-text truncate">{episode.task}</h3>
                          <div className="flex items-center gap-3 text-xs font-theme-data text-text-muted mt-1">
                            <span>
                              {Math.floor(episode.duration_seconds / 60)}:
                              {String(episode.duration_seconds % 60).padStart(2, '0')}
                            </span>
                            <span>|</span>
                            <span>{(episode.file_size_bytes / 1024 / 1024).toFixed(1)} MB</span>
                            <span>|</span>
                            <span>{new Date(episode.generated_at).toLocaleDateString()}</span>
                          </div>
                          <div className="flex gap-1 mt-2">
                            {episode.agents.map((agent) => (
                              <span
                                key={agent}
                                className="px-2 py-0.5 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)]/70 rounded"
                              >
                                {agent}
                              </span>
                            ))}
                          </div>
                        </div>
                        <div className="flex gap-2 flex-shrink-0 ml-4">
                          <a
                            href={episode.audio_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="px-3 py-1 text-xs font-theme-data border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                          >
                            [PLAY]
                          </a>
                          <Link
                            href={`/debate/${episode.debate_id}`}
                            className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors"
                          >
                            [VIEW]
                          </Link>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Providers Tab */}
          {activeTab === 'providers' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h2 className="font-theme-data text-text">Speech-to-Text Providers</h2>
                <button
                  onClick={fetchProviders}
                  disabled={providersLoading}
                  className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                >
                  {providersLoading ? '[LOADING...]' : '[REFRESH]'}
                </button>
              </div>

              {providersLoading ? (
                <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
                  Loading providers...
                </div>
              ) : providers.length === 0 ? (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="font-theme-data text-text-muted">No providers configured.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {providers.map((provider) => (
                    <div
                      key={provider.name}
                      className={`p-4 border rounded bg-surface/30 ${
                        provider.available
                          ? 'border-[var(--accent)]/40'
                          : 'border-[var(--accent)]/20 opacity-60'
                      }`}
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div>
                          <h3 className="font-theme-data text-text">{provider.display_name}</h3>
                          <div className="text-xs font-theme-data text-text-muted">
                            Model: {provider.model}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {provider.is_default && (
                            <span className="px-2 py-0.5 text-xs font-theme-data bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] rounded">
                              DEFAULT
                            </span>
                          )}
                          <span
                            className={`px-2 py-0.5 text-xs font-theme-data rounded ${
                              provider.available
                                ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                                : 'bg-text-muted/20 text-text-muted'
                            }`}
                          >
                            {provider.available ? 'ONLINE' : 'OFFLINE'}
                          </span>
                        </div>
                      </div>

                      <div className="text-xs font-theme-data text-text-muted mb-2">
                        Max file size: {provider.max_size_mb}MB
                      </div>

                      <div className="flex flex-wrap gap-1 mb-3">
                        {provider.features.map((feature) => (
                          <span
                            key={feature}
                            className="px-2 py-0.5 text-xs font-theme-data bg-[var(--accent)]/10 text-[var(--accent)]/70 rounded"
                          >
                            {feature}
                          </span>
                        ))}
                      </div>

                      <div className="text-xs font-theme-data text-text-muted">
                        Formats: {provider.formats.join(', ')}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Environment Setup */}
              <div className="p-4 border border-[var(--accent)]/20 rounded bg-bg/50">
                <h3 className="font-theme-data text-text text-sm mb-3">Provider Configuration</h3>
                <pre className="font-theme-data text-xs text-text-muted whitespace-pre overflow-x-auto">
                  {`# OpenAI Whisper (default)
OPENAI_API_KEY=sk-...

# Default provider selection
ARAGORA_STT_PROVIDER=openai_whisper`}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // SPEECH</p>
        </footer>
      </main>
    </>
  );
}
