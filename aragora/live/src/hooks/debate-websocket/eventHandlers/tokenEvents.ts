/**
 * Handlers for token streaming events
 * (token_start, token_delta, token_end)
 */

import { logger } from '@/utils/logger';
import type { TranscriptMessage } from '../types';
import { makeStreamingKey } from '../utils';
import type { EventHandlerContext, ParsedEventData } from './types';

/**
 * Handle token_start event - begin streaming for an agent
 */
export function handleTokenStartEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const agent = (data.agent as string) || (eventData?.agent as string);
  const taskId = (data.task_id as string) || '';

  if (!agent) return;

  if (process.env.NODE_ENV === 'development') {
    logger.debug(`[WS] TOKEN_START: ${agent} (task=${taskId || 'default'})`);
  }

  const streamKey = makeStreamingKey(agent, taskId);

  ctx.setStreamingMessages((prev) => {
    const updated = new Map(prev);
    updated.set(streamKey, {
      agent,
      taskId,
      content: '',
      isComplete: false,
      startTime: Date.now(),
      expectedSeq: 1,
      pendingTokens: new Map(),
      reasoning: [],
      evidence: [],
      confidence: null,
      reasoningPhase: '',
    });
    return updated;
  });

  ctx.setAgents((prev) => (prev.includes(agent) ? prev : [...prev, agent]));
}

/**
 * Handle token_delta event - append token to streaming message
 */
export function handleTokenDeltaEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const agent = (data.agent as string) || (eventData?.agent as string);
  const taskId = (data.task_id as string) || '';
  const token = (eventData?.token as string) || '';
  const agentSeq = (data.agent_seq as number) || 0;

  if (!agent || !token) return;

  const streamKey = makeStreamingKey(agent, taskId);

  ctx.setStreamingMessages((prev) => {
    const updated = new Map(prev);
    const existing = updated.get(streamKey);

    if (existing) {
      // If we have sequence info, use it for ordering
      if (agentSeq > 0) {
        // Check if this is the expected sequence
        if (agentSeq === existing.expectedSeq) {
          // Token is in order - append it
          let newContent = existing.content + token;
          let nextExpected = agentSeq + 1;

          // Check if we have buffered tokens that can now be appended
          const pending = new Map(existing.pendingTokens);
          while (pending.has(nextExpected)) {
            newContent += pending.get(nextExpected)!;
            pending.delete(nextExpected);
            nextExpected++;
          }

          updated.set(streamKey, {
            ...existing,
            content: newContent,
            expectedSeq: nextExpected,
            pendingTokens: pending,
          });
        } else if (agentSeq > existing.expectedSeq) {
          // Token arrived out of order - buffer it
          const pending = new Map(existing.pendingTokens);
          pending.set(agentSeq, token);
          updated.set(streamKey, { ...existing, pendingTokens: pending });
        }
        // Ignore tokens with seq < expectedSeq (duplicate/old)
      } else {
        // No sequence info - fall back to simple append (backward compat)
        updated.set(streamKey, { ...existing, content: existing.content + token });
      }
    } else {
      // First token for this agent+task (no token_start received)
      updated.set(streamKey, {
        agent,
        taskId,
        content: token,
        isComplete: false,
        startTime: Date.now(),
        expectedSeq: agentSeq > 0 ? agentSeq + 1 : 1,
        pendingTokens: new Map(),
        reasoning: [],
        evidence: [],
        confidence: null,
        reasoningPhase: '',
      });
    }

    return updated;
  });
}

/**
 * Handle token_end event - complete streaming message
 */
export function handleTokenEndEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const agent = (data.agent as string) || (eventData?.agent as string);
  const taskId = (data.task_id as string) || '';

  if (!agent) return;

  const streamKey = makeStreamingKey(agent, taskId);

  ctx.setStreamingMessages((prev) => {
    const updated = new Map(prev);
    const existing = updated.get(streamKey);

    if (existing) {
      // Flush any remaining buffered tokens in order
      let finalContent = existing.content;
      if (existing.pendingTokens.size > 0) {
        const sortedSeqs = Array.from(existing.pendingTokens.keys()).sort((a, b) => a - b);
        for (const seq of sortedSeqs) {
          finalContent += existing.pendingTokens.get(seq)!;
        }
      }

      // Log completion stats in development
      if (process.env.NODE_ENV === 'development') {
        const duration = Date.now() - existing.startTime;
        logger.debug(`[WS] TOKEN_END: ${agent} - ${finalContent.length} chars in ${duration}ms`);
      }

      if (finalContent) {
        const msg: TranscriptMessage = {
          agent,
          content: finalContent,
          timestamp: Date.now() / 1000,
        };

        // Propagate accumulated reasoning metadata from streaming state
        if (existing.confidence !== null && existing.confidence !== undefined) {
          msg.confidence_score = existing.confidence;
        }
        if (existing.reasoningPhase) {
          msg.reasoning_phase = existing.reasoningPhase;
        }
        if (existing.reasoning.length > 0) {
          msg.thinking = existing.reasoning.map((r) => r.thinking).join(' ');
        }

        // Use addMessageIfNew which handles deduplication
        ctx.addMessageIfNew(msg);
      }
    }

    updated.delete(streamKey);
    return updated;
  });
}

