interface LeaderboardAgentLike {
  name?: string;
}

interface LeaderboardAgentsPayload {
  agents?: LeaderboardAgentLike[];
  leaderboard?: LeaderboardAgentLike[];
}

export function extractLeaderboardAgentNames(data: LeaderboardAgentsPayload): string[] {
  const entries = data.leaderboard ?? data.agents ?? [];
  return entries.map((entry) => entry.name?.trim()).filter((name): name is string => Boolean(name));
}
