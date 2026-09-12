'use client';

import { useEffect, useState } from 'react';
import type { ReviewAgent } from './CodeReviewWorkflow';

interface ReviewProgressProps {
  progress: {
    phase: string;
    percent: number;
    currentAgent: string;
    debateRound: number;
    totalRounds: number;
  };
  agents: ReviewAgent[];
}

export function ReviewProgress({ progress, agents }: ReviewProgressProps) {
  const [dots, setDots] = useState('');

  // Animate the dots
  useEffect(() => {
    const interval = setInterval(() => {
      setDots((prev) => (prev.length >= 3 ? '' : prev + '.'));
    }, 500);
    return () => clearInterval(interval);
  }, []);

  const phases = [
    { name: 'Initialize', threshold: 10 },
    { name: 'Analyze', threshold: 25 },
    { name: 'Security Review', threshold: 40 },
    { name: 'Performance Review', threshold: 55 },
    { name: 'Quality Review', threshold: 70 },
    { name: 'Synthesize', threshold: 85 },
    { name: 'Generate Report', threshold: 100 },
  ];

  const currentPhaseIndex = phases.findIndex((p) => progress.percent <= p.threshold);
  const activeAgent = agents.find((a) => a.name === progress.currentAgent);

  return (
    <div className="space-y-6">
      {/* Main Progress Card */}
      <div className="bg-[var(--surface)] border border-[var(--acid-green)]/30 rounded p-6">
        {/* Current Phase */}
        <div className="text-center mb-6">
          <div className="text-4xl mb-3">
            {progress.percent < 35 ? '1' : progress.percent < 70 ? '2' : '3'}
          </div>
          <h2 className="text-lg font-theme-data text-[var(--acid-green)]">
            {progress.phase}
            {dots}
          </h2>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Round {progress.debateRound} of {progress.totalRounds}
          </p>
        </div>

        {/* Progress Bar */}
        <div className="relative mb-6">
          <div className="h-2 bg-[var(--bg)] rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-[var(--acid-green)] to-[var(--acid-cyan)] transition-all duration-500"
              style={{ width: `${progress.percent}%` }}
            />
          </div>
          <div className="flex justify-between mt-2 text-xs text-[var(--text-muted)]">
            <span>Starting</span>
            <span className="font-theme-data text-[var(--acid-green)]">{progress.percent}%</span>
            <span>Complete</span>
          </div>
        </div>

        {/* Phase Timeline */}
        <div className="flex justify-between mb-6">
          {phases.map((phase, i) => {
            const isComplete = progress.percent > phase.threshold;
            const isCurrent = i === currentPhaseIndex;
            return (
              <div
                key={phase.name}
                className={`flex flex-col items-center ${i === 0 ? '' : 'flex-1'}`}
              >
                <div
                  className={`w-3 h-3 rounded-full transition-colors ${
                    isComplete
                      ? 'bg-[var(--acid-green)]'
                      : isCurrent
                        ? 'bg-[var(--acid-cyan)] animate-pulse'
                        : 'bg-[var(--border)]'
                  }`}
                />
                <span
                  className={`text-xs mt-1 hidden md:block ${
                    isCurrent ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'
                  }`}
                >
                  {phase.name}
                </span>
              </div>
            );
          })}
        </div>

        {/* Active Agent */}
        {activeAgent && (
          <div className="flex items-center justify-center gap-3 p-4 bg-[var(--bg)] rounded">
            <span className="text-3xl">{activeAgent.icon}</span>
            <div>
              <div className="font-theme-data text-sm text-[var(--text)]">
                {activeAgent.name} is analyzing
              </div>
              <div className="text-xs text-[var(--text-muted)]">{activeAgent.specialty}</div>
            </div>
          </div>
        )}
      </div>

      {/* Agent Activity Panel */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
          {'>'} AGENT ACTIVITY
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {agents.map((agent) => {
            const isActive = agent.name === progress.currentAgent;
            const hasSpoken = progress.percent > 30;
            return (
              <div
                key={agent.id}
                className={`p-3 rounded border transition-all ${
                  isActive
                    ? 'bg-[var(--acid-green)]/10 border-[var(--acid-green)] animate-pulse'
                    : hasSpoken
                      ? 'bg-[var(--bg)] border-[var(--border)]'
                      : 'bg-[var(--bg)] border-[var(--border)] opacity-50'
                }`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xl">{agent.icon}</span>
                  <span
                    className={`text-sm font-theme-data ${isActive ? 'text-[var(--acid-green)]' : 'text-[var(--text)]'}`}
                  >
                    {agent.name}
                  </span>
                </div>
                <div className="text-xs text-[var(--text-muted)]">
                  {isActive ? 'Analyzing...' : hasSpoken ? 'Ready' : 'Waiting'}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Debate Preview */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">{'>'} LIVE DEBATE</h3>
        <div className="space-y-3 max-h-64 overflow-y-auto">
          {progress.debateRound >= 1 && (
            <DebateMessage
              agent={agents[0]}
              message="Analyzing code structure and identifying potential security vulnerabilities..."
              isTyping={progress.percent < 40}
            />
          )}
          {progress.percent >= 35 && (
            <DebateMessage
              agent={agents[1]}
              message="Evaluating performance characteristics and looking for optimization opportunities..."
              isTyping={progress.percent < 55}
            />
          )}
          {progress.percent >= 55 && (
            <DebateMessage
              agent={agents[2] || agents[0]}
              message="Reviewing code quality, patterns, and maintainability concerns..."
              isTyping={progress.percent < 70}
            />
          )}
          {progress.percent >= 70 && (
            <DebateMessage
              agent={agents[0]}
              message="Building consensus on findings and determining final verdict..."
              isTyping={progress.percent < 90}
            />
          )}
        </div>
      </div>

      {/* Tips */}
      <div className="flex items-center gap-3 p-4 bg-[var(--bg)] rounded border border-[var(--border)]">
        <span className="text-xl">i</span>
        <p className="text-sm text-[var(--text-muted)]">
          Multiple AI agents are debating your code changes. Each agent brings unique expertise to
          identify issues that a single reviewer might miss.
        </p>
      </div>
    </div>
  );
}

interface DebateMessageProps {
  agent?: ReviewAgent;
  message: string;
  isTyping: boolean;
}

function DebateMessage({ agent, message, isTyping }: DebateMessageProps) {
  if (!agent) return null;

  return (
    <div className="flex items-start gap-3 p-3 bg-[var(--bg)] rounded">
      <span className="text-xl flex-shrink-0">{agent.icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-theme-data text-sm text-[var(--text)]">{agent.name}</span>
          {isTyping && <span className="text-xs text-[var(--acid-cyan)]">typing...</span>}
        </div>
        <p className={`text-sm ${isTyping ? 'text-[var(--text-muted)]' : 'text-[var(--text)]'}`}>
          {message}
        </p>
      </div>
    </div>
  );
}

export default ReviewProgress;
