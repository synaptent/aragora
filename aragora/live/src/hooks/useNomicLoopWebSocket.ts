'use client';

/**
 * Nomic Loop WebSocket hook for real-time loop status updates.
 *
 * Provides:
 * - Loop lifecycle events (started, paused, resumed, stopped)
 * - Phase transitions (context, debate, design, implement, verify)
 * - Cycle events (started, completed)
 * - Proposal events (generated, approved, rejected)
 * - Health and stall detection updates
 */

import { useState, useCallback, useMemo } from 'react';
import { useWebSocketBase, WebSocketConnectionStatus } from './useWebSocketBase';
import { useBackend } from '@/components/BackendSelector';
import { NOMIC_LOOP_WS_URL } from '@/config';
import { logger } from '@/utils/logger';

// Event types from the nomic loop stream (matches backend NomicLoopEventType)
export type NomicLoopEventType =
  | 'connected'
  | 'disconnected'
  | 'loop_started'
  | 'loop_paused'
  | 'loop_resumed'
  | 'loop_stopped'
  | 'phase_started'
  | 'phase_completed'
  | 'phase_skipped'
  | 'phase_failed'
  | 'cycle_started'
  | 'cycle_completed'
  | 'proposal_generated'
  | 'proposal_approved'
  | 'proposal_rejected'
  | 'health_update'
  | 'stall_detected'
  | 'stall_resolved'
  | 'log_message'
  | 'error';

// Nomic loop phases
export type NomicPhase = 'context' | 'debate' | 'design' | 'implement' | 'verify';

// Loop state
export interface NomicLoopState {
  running: boolean;
  paused: boolean;
  currentPhase: NomicPhase | null;
  currentCycle: number;
  totalCycles: number;
  stalled: boolean;
  stallDurationSec?: number;
  startedAt?: string;
  pausedAt?: string;
}

// Proposal state
export interface NomicProposal {
  id: string;
  title: string;
  description: string;
  phase: string;
  status: 'pending' | 'approved' | 'rejected';
  requiresApproval: boolean;
  generatedAt: number;
}

// Event payload from the backend WebSocket
export interface NomicLoopEvent {
  type: NomicLoopEventType;
  timestamp: number;
  data: Record<string, unknown>;
}

export interface UseNomicLoopWebSocketOptions {
  /** Whether the connection is enabled */
  enabled?: boolean;
  /** Whether to automatically reconnect on disconnection */
  autoReconnect?: boolean;
  /** Custom WebSocket URL (overrides default) */
  wsUrl?: string;
  /** Callback when loop starts */
  onLoopStarted?: (cycles: number, autoApprove: boolean) => void;
  /** Callback when loop pauses */
  onLoopPaused?: (phase: string, cycle: number) => void;
  /** Callback when loop resumes */
  onLoopResumed?: (phase: string, cycle: number) => void;
  /** Callback when loop stops */
  onLoopStopped?: (forced: boolean, reason: string) => void;
  /** Callback when phase starts */
  onPhaseStarted?: (phase: string, cycle: number) => void;
  /** Callback when phase completes */
  onPhaseCompleted?: (phase: string, cycle: number, durationSec: number) => void;
  /** Callback when phase is skipped */
  onPhaseSkipped?: (phase: string, cycle: number, reason: string) => void;
  /** Callback when phase fails */
  onPhaseFailed?: (phase: string, cycle: number, error: string) => void;
  /** Callback when cycle starts */
  onCycleStarted?: (cycle: number, totalCycles: number) => void;
  /** Callback when cycle completes */
  onCycleCompleted?: (cycle: number, totalCycles: number, durationSec: number) => void;
  /** Callback when proposal is generated */
  onProposalGenerated?: (proposal: NomicProposal) => void;
  /** Callback when proposal is approved */
  onProposalApproved?: (proposalId: string, approvedBy: string) => void;
  /** Callback when proposal is rejected */
  onProposalRejected?: (proposalId: string, rejectedBy: string, reason: string) => void;
  /** Callback when stall is detected */
  onStallDetected?: (phase: string, durationSec: number) => void;
  /** Callback when stall is resolved */
  onStallResolved?: (phase: string, resolution: string) => void;
  /** Callback for any event */
  onEvent?: (event: NomicLoopEvent) => void;
}

export interface UseNomicLoopWebSocketReturn {
  /** Current WebSocket connection status */
  status: WebSocketConnectionStatus;
  /** Whether connected to the nomic loop stream */
  isConnected: boolean;
  /** Connection error message if any */
  error: string | null;
  /** Current reconnection attempt */
  reconnectAttempt: number;
  /** Current loop state */
  loopState: NomicLoopState;
  /** Pending proposals */
  proposals: NomicProposal[];
  /** Recent events (last 100) */
  recentEvents: NomicLoopEvent[];
  /** Recent log messages (last 50) */
  logMessages: Array<{ level: string; message: string; timestamp: number }>;
  /** Manually reconnect */
  reconnect: () => void;
  /** Manually disconnect */
  disconnect: () => void;
  /** Send ping to server */
  sendPing: () => void;
}

