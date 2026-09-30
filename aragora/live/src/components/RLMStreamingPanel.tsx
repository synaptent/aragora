'use client';

import { useEffect, useMemo, useState } from 'react';
import { logger } from '@/utils/logger';

interface RLMStreamEvent {
  type: 'context_start' | 'chunk_loaded' | 'compression_progress' | 'context_complete' | 'error';
  timestamp: number;
  data: {
    chunkId?: string;
    level?: number;
    tokensBefore?: number;
    tokensAfter?: number;
    compressionRatio?: number;
    relevanceScore?: number;
    source?: string;
    totalChunks?: number;
    loadedChunks?: number;
    message?: string;
  };
}

interface RLMContextChunk {
  id: string;
  level: number;
  tokens: number;
  relevance: number;
  source: string;
  loadedAt: number;
}

interface RLMStreamingPanelProps {
  debateId: string;
  onContextReady?: (totalTokens: number) => void;
}

export function RLMStreamingPanel({ debateId, onContextReady }: RLMStreamingPanelProps) {
  const [events, setEvents] = useState<RLMStreamEvent[]>([]);
  const [chunks, setChunks] = useState<RLMContextChunk[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [compressionStats, setCompressionStats] = useState({
    tokensBefore: 0,
    tokensAfter: 0,
    ratio: 0,
  });
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);

  // Connect to RLM streaming endpoint
  useEffect(() => {
    if (!debateId) return;

    const eventSource = new EventSource(`/api/v2/debates/${debateId}/rlm/stream`);

    eventSource.onopen = () => {
      setIsStreaming(true);
      setError(null);
    };

    eventSource.onmessage = (e) => {
      try {
        const event: RLMStreamEvent = JSON.parse(e.data);
        event.timestamp = Date.now();

        setEvents((prev) => [...prev, event]);

        switch (event.type) {
          case 'context_start':
            setChunks([]);
            setCompressionStats({ tokensBefore: 0, tokensAfter: 0, ratio: 0 });
            break;

          case 'chunk_loaded':
            if (event.data.chunkId) {
              setChunks((prev) => [
                ...prev,
                {
                  id: event.data.chunkId!,
                  level: event.data.level || 0,
                  tokens: event.data.tokensAfter || 0,
                  relevance: event.data.relevanceScore || 0,
                  source: event.data.source || 'unknown',
                  loadedAt: event.timestamp,
                },
              ]);
            }
            break;

          case 'compression_progress':
            setCompressionStats({
              tokensBefore: event.data.tokensBefore || 0,
              tokensAfter: event.data.tokensAfter || 0,
              ratio: event.data.compressionRatio || 0,
            });
            break;

          case 'context_complete':
            setIsStreaming(false);
            if (onContextReady && event.data.tokensAfter) {
              onContextReady(event.data.tokensAfter);
            }
            break;

          case 'error':
            setError(event.data.message || 'Unknown error');
            setIsStreaming(false);
            break;
        }
      } catch (err) {
        logger.error('Failed to parse RLM event:', err);
      }
    };

    eventSource.onerror = () => {
      setIsStreaming(false);
      setError('Connection lost');
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [debateId, onContextReady]);

  // Calculate progress
  const progress = useMemo(() => {
    const lastEvent = events[events.length - 1];
    if (!lastEvent?.data?.totalChunks) return 0;
    return ((lastEvent.data.loadedChunks || 0) / lastEvent.data.totalChunks) * 100;
  }, [events]);

  // Group chunks by level
  const chunksByLevel = useMemo(() => {
    const grouped: Record<number, RLMContextChunk[]> = {};
    for (const chunk of chunks) {
      if (!grouped[chunk.level]) grouped[chunk.level] = [];
      grouped[chunk.level].push(chunk);
    }
    return grouped;
  }, [chunks]);

  const totalTokens = useMemo(() => {
    return chunks.reduce((sum, c) => sum + c.tokens, 0);
  }, [chunks]);

  // Get color based on relevance score
  const getChunkColor = (relevance: number): string => {
    const hue = 270 - relevance * 90; // purple to pink
    const lightness = 40 + relevance * 20;
    return `hsl(${hue}, 70%, ${lightness}%)`;
  };

  if (!debateId) return null;

  return (
    <div className="bg-bg-secondary rounded border border-border overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between p-3 cursor-pointer hover:bg-bg-primary/50"
        onClick={() => setExpanded(!expanded)}
      >
        <h3 className="text-text-primary font-medium text-sm flex items-center gap-2">
          <span className="text-purple-400">RLM</span> Context Loading
          {isStreaming && (
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 bg-purple-500 rounded-full animate-pulse" />
              <span className="text-xs text-purple-400">streaming</span>
            </span>
          )}
        </h3>
        <div className="flex items-center gap-3">
          <span className="text-xs text-text-muted">{totalTokens.toLocaleString()} tokens</span>
          <span className="text-text-muted">{expanded ? '\u25B2' : '\u25BC'}</span>
        </div>
      </div>

      {expanded && (
        <div className="p-3 pt-0 space-y-3">
          {/* Error state */}
          {error && (
            <div className="bg-red-900/20 border border-red-500/30 rounded p-2 text-xs text-red-400">
              {error}
            </div>
          )}

          {/* Progress bar */}
          <div>
            <div className="flex justify-between text-xs text-text-muted mb-1">
              <span>Loading Progress</span>
              <span>{progress.toFixed(0)}%</span>
            </div>
            <div className="h-2 bg-bg-primary rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-purple-600 to-pink-500 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>

          {/* Compression stats */}
          {compressionStats.tokensBefore > 0 && (
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="bg-bg-primary rounded p-2">
                <div className="text-xs text-text-muted">Before</div>
                <div className="text-sm text-text-primary font-theme-data">
                  {compressionStats.tokensBefore.toLocaleString()}
                </div>
              </div>
              <div className="bg-bg-primary rounded p-2">
                <div className="text-xs text-text-muted">After</div>
                <div className="text-sm text-green-400 font-theme-data">
                  {compressionStats.tokensAfter.toLocaleString()}
                </div>
              </div>
              <div className="bg-bg-primary rounded p-2">
                <div className="text-xs text-text-muted">Saved</div>
                <div className="text-sm text-cyan-400 font-theme-data">
                  {((1 - compressionStats.ratio) * 100).toFixed(0)}%
                </div>
              </div>
            </div>
          )}

          {/* Context levels visualization */}
          {Object.keys(chunksByLevel).length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs text-text-muted">Context Levels</h4>
              {Object.entries(chunksByLevel)
                .sort(([a], [b]) => Number(a) - Number(b))
                .map(([level, levelChunks]) => (
                  <div key={level} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-text-secondary">Level {level}</span>
                      <span className="text-text-muted">
                        {levelChunks.length} chunks,{' '}
                        {levelChunks.reduce((s, c) => s + c.tokens, 0).toLocaleString()} tokens
                      </span>
                    </div>
                    <div className="flex gap-0.5 flex-wrap">
                      {levelChunks.map((chunk) => (
                        <div
                          key={chunk.id}
                          className="w-6 h-4 rounded-sm transition-all duration-300"
                          style={{
                            backgroundColor: getChunkColor(chunk.relevance),
                            opacity: 0.7 + chunk.relevance * 0.3,
                          }}
                          title={`${chunk.source}: ${chunk.tokens} tokens (${(chunk.relevance * 100).toFixed(0)}% relevant)`}
                        />
                      ))}
                    </div>
                  </div>
                ))}
            </div>
          )}

          {/* Source breakdown */}
          {chunks.length > 0 && (
            <div>
              <h4 className="text-xs text-text-muted mb-2">Sources</h4>
              <div className="flex flex-wrap gap-2">
                {Array.from(new Set(chunks.map((c) => c.source))).map((source) => {
                  const sourceChunks = chunks.filter((c) => c.source === source);
                  const sourceTokens = sourceChunks.reduce((s, c) => s + c.tokens, 0);
                  return (
                    <div key={source} className="px-2 py-1 bg-bg-primary rounded text-xs">
                      <span className="text-text-secondary">{source}</span>
                      <span className="text-text-muted ml-1">
                        ({sourceTokens.toLocaleString()})
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Live events (collapsed by default) */}
          {events.length > 0 && (
            <details className="text-xs">
              <summary className="text-text-muted cursor-pointer hover:text-text-secondary">
                Event Log ({events.length})
              </summary>
              <div className="mt-2 max-h-32 overflow-y-auto space-y-1 font-theme-data">
                {events.slice(-10).map((event, i) => (
                  <div key={i} className="text-text-muted">
                    <span className="text-purple-400">{event.type}</span>
                    {event.data.chunkId && (
                      <span className="text-text-secondary"> {event.data.chunkId}</span>
                    )}
                    {event.data.relevanceScore !== undefined && (
                      <span className="text-cyan-400">
                        {' '}
                        rel:{(event.data.relevanceScore * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

export default RLMStreamingPanel;
