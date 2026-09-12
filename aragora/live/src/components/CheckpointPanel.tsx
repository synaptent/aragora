'use client';

import { useState, useEffect, useCallback } from 'react';
import { fetchWithRetry } from '@/utils/retry';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

interface Checkpoint {
  checkpoint_id: string;
  debate_id: string;
  task: string;
  current_round: number;
  total_rounds: number;
  phase: string;
  status: 'creating' | 'complete' | 'resuming' | 'corrupted' | 'expired';
  created_at: string;
  expires_at?: string;
  message_count: number;
  consensus_confidence: number;
  agent_count: number;
}

interface DebateSummary {
  id: string;
  task: string;
  phase: string;
  cycle_number: number;
  consensus_reached: boolean;
  confidence: number;
  created_at: string;
  agents: string[];
}

interface BackendConfig {
  apiUrl: string;
  wsUrl: string;
}

interface CheckpointPanelProps {
  backendConfig?: BackendConfig;
  debateId?: string;
  onResume?: (checkpointId: string) => void;
}

const DEFAULT_API_BASE = API_BASE_URL;

const STATUS_STYLES: Record<string, { text: string; bg: string }> = {
  complete: { text: 'text-[var(--accent)]', bg: 'bg-[var(--accent)]/20' },
  creating: { text: 'text-[var(--acid-cyan)]', bg: 'bg-[var(--acid-cyan)]/20' },
  resuming: { text: 'text-[var(--acid-yellow)]', bg: 'bg-acid-yellow/20' },
  corrupted: { text: 'text-acid-red', bg: 'bg-acid-red/20' },
  expired: { text: 'text-text-muted', bg: 'bg-surface' },
};

