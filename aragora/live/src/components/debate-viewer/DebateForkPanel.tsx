'use client';

import { useState, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';

interface ForkResult {
  success: boolean;
  branch_id: string;
  parent_debate_id: string;
  branch_point: number;
  messages_inherited: number;
  modified_context?: string;
  status: string;
  message: string;
}

interface FollowupSuggestion {
  id: string;
  crux_description: string;
  suggested_task: string;
  priority: number;
  suggested_agents?: string[];
  evidence_needed?: string;
}

interface FollowupResult {
  success: boolean;
  followup_id: string;
  parent_debate_id: string;
  task: string;
  agents?: string[];
  crux_id?: string;
  status: string;
  message: string;
}

interface DebateForkPanelProps {
  debateId: string;
  messageCount: number;
  onForkCreated?: (result: ForkResult) => void;
  onFollowupCreated?: (result: FollowupResult) => void;
}

export function DebateForkPanel({
  debateId,
  messageCount,
  onForkCreated,
  onFollowupCreated,
}: DebateForkPanelProps) {
  const [activeTab, setActiveTab] = useState<'fork' | 'followup'>('fork');
  const [branchPoint, setBranchPoint] = useState(Math.max(0, messageCount - 1));
  const [modifiedContext, setModifiedContext] = useState('');
  const [isForking, setIsForking] = useState(false);
  const [forkResult, setForkResult] = useState<ForkResult | null>(null);
  const [forkError, setForkError] = useState<string | null>(null);

  const [suggestions, setSuggestions] = useState<FollowupSuggestion[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [selectedCrux, setSelectedCrux] = useState<string | null>(null);
  const [customTask, setCustomTask] = useState('');
  const [isCreatingFollowup, setIsCreatingFollowup] = useState(false);
  const [followupResult, setFollowupResult] = useState<FollowupResult | null>(null);
  const [followupError, setFollowupError] = useState<string | null>(null);

  const { config: backendConfig } = useBackend();
  const apiUrl = backendConfig.api;

  const handleFork = useCallback(async () => {
    setIsForking(true);
    setForkError(null);
    setForkResult(null);

    try {
      const response = await fetch(`${apiUrl}/api/debates/${debateId}/fork`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          branch_point: branchPoint,
          modified_context: modifiedContext || undefined,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to create fork');
      }

      setForkResult(data);
      onForkCreated?.(data);
    } catch (err) {
      setForkError(err instanceof Error ? err.message : 'Failed to create fork');
    } finally {
      setIsForking(false);
    }
  }, [apiUrl, debateId, branchPoint, modifiedContext, onForkCreated]);

  const loadSuggestions = useCallback(async () => {
    setLoadingSuggestions(true);
    try {
      const response = await fetch(`${apiUrl}/api/debates/${debateId}/followups`);
      const data = await response.json();

      if (response.ok && data.suggestions) {
        setSuggestions(data.suggestions);
      }
    } catch {
      // Silently fail - suggestions are optional
    } finally {
      setLoadingSuggestions(false);
    }
  }, [apiUrl, debateId]);

  const handleCreateFollowup = useCallback(async () => {
    if (!selectedCrux && !customTask) {
      setFollowupError('Please select a crux or enter a custom task');
      return;
    }

    setIsCreatingFollowup(true);
    setFollowupError(null);
    setFollowupResult(null);

    try {
      const response = await fetch(`${apiUrl}/api/debates/${debateId}/followup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ crux_id: selectedCrux || undefined, task: customTask || undefined }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to create follow-up');
      }

      setFollowupResult(data);
      onFollowupCreated?.(data);
    } catch (err) {
      setFollowupError(err instanceof Error ? err.message : 'Failed to create follow-up');
    } finally {
      setIsCreatingFollowup(false);
    }
  }, [apiUrl, debateId, selectedCrux, customTask, onFollowupCreated]);

  return (
    <div className="bg-surface border border-[var(--accent)]/30">
      {/* Tabs */}
      <div className="flex border-b border-[var(--accent)]/20">
        <button
          onClick={() => setActiveTab('fork')}
          className={`flex-1 px-4 py-2 text-xs font-theme-data transition-colors ${
            activeTab === 'fork'
              ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-b-2 border-[var(--accent)]'
              : 'text-text-muted hover:text-[var(--accent)]'
          }`}
        >
          [FORK DEBATE]
        </button>
        <button
          onClick={() => {
            setActiveTab('followup');
            if (suggestions.length === 0) loadSuggestions();
          }}
          className={`flex-1 px-4 py-2 text-xs font-theme-data transition-colors ${
            activeTab === 'followup'
              ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-b-2 border-[var(--accent)]'
              : 'text-text-muted hover:text-[var(--accent)]'
          }`}
        >
          [FOLLOW-UP]
        </button>
      </div>

      <div className="p-4">
        {activeTab === 'fork' && (
          <div className="space-y-4">
            <p className="text-xs text-text-muted font-theme-data">
              Create a counterfactual branch from this debate at a specific point.
            </p>

            {/* Branch Point Selector */}
            <div>
              <label className="block text-xs font-theme-data text-[var(--acid-cyan)] mb-1">
                BRANCH POINT (message #)
              </label>
              <input
                type="range"
                min={0}
                max={messageCount}
                value={branchPoint}
                onChange={(e) => setBranchPoint(parseInt(e.target.value))}
                className="w-full accent-acid-green"
              />
              <div className="flex justify-between text-xs text-text-muted font-theme-data">
                <span>0 (start)</span>
                <span className="text-[var(--accent)]">{branchPoint}</span>
                <span>{messageCount} (end)</span>
              </div>
            </div>

            {/* Modified Context */}
            <div>
              <label className="block text-xs font-theme-data text-[var(--acid-cyan)] mb-1">
                MODIFIED CONTEXT (optional)
              </label>
              <textarea
                value={modifiedContext}
                onChange={(e) => setModifiedContext(e.target.value)}
                placeholder="What if we assumed X instead of Y..."
                className="w-full bg-bg border border-[var(--accent)]/30 rounded px-3 py-2 text-sm font-theme-data text-text placeholder-text-muted/50 focus:outline-none focus:border-[var(--accent)]"
                rows={3}
              />
            </div>

            {/* Fork Button */}
            <button
              onClick={handleFork}
              disabled={isForking}
              className="w-full px-4 py-2 text-sm font-theme-data bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isForking ? '[CREATING FORK...]' : '[CREATE FORK]'}
            </button>

            {/* Results */}
            {forkError && (
              <div className="p-3 bg-warning/10 border border-warning/30 rounded text-xs font-theme-data text-warning">
                {forkError}
              </div>
            )}

            {forkResult && (
              <div className="p-3 bg-accent/10 border border-accent/30 rounded">
                <div className="text-xs font-theme-data text-accent mb-1">FORK CREATED</div>
                <div className="text-xs font-theme-data text-text-muted">
                  Branch ID: {forkResult.branch_id}
                </div>
                <div className="text-xs font-theme-data text-text-muted">
                  Inherited {forkResult.messages_inherited} messages
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'followup' && (
          <div className="space-y-4">
            <p className="text-xs text-text-muted font-theme-data">
              Create a follow-up debate to explore unresolved disagreements.
            </p>

            {/* Loading Suggestions */}
            {loadingSuggestions && (
              <div className="text-xs font-theme-data text-[var(--accent)] animate-pulse">
                Loading suggestions...
              </div>
            )}

            {/* Suggestions List */}
            {suggestions.length > 0 && (
              <div className="space-y-2">
                <label className="block text-xs font-theme-data text-[var(--acid-cyan)]">
                  SUGGESTED FOLLOW-UPS
                </label>
                {suggestions.map((suggestion) => (
                  <button
                    key={suggestion.id}
                    onClick={() => setSelectedCrux(suggestion.id)}
                    className={`w-full text-left p-3 border rounded transition-colors ${
                      selectedCrux === suggestion.id
                        ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                        : 'border-[var(--accent)]/30 hover:border-[var(--accent)]/50'
                    }`}
                  >
                    <div className="text-xs font-theme-data text-[var(--accent)] mb-1">
                      {suggestion.crux_description}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">
                      {suggestion.suggested_task}
                    </div>
                    <div className="flex gap-2 mt-1">
                      <span className="text-xs font-theme-data text-accent">
                        Priority: {suggestion.priority}
                      </span>
                      {suggestion.suggested_agents && (
                        <span className="text-xs font-theme-data text-text-muted">
                          Agents: {suggestion.suggested_agents.join(', ')}
                        </span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}

            {/* Custom Task */}
            <div>
              <label className="block text-xs font-theme-data text-[var(--acid-cyan)] mb-1">
                OR ENTER CUSTOM TASK
              </label>
              <textarea
                value={customTask}
                onChange={(e) => {
                  setCustomTask(e.target.value);
                  if (e.target.value) setSelectedCrux(null);
                }}
                placeholder="What specific question should the follow-up debate address?"
                className="w-full bg-bg border border-[var(--accent)]/30 rounded px-3 py-2 text-sm font-theme-data text-text placeholder-text-muted/50 focus:outline-none focus:border-[var(--accent)]"
                rows={3}
              />
            </div>

            {/* Create Button */}
            <button
              onClick={handleCreateFollowup}
              disabled={isCreatingFollowup || (!selectedCrux && !customTask)}
              className="w-full px-4 py-2 text-sm font-theme-data bg-accent text-bg hover:bg-accent/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isCreatingFollowup ? '[CREATING...]' : '[CREATE FOLLOW-UP]'}
            </button>

            {/* Results */}
            {followupError && (
              <div className="p-3 bg-warning/10 border border-warning/30 rounded text-xs font-theme-data text-warning">
                {followupError}
              </div>
            )}

            {followupResult && (
              <div className="p-3 bg-accent/10 border border-accent/30 rounded">
                <div className="text-xs font-theme-data text-accent mb-1">FOLLOW-UP CREATED</div>
                <div className="text-xs font-theme-data text-text-muted">
                  ID: {followupResult.followup_id}
                </div>
                <div className="text-xs font-theme-data text-text-muted">
                  Task: {followupResult.task}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
