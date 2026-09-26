'use client';

interface RoleBadgeProps {
  role: string;
  cognitiveRole?: string;
  size?: 'sm' | 'md';
}

// Cognitive role configurations (Heavy3-inspired)
const COGNITIVE_ROLES: Record<string, { icon: string; label: string; color: string }> = {
  analyst: {
    icon: '🔬',
    label: 'Analyst',
    color: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  },
  skeptic: {
    icon: '🤔',
    label: 'Skeptic',
    color: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  },
  lateral_thinker: {
    icon: '💡',
    label: 'Lateral',
    color: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  },
  synthesizer: {
    icon: '⚖️',
    label: 'Synthesizer',
    color: 'bg-green-500/20 text-green-400 border-green-500/30',
  },
  devil_advocate: {
    icon: '😈',
    label: "Devil's Advocate",
    color: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
  advocate: {
    icon: '🛡️',
    label: 'Advocate',
    color: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  },
};

// Standard debate role configurations
const DEBATE_ROLES: Record<string, { icon: string; label: string; color: string }> = {
  proposer: { icon: '💡', label: 'Proposer', color: 'bg-accent/20 text-accent border-accent/30' },
  critic: {
    icon: '🔍',
    label: 'Critic',
    color: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  },
  synthesizer: {
    icon: '🔮',
    label: 'Synthesizer',
    color: 'bg-green-500/20 text-green-400 border-green-500/30',
  },
  judge: {
    icon: '⚖️',
    label: 'Judge',
    color: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  },
  reviewer: {
    icon: '📋',
    label: 'Reviewer',
    color: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  },
  implementer: {
    icon: '🔧',
    label: 'Implementer',
    color: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  },
};

export function RoleBadge({ role, cognitiveRole, size = 'md' }: RoleBadgeProps) {
  // Prefer cognitive role if available (Heavy3-style)
  const cognitiveConfig = cognitiveRole ? COGNITIVE_ROLES[cognitiveRole.toLowerCase()] : null;
  const debateConfig = DEBATE_ROLES[role?.toLowerCase()] || {
    icon: '🤖',
    label: role || 'Agent',
    color: 'bg-surface text-text-muted border-border',
  };

  const _config = cognitiveConfig || debateConfig;
  const sizeClasses = size === 'sm' ? 'text-xs px-1.5 py-0.5' : 'text-sm px-2 py-1';

  return (
    <div className="flex items-center gap-2">
      {/* Cognitive Role Badge (if present) */}
      {cognitiveConfig && (
        <span
          className={`inline-flex items-center gap-1 rounded border ${cognitiveConfig.color} ${sizeClasses}`}
        >
          <span>{cognitiveConfig.icon}</span>
          <span>{cognitiveConfig.label}</span>
        </span>
      )}

      {/* Debate Role Badge */}
      <span
        className={`inline-flex items-center gap-1 rounded border ${debateConfig.color} ${sizeClasses}`}
      >
        <span>{debateConfig.icon}</span>
        <span>{debateConfig.label}</span>
      </span>
    </div>
  );
}

// Compact version for inline use
export function RoleIcon({ role, cognitiveRole }: { role: string; cognitiveRole?: string }) {
  const cognitiveConfig = cognitiveRole ? COGNITIVE_ROLES[cognitiveRole.toLowerCase()] : null;
  const debateConfig = DEBATE_ROLES[role?.toLowerCase()];

  if (cognitiveConfig) {
    return (
      <span title={cognitiveConfig.label} className="cursor-help">
        {cognitiveConfig.icon}
      </span>
    );
  }

  if (debateConfig) {
    return (
      <span title={debateConfig.label} className="cursor-help">
        {debateConfig.icon}
      </span>
    );
  }

  return <span>🤖</span>;
}
