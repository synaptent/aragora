import { useMemo } from 'react';
import type { StreamEvent } from '@/types/events';
import type { RoundData, AuditState } from './types';
import { AUDIT_ROUNDS } from './types';

export function useAuditData(events: StreamEvent[]) {
  return useMemo(() => {
    const rounds: Record<number, RoundData> = {};
    let maxRound = 0;
    const state: AuditState = { findings: [] };

    // Initialize rounds
    AUDIT_ROUNDS.forEach((r) => {
      rounds[r.round] = { round: r.round, messages: [], status: 'pending' };
    });

    // Process all event types
    events.forEach((event) => {
      // Handle audit_start event
      if (event.type === 'audit_start') {
        state.auditId = event.data?.audit_id as string;
        state.task = event.data?.task as string;
        state.agents = event.data?.agents as string[];
      }

      // Handle audit_round event (from new Deep Audit streaming)
      if (event.type === 'audit_round') {
        const round = (event.data?.round as number) || event.round || 1;
        if (round > maxRound) maxRound = round;

        if (rounds[round]) {
          rounds[round].name = event.data?.name as string;
          rounds[round].cognitiveRole = event.data?.cognitive_role as string;
          rounds[round].durationMs = event.data?.duration_ms as number;
          rounds[round].status = 'complete';

          // Add messages from this round
          const messages =
            (event.data?.messages as Array<{
              agent: string;
              content: string;
              confidence?: number;
            }>) || [];
          messages.forEach((msg) => {
            rounds[round].messages.push({
              agent: msg.agent,
              content: msg.content,
              role: 'analyst',
              cognitiveRole: event.data?.cognitive_role as string,
              confidence: msg.confidence,
              citations: 0,
              timestamp: event.timestamp,
            });
          });
        }
      }

      // Handle audit_finding event
      if (event.type === 'audit_finding') {
        state.findings.push({
          category: event.data?.category as 'unanimous' | 'split' | 'risk' | 'insight',
          summary: (event.data?.summary as string) || '',
          details: (event.data?.details as string) || '',
          agents_agree: (event.data?.agents_agree as string[]) || [],
          agents_disagree: (event.data?.agents_disagree as string[]) || [],
          confidence: (event.data?.confidence as number) || 0,
          citations: [],
          severity: (event.data?.severity as number) || 0,
        });
      }

      // Handle audit_cross_exam event
      if (event.type === 'audit_cross_exam') {
        state.crossExamNotes = event.data?.notes as string;
      }

      // Handle audit_verdict event
      if (event.type === 'audit_verdict') {
        state.verdict = {
          recommendation: (event.data?.recommendation as string) || '',
          confidence: (event.data?.confidence as number) || 0,
          unanimousIssues: (event.data?.unanimous_issues as string[]) || [],
          splitOpinions: (event.data?.split_opinions as string[]) || [],
          riskAreas: (event.data?.risk_areas as string[]) || [],
        };
      }

      // Also handle legacy agent_message events for backwards compatibility
      if (event.type === 'agent_message' && event.agent) {
        const round = event.round || 1;
        if (round > maxRound) maxRound = round;

        if (rounds[round]) {
          rounds[round].messages.push({
            agent: event.agent,
            content: (event.data?.content as string) || '',
            role: (event.data?.role as string) || 'proposer',
            cognitiveRole: event.data?.cognitive_role as string,
            confidence: event.data?.confidence as number,
            citations: (event.data?.citations as unknown[])?.length,
            timestamp: event.timestamp,
          });
        }
      }
    });

    // Update statuses based on maxRound
    AUDIT_ROUNDS.forEach((r) => {
      if (rounds[r.round].status !== 'complete') {
        if (r.round < maxRound) {
          rounds[r.round].status = 'complete';
        } else if (r.round === maxRound && rounds[r.round].messages.length > 0) {
          rounds[r.round].status = 'active';
        }
      }
    });

    return { roundData: Object.values(rounds), auditState: state };
  }, [events]);
}
