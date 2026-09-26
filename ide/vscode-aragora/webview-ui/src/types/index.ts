/**
 * Shared types for the webview UI
 * These mirror the types from the extension
 */

export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  cost?: number;
}

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export interface CodeLocation {
  file: string;
  line: number;
  column: number;
  endLine?: number;
  endColumn?: number;
}

export interface Agent {
  id: string;
  name: string;
  provider: string;
  avatar?: string;
  color?: string;
}

export interface SecurityFinding {
  id: string;
  title: string;
  description: string;
  severity: Severity;
  category: string;
  location: CodeLocation;
  suggestion?: string;
  cweId?: string;
  owaspCategory?: string;
}

export interface DebateMessage {
  id: string;
  agent: Agent;
  content: string;
  round: number;
  timestamp: number;
  tokens?: TokenUsage;
  isCritique?: boolean;
  replyTo?: string;
}

export interface DebateConsensus {
  answer: string;
  confidence: number;
  method: 'majority' | 'unanimous' | 'synthesis' | 'weighted';
  agreeingAgents: string[];
  dissent?: { agent: string; reason: string }[];
}

export interface DebateState {
  id: string;
  question: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  currentRound: number;
  totalRounds: number;
  messages: DebateMessage[];
  consensus?: DebateConsensus;
  startTime: number;
  endTime?: number;
  totalTokens?: TokenUsage;
}

export interface ReviewComment {
  id: string;
  agent: Agent;
  content: string;
  location: CodeLocation;
  severity: Severity;
  category: 'bug' | 'security' | 'performance' | 'style' | 'suggestion' | 'praise';
  suggestedFix?: { oldCode: string; newCode: string };
  isResolved?: boolean;
}

export interface ReviewResult {
  id: string;
  file: string;
  status: 'pending' | 'in_progress' | 'completed';
  comments: ReviewComment[];
  summary: string;
  overallScore?: number;
  agents: Agent[];
}

export interface ExtensionSettings {
  apiUrl: string;
  defaultAgents: string[];
  defaultRounds: number;
  autoAnalyze: boolean;
  showInlineHints: boolean;
  theme: 'auto' | 'light' | 'dark';
}

export interface WebviewState {
  debates: DebateState[];
  reviews: ReviewResult[];
  findings: SecurityFinding[];
  settings: ExtensionSettings;
  connectionStatus: 'connected' | 'disconnected' | 'connecting';
}

// Extension → Webview Messages
export type ExtensionMessage =
  | { type: 'debate_started'; debate: DebateState }
  | { type: 'debate_updated'; debate: DebateState }
  | { type: 'agent_message'; message: DebateMessage }
  | { type: 'agent_message_streaming'; agentId: string; content: string; round: number }
  | { type: 'consensus_reached'; consensus: DebateConsensus }
  | { type: 'debate_completed'; debate: DebateState }
  | { type: 'debate_failed'; debateId: string; error: string }
  | { type: 'review_started'; review: ReviewResult }
  | { type: 'review_comment'; comment: ReviewComment }
  | { type: 'review_completed'; review: ReviewResult }
  | { type: 'security_scan_started'; file: string }
  | { type: 'security_finding'; finding: SecurityFinding }
  | { type: 'security_scan_completed'; file: string; findings: SecurityFinding[] }
  | { type: 'state_sync'; state: WebviewState }
  | { type: 'settings_updated'; settings: ExtensionSettings }
  | { type: 'error'; message: string; code?: string }
  | { type: 'info'; message: string };

// Webview → Extension Messages
export type WebviewMessage =
  | { type: 'start_debate'; question: string; agents?: string[]; rounds?: number }
  | { type: 'stop_debate'; debateId: string }
  | { type: 'send_feedback'; debateId: string; vote: 'up' | 'down'; comment?: string }
  | { type: 'copy_result'; debateId: string }
  | { type: 'export_debate'; debateId: string; format: 'json' | 'markdown' | 'html' }
  | { type: 'apply_fix'; reviewId: string; commentId: string }
  | { type: 'apply_all_fixes'; reviewId: string }
  | { type: 'dismiss_comment'; reviewId: string; commentId: string }
  | { type: 'navigate_to_comment'; reviewId: string; commentId: string }
  | { type: 'fix_finding'; findingId: string }
  | { type: 'ignore_finding'; findingId: string; scope: 'file' | 'workspace' | 'global' }
  | { type: 'navigate_to_finding'; findingId: string }
  | { type: 'ready' }
  | { type: 'get_state' }
  | { type: 'open_settings' }
  | { type: 'refresh' };

// Agent colors for consistent theming
export const AGENT_COLORS: Record<string, string> = {
  claude: '#C97539',
  'gpt-4': '#10A37F',
  'gpt-4o': '#10A37F',
  gemini: '#4285F4',
  mistral: '#FF7000',
  grok: '#1DA1F2',
  llama: '#0467DF',
  deepseek: '#4B6EF5',
  qwen: '#6C5CE7',
  default: '#6B7280',
};

export function getAgentColor(agentName: string): string {
  const normalized = agentName.toLowerCase();
  for (const [key, color] of Object.entries(AGENT_COLORS)) {
    if (normalized.includes(key)) {
      return color;
    }
  }
  return AGENT_COLORS.default;
}