/**
 * Handle agent_thinking event - add reasoning step to streaming message
 */
export function handleAgentThinkingEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const agent = (data.agent as string) || (eventData?.agent as string);
  const thinking = (eventData?.thinking as string) || '';
  const step = (eventData?.step as number) || undefined;

  if (!agent || !thinking) return;

  ctx.setStreamingMessages((prev) => {
    const updated = new Map(prev);
    for (const [key, msg] of updated.entries()) {
      if (msg.agent === agent && !msg.isComplete) {
        updated.set(key, {
          ...msg,
          reasoning: [...msg.reasoning, { thinking, timestamp: Date.now(), step }],
        });
        break;
      }
    }
    return updated;
  });

  ctx.addStreamEvent({
    type: 'agent_thinking',
    data: eventData as Record<string, unknown>,
    agent,
    timestamp: data.timestamp || Date.now() / 1000,
  });
}

/**
 * Handle agent_evidence event - add evidence sources to streaming message
 */
export function handleAgentEvidenceEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const agent = (data.agent as string) || (eventData?.agent as string);
  const sources =
    (eventData?.sources as Array<{ title: string; url?: string; relevance?: number }>) || [];

  if (!agent || sources.length === 0) return;

  ctx.setStreamingMessages((prev) => {
    const updated = new Map(prev);
    for (const [key, msg] of updated.entries()) {
      if (msg.agent === agent && !msg.isComplete) {
        updated.set(key, { ...msg, evidence: [...msg.evidence, ...sources] });
        break;
      }
    }
    return updated;
  });

  ctx.addStreamEvent({
    type: 'agent_evidence',
    data: eventData as Record<string, unknown>,
    agent,
    timestamp: data.timestamp || Date.now() / 1000,
  });
}

/**
 * Handle agent_confidence event - update confidence on streaming message
 */
export function handleAgentConfidenceEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const agent = (data.agent as string) || (eventData?.agent as string);
  const confidence = (eventData?.confidence as number) ?? null;

  if (!agent || confidence === null) return;

  ctx.setStreamingMessages((prev) => {
    const updated = new Map(prev);
    for (const [key, msg] of updated.entries()) {
      if (msg.agent === agent && !msg.isComplete) {
        updated.set(key, { ...msg, confidence });
        break;
      }
    }
    return updated;
  });

  ctx.addStreamEvent({
    type: 'agent_confidence',
    data: eventData as Record<string, unknown>,
    agent,
    timestamp: data.timestamp || Date.now() / 1000,
  });
}

/**
 * Handle agent_reasoning event - update reasoning phase on streaming message
 */
export function handleAgentReasoningEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const agent = (data.agent as string) || (eventData?.agent as string);
  const phase = (eventData?.phase as string) || (eventData?.reasoning_phase as string) || '';

  if (!agent) return;

  if (phase) {
    ctx.setStreamingMessages((prev) => {
      const updated = new Map(prev);
      for (const [key, msg] of updated.entries()) {
        if (msg.agent === agent && !msg.isComplete) {
          updated.set(key, { ...msg, reasoningPhase: phase });
          break;
        }
      }
      return updated;
    });
  }

  ctx.addStreamEvent({
    type: 'agent_reasoning',
    data: eventData as Record<string, unknown>,
    agent,
    timestamp: data.timestamp || Date.now() / 1000,
  });
}

/**
 * Registry of token event handlers
 */
export const tokenHandlers = {
  token_start: handleTokenStartEvent,
  token_delta: handleTokenDeltaEvent,
  token_end: handleTokenEndEvent,
  agent_thinking: handleAgentThinkingEvent,
  agent_reasoning: handleAgentReasoningEvent,
  agent_evidence: handleAgentEvidenceEvent,
  agent_confidence: handleAgentConfidenceEvent,
};
