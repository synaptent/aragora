'use client';

import { useState } from 'react';
import type { ReviewAgent, ReviewFocus } from './CodeReviewWorkflow';

interface ReviewInputProps {
  prUrl: string;
  setPrUrl: (url: string) => void;
  diffContent: string;
  setDiffContent: (content: string) => void;
  agents: ReviewAgent[];
  setAgents: (agents: ReviewAgent[]) => void;
  focus: ReviewFocus;
  setFocus: (focus: ReviewFocus) => void;
  onStartReview: () => void;
}

type InputMode = 'pr' | 'diff';

export function ReviewInput({
  prUrl,
  setPrUrl,
  diffContent,
  setDiffContent,
  agents,
  setAgents,
  focus,
  setFocus,
  onStartReview,
}: ReviewInputProps) {
  const [inputMode, setInputMode] = useState<InputMode>('pr');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const hasValidInput =
    inputMode === 'pr' ? prUrl.trim().length > 0 : diffContent.trim().length > 0;
  const enabledAgentsCount = agents.filter((a) => a.enabled).length;
  const canStart = hasValidInput && enabledAgentsCount >= 2;

  const toggleAgent = (agentId: string) => {
    setAgents(agents.map((a) => (a.id === agentId ? { ...a, enabled: !a.enabled } : a)));
  };

  const focusOptions: Array<{ value: ReviewFocus; label: string; icon: string }> = [
    { value: 'all', label: 'Full Review', icon: '360' },
    { value: 'security', label: 'Security Focus', icon: 'S' },
    { value: 'performance', label: 'Performance Focus', icon: 'P' },
    { value: 'quality', label: 'Quality Focus', icon: 'Q' },
  ];

  return (
    <div className="space-y-6">
      {/* Input Mode Selector */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <div className="flex items-center gap-4 mb-4">
          <button
            onClick={() => setInputMode('pr')}
            className={`px-4 py-2 text-sm font-theme-data rounded transition-colors ${
              inputMode === 'pr'
                ? 'bg-[var(--acid-green)] text-black'
                : 'bg-[var(--bg)] text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
          >
            GitHub PR URL
          </button>
          <button
            onClick={() => setInputMode('diff')}
            className={`px-4 py-2 text-sm font-theme-data rounded transition-colors ${
              inputMode === 'diff'
                ? 'bg-[var(--acid-green)] text-black'
                : 'bg-[var(--bg)] text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
          >
            Paste Diff
          </button>
        </div>

        {inputMode === 'pr' ? (
          <div>
            <label className="block text-xs text-[var(--text-muted)] mb-2">Pull Request URL</label>
            <input
              type="url"
              value={prUrl}
              onChange={(e) => setPrUrl(e.target.value)}
              placeholder="https://github.com/owner/repo/pull/123"
              className="w-full px-4 py-3 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)] placeholder:text-[var(--text-muted)]/50 focus:border-[var(--acid-green)] focus:outline-none"
            />
            <p className="text-xs text-[var(--text-muted)] mt-2">
              Enter a GitHub, GitLab, or Bitbucket pull request URL
            </p>
          </div>
        ) : (
          <div>
            <label className="block text-xs text-[var(--text-muted)] mb-2">Diff Content</label>
            <textarea
              value={diffContent}
              onChange={(e) => setDiffContent(e.target.value)}
              placeholder="Paste your git diff here...

$ git diff main..feature-branch"
              rows={12}
              className="w-full px-4 py-3 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)] placeholder:text-[var(--text-muted)]/50 focus:border-[var(--acid-green)] focus:outline-none resize-none"
            />
            <p className="text-xs text-[var(--text-muted)] mt-2">
              Paste output from: git diff, git show, or unified diff format
            </p>
          </div>
        )}
      </div>

      {/* Review Focus */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
          {'>'} REVIEW FOCUS
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {focusOptions.map((option) => (
            <button
              key={option.value}
              onClick={() => setFocus(option.value)}
              className={`p-3 rounded border transition-all ${
                focus === option.value
                  ? 'bg-[var(--acid-green)]/10 border-[var(--acid-green)] text-[var(--acid-green)]'
                  : 'bg-[var(--bg)] border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--acid-green)]/50'
              }`}
            >
              <div className="text-lg font-theme-data font-bold mb-1">{option.icon}</div>
              <div className="text-xs">{option.label}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Agent Selection */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} REVIEW AGENTS</h3>
          <span className="text-xs text-[var(--text-muted)]">
            {enabledAgentsCount} of {agents.length} selected (min 2)
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {agents.map((agent) => (
            <button
              key={agent.id}
              onClick={() => toggleAgent(agent.id)}
              className={`flex items-center gap-3 p-3 rounded border transition-all text-left ${
                agent.enabled
                  ? 'bg-[var(--acid-green)]/10 border-[var(--acid-green)]'
                  : 'bg-[var(--bg)] border-[var(--border)] opacity-60 hover:opacity-100'
              }`}
            >
              <span className="text-2xl">{agent.icon}</span>
              <div className="flex-1">
                <div
                  className={`font-theme-data text-sm ${agent.enabled ? 'text-[var(--text)]' : 'text-[var(--text-muted)]'}`}
                >
                  {agent.name}
                </div>
                <div className="text-xs text-[var(--text-muted)]">{agent.specialty}</div>
              </div>
              <div
                className={`w-4 h-4 rounded-full border-2 transition-colors ${
                  agent.enabled
                    ? 'bg-[var(--acid-green)] border-[var(--acid-green)]'
                    : 'border-[var(--border)]'
                }`}
              >
                {agent.enabled && (
                  <svg className="w-full h-full text-black" viewBox="0 0 20 20" fill="currentColor">
                    <path
                      fillRule="evenodd"
                      d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                      clipRule="evenodd"
                    />
                  </svg>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Advanced Options */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded overflow-hidden">
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="w-full px-4 py-3 flex items-center justify-between text-sm font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
        >
          <span>Advanced Options</span>
          <span
            className="transition-transform"
            style={{ transform: showAdvanced ? 'rotate(180deg)' : 'rotate(0)' }}
          >
            v
          </span>
        </button>
        {showAdvanced && (
          <div className="px-4 pb-4 space-y-4 border-t border-[var(--border)]">
            <div className="pt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-[var(--text-muted)] mb-2">Debate Rounds</label>
                <select className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)]">
                  <option value="2">2 rounds (faster)</option>
                  <option value="3" selected>
                    3 rounds (balanced)
                  </option>
                  <option value="5">5 rounds (thorough)</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-[var(--text-muted)] mb-2">
                  Consensus Threshold
                </label>
                <select className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)]">
                  <option value="0.6">60% (lenient)</option>
                  <option value="0.75" selected>
                    75% (standard)
                  </option>
                  <option value="0.9">90% (strict)</option>
                </select>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="autoSubmit"
                className="w-4 h-4 rounded border-[var(--border)]"
              />
              <label htmlFor="autoSubmit" className="text-sm text-[var(--text-muted)]">
                Auto-submit review to GitHub when complete
              </label>
            </div>
          </div>
        )}
      </div>

      {/* Start Button */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-[var(--text-muted)]">
          {!hasValidInput && 'Enter a PR URL or paste a diff to continue'}
          {hasValidInput && enabledAgentsCount < 2 && 'Select at least 2 agents for debate'}
        </div>
        <button
          onClick={onStartReview}
          disabled={!canStart}
          className={`px-6 py-3 font-theme-data text-sm rounded transition-all ${
            canStart
              ? 'bg-[var(--acid-green)] text-black hover:bg-[var(--acid-green)]/90'
              : 'bg-[var(--surface)] text-[var(--text-muted)] cursor-not-allowed'
          }`}
        >
          Start Multi-Agent Review
        </button>
      </div>
    </div>
  );
}

export default ReviewInput;
