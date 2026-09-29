'use client';

import { useMemo } from 'react';
import type { StreamEvent, MoodData } from '@/types/events';

interface MoodTrackerPanelProps {
  events: StreamEvent[];
  agents?: string[];
}

interface AgentMood {
  agent: string;
  currentMood: string;
  confidence: number;
  history: Array<{ mood: string; confidence: number; timestamp: number }>;
  indicators: string[];
}

// Mood to color/emoji mapping
const MOOD_STYLES: Record<string, { color: string; bg: string; emoji: string }> = {
  confident: { color: 'text-green-400', bg: 'bg-green-900/30', emoji: '💪' },
  assertive: { color: 'text-green-300', bg: 'bg-green-900/20', emoji: '✊' },
  curious: { color: 'text-blue-400', bg: 'bg-blue-900/30', emoji: '🤔' },
  analytical: { color: 'text-cyan-400', bg: 'bg-cyan-900/30', emoji: '🔬' },
  skeptical: { color: 'text-orange-400', bg: 'bg-orange-900/30', emoji: '🧐' },
  defensive: { color: 'text-yellow-400', bg: 'bg-yellow-900/30', emoji: '🛡️' },
  conciliatory: { color: 'text-purple-400', bg: 'bg-purple-900/30', emoji: '🤝' },
  frustrated: { color: 'text-red-400', bg: 'bg-red-900/30', emoji: '😤' },
  uncertain: { color: 'text-gray-400', bg: 'bg-gray-900/30', emoji: '❓' },
  excited: { color: 'text-pink-400', bg: 'bg-pink-900/30', emoji: '✨' },
  neutral: { color: 'text-gray-300', bg: 'bg-gray-800/30', emoji: '😐' },
};

function getMoodStyle(mood: string) {
  const normalized = mood.toLowerCase();
  return MOOD_STYLES[normalized] || MOOD_STYLES.neutral;
}

function getMoodEnergy(mood: string): number {
  const energyMap: Record<string, number> = {
    excited: 0.9,
    confident: 0.8,
    assertive: 0.75,
    frustrated: 0.7,
    curious: 0.6,
    analytical: 0.5,
    skeptical: 0.5,
    defensive: 0.4,
    conciliatory: 0.4,
    uncertain: 0.3,
    neutral: 0.5,
  };
  return energyMap[mood.toLowerCase()] || 0.5;
}

export function MoodTrackerPanel({ events, agents = [] }: MoodTrackerPanelProps) {
  const agentMoods = useMemo(() => {
    const moods: Record<string, AgentMood> = {};

    // Initialize with known agents
    for (const agent of agents) {
      moods[agent] = {
        agent,
        currentMood: 'neutral',
        confidence: 0.5,
        history: [],
        indicators: [],
      };
    }

    // Process mood events
    for (const event of events) {
      if (event.type === 'mood_detected' || event.type === 'mood_shift') {
        const data = event.data as MoodData;
        if (!moods[data.agent]) {
          moods[data.agent] = {
            agent: data.agent,
            currentMood: 'neutral',
            confidence: 0.5,
            history: [],
            indicators: [],
          };
        }

        moods[data.agent].currentMood = data.mood;
        moods[data.agent].confidence = data.confidence;
        moods[data.agent].indicators = data.indicators || [];
        moods[data.agent].history.push({
          mood: data.mood,
          confidence: data.confidence,
          timestamp: event.timestamp,
        });
      }
    }

    return Object.values(moods);
  }, [events, agents]);

  // Calculate overall debate energy
  const debateEnergy = useMemo(() => {
    if (agentMoods.length === 0) return 0.5;
    const totalEnergy = agentMoods.reduce(
      (sum, m) => sum + getMoodEnergy(m.currentMood) * m.confidence,
      0,
    );
    return totalEnergy / agentMoods.length;
  }, [agentMoods]);

  if (agentMoods.length === 0) {
    return null;
  }

  return (
    <div className="bg-bg-secondary rounded border border-border p-3">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-text-primary font-medium text-sm">Debate Mood</h3>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Energy</span>
          <div className="w-16 h-2 bg-bg-primary rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-blue-500 via-yellow-500 to-red-500 transition-all duration-300"
              style={{ width: `${debateEnergy * 100}%` }}
            />
          </div>
        </div>
      </div>

      <div className="space-y-2">
        {agentMoods.map((agentMood) => {
          const style = getMoodStyle(agentMood.currentMood);
          return (
            <div
              key={agentMood.agent}
              className={`rounded p-2 ${style.bg} border border-border/50`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-text-primary">{agentMood.agent}</span>
                  <span className="text-lg">{style.emoji}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-medium capitalize ${style.color}`}>
                    {agentMood.currentMood}
                  </span>
                  <span className="text-xs text-text-muted">
                    {Math.round(agentMood.confidence * 100)}%
                  </span>
                </div>
              </div>

              {/* Indicators */}
              {agentMood.indicators.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {agentMood.indicators.slice(0, 3).map((indicator, i) => (
                    <span
                      key={i}
                      className="text-xs px-1.5 py-0.5 rounded bg-bg-primary text-text-muted"
                    >
                      {indicator}
                    </span>
                  ))}
                </div>
              )}

              {/* Mood history sparkline (last 5 moods) */}
              {agentMood.history.length > 1 && (
                <div className="mt-2 flex items-center gap-1">
                  <span className="text-xs text-text-muted">History:</span>
                  <div className="flex gap-0.5">
                    {agentMood.history.slice(-5).map((h, i) => {
                      const hStyle = getMoodStyle(h.mood);
                      return (
                        <span
                          key={i}
                          className={`w-4 h-4 rounded-full flex items-center justify-center text-xs ${hStyle.bg}`}
                          title={`${h.mood} (${Math.round(h.confidence * 100)}%)`}
                        >
                          {hStyle.emoji}
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default MoodTrackerPanel;
