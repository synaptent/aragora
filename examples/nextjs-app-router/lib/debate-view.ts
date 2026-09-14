import type { Debate } from '@aragora/sdk';

type StoredDebate = Debate & {
  messages?: NonNullable<Debate['rounds']>[number]['messages'];
};

export function formatPercentage(value: number | undefined): string {
  return value === undefined || !Number.isFinite(value)
    ? 'Not reported'
    : `${(value * 100).toFixed(1)}%`;
}

export function debateView(debate: StoredDebate) {
  const rounds = Array.isArray(debate.rounds) ? debate.rounds : [];
  const roundMessages = rounds.flatMap(round =>
    round.messages.map(message => ({ ...message, round: message.round ?? round.round_number }))
  );
  const savedMessages = Array.isArray(debate.messages) ? debate.messages : [];
  return {
    roundsCompleted: debate.rounds_used ?? rounds.length,
    answer: debate.consensus?.final_answer ?? debate.consensus?.conclusion ?? debate.final_answer,
    confidence: formatPercentage(debate.consensus?.confidence),
    agreement: formatPercentage(debate.consensus?.agreement),
    messages: roundMessages.length > 0 ? roundMessages : savedMessages,
  };
}
