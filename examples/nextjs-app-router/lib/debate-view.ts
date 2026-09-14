import type { Debate } from '@aragora/sdk';

export function formatPercentage(value: number | undefined): string {
  return value === undefined || !Number.isFinite(value)
    ? 'Not reported'
    : `${(value * 100).toFixed(1)}%`;
}

export function debateView(debate: Debate) {
  const rounds = Array.isArray(debate.rounds) ? debate.rounds : [];
  return {
    roundsCompleted: debate.rounds_used ?? rounds.length,
    answer: debate.consensus?.final_answer ?? debate.consensus?.conclusion ?? debate.final_answer,
    confidence: formatPercentage(debate.consensus?.confidence),
    agreement: formatPercentage(debate.consensus?.agreement),
    messages: rounds.flatMap(round =>
      round.messages.map(message => ({
        ...message,
        round: message.round ?? round.round_number,
      }))
    ),
  };
}
