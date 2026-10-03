'use client';

import { useState, useEffect } from 'react';
import { ErrorWithRetry } from './RetryButton';
import { fetchWithRetry } from '@/utils/retry';
import { logger } from '@/utils/logger';
import { API_BASE_URL } from '@/config';

interface Replay {
  id: string;
  topic: string;
  created_at: string;
  event_count: number;
  status: string;
}

interface ReplayEvent {
  event_id: string;
  timestamp: number;
  event_type: string;
  source: string;
  content: string;
  metadata: Record<string, unknown>;
}

interface ReplayDetail {
  meta: Record<string, unknown>;
  events: ReplayEvent[];
}

function simpleSimilarity(text1: string, text2: string): number {
  const words1 = text1.toLowerCase().split(/\s+/);
  const words2 = text2.toLowerCase().split(/\s+/);
  const common = words1.filter(word => words2.includes(word)).length;
  const total = new Set([...words1, ...words2]).size;
  return total > 0 ? common / total : 0;
}

function findSimilarEvents(events: ReplayEvent[], currentIndex: number, threshold = 0.3): number[] {
  const current = events[currentIndex];
  const similar: number[] = [];

  for (let i = 0; i < events.length; i++) {
    if (i === currentIndex) continue;
    const similarity = simpleSimilarity(current.content, events[i].content);
    if (similarity >= threshold) {
      similar.push(i);
    }
  }

  return similar;
}

export function ReplayBrowser() {
  const [replays, setReplays] = useState<Replay[]>([]);
  const [selectedReplay, setSelectedReplay] = useState<ReplayDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forking, setForking] = useState<string | null>(null);
  const [highlightedEvents, setHighlightedEvents] = useState<Set<number>>(new Set());

  const fetchReplays = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchWithRetry(`${API_BASE_URL}/api/replays`, undefined, { maxRetries: 2 });
      if (response.ok) {
        const data = await response.json();
        setReplays(data);
      } else {
        throw new Error(`Failed to fetch: ${response.statusText}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch replays');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReplays();
  }, []);

  const loadReplay = async (replayId: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchWithRetry(`${API_BASE_URL}/api/replays/${replayId}`, undefined, { maxRetries: 2 });
      if (response.ok) {
        const data = await response.json();
        setSelectedReplay(data);
      } else {
        throw new Error(`Failed to load: ${response.statusText}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load replay');
    } finally {
      setLoading(false);
    }
  };

  const forkReplay = async (replayId: string, eventId: string) => {
    setForking(eventId);
    try {
      const response = await fetchWithRetry(
        `${API_BASE_URL}/api/replays/${replayId}/fork`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ event_id: eventId }),
        },
        { maxRetries: 2 }
      );
      if (response.ok) {
        const forkData = await response.json();
        alert(`Fork created: ${forkData.fork_id}. Use this to start a new debate.`);
      } else {
        alert('Fork failed');
      }
    } catch (err) {
      logger.error('Fork error:', err);
      alert('Fork failed');
    } finally {
      setForking(null);
    }
  };

  return (
    <div className="bg-surface border border-border rounded-lg p-4">
      <h3 className="text-lg font-semibold mb-4">Replay Browser</h3>

      {error && <ErrorWithRetry error={error} onRetry={fetchReplays} className="mb-4" />}

      {!selectedReplay ? (
        <div>
          <h4 className="text-sm font-medium mb-2">Available Replays</h4>
          <div className="space-y-2 max-h-60 overflow-y-auto">
            {replays.map((replay) => (
              <div key={replay.id} className="flex items-center justify-between p-2 bg-bg rounded border">
                <div>
                  <div className="font-medium text-sm">{replay.topic}</div>
                  <div className="text-xs text-text-muted">
                    {new Date(replay.created_at).toLocaleString()} • {replay.event_count} events
                  </div>
                </div>
                <button
                  onClick={() => loadReplay(replay.id)}
                  disabled={loading}
                  className="px-3 py-1 bg-accent text-bg rounded text-sm hover:bg-accent/80 disabled:opacity-50"
                >
                  {loading ? 'Loading...' : 'View'}
                </button>
              </div>
            ))}
            {replays.length === 0 && (
              <div className="text-text-muted text-sm">No replays available</div>
            )}
          </div>
        </div>
      ) : (
        <div>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h4 className="text-sm font-medium">Replay: {String(selectedReplay.meta.topic || '')}</h4>
              <div className="text-xs text-text-muted">
                Convergence patterns: {selectedReplay.events.filter(e => e.event_type === 'consensus').length} consensus points
                • {selectedReplay.events.filter(e => e.event_type === 'fork').length} branches
              </div>
            </div>
            <button
              onClick={() => setSelectedReplay(null)}
              className="px-3 py-1 bg-border text-text rounded text-sm hover:bg-border/80"
            >
              Back
            </button>
          </div>

          <div className="max-h-96 overflow-y-auto space-y-2">
            {selectedReplay.events.map((event, index) => {
              const similarIndices = findSimilarEvents(selectedReplay.events, index);
              const hasSimilar = similarIndices.length > 0;
              const isHighlighted = highlightedEvents.has(index);

              return (
                <div
                  key={event.event_id}
                  className={`p-3 rounded border text-sm cursor-pointer transition-colors ${
                    isHighlighted ? 'bg-warning/10 border-warning/50' : 'bg-bg'
                  }`}
                  onClick={() => {
                    if (hasSimilar) {
                      const newHighlighted = new Set(highlightedEvents);
                      if (isHighlighted) {
                        newHighlighted.delete(index);
                      } else {
                        newHighlighted.add(index);
                        similarIndices.forEach(i => newHighlighted.add(i));
                      }
                      setHighlightedEvents(newHighlighted);
                    }
                  }}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium">{event.event_type}</span>
                    <span className="text-xs text-text-muted">
                      {new Date(event.timestamp * 1000).toLocaleTimeString()}
                      {hasSimilar && <span className="ml-2 text-warning">🔗 Similar</span>}
                    </span>
                  </div>
                  <div className="text-xs text-text-muted mb-2">
                    Source: {event.source} • Round: {String(event.metadata?.round ?? 'N/A')}
                    {typeof event.metadata?.confidence === 'number' && (
                      <span className="ml-2">Confidence: {Math.round(event.metadata.confidence * 100)}%</span>
                    )}
                  </div>
                  <div className="mb-2">{event.content}</div>
                  {Array.isArray(event.metadata?.citations) && event.metadata.citations.length > 0 && (
                    <div className="text-xs text-text-muted mb-2">
                      Citations: {(event.metadata.citations as string[]).join(', ')}
                    </div>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      forkReplay(String(selectedReplay.meta.debate_id || ''), event.event_id);
                    }}
                    disabled={forking === event.event_id}
                    className="px-2 py-1 bg-accent text-bg rounded text-xs hover:bg-accent/80 disabled:opacity-50"
                  >
                    {forking === event.event_id ? 'Forking...' : 'Fork Here'}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
