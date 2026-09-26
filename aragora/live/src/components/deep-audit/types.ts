import type { StreamEvent, AuditFinding } from '@/types/events';

export interface DeepAuditViewProps {
  events: StreamEvent[];
  isActive: boolean;
  onToggle: () => void;
}

export interface RoundMessage {
  agent: string;
  content: string;
  role: string;
  cognitiveRole?: string;
  confidence?: number;
  citations?: number;
  timestamp: number;
}

export interface RoundData {
  round: number;
  name?: string;
  cognitiveRole?: string;
  messages: RoundMessage[];
  status: 'pending' | 'active' | 'complete';
  durationMs?: number;
}

export interface AuditVerdict {
  recommendation: string;
  confidence: number;
  unanimousIssues: string[];
  splitOpinions: string[];
  riskAreas: string[];
}

export interface AuditState {
  auditId?: string;
  task?: string;
  agents?: string[];
  findings: AuditFinding[];
  crossExamNotes?: string;
  verdict?: AuditVerdict;
}

export interface AuditRoundInfo {
  round: number;
  name: string;
  icon: string;
  description: string;
}

export const AUDIT_ROUNDS: AuditRoundInfo[] = [
  {
    round: 1,
    name: 'Initial Analysis',
    icon: '🔬',
    description: 'Agents present initial assessments',
  },
  {
    round: 2,
    name: 'Skeptical Review',
    icon: '🤔',
    description: 'Challenge assumptions and identify gaps',
  },
  {
    round: 3,
    name: 'Lateral Exploration',
    icon: '💡',
    description: 'Explore alternative perspectives',
  },
  {
    round: 4,
    name: "Devil's Advocacy",
    icon: '😈',
    description: 'Argue against the emerging consensus',
  },
  {
    round: 5,
    name: 'Synthesis',
    icon: '⚖️',
    description: 'Integrate insights into recommendations',
  },
  { round: 6, name: 'Cross-Examination', icon: '🎯', description: 'Final probing of conclusions' },
];

export const STATUS_CONFIG = {
  pending: { bg: 'bg-surface', border: 'border-border', text: 'text-text-muted' },
  active: { bg: 'bg-accent/10', border: 'border-accent', text: 'text-accent' },
  complete: { bg: 'bg-success/10', border: 'border-success/50', text: 'text-success' },
} as const;

export const CATEGORY_CONFIG = {
  unanimous: {
    icon: '✅',
    color: 'text-green-400',
    bg: 'bg-green-500/10',
    border: 'border-green-500/30',
  },
  split: {
    icon: '⚖️',
    color: 'text-yellow-400',
    bg: 'bg-yellow-500/10',
    border: 'border-yellow-500/30',
  },
  risk: { icon: '⚠️', color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/30' },
  insight: {
    icon: '💡',
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
  },
} as const;
