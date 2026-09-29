'use client';

interface PhaseConfig {
  number: number;
  name: string;
  emoji: string;
  cognitiveMode: string;
  description: string;
}

// 9-round structured debate format matching STRUCTURED_ROUND_PHASES in protocol.py
export const DEBATE_PHASES: PhaseConfig[] = [
  {
    number: 0,
    name: 'Context Gathering',
    emoji: '\u{1F50D}', // Magnifying glass
    cognitiveMode: 'Researcher',
    description: 'Gathering background information and assigning personas',
  },
  {
    number: 1,
    name: 'Initial Analysis',
    emoji: '\u{1F4CA}', // Bar chart
    cognitiveMode: 'Analyst',
    description: 'Establishing foundational understanding and key considerations',
  },
  {
    number: 2,
    name: 'Skeptical Review',
    emoji: '\u{1F914}', // Thinking face
    cognitiveMode: 'Skeptic',
    description: 'Challenging assumptions and identifying weaknesses',
  },
  {
    number: 3,
    name: 'Lateral Exploration',
    emoji: '\u{1F4A1}', // Light bulb
    cognitiveMode: 'Lateral Thinker',
    description: 'Exploring alternative perspectives and creative solutions',
  },
  {
    number: 4,
    name: "Devil's Advocacy",
    emoji: '\u{1F608}', // Smiling devil
    cognitiveMode: "Devil's Advocate",
    description: 'Arguing the strongest opposing viewpoint',
  },
  {
    number: 5,
    name: 'Synthesis',
    emoji: '\u{2696}\u{FE0F}', // Balance scale
    cognitiveMode: 'Synthesizer',
    description: 'Integrating insights from previous rounds',
  },
  {
    number: 6,
    name: 'Cross-Examination',
    emoji: '\u{1F3AF}', // Direct hit / target
    cognitiveMode: 'Examiner',
    description: 'Direct questioning between agents on remaining disputes',
  },
  {
    number: 7,
    name: 'Final Synthesis',
    emoji: '\u{1F3AF}', // Target
    cognitiveMode: 'Synthesizer',
    description: 'Each agent synthesizes discussion and revises to final form',
  },
  {
    number: 8,
    name: 'Final Adjudication',
    emoji: '\u{1F3C6}', // Trophy
    cognitiveMode: 'Adjudicator',
    description: 'Voting, judge verdict, and final synthesis',
  },
];

interface PhaseIndicatorProps {
  currentRound: number;
  totalRounds?: number;
  isComplete?: boolean;
  showProgress?: boolean;
  compact?: boolean;
}

export function PhaseIndicator({
  currentRound,
  totalRounds = 9,
  isComplete = false,
  showProgress = true,
  compact = false,
}: PhaseIndicatorProps) {
  // Get current phase config, default to last phase if out of bounds
  const phase = DEBATE_PHASES[Math.min(currentRound, DEBATE_PHASES.length - 1)];
  const progress = totalRounds > 0 ? ((currentRound + 1) / totalRounds) * 100 : 0;

  if (compact) {
    return (
      <div className="flex items-center gap-2 text-xs font-theme-data">
        <span className="text-lg">{phase.emoji}</span>
        <span className="text-text-muted">
          R{currentRound}: {phase.name}
        </span>
        {isComplete && <span className="text-green-400">[COMPLETE]</span>}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Phase Header */}
      <div className="flex items-center gap-3">
        <span className="text-2xl">{phase.emoji}</span>
        <div>
          <div className="text-sm font-theme-data text-text">
            Round {currentRound}: {phase.name}
          </div>
          <div className="text-xs font-theme-data text-text-muted">{phase.cognitiveMode} Mode</div>
        </div>
        {isComplete && (
          <span className="ml-auto px-2 py-1 text-xs font-theme-data bg-green-900/30 text-green-400 border border-green-500/30">
            COMPLETE
          </span>
        )}
      </div>

      {/* Phase Description */}
      <div className="text-xs font-theme-data text-text-muted pl-10">{phase.description}</div>

      {/* Progress Bar */}
      {showProgress && (
        <div className="mt-3">
          <div className="flex justify-between text-xs font-theme-data text-text-muted mb-1">
            <span>Progress</span>
            <span>{Math.round(progress)}%</span>
          </div>
          <div className="h-1.5 bg-bg-secondary border border-border overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                isComplete ? 'bg-green-500' : 'bg-accent'
              }`}
              style={{ width: `${isComplete ? 100 : progress}%` }}
            />
          </div>
          {/* Phase Markers */}
          <div className="flex justify-between mt-1">
            {DEBATE_PHASES.map((p) => (
              <div
                key={p.number}
                className={`w-2 h-2 rounded-full transition-colors ${
                  p.number < currentRound
                    ? 'bg-accent'
                    : p.number === currentRound
                      ? 'bg-accent animate-pulse'
                      : 'bg-border'
                }`}
                title={`R${p.number}: ${p.name}`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Mini version for inline use
export function PhaseChip({ round }: { round: number }) {
  const phase = DEBATE_PHASES[Math.min(round, DEBATE_PHASES.length - 1)];
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-theme-data bg-bg border border-border text-text-muted"
      title={phase.description}
    >
      {phase.emoji} R{round}
    </span>
  );
}

export default PhaseIndicator;
