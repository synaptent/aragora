/**
 * Handlers for message-related events
 * (synthesis, consensus, debate_message, agent_message, agent_response, critique)
 */

import type { StreamEvent } from '@/types/events';
import type { TranscriptMessage } from '../types';
import type { EventHandlerContext, ParsedEventData } from './types';

/**
 * Handle synthesis event - final debate summary
 */
export function handleSynthesisEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const synthesisContent = (eventData?.content as string) || '';

  if (!synthesisContent) return;

  const msg: TranscriptMessage = {
    agent: (data.agent as string) || (eventData?.agent as string) || 'synthesis-agent',
    role: 'synthesis',
    content: synthesisContent,
    round: (data.round as number) || (eventData?.round as number),
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };
  ctx.addMessageIfNew(msg);

  // Also track as stream event for analytics panels
  const streamEvent: StreamEvent = {
    type: 'synthesis',
    data: {
      agent: msg.agent,
      content: synthesisContent,
      confidence: eventData?.confidence as number,
    },
    timestamp: msg.timestamp || Date.now() / 1000,
  };
  ctx.addStreamEvent(streamEvent);
}

/**
 * Handle consensus event - agreement reached between agents
 */
export function handleConsensusEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const consensusData = data.data;
  const reached = consensusData?.reached as boolean;
  const confidence = (consensusData?.confidence as number) || 0;
  const answer = (consensusData?.answer as string) || '';
  const synthesis = (consensusData?.synthesis as string) || '';

  // Track consensus as stream event for analytics
  const streamEvent: StreamEvent = {
    type: 'consensus',
    data: { reached, confidence, answer, synthesis },
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };
  ctx.addStreamEvent(streamEvent);

  // Add status message
  const statusMsg: TranscriptMessage = {
    agent: 'system',
    role: 'consensus-status',
    content: `[CONSENSUS ${reached ? 'REACHED' : 'NOT REACHED'}] Confidence: ${Math.round(confidence * 100)}%`,
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };
  ctx.addMessageIfNew(statusMsg);

  // If there's a fallback synthesis in consensus data, add it as final synthesis
  const synthContent = synthesis || answer;
  if (synthContent) {
    const synthesisMsg: TranscriptMessage = {
      agent: 'synthesis-agent',
      role: 'synthesis',
      content: synthContent,
      timestamp: ((data.timestamp as number) || Date.now() / 1000) + 0.001,
    };
    ctx.addMessageIfNew(synthesisMsg);
  }
}

/**
 * Handle debate_message or agent_message events
 */
export function handleAgentMessageEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const msg: TranscriptMessage = {
    agent: (data.agent as string) || (eventData?.agent as string) || 'unknown',
    role: eventData?.role as string,
    content: (eventData?.content as string) || '',
    round: (data.round as number) || (eventData?.round as number),
    timestamp: (data.timestamp as number) || (eventData?.timestamp as number) || Date.now() / 1000,
  };

  // Include reasoning visibility fields when present in event data
  const confidenceScore =
    (eventData?.confidence_score as number | undefined) ??
    (eventData?.confidence as number | undefined) ??
    null;
  if (confidenceScore !== null && confidenceScore !== undefined) {
    msg.confidence_score = confidenceScore;
  }
  if (eventData?.reasoning_phase) {
    msg.reasoning_phase = eventData.reasoning_phase as string;
  }
  if (eventData?.thinking) {
    msg.thinking = eventData.thinking as string;
  }

  if (msg.content && ctx.addMessageIfNew(msg)) {
    const agentName = msg.agent;
    if (agentName) {
      ctx.setAgents((prev) => (prev.includes(agentName) ? prev : [...prev, agentName]));
    }
  }

  // Also track as stream event with reasoning fields forwarded
  const streamEventData: Record<string, unknown> = {
    agent: (data.agent as string) || (eventData?.agent as string) || 'unknown',
    content: (eventData?.content as string) || '',
    role: (eventData?.role as string) || '',
  };
  if (confidenceScore !== null && confidenceScore !== undefined) {
    streamEventData.confidence_score = confidenceScore;
  }
  if (eventData?.reasoning_phase) {
    streamEventData.reasoning_phase = eventData.reasoning_phase;
  }
  if (eventData?.thinking) {
    streamEventData.thinking = eventData.thinking;
  }
  const streamEvent: StreamEvent = {
    type: 'agent_message',
    data: streamEventData,
    timestamp: (data.timestamp as number) || Date.now() / 1000,
    round: (data.round as number) || (eventData?.round as number),
    agent: (data.agent as string) || (eventData?.agent as string),
  };
  ctx.addStreamEvent(streamEvent);
}

/**
 * Handle legacy agent_response events
 */
export function handleAgentResponseEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const msg: TranscriptMessage = {
    agent: (eventData?.agent as string) || 'unknown',
    role: eventData?.role as string,
    content: (eventData?.content as string) || (eventData?.response as string) || '',
    round: eventData?.round as number,
    timestamp: Date.now() / 1000,
  };

  if (msg.content) {
    ctx.addMessageIfNew(msg);
  }
}

/**
 * Handle critique events
 */
export function handleCritiqueEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const issues = eventData?.issues as string[] | undefined;
  const target = (eventData?.target as string) || 'unknown';
  const critic = (data.agent as string) || (eventData?.agent as string) || 'unknown';

  const rawContent =
    (eventData?.content as string | undefined) ||
    (eventData?.full_content as string | undefined) ||
    (eventData?.fullContent as string | undefined) ||
    (eventData?.reasoning as string | undefined);
  const errorDetail = eventData?.error as string | undefined;

  // Build critique content: prefer full content, fallback to issues, then error/placeholder
  let critiqueBody = '';
  if (rawContent && rawContent.trim()) {
    critiqueBody = rawContent;
  } else if (issues && issues.length > 0) {
    critiqueBody = issues.join('; ');
  } else if (errorDetail) {
    critiqueBody = `[Critique error: ${errorDetail}]`;
  } else {
    critiqueBody = '[Critique content not available]';
  }

  const msg: TranscriptMessage = {
    agent: critic,
    role: 'critic',
    content: `[CRITIQUE → ${target}] ${critiqueBody}`,
    round: (data.round as number) || (eventData?.round as number),
    timestamp: (data.timestamp as number) || Date.now() / 1000,
  };

  if (msg.content) {
    ctx.addMessageIfNew(msg);
  }
}

/**
 * Registry of message event handlers
 */
export const messageHandlers = {
  synthesis: handleSynthesisEvent,
  consensus: handleConsensusEvent,
  debate_message: handleAgentMessageEvent,
  agent_message: handleAgentMessageEvent,
  agent_response: handleAgentResponseEvent,
  critique: handleCritiqueEvent,
};
