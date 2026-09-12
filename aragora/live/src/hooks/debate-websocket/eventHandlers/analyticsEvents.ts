/**
 * Handlers for analytics and auxiliary events
 * (audience, grounded_verdict, uncertainty, vote, rhetorical, trickster, memory, etc.)
 */

import type { StreamEvent } from '@/types/events';
import { logger } from '@/utils/logger';
import type { EventHandlerContext, ParsedEventData } from './types';

const AGENT_ERROR_THROTTLE_MS = 10000;
const agentErrorTimestamps = new Map<string, number>();

function shouldEmitAgentError(debateId: string, agentName: string, round?: number): boolean {
  const key = `${debateId}:${agentName}:${round ?? 'none'}`;
  const now = Date.now();
  const last = agentErrorTimestamps.get(key) || 0;
  if (now - last < AGENT_ERROR_THROTTLE_MS) {
    return false;
  }
  agentErrorTimestamps.set(key, now);
  return true;
}

/**
 * Create a generic stream event handler
 */
function createStreamEventHandler(eventType: StreamEvent['type']) {
  return (data: ParsedEventData, ctx: EventHandlerContext): void => {
    const eventData = data.data;
    const event: StreamEvent = {
      type: eventType,
      data: (eventData as Record<string, unknown>) || {},
      timestamp: (data.timestamp as number) || Date.now() / 1000,
    };
    ctx.addStreamEvent(event);
  };
}

/**
 * Handle audience_summary and audience_metrics events
 */
export function handleAudienceEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const event: StreamEvent = {
    type: data.type as 'audience_summary' | 'audience_metrics',
    data: (eventData as Record<string, unknown>) || {},
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };
  ctx.addStreamEvent(event);
}

/**
 * Handle grounded_verdict event (citations)
 */
export function handleGroundedVerdictEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const event: StreamEvent = {
    type: 'grounded_verdict',
    data: (eventData as Record<string, unknown>) || {},
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };
  ctx.addStreamEvent(event);
  ctx.setHasCitations(true);
}

/**
 * Handle vote event
 */
export function handleVoteEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const event: StreamEvent = {
    type: 'vote',
    data: (eventData as Record<string, unknown>) || {},
    timestamp: (data.timestamp as number) || Date.now() / 1000,
    agent: (data.agent as string) || (eventData?.agent as string),
  };
  ctx.addStreamEvent(event);
}

/**
 * Handle rhetorical_observation event
 */
export function handleRhetoricalObservationEvent(
  data: ParsedEventData,
  ctx: EventHandlerContext,
): void {
  const eventData = data.data;
  const event: StreamEvent = {
    type: 'rhetorical_observation',
    data: (eventData as Record<string, unknown>) || {},
    timestamp: (data.timestamp as number) || Date.now() / 1000,
    agent: (data.agent as string) || (eventData?.agent as string),
    round: (data.round as number) || (eventData?.round as number),
  };
  ctx.addStreamEvent(event);
}

/**
 * Handle hollow_consensus or trickster_intervention events
 */
export function handleTricksterEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const event: StreamEvent = {
    type: data.type as 'hollow_consensus' | 'trickster_intervention',
    data: (eventData as Record<string, unknown>) || {},
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };
  ctx.addStreamEvent(event);
}

/**
 * Handle agent_error event (agent failed but debate continues)
 */
export function handleAgentErrorEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const agentName = (data.agent as string) || (eventData?.agent as string) || 'unknown';
  const event: StreamEvent = {
    type: 'agent_error',
    data: (eventData as Record<string, unknown>) || {},
    timestamp: (data.timestamp as number) || Date.now() / 1000,
    agent: agentName,
  };
  ctx.addStreamEvent(event);

  if (shouldEmitAgentError(ctx.debateId, agentName, data.round as number)) {
    // Log for debugging but don't show error state - debate continues
    logger.warn(`[Agent Error] ${agentName}: ${eventData?.message}`);

    const message = (eventData?.message as string) || 'Agent failed during this phase';
    ctx.addMessageIfNew({
      agent: agentName,
      role: 'system',
      content: `[AGENT ERROR] ${message}`,
      round: data.round as number,
      timestamp: (data.timestamp as number) || Date.now() / 1000,
    });
  }
}

/**
 * Handle quick_classification event
 */
export function handleQuickClassificationEvent(
  data: ParsedEventData,
  ctx: EventHandlerContext,
): void {
  const eventData = data.data;

  // Always log classification for debugging (visible in browser console)
  logger.debug('[WS] QUICK_CLASSIFICATION received:', {
    question_type: eventData?.question_type,
    domain: eventData?.domain,
    complexity: eventData?.complexity,
    key_aspects: eventData?.key_aspects,
    timestamp: Date.now(),
  });

  const event: StreamEvent = {
    type: 'quick_classification',
    data: (eventData as Record<string, unknown>) || {},
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };
  ctx.addStreamEvent(event);
}

/**
 * Handle agent_preview event
 */
export function handleAgentPreviewEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const event: StreamEvent = {
    type: 'agent_preview',
    data: (eventData as Record<string, unknown>) || {},
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };
  ctx.addStreamEvent(event);

  if (process.env.NODE_ENV === 'development') {
    logger.debug('[WS] AGENT_PREVIEW:', eventData);
  }
}

/**
 * Handle context_preview event
 */
export function handleContextPreviewEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const event: StreamEvent = {
    type: 'context_preview',
    data: (eventData as Record<string, unknown>) || {},
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };
  ctx.addStreamEvent(event);

  if (process.env.NODE_ENV === 'development') {
    logger.debug('[WS] CONTEXT_PREVIEW:', eventData);
  }
}

/**
 * Handle heartbeat event (debate is still alive)
 */
export function handleHeartbeatEvent(data: ParsedEventData, _ctx: EventHandlerContext): void {
  const eventData = data.data;
  // Just log - this confirms the debate is still running
  logger.debug(`[Heartbeat] phase=${eventData?.phase} status=${eventData?.status}`);
}

/**
 * Handle evidence_found event (real-time evidence collection)
 */
export function handleEvidenceFoundEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const event: StreamEvent = {
    type: 'evidence_found',
    data: (eventData as Record<string, unknown>) || {},
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };
  ctx.addStreamEvent(event);

  // Also mark that we have citations available
  if ((eventData?.count as number) > 0) {
    ctx.setHasCitations(true);
  }
}

/**
 * Registry of analytics event handlers
 */
export const analyticsHandlers = {
  audience_summary: handleAudienceEvent,
  audience_metrics: handleAudienceEvent,
  grounded_verdict: handleGroundedVerdictEvent,
  uncertainty_analysis: createStreamEventHandler('uncertainty_analysis'),
  vote: handleVoteEvent,
  rhetorical_observation: handleRhetoricalObservationEvent,
  hollow_consensus: handleTricksterEvent,
  trickster_intervention: handleTricksterEvent,
  memory_recall: createStreamEventHandler('memory_recall'),
  flip_detected: createStreamEventHandler('flip_detected'),
  agent_error: handleAgentErrorEvent,
  phase_progress: createStreamEventHandler('phase_progress'),
  quick_classification: handleQuickClassificationEvent,
  agent_preview: handleAgentPreviewEvent,
  context_preview: handleContextPreviewEvent,
  heartbeat: handleHeartbeatEvent,
  evidence_found: handleEvidenceFoundEvent,
};
