'use client';

/**
 * useEventStream - Unified WebSocket event stream for the Command Center.
 *
 * Connects to the main event stream and categorizes all incoming events
 * for display in the LiveActivityFeed and node-attached event badges.
 */

import { useState, useCallback, useRef, useMemo } from 'react';
import { useWebSocketBase } from '@/hooks/useWebSocketBase';
import { WS_URL } from '@/config';

export type EventCategory =
  'debate' | 'execution' | 'knowledge' | 'memory' | 'verification' | 'gauntlet' | 'system';
export type EventSeverity = 'info' | 'warning' | 'error' | 'success';

export interface StreamEvent {
  id: string;
  type: string;
  category: EventCategory;
  summary: string;
  timestamp: number;
  nodeId?: string;
  severity: EventSeverity;
  data: Record<string, unknown>;
}

export interface EventFilters {
  nodeId?: string;
  category?: EventCategory;
  severity?: EventSeverity;
}

const MAX_EVENTS = 500;

// Map event types to categories
const EVENT_CATEGORY_MAP: Record<string, EventCategory> = {
  // Debate events
  DEBATE_START: 'debate',
  DEBATE_END: 'debate',
  AGENT_MESSAGE: 'debate',
  CRITIQUE: 'debate',
  VOTE: 'debate',
  CONSENSUS: 'debate',
  FLIP_DETECTED: 'debate',
  HOLLOW_CONSENSUS: 'debate',
  CRUX_DETECTED: 'debate',
  BELIEF_CONVERGED: 'debate',
  debate_start: 'debate',
  debate_end: 'debate',
  agent_message: 'debate',
  critique: 'debate',
  vote: 'debate',
  consensus: 'debate',
  round_start: 'debate',
  round_end: 'debate',
  // Execution
  TASK_COMPLETE: 'execution',
  WORKFLOW_STEP_COMPLETE: 'execution',
  AGENT_ELO_UPDATED: 'execution',
  pipeline_stage_started: 'execution',
  pipeline_stage_completed: 'execution',
  pipeline_completed: 'execution',
  pipeline_step_progress: 'execution',
  pipeline_node_status: 'execution',
  // Knowledge
  KNOWLEDGE_INDEXED: 'knowledge',
  MEMORY_STORED: 'knowledge',
  MEMORY_TIER_PROMOTION: 'knowledge',
  MOUND_UPDATED: 'knowledge',
  // Verification & Gauntlet
  FORMAL_VERIFICATION_RESULT: 'verification',
  GAUNTLET_FINDING: 'gauntlet',
  GAUNTLET_START: 'gauntlet',
  GAUNTLET_ATTACK: 'gauntlet',
  GAUNTLET_VERDICT: 'gauntlet',
};

// Determine severity from event data
function inferSeverity(type: string, data: Record<string, unknown>): EventSeverity {
  if (type.includes('ERROR') || type.includes('FAILED') || type === 'pipeline_failed')
    return 'error';
  if (type === 'HOLLOW_CONSENSUS' || type === 'GAUNTLET_FINDING') return 'warning';
  if (
    type === 'CONSENSUS' ||
    type === 'BELIEF_CONVERGED' ||
    type.includes('COMPLETE') ||
    type.includes('completed')
  )
    return 'success';
  if (data?.severity === 'critical' || data?.severity === 'high') return 'warning';
  return 'info';
}

// Generate human-readable summary
function generateSummary(type: string, data: Record<string, unknown>): string {
  const summaries: Record<string, string> = {
    DEBATE_START: `Debate started${data.topic ? `: ${data.topic}` : ''}`,
    DEBATE_END: 'Debate concluded',
    AGENT_MESSAGE: `${data.agent || 'Agent'}: ${((data.content || data.message || '') as string).slice(0, 60)}`,
    CRITIQUE: `${data.agent || 'Agent'} critiqued proposal`,
    VOTE: `${data.agent || 'Agent'} voted`,
    CONSENSUS: `Consensus reached${data.confidence ? ` (${Math.round((data.confidence as number) * 100)}%)` : ''}`,
    FLIP_DETECTED: `${data.agent || 'Agent'} changed position`,
    HOLLOW_CONSENSUS: 'Warning: Hollow consensus detected',
    CRUX_DETECTED: `Key disagreement: ${data.crux || 'identified'}`,
    BELIEF_CONVERGED: `Agreement reached: ${data.topic || 'on key point'}`,
    TASK_COMPLETE: `Task completed: ${data.task || data.name || ''}`,
    WORKFLOW_STEP_COMPLETE: `Workflow step done: ${data.step || ''}`,
    AGENT_ELO_UPDATED: `${data.agent || 'Agent'} ELO ${data.delta ? ((data.delta as number) > 0 ? '+' : '') + data.delta : 'updated'}`,
    KNOWLEDGE_INDEXED: `Saved to knowledge: ${data.key || data.topic || ''}`,
    MEMORY_STORED: 'Memory stored',
    MEMORY_TIER_PROMOTION: `Memory promoted: ${data.tier || ''}`,
    FORMAL_VERIFICATION_RESULT: `Verification: ${data.result || data.status || 'complete'}`,
    GAUNTLET_FINDING: `Finding: ${data.title || data.description || ''}`,
    GAUNTLET_START: 'Gauntlet validation started',
    GAUNTLET_ATTACK: `Attack: ${data.attack_type || data.type || ''}`,
    GAUNTLET_VERDICT: `Verdict: ${data.verdict || data.result || ''}`,
  };
  return summaries[type] || `${type.replace(/_/g, ' ').toLowerCase()}`;
}

export function useEventStream(enabled: boolean = true) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [filters, setFilters] = useState<EventFilters>({});
  const eventCounter = useRef(0);

  const handleEvent = useCallback((raw: Record<string, unknown>) => {
    const type = (raw.type as string) || 'unknown';
    const category = EVENT_CATEGORY_MAP[type] || 'system';
    const id = `evt-${++eventCounter.current}`;

    const event: StreamEvent = {
      id,
      type,
      category,
      summary: generateSummary(type, raw),
      timestamp: (raw.timestamp as number) || Date.now(),
      nodeId: (raw.node_id as string) || (raw.nodeId as string) || undefined,
      severity: inferSeverity(type, raw),
      data: raw,
    };

    setEvents((prev) => {
      const updated = [...prev, event];
      return updated.length > MAX_EVENTS ? updated.slice(-MAX_EVENTS) : updated;
    });
  }, []);

  const wsUrl = `${WS_URL.replace(/\/ws\/?$/, '')}/ws/events`;

  const { status, isConnected } = useWebSocketBase({
    wsUrl,
    enabled,
    onEvent: handleEvent,
    subscribeMessage: { type: 'subscribe_all' },
    logPrefix: '[EventStream]',
  });

  const clearEvents = useCallback(() => setEvents([]), []);

  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      if (filters.nodeId && e.nodeId !== filters.nodeId) return false;
      if (filters.category && e.category !== filters.category) return false;
      if (filters.severity && e.severity !== filters.severity) return false;
      return true;
    });
  }, [events, filters]);

  return { events, filteredEvents, status, isConnected, clearEvents, filters, setFilters };
}
