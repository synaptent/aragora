import type { DebateArtifact } from '@/utils/supabase';
import type { TranscriptMessage, DebateConnectionStatus } from '@/hooks/useDebateWebSocket';
import type { SettlementMetadata } from '@/hooks/debate-websocket';
import type { StreamEvent } from '@/types/events';
import type { StreamMetrics, TTSControls as TTSControlsType } from '@/hooks/useDebateStream';

export interface DebateViewerProps {
  debateId: string;
  wsUrl?: string;
}

export interface LiveDebateViewProps {
  debateId: string;
  status: DebateConnectionStatus;
  task: string;
  agents: string[];
  debateMode?: string | null;
  settlement?: SettlementMetadata | null;
  messages: TranscriptMessage[];
  streamingMessages: Map<string, StreamingMessage>;
  streamEvents: StreamEvent[];
  hasCitations: boolean;
  showCitations: boolean;
  setShowCitations: (show: boolean) => void;
  showParticipation: boolean;
  setShowParticipation: (show: boolean) => void;
  onShare: () => void;
  copied: boolean;
  onVote: (choice: string, intensity?: number) => void;
  onSuggest: (suggestion: string) => void;
  onAck: (callback: (msgType: string) => void) => () => void;
  onError: (callback: (message: string) => void) => () => void;
  // Scroll handling props
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  userScrolled: boolean;
  onResumeAutoScroll: () => void;
  // Crux highlighting props
  cruxes?: CruxClaim[];
  showCruxHighlighting?: boolean;
  setShowCruxHighlighting?: (show: boolean) => void;
  // Oracle streaming + TTS props (optional, enabled when useDebateStream is active)
  streamMetrics?: StreamMetrics;
  tts?: TTSControlsType;
}

export interface ArchivedDebateViewProps {
  debate: DebateArtifact;
  onShare: () => void;
  copied: boolean;
}

export interface ReasoningStep {
  thinking: string;
  timestamp: number;
  step?: number;
}

export interface EvidenceSource {
  title: string;
  url?: string;
  relevance?: number;
}

export interface StreamingMessage {
  agent: string;
  taskId?: string; // Task ID for composite React key support
  content: string;
  startTime: number;
  reasoning?: ReasoningStep[];
  evidence?: EvidenceSource[];
  confidence?: number | null;
  reasoningPhase?: string;
}

export interface CruxClaim {
  claim_id: string;
  statement: string;
  author: string;
  crux_score?: number;
}

export interface TranscriptMessageCardProps {
  message: TranscriptMessage;
  cruxes?: CruxClaim[];
  onChallenge?: (content: string, agent: string) => void;
}

export interface StreamingMessageCardProps {
  message: StreamingMessage;
}

export { type TranscriptMessage } from '@/hooks/useDebateWebSocket';
export { type DebateArtifact } from '@/utils/supabase';