const DEFAULT_LOOP_STATE: NomicLoopState = {
  running: false,
  paused: false,
  currentPhase: null,
  currentCycle: 0,
  totalCycles: 0,
  stalled: false,
};

/**
 * Hook for connecting to the Nomic Loop WebSocket stream.
 *
 * @example
 * ```tsx
 * const {
 *   status,
 *   isConnected,
 *   loopState,
 *   proposals,
 * } = useNomicLoopWebSocket({
 *   enabled: true,
 *   onProposalGenerated: (proposal) => {
 *     toast(`New proposal: ${proposal.title}`);
 *   },
 * });
 * ```
 */
export function useNomicLoopWebSocket({
  enabled = true,
  autoReconnect = true,
  wsUrl: customWsUrl,
  onLoopStarted,
  onLoopPaused,
  onLoopResumed,
  onLoopStopped,
  onPhaseStarted,
  onPhaseCompleted,
  onPhaseSkipped,
  onPhaseFailed,
  onCycleStarted,
  onCycleCompleted,
  onProposalGenerated,
  onProposalApproved,
  onProposalRejected,
  onStallDetected,
  onStallResolved,
  onEvent,
}: UseNomicLoopWebSocketOptions = {}): UseNomicLoopWebSocketReturn {
  const { config: backendConfig } = useBackend();

  // State for loop, proposals, and events
  const [loopState, setLoopState] = useState<NomicLoopState>(DEFAULT_LOOP_STATE);
  const [proposals, setProposals] = useState<NomicProposal[]>([]);
  const [recentEvents, setRecentEvents] = useState<NomicLoopEvent[]>([]);
  const [logMessages, setLogMessages] = useState<
    Array<{ level: string; message: string; timestamp: number }>
  >([]);

  // Build WebSocket URL - use custom URL, backend config, or default
  const wsUrl = useMemo(() => {
    if (customWsUrl) return customWsUrl;
    // Check for nomic loop WebSocket URL in backend config
    const config = backendConfig as { nomicLoopWs?: string } | undefined;
    if (config?.nomicLoopWs) return config.nomicLoopWs;
    return NOMIC_LOOP_WS_URL;
  }, [customWsUrl, backendConfig]);

  // Handle incoming events
  const handleEvent = useCallback(
    (event: NomicLoopEvent) => {
      // Add to recent events
      setRecentEvents((prev) => [event, ...prev].slice(0, 100));

      // Call generic event handler
      onEvent?.(event);

      const { data } = event;

      switch (event.type) {
        case 'connected':
          // Connection confirmed
          break;

        case 'loop_started': {
          const cycles = (data.cycles as number) || 1;
          const autoApprove = (data.auto_approve as boolean) || false;
          setLoopState((prev) => ({
            ...prev,
            running: true,
            paused: false,
            currentPhase: 'context',
            currentCycle: 1,
            totalCycles: cycles,
            stalled: false,
            startedAt: new Date().toISOString(),
          }));
          onLoopStarted?.(cycles, autoApprove);
          break;
        }

        case 'loop_paused': {
          const phase = data.current_phase as string;
          const cycle = data.current_cycle as number;
          setLoopState((prev) => ({ ...prev, paused: true, pausedAt: new Date().toISOString() }));
          onLoopPaused?.(phase, cycle);
          break;
        }

        case 'loop_resumed': {
          const phase = data.current_phase as string;
          const cycle = data.current_cycle as number;
          setLoopState((prev) => ({ ...prev, paused: false, pausedAt: undefined }));
          onLoopResumed?.(phase, cycle);
          break;
        }

        case 'loop_stopped': {
          const forced = (data.forced as boolean) || false;
          const reason = (data.reason as string) || '';
          setLoopState((prev) => ({ ...prev, running: false, paused: false, currentPhase: null }));
          onLoopStopped?.(forced, reason);
          break;
        }

        case 'phase_started': {
          const phase = data.phase as NomicPhase;
          const cycle = data.cycle as number;
          setLoopState((prev) => ({ ...prev, currentPhase: phase, currentCycle: cycle }));
          onPhaseStarted?.(phase, cycle);
          break;
        }

        case 'phase_completed': {
          const phase = data.phase as string;
          const cycle = data.cycle as number;
          const durationSec = (data.duration_sec as number) || 0;
          onPhaseCompleted?.(phase, cycle, durationSec);
          break;
        }

        case 'phase_skipped': {
          const phase = data.phase as string;
          const cycle = data.cycle as number;
          const reason = (data.reason as string) || '';
          onPhaseSkipped?.(phase, cycle, reason);
          break;
        }

        case 'phase_failed': {
          const phase = data.phase as string;
          const cycle = data.cycle as number;
          const error = (data.error as string) || 'Unknown error';
          onPhaseFailed?.(phase, cycle, error);
          break;
        }

        case 'cycle_started': {
          const cycle = data.cycle as number;
          const totalCycles = data.total_cycles as number;
          setLoopState((prev) => ({ ...prev, currentCycle: cycle, totalCycles }));
          onCycleStarted?.(cycle, totalCycles);
          break;
        }

        case 'cycle_completed': {
          const cycle = data.cycle as number;
          const totalCycles = data.total_cycles as number;
          const durationSec = (data.duration_sec as number) || 0;
          onCycleCompleted?.(cycle, totalCycles, durationSec);
          break;
        }

        case 'proposal_generated': {
          const proposal: NomicProposal = {
            id: data.proposal_id as string,
            title: data.title as string,
            description: (data.description as string) || '',
            phase: data.phase as string,
            status: 'pending',
            requiresApproval: (data.requires_approval as boolean) || true,
            generatedAt: event.timestamp,
          };
          setProposals((prev) => [proposal, ...prev]);
          onProposalGenerated?.(proposal);
          break;
        }

        case 'proposal_approved': {
          const proposalId = data.proposal_id as string;
          const approvedBy = (data.approved_by as string) || 'user';
          setProposals((prev) =>
            prev.map((p) => (p.id === proposalId ? { ...p, status: 'approved' as const } : p)),
          );
          onProposalApproved?.(proposalId, approvedBy);
          break;
        }

        case 'proposal_rejected': {
          const proposalId = data.proposal_id as string;
          const rejectedBy = (data.rejected_by as string) || 'user';
          const reason = (data.reason as string) || '';
          setProposals((prev) =>
            prev.map((p) => (p.id === proposalId ? { ...p, status: 'rejected' as const } : p)),
          );
          onProposalRejected?.(proposalId, rejectedBy, reason);
          break;
        }

        case 'health_update': {
          const stalled = (data.stalled as boolean) || false;
          setLoopState((prev) => ({
            ...prev,
            running: (data.running as boolean) || prev.running,
            paused: (data.paused as boolean) || prev.paused,
            currentPhase: (data.current_phase as NomicPhase) || prev.currentPhase,
            currentCycle: (data.current_cycle as number) || prev.currentCycle,
            stalled,
          }));
          break;
        }

        case 'stall_detected': {
          const phase = data.phase as string;
          const durationSec = (data.stall_duration_sec as number) || 0;
          setLoopState((prev) => ({ ...prev, stalled: true, stallDurationSec: durationSec }));
          onStallDetected?.(phase, durationSec);
          break;
        }

        case 'stall_resolved': {
          const phase = data.phase as string;
          const resolution = (data.resolution as string) || '';
          setLoopState((prev) => ({ ...prev, stalled: false, stallDurationSec: undefined }));
          onStallResolved?.(phase, resolution);
          break;
        }

        case 'log_message': {
          const level = (data.level as string) || 'info';
          const message = (data.message as string) || '';
          setLogMessages((prev) =>
            [{ level, message, timestamp: event.timestamp }, ...prev].slice(0, 50),
          );
          break;
        }

        case 'error':
          // Log errors but don't disrupt state
          logger.error('[NomicLoop] Error event:', data.error, data.context);
          break;

        default:
          // Unknown event type - log for debugging

          logger.debug('[NomicLoop] Unknown event type:', event.type);
          break;
      }
    },
    [
      onEvent,
      onLoopStarted,
      onLoopPaused,
      onLoopResumed,
      onLoopStopped,
      onPhaseStarted,
      onPhaseCompleted,
      onPhaseSkipped,
      onPhaseFailed,
      onCycleStarted,
      onCycleCompleted,
      onProposalGenerated,
      onProposalApproved,
      onProposalRejected,
      onStallDetected,
      onStallResolved,
    ],
  );

  // Use base WebSocket hook
  const { status, error, isConnected, reconnectAttempt, send, reconnect, disconnect } =
    useWebSocketBase<NomicLoopEvent>({
      wsUrl,
      enabled: enabled && !!wsUrl,
      autoReconnect,
      onEvent: handleEvent,
      logPrefix: '[NomicLoop]',
    });

  // Send ping to server
  const sendPing = useCallback(() => {
    send({ type: 'ping' });
  }, [send]);

  return {
    status,
    isConnected,
    error,
    reconnectAttempt,
    loopState,
    proposals,
    recentEvents,
    logMessages,
    reconnect,
    disconnect,
    sendPing,
  };
}

export default useNomicLoopWebSocket;