export function CheckpointPanel({ backendConfig, debateId, onResume }: CheckpointPanelProps) {
  const apiBase = backendConfig?.apiUrl || DEFAULT_API_BASE;

  const [debates, setDebates] = useState<DebateSummary[]>([]);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDebate, setSelectedDebate] = useState<string | null>(debateId || null);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<Checkpoint | null>(null);

  // Fetch recent debates that could have checkpoints
  const fetchDebates = useCallback(async () => {
    try {
      const response = await fetchWithRetry(`${apiBase}/api/debates?limit=50`, undefined, {
        maxRetries: 2,
      });
      if (response.ok) {
        const data = await response.json();
        setDebates(data.debates || []);
      }
    } catch (err) {
      logger.error('Failed to fetch debates:', err);
    }
  }, [apiBase]);

  // Generate mock checkpoints from debates (until backend endpoint exists)
  const generateCheckpoints = useCallback((debatesList: DebateSummary[]) => {
    // Create simulated checkpoints based on debate state
    const mockCheckpoints: Checkpoint[] = debatesList
      .filter((d) => d.cycle_number > 1 || d.phase !== 'complete')
      .map((d) => ({
        checkpoint_id: `chk-${d.id.slice(0, 8)}`,
        debate_id: d.id,
        task: d.task,
        current_round: d.cycle_number,
        total_rounds: 5,
        phase: d.phase,
        status: d.consensus_reached ? 'complete' : d.phase === 'voting' ? 'creating' : 'complete',
        created_at: d.created_at,
        message_count: d.cycle_number * d.agents.length * 2,
        consensus_confidence: d.confidence,
        agent_count: d.agents.length,
      }));
    setCheckpoints(mockCheckpoints);
  }, []);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      await fetchDebates();
      setLoading(false);
    };
    load();
  }, [fetchDebates]);

  useEffect(() => {
    generateCheckpoints(debates);
  }, [debates, generateCheckpoints]);

  const filteredCheckpoints = selectedDebate
    ? checkpoints.filter((c) => c.debate_id === selectedDebate)
    : checkpoints;

  const handleResume = (checkpoint: Checkpoint) => {
    if (onResume) {
      onResume(checkpoint.checkpoint_id);
    } else {
      // Navigate to debate with resume flag
      window.location.href = `/debates/${checkpoint.debate_id}?resume=${checkpoint.checkpoint_id}`;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="card p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-theme-data text-[var(--accent)] text-lg">CHECKPOINT MANAGER</h3>
            <p className="text-xs font-theme-data text-text-muted mt-1">
              Resume paused debates or restore from previous states
            </p>
          </div>
          <div className="text-right">
            <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
              {checkpoints.length}
            </div>
            <div className="text-xs font-theme-data text-text-muted">checkpoints</div>
          </div>
        </div>

        {/* Debate Filter */}
        <div className="flex gap-4">
          <label htmlFor="debate-filter" className="sr-only">
            Filter by debate
          </label>
          <select
            id="debate-filter"
            value={selectedDebate || ''}
            onChange={(e) => setSelectedDebate(e.target.value || null)}
            aria-label="Filter by debate"
            className="flex-1 bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
          >
            <option value="">All Debates</option>
            {debates.map((d) => (
              <option key={d.id} value={d.id}>
                {d.task.slice(0, 50)}
                {d.task.length > 50 ? '...' : ''} - {d.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="text-center py-12">
          <div className="text-[var(--accent)] font-theme-data animate-pulse">
            Loading checkpoints...
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Checkpoint List */}
          <div className="space-y-3">
            {filteredCheckpoints.length === 0 ? (
              <div className="card p-8 text-center">
                <p className="text-text-muted font-theme-data">No checkpoints found.</p>
                <p className="text-xs font-theme-data text-text-muted mt-2">
                  Checkpoints are created automatically during long debates.
                </p>
              </div>
            ) : (
              filteredCheckpoints.map((checkpoint) => {
                const style = STATUS_STYLES[checkpoint.status] || STATUS_STYLES.complete;
                return (
                  <button
                    key={checkpoint.checkpoint_id}
                    onClick={() => setSelectedCheckpoint(checkpoint)}
                    className={`w-full text-left card p-4 transition-all hover:border-[var(--accent)]/60 ${
                      selectedCheckpoint?.checkpoint_id === checkpoint.checkpoint_id
                        ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                        : ''
                    }`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <div className="font-theme-data text-[var(--accent)] text-sm line-clamp-1">
                          {checkpoint.task}
                        </div>
                        <div className="text-xs font-theme-data text-text-muted mt-1">
                          {checkpoint.checkpoint_id}
                        </div>
                      </div>
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-theme-data ${style.bg} ${style.text}`}
                      >
                        {checkpoint.status}
                      </span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-xs font-theme-data">
                      <div>
                        <span className="text-text-muted">Round:</span>
                        <span className="text-[var(--acid-cyan)] ml-1">
                          {checkpoint.current_round}/{checkpoint.total_rounds}
                        </span>
                      </div>
                      <div>
                        <span className="text-text-muted">Phase:</span>
                        <span className="text-[var(--acid-yellow)] ml-1">{checkpoint.phase}</span>
                      </div>
                      <div>
                        <span className="text-text-muted">Msgs:</span>
                        <span className="text-text ml-1">{checkpoint.message_count}</span>
                      </div>
                    </div>
                  </button>
                );
              })
            )}
          </div>

          {/* Checkpoint Details */}
          <div className="card p-4">
            <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-4">
              CHECKPOINT DETAILS
            </div>
            {selectedCheckpoint ? (
              <div className="space-y-4">
                <div>
                  <div className="text-xs text-text-muted mb-1">CHECKPOINT ID</div>
                  <div className="font-theme-data text-sm text-[var(--accent)]">
                    {selectedCheckpoint.checkpoint_id}
                  </div>
                </div>

                <div>
                  <div className="text-xs text-text-muted mb-1">DEBATE</div>
                  <div className="font-theme-data text-sm text-text line-clamp-2">
                    {selectedCheckpoint.task}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-xs text-text-muted mb-1">PROGRESS</div>
                    <div className="font-theme-data text-lg text-[var(--acid-cyan)]">
                      Round {selectedCheckpoint.current_round} / {selectedCheckpoint.total_rounds}
                    </div>
                    <div className="w-full bg-surface rounded-full h-2 mt-2">
                      <div
                        className="bg-[var(--accent)] h-2 rounded-full"
                        style={{
                          width: `${(selectedCheckpoint.current_round / selectedCheckpoint.total_rounds) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-text-muted mb-1">CONSENSUS</div>
                    <div className="font-theme-data text-lg text-[var(--acid-yellow)]">
                      {(selectedCheckpoint.consensus_confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-4 text-center">
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-[var(--accent)]">
                      {selectedCheckpoint.message_count}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">messages</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
                      {selectedCheckpoint.agent_count}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">agents</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-text">
                      {selectedCheckpoint.phase}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">phase</div>
                  </div>
                </div>

                <div>
                  <div className="text-xs text-text-muted mb-1">CREATED</div>
                  <div className="font-theme-data text-sm text-text-muted">
                    {new Date(selectedCheckpoint.created_at).toLocaleString()}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex gap-3 pt-4 border-t border-[var(--accent)]/20">
                  <button
                    onClick={() => handleResume(selectedCheckpoint)}
                    disabled={
                      selectedCheckpoint.status === 'corrupted' ||
                      selectedCheckpoint.status === 'expired'
                    }
                    className="flex-1 px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    [RESUME DEBATE]
                  </button>
                  <button
                    onClick={() =>
                      window.open(`/debates/${selectedCheckpoint.debate_id}`, '_blank')
                    }
                    className="px-4 py-2 bg-surface border border-[var(--accent)]/30 text-text font-theme-data text-sm rounded hover:border-[var(--accent)]/50 transition-colors"
                  >
                    [VIEW]
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-center text-text-muted font-theme-data text-sm py-8">
                Select a checkpoint to view details
              </div>
            )}
          </div>
        </div>
      )}

      {/* Storage Info */}
      <div className="card p-4">
        <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-2">
          CHECKPOINT STORAGE
        </div>
        <div className="grid grid-cols-4 gap-4 text-center text-xs font-theme-data">
          <div className="p-2 bg-surface rounded">
            <div className="text-[var(--accent)]">FILE</div>
            <div className="text-text-muted mt-1">Local disk</div>
          </div>
          <div className="p-2 bg-surface rounded">
            <div className="text-[var(--acid-cyan)]">S3</div>
            <div className="text-text-muted mt-1">AWS bucket</div>
          </div>
          <div className="p-2 bg-surface rounded">
            <div className="text-[var(--acid-yellow)]">GIT</div>
            <div className="text-text-muted mt-1">Version control</div>
          </div>
          <div className="p-2 bg-surface rounded">
            <div className="text-accent">DATABASE</div>
            <div className="text-text-muted mt-1">Supabase</div>
          </div>
        </div>
      </div>
    </div>
  );
}
