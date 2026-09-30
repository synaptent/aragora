/**
 * Handlers for debate lifecycle events
 * (sync, debate_start, debate_end, debate_error)
 */

import type { SettlementMetadata, TranscriptMessage } from '../types';
import type { EventHandlerContext, ParsedEventData } from './types';

function normalizeMode(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const mode = raw.trim();
  return mode ? mode : null;
}

function normalizeSettlement(raw: unknown): SettlementMetadata | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  return raw as SettlementMetadata;
}

/**
 * Handle sync event - full state restore for existing debates
 */
export function handleSyncEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const syncData = data.data;
  if (!syncData) return;

  // Set task and agents
  if (syncData.task) {
    ctx.setTask(syncData.task as string);
  }
  if (syncData.agents && Array.isArray(syncData.agents)) {
    ctx.setAgents(syncData.agents as string[]);
  }
  const mode = normalizeMode(syncData.mode);
  if (mode) {
    ctx.setDebateMode(mode);
  }
  const settlement = normalizeSettlement(syncData.settlement);
  if (settlement) {
    ctx.setSettlementMetadata(settlement);
  }

  // Restore messages from sync
  if (syncData.messages && Array.isArray(syncData.messages)) {
    const syncMessages = syncData.messages as Array<Record<string, unknown>>;
    for (const msg of syncMessages) {
      const transcriptMsg: TranscriptMessage = {
        agent: (msg.agent as string) || 'unknown',
        role: msg.role as string | undefined,
        content: (msg.content as string) || '',
        round: msg.round as number | undefined,
        timestamp: (msg.timestamp as number) || Date.now() / 1000,
      };
      if (transcriptMsg.content) {
        ctx.addMessageIfNew(transcriptMsg);
      }
    }
  }

  // Set status based on whether debate has ended
  if (syncData.ended) {
    ctx.setStatus('complete');
    ctx.setHasReceivedDebateStart(true);
    ctx.clearDebateStartTimeout();
  } else if (syncData.task || (syncData.agents && (syncData.agents as string[]).length > 0)) {
    // Debate is in progress
    ctx.setHasReceivedDebateStart(true);
    ctx.clearDebateStartTimeout();
  }
}

/**
 * Handle debate_start event - debate has begun
 */
export function handleDebateStartEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;

  // Only update task if provided and non-empty (don't overwrite with fallback)
  const taskFromStart = eventData?.task as string;
  if (taskFromStart && taskFromStart.trim()) {
    ctx.setTask(taskFromStart);
  }
  ctx.setAgents((eventData?.agents as string[]) || []);
  const mode = normalizeMode(eventData?.mode);
  if (mode) {
    ctx.setDebateMode(mode);
  }
  const settlement = normalizeSettlement(eventData?.settlement);
  if (settlement) {
    ctx.setSettlementMetadata(settlement);
  }
  ctx.setHasReceivedDebateStart(true);
  ctx.clearDebateStartTimeout();
}

/**
 * Handle debate_end event - debate has concluded
 */
export function handleDebateEndEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const endData = data.data;
  const hasError = endData?.error as string | undefined;

  // Set status based on whether there was an error
  ctx.setStatus(hasError ? 'error' : 'complete');

  const summary = endData?.summary as Record<string, unknown> | undefined;
  const taskFromEvent = (endData?.task as string) || (summary?.task as string);
  const mode = normalizeMode(endData?.mode) || normalizeMode(summary?.mode);
  if (mode) {
    ctx.setDebateMode(mode);
  }
  const settlement =
    normalizeSettlement(endData?.settlement) || normalizeSettlement(summary?.settlement);
  if (settlement) {
    ctx.setSettlementMetadata(settlement);
  }

  ctx.setTask((prev) => {
    // If we have a task from the event, use it
    if (taskFromEvent) return taskFromEvent;
    // If current task is the fallback, clear it
    if (prev === 'Debate in progress...') return hasError ? 'Debate failed' : 'Debate concluded';
    // Otherwise keep existing task
    return prev;
  });

  ctx.clearDebateStartTimeout();
}

/**
 * Handle debate_error event - debate failed to start
 */
export function handleDebateErrorEvent(data: ParsedEventData, ctx: EventHandlerContext): void {
  const eventData = data.data;
  const errorMsg =
    (eventData?.message as string) || (eventData?.error as string) || 'Debate failed to start';

  ctx.setStatus('error');
  ctx.setError('Debate failed to start');
  ctx.setErrorDetails(errorMsg);
  ctx.clearDebateStartTimeout();

  ctx.errorCallbackRef.current?.(errorMsg);
}

/**
 * Registry of lifecycle event handlers
 */
export const lifecycleHandlers = {
  sync: handleSyncEvent,
  debate_start: handleDebateStartEvent,
  debate_end: handleDebateEndEvent,
  debate_error: handleDebateErrorEvent,
};
