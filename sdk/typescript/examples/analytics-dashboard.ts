/**
 * Analytics Dashboard Example
 *
 * Demonstrates analytics and metrics operations using the Aragora SDK:
 * - Dashboard overview and summary metrics
 * - Debate analytics and trends
 * - Cost tracking and usage reports
 * - Agent performance analytics
 *
 * Usage:
 *   npx ts-node examples/analytics-dashboard.ts
 *
 * Environment:
 *   ARAGORA_API_KEY - Your API key
 *   ARAGORA_API_URL - API URL (default: https://api.aragora.ai)
 */

import {
  createClient,
  AragoraError,
  type AragoraConfig,
} from '@aragora/sdk';

// =============================================================================
// Configuration
// =============================================================================

const config: AragoraConfig = {
  baseUrl: process.env.ARAGORA_API_URL || 'https://api.aragora.ai',
  apiKey: process.env.ARAGORA_API_KEY,
  timeout: 30000,
};

// =============================================================================
// Dashboard Overview
// =============================================================================

async function demonstrateDashboardOverview(): Promise<void> {
  console.log('=== Dashboard Overview ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Get Summary Metrics
  // -------------------------------------------------------------------------
  console.log('1. Summary Metrics');
  console.log('-'.repeat(40));

  try {
    const summary = await client.analytics.getSummary({
      time_range: '30d',
    }) as {
      total_debates: number;
      consensus_rate: number;
      average_rounds: number;
      active_agents: number;
      total_tokens: number;
      cost_estimate: number;
      top_topics: string[];
    };

    console.log(`  Total Debates: ${summary.total_debates}`);
    console.log(`  Consensus Rate: ${(summary.consensus_rate * 100).toFixed(1)}%`);
    console.log(`  Average Rounds: ${summary.average_rounds.toFixed(1)}`);
    console.log(`  Active Agents: ${summary.active_agents}`);
    console.log(`  Total Tokens: ${formatNumber(summary.total_tokens)}`);
    console.log(`  Cost Estimate: $${summary.cost_estimate.toFixed(2)}`);

    if (summary.top_topics?.length) {
      console.log(`\n  Top Topics:`);
      for (const topic of summary.top_topics.slice(0, 5)) {
        console.log(`    - ${topic}`);
      }
    }
  } catch (error) {
    handleError('Get summary', error);
  }

  // -------------------------------------------------------------------------
  // Get Debates Overview
  // -------------------------------------------------------------------------
  console.log('\n2. Debates Overview');
  console.log('-'.repeat(40));

  try {
    const debatesOverview = await client.analytics.getDebatesOverview();

    console.log(`  Total Debates: ${debatesOverview.total}`);
    console.log(`  Consensus Rate: ${(debatesOverview.consensus_rate * 100).toFixed(1)}%`);
    console.log(`  Average Rounds: ${debatesOverview.average_rounds.toFixed(1)}`);
  } catch (error) {
    handleError('Get debates overview', error);
  }

  // -------------------------------------------------------------------------
  // Get Ranking Stats
  // -------------------------------------------------------------------------
  console.log('\n3. Ranking Statistics');
  console.log('-'.repeat(40));

  try {
    const rankingStats = await client.analytics.rankingStats();

    console.log(`  Total Ranked Agents: ${rankingStats.total_agents}`);
    console.log(`  Average ELO: ${rankingStats.avg_elo.toFixed(0)}`);
    console.log(`  ELO Range: ${rankingStats.min_elo} - ${rankingStats.max_elo}`);
    console.log(`  Total Debates: ${rankingStats.total_debates}`);

    if (rankingStats.top_agent) {
      console.log(`\n  Top Agent: ${rankingStats.top_agent.name}`);
      console.log(`    ELO: ${rankingStats.top_agent.elo}`);
      console.log(`    Win Rate: ${(rankingStats.top_agent.win_rate * 100).toFixed(1)}%`);
    }
  } catch (error) {
    handleError('Get ranking stats', error);
  }

  // -------------------------------------------------------------------------
  // Get Memory Stats
  // -------------------------------------------------------------------------
  console.log('\n4. Memory Statistics');
  console.log('-'.repeat(40));

  try {
    const memoryStats = await client.analytics.memoryStats();

    console.log(`  Total Entries: ${memoryStats.total_entries}`);
    console.log(`  Storage Used: ${formatBytes(memoryStats.storage_bytes)}`);
    console.log(`  Cache Hit Rate: ${(memoryStats.cache_hit_rate * 100).toFixed(1)}%`);
    console.log(`  Health: ${memoryStats.health_status}`);

    console.log(`\n  By Tier:`);
    for (const [tier, count] of Object.entries(memoryStats.tier_counts)) {
      console.log(`    ${tier}: ${count}`);
    }
  } catch (error) {
    handleError('Get memory stats', error);
  }
}

// =============================================================================
// Debate Analytics
// =============================================================================

async function demonstrateDebateAnalytics(): Promise<void> {
  console.log('\n=== Debate Analytics ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Get Debate Trends
  // -------------------------------------------------------------------------
  console.log('1. Debate Trends');
  console.log('-'.repeat(40));

  try {
    const trends = await client.analytics.getDebateTrends({
      time_range: '30d',
      granularity: 'day',
    }) as {
      data_points: Array<{
        date: string;
        count: number;
        consensus_rate: number;
      }>;
      total_debates: number;
      growth_rate: number;
    };

    console.log(`  Total Debates (30d): ${trends.total_debates}`);
    console.log(`  Growth Rate: ${trends.growth_rate >= 0 ? '+' : ''}${(trends.growth_rate * 100).toFixed(1)}%`);

    console.log('\n  Recent Activity:');
    for (const point of trends.data_points.slice(-7)) {
      console.log(`    ${point.date}: ${point.count} debates (${(point.consensus_rate * 100).toFixed(0)}% consensus)`);
    }
  } catch (error) {
    handleError('Get debate trends', error);
  }

  // -------------------------------------------------------------------------
  // Get Topic Distribution
  // -------------------------------------------------------------------------
  console.log('\n2. Topic Distribution');
  console.log('-'.repeat(40));

  try {
    const topics = await client.analytics.getDebateTopics({
      time_range: '30d',
      limit: 10,
    }) as {
      topics: Array<{
        topic: string;
        count: number;
        consensus_rate: number;
        average_duration: number;
      }>;
    };

    console.log('  Top Topics:\n');

    for (const topic of topics.topics) {
      console.log(`  ${topic.topic}`);
      console.log(`    Debates: ${topic.count}`);
      console.log(`    Consensus Rate: ${(topic.consensus_rate * 100).toFixed(1)}%`);
      console.log(`    Avg Duration: ${topic.average_duration}s`);
    }
  } catch (error) {
    handleError('Get topics', error);
  }

  // -------------------------------------------------------------------------
  // Get Outcome Distribution
  // -------------------------------------------------------------------------
  console.log('\n3. Outcome Distribution');
  console.log('-'.repeat(40));

  try {
    const outcomes = await client.analytics.getDebateOutcomes({
      time_range: '30d',
    }) as {
      total: number;
      outcomes: {
        consensus: number;
        majority: number;
        split: number;
        timeout: number;
        error: number;
      };
    };

    console.log(`  Total Debates: ${outcomes.total}\n`);
    console.log(`  Outcomes:`);
    console.log(`    Consensus: ${outcomes.outcomes.consensus} (${((outcomes.outcomes.consensus / outcomes.total) * 100).toFixed(1)}%)`);
    console.log(`    Majority: ${outcomes.outcomes.majority} (${((outcomes.outcomes.majority / outcomes.total) * 100).toFixed(1)}%)`);
    console.log(`    Split: ${outcomes.outcomes.split} (${((outcomes.outcomes.split / outcomes.total) * 100).toFixed(1)}%)`);
    console.log(`    Timeout: ${outcomes.outcomes.timeout} (${((outcomes.outcomes.timeout / outcomes.total) * 100).toFixed(1)}%)`);
    console.log(`    Error: ${outcomes.outcomes.error} (${((outcomes.outcomes.error / outcomes.total) * 100).toFixed(1)}%)`);
  } catch (error) {
    handleError('Get outcomes', error);
  }

  // -------------------------------------------------------------------------
  // Get Consensus Quality
  // -------------------------------------------------------------------------
  console.log('\n4. Consensus Quality');
  console.log('-'.repeat(40));

  try {
    const quality = await client.analytics.consensusQuality({ period: '30d' });

    console.log(`  Average Confidence: ${(quality.avg_confidence * 100).toFixed(1)}%`);
    console.log(`  Average Agreement: ${(quality.avg_agreement * 100).toFixed(1)}%`);
    console.log(`  High Quality Rate: ${(quality.high_quality_rate * 100).toFixed(1)}%`);
    console.log(`  Unanimous Rate: ${(quality.unanimous_rate * 100).toFixed(1)}%`);
    console.log(`  Contested Rate: ${(quality.contested_rate * 100).toFixed(1)}%`);
    console.log(`  Sample Size: ${quality.sample_size}`);

    if (quality.by_domain) {
      console.log('\n  By Domain:');
      for (const [domain, metrics] of Object.entries(quality.by_domain)) {
        const domainMetrics = metrics as { avg_confidence: number; count: number };
        console.log(`    ${domain}: ${(domainMetrics.avg_confidence * 100).toFixed(1)}% (${domainMetrics.count} debates)`);
      }
    }
  } catch (error) {
    handleError('Get consensus quality', error);
  }

  // -------------------------------------------------------------------------
  // Get Disagreement Analytics
  // -------------------------------------------------------------------------
  console.log('\n5. Disagreement Analytics');
  console.log('-'.repeat(40));

  try {
    const disagreements = await client.analytics.disagreements({ period: '30d' });

    console.log(`  Total Disagreements: ${disagreements.total}`);
    console.log(`  Disagreement Rate: ${(disagreements.rate * 100).toFixed(1)}%`);
    console.log(`  Resolution Rate: ${(disagreements.resolution_rate * 100).toFixed(1)}%`);

    console.log('\n  Top Disagreement Pairs:');
    for (const pair of disagreements.top_pairs.slice(0, 3)) {
      console.log(`    ${pair.agent_a} vs ${pair.agent_b}: ${pair.count} times`);
    }

    if (disagreements.by_topic?.length) {
      console.log('\n  By Topic:');
      for (const topic of disagreements.by_topic.slice(0, 3)) {
        console.log(`    ${topic.topic}: ${topic.count} disagreements`);
      }
    }
  } catch (error) {
    handleError('Get disagreements', error);
  }
}

// =============================================================================
// Cost Tracking
// =============================================================================

async function demonstrateCostTracking(): Promise<void> {
  console.log('\n=== Cost Tracking ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Get Token Usage Summary
  // -------------------------------------------------------------------------
  console.log('1. Token Usage Summary');
  console.log('-'.repeat(40));

  try {
    const tokenSummary = await client.analytics.getTokenSummary({
      days: 30,
    }) as {
      total_tokens: number;
      input_tokens: number;
      output_tokens: number;
      cost_estimate: number;
      by_provider: Record<string, {
        tokens: number;
        cost: number;
      }>;
    };

    console.log(`  Total Tokens: ${formatNumber(tokenSummary.total_tokens)}`);
    console.log(`  Input Tokens: ${formatNumber(tokenSummary.input_tokens)}`);
    console.log(`  Output Tokens: ${formatNumber(tokenSummary.output_tokens)}`);
    console.log(`  Estimated Cost: $${tokenSummary.cost_estimate.toFixed(2)}`);

    console.log('\n  By Provider:');
    for (const [provider, stats] of Object.entries(tokenSummary.by_provider)) {
      console.log(`    ${provider}:`);
      console.log(`      Tokens: ${formatNumber(stats.tokens)}`);
      console.log(`      Cost: $${stats.cost.toFixed(2)}`);
    }
  } catch (error) {
    handleError('Get token summary', error);
  }

  // -------------------------------------------------------------------------
  // Get Token Trends
  // -------------------------------------------------------------------------
  console.log('\n2. Token Usage Trends');
  console.log('-'.repeat(40));

  try {
    const tokenTrends = await client.analytics.getTokenTrends({
      days: 14,
      granularity: 'day',
    }) as {
      data_points: Array<{
        date: string;
        tokens: number;
        cost: number;
      }>;
      trend: 'increasing' | 'decreasing' | 'stable';
      avg_daily: number;
    };

    console.log(`  Trend: ${tokenTrends.trend}`);
    console.log(`  Average Daily: ${formatNumber(tokenTrends.avg_daily)} tokens`);

    console.log('\n  Last 7 Days:');
    for (const point of tokenTrends.data_points.slice(-7)) {
      console.log(`    ${point.date}: ${formatNumber(point.tokens)} ($${point.cost.toFixed(2)})`);
    }
  } catch (error) {
    handleError('Get token trends', error);
  }

  // -------------------------------------------------------------------------
  // Get Cost Breakdown
  // -------------------------------------------------------------------------
  console.log('\n3. Cost Breakdown');
  console.log('-'.repeat(40));

  try {
    const costBreakdown = await client.analytics.getCostBreakdown({
      time_range: '30d',
    }) as {
      total_cost: number;
      by_provider: Record<string, number>;
      by_model: Record<string, number>;
      by_category: {
        debates: number;
        knowledge: number;
        analysis: number;
        other: number;
      };
    };

    console.log(`  Total Cost (30d): $${costBreakdown.total_cost.toFixed(2)}`);

    console.log('\n  By Provider:');
    for (const [provider, cost] of Object.entries(costBreakdown.by_provider)) {
      const percentage = (cost / costBreakdown.total_cost * 100).toFixed(1);
      console.log(`    ${provider}: $${cost.toFixed(2)} (${percentage}%)`);
    }

    console.log('\n  By Model:');
    for (const [model, cost] of Object.entries(costBreakdown.by_model)) {
      console.log(`    ${model}: $${cost.toFixed(2)}`);
    }

    console.log('\n  By Category:');
    console.log(`    Debates: $${costBreakdown.by_category.debates.toFixed(2)}`);
    console.log(`    Knowledge: $${costBreakdown.by_category.knowledge.toFixed(2)}`);
    console.log(`    Analysis: $${costBreakdown.by_category.analysis.toFixed(2)}`);
    console.log(`    Other: $${costBreakdown.by_category.other.toFixed(2)}`);
  } catch (error) {
    handleError('Get cost breakdown', error);
  }

  // -------------------------------------------------------------------------
  // Get Provider Breakdown
  // -------------------------------------------------------------------------
  console.log('\n4. Provider Breakdown');
  console.log('-'.repeat(40));

  try {
    const providerBreakdown = await client.analytics.getProviderBreakdown({
      days: 30,
    }) as {
      providers: Array<{
        name: string;
        models: Array<{
          model: string;
          input_tokens: number;
          output_tokens: number;
          requests: number;
          cost: number;
        }>;
        total_cost: number;
      }>;
    };

    for (const provider of providerBreakdown.providers) {
      console.log(`\n  ${provider.name} (Total: $${provider.total_cost.toFixed(2)}):`);

      for (const model of provider.models.slice(0, 3)) {
        console.log(`    ${model.model}:`);
        console.log(`      Requests: ${formatNumber(model.requests)}`);
        console.log(`      Tokens: ${formatNumber(model.input_tokens)} in / ${formatNumber(model.output_tokens)} out`);
        console.log(`      Cost: $${model.cost.toFixed(2)}`);
      }
    }
  } catch (error) {
    handleError('Get provider breakdown', error);
  }
}

// =============================================================================
// Agent Performance Analytics
// =============================================================================

async function demonstrateAgentAnalytics(): Promise<void> {
  console.log('\n=== Agent Performance Analytics ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Get Agent Leaderboard
  // -------------------------------------------------------------------------
  console.log('1. Agent Leaderboard');
  console.log('-'.repeat(40));

  try {
    const leaderboard = await client.analytics.getAgentLeaderboard({
      limit: 10,
    }) as {
      agents: Array<{
        rank: number;
        name: string;
        elo: number;
        wins: number;
        losses: number;
        win_rate: number;
        trend: 'up' | 'down' | 'stable';
      }>;
    };

    console.log('  Top Agents:\n');

    for (const agent of leaderboard.agents) {
      const trendIcon = agent.trend === 'up' ? '^' : agent.trend === 'down' ? 'v' : '-';
      console.log(`  ${agent.rank}. ${agent.name}`);
      console.log(`     ELO: ${agent.elo} (${trendIcon})`);
      console.log(`     Record: ${agent.wins}W - ${agent.losses}L`);
      console.log(`     Win Rate: ${(agent.win_rate * 100).toFixed(1)}%`);
    }
  } catch (error) {
    handleError('Get agent leaderboard', error);
  }

  // -------------------------------------------------------------------------
  // Get Individual Agent Performance
  // -------------------------------------------------------------------------
  console.log('\n2. Individual Agent Performance');
  console.log('-'.repeat(40));

  try {
    const agentPerf = await client.analytics.getAgentPerformance('claude', {
      time_range: '30d',
    }) as {
      agent: string;
      elo: number;
      elo_change: number;
      debates: number;
      wins: number;
      losses: number;
      draws: number;
      consensus_rate: number;
      avg_confidence: number;
      domains: Array<{
        name: string;
        elo: number;
        debates: number;
      }>;
    };

    console.log(`  Agent: ${agentPerf.agent}`);
    console.log(`  Current ELO: ${agentPerf.elo} (${agentPerf.elo_change >= 0 ? '+' : ''}${agentPerf.elo_change})`);
    console.log(`  Debates: ${agentPerf.debates}`);
    console.log(`  Record: ${agentPerf.wins}W - ${agentPerf.losses}L - ${agentPerf.draws}D`);
    console.log(`  Consensus Rate: ${(agentPerf.consensus_rate * 100).toFixed(1)}%`);
    console.log(`  Avg Confidence: ${(agentPerf.avg_confidence * 100).toFixed(1)}%`);

    if (agentPerf.domains?.length) {
      console.log('\n  Domain Expertise:');
      for (const domain of agentPerf.domains.slice(0, 5)) {
        console.log(`    ${domain.name}: ELO ${domain.elo} (${domain.debates} debates)`);
      }
    }
  } catch (error) {
    handleError('Get agent performance', error);
  }

  // -------------------------------------------------------------------------
  // Compare Multiple Agents
  // -------------------------------------------------------------------------
  console.log('\n3. Agent Comparison');
  console.log('-'.repeat(40));

  try {
    const comparison = await client.analytics.compareAgents(['claude', 'gpt-4', 'gemini']) as {
      agents: Array<{
        name: string;
        elo: number;
        win_rate: number;
        consensus_rate: number;
        avg_confidence: number;
      }>;
      head_to_head: Array<{
        agent_a: string;
        agent_b: string;
        wins_a: number;
        wins_b: number;
        draws: number;
      }>;
    };

    console.log('  Metrics Comparison:\n');

    // Print header
    console.log(`  ${'Agent'.padEnd(12)} ${'ELO'.padStart(6)} ${'Win%'.padStart(6)} ${'Cons%'.padStart(6)} ${'Conf%'.padStart(6)}`);
    console.log('  ' + '-'.repeat(42));

    for (const agent of comparison.agents) {
      console.log(`  ${agent.name.padEnd(12)} ${String(agent.elo).padStart(6)} ${((agent.win_rate * 100).toFixed(1) + '%').padStart(6)} ${((agent.consensus_rate * 100).toFixed(1) + '%').padStart(6)} ${((agent.avg_confidence * 100).toFixed(1) + '%').padStart(6)}`);
    }

    if (comparison.head_to_head?.length) {
      console.log('\n  Head-to-Head:');
      for (const h2h of comparison.head_to_head) {
        console.log(`    ${h2h.agent_a} vs ${h2h.agent_b}: ${h2h.wins_a}W-${h2h.wins_b}L-${h2h.draws}D`);
      }
    }
  } catch (error) {
    handleError('Compare agents', error);
  }

  // -------------------------------------------------------------------------
  // Get Calibration Stats
  // -------------------------------------------------------------------------
  console.log('\n4. Calibration Statistics');
  console.log('-'.repeat(40));

  try {
    const calibration = await client.analytics.getCalibrationStats() as {
      overall_calibration: number;
      by_agent: Array<{
        agent: string;
        score: number;
        sample_size: number;
      }>;
      trend: 'improving' | 'declining' | 'stable';
    };

    console.log(`  Overall Calibration: ${(calibration.overall_calibration * 100).toFixed(1)}%`);
    console.log(`  Trend: ${calibration.trend}`);

    console.log('\n  By Agent:');
    for (const agent of calibration.by_agent.slice(0, 5)) {
      console.log(`    ${agent.agent}: ${(agent.score * 100).toFixed(1)}% (n=${agent.sample_size})`);
    }
  } catch (error) {
    handleError('Get calibration stats', error);
  }
}

// =============================================================================
// Usage Reports
// =============================================================================

async function demonstrateUsageReports(): Promise<void> {
  console.log('\n=== Usage Reports ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Get Active Users
  // -------------------------------------------------------------------------
  console.log('1. Active Users');
  console.log('-'.repeat(40));

  try {
    const activeUsers = await client.analytics.getActiveUsers({
      time_range: '30d',
    }) as {
      daily_active: number;
      weekly_active: number;
      monthly_active: number;
      growth_rate: number;
      by_day: Array<{
        date: string;
        count: number;
      }>;
    };

    console.log(`  Daily Active Users: ${activeUsers.daily_active}`);
    console.log(`  Weekly Active Users: ${activeUsers.weekly_active}`);
    console.log(`  Monthly Active Users: ${activeUsers.monthly_active}`);
    console.log(`  Growth Rate: ${activeUsers.growth_rate >= 0 ? '+' : ''}${(activeUsers.growth_rate * 100).toFixed(1)}%`);

    console.log('\n  Last 7 Days:');
    for (const day of activeUsers.by_day.slice(-7)) {
      console.log(`    ${day.date}: ${day.count} users`);
    }
  } catch (error) {
    handleError('Get active users', error);
  }

  // -------------------------------------------------------------------------
  // Get Role Rotation Analytics
  // -------------------------------------------------------------------------
  console.log('\n2. Role Rotation Analytics');
  console.log('-'.repeat(40));

  try {
    const roleRotation = await client.analytics.roleRotation({ period: '30d' });

    console.log(`  Total Rotations: ${roleRotation.total_rotations}`);
    console.log(`  Average Rotations/Debate: ${roleRotation.avg_rotations_per_debate.toFixed(1)}`);
    console.log(`  Beneficial Rate: ${(roleRotation.beneficial_rate * 100).toFixed(1)}%`);

    console.log('\n  By Role:');
    for (const [role, stats] of Object.entries(roleRotation.by_role)) {
      const roleStats = stats as { count: number; impact: number };
      console.log(`    ${role}: ${roleStats.count} (impact: ${roleStats.impact.toFixed(2)})`);
    }
  } catch (error) {
    handleError('Get role rotation', error);
  }

  // -------------------------------------------------------------------------
  // Get Early Stop Analytics
  // -------------------------------------------------------------------------
  console.log('\n3. Early Stop Analytics');
  console.log('-'.repeat(40));

  try {
    const earlyStops = await client.analytics.earlyStops({ period: '30d' });

    console.log(`  Total Early Stops: ${earlyStops.total}`);
    console.log(`  Early Stop Rate: ${(earlyStops.rate * 100).toFixed(1)}%`);
    console.log(`  Rounds Saved: ${earlyStops.rounds_saved}`);
    console.log(`  Cost Saved: $${earlyStops.cost_saved.toFixed(2)}`);

    console.log('\n  By Reason:');
    for (const [reason, count] of Object.entries(earlyStops.by_reason)) {
      console.log(`    ${reason}: ${count}`);
    }
  } catch (error) {
    handleError('Get early stops', error);
  }

  // -------------------------------------------------------------------------
  // Get Deliberation Summary
  // -------------------------------------------------------------------------
  console.log('\n4. Deliberation Summary');
  console.log('-'.repeat(40));

  try {
    const deliberations = await client.analytics.getDeliberationSummary({
      days: 30,
    }) as {
      total: number;
      completed: number;
      avg_duration: number;
      avg_participants: number;
      satisfaction_rate: number;
      by_status: Record<string, number>;
    };

    console.log(`  Total Deliberations: ${deliberations.total}`);
    console.log(`  Completed: ${deliberations.completed}`);
    console.log(`  Avg Duration: ${deliberations.avg_duration}s`);
    console.log(`  Avg Participants: ${deliberations.avg_participants.toFixed(1)}`);
    console.log(`  Satisfaction Rate: ${(deliberations.satisfaction_rate * 100).toFixed(1)}%`);

    console.log('\n  By Status:');
    for (const [status, count] of Object.entries(deliberations.by_status)) {
      console.log(`    ${status}: ${count}`);
    }
  } catch (error) {
    handleError('Get deliberation summary', error);
  }

  // -------------------------------------------------------------------------
  // Generate Custom Report
  // -------------------------------------------------------------------------
  console.log('\n5. Generate Custom Report');
  console.log('-'.repeat(40));

  try {
    const report = await client.analytics.generateReport('monthly_summary', {
      month: new Date().getMonth() + 1,
      year: new Date().getFullYear(),
      include_trends: true,
      include_recommendations: true,
    }) as {
      report_id: string;
      generated_at: string;
      summary: string;
      recommendations: string[];
    };

    console.log(`  Report ID: ${report.report_id}`);
    console.log(`  Generated: ${report.generated_at}`);
    console.log(`\n  Summary: ${report.summary.substring(0, 200)}...`);

    if (report.recommendations?.length) {
      console.log('\n  Recommendations:');
      for (const rec of report.recommendations.slice(0, 3)) {
        console.log(`    - ${rec}`);
      }
    }
  } catch (error) {
    handleError('Generate report', error);
  }
}

// =============================================================================
// Flip Detection
// =============================================================================

async function demonstrateFlipDetection(): Promise<void> {
  console.log('\n=== Flip Detection ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Get Flip Summary
  // -------------------------------------------------------------------------
  console.log('1. Flip Summary');
  console.log('-'.repeat(40));

  try {
    const flipSummary = await client.analytics.getFlipSummary() as {
      total_flips: number;
      flips_today: number;
      flips_this_week: number;
      avg_flip_rate: number;
      most_volatile_agent: string;
      most_stable_agent: string;
    };

    console.log(`  Total Flips: ${flipSummary.total_flips}`);
    console.log(`  Flips Today: ${flipSummary.flips_today}`);
    console.log(`  Flips This Week: ${flipSummary.flips_this_week}`);
    console.log(`  Average Flip Rate: ${(flipSummary.avg_flip_rate * 100).toFixed(2)}%`);
    console.log(`  Most Volatile: ${flipSummary.most_volatile_agent}`);
    console.log(`  Most Stable: ${flipSummary.most_stable_agent}`);
  } catch (error) {
    handleError('Get flip summary', error);
  }

  // -------------------------------------------------------------------------
  // Get Recent Flips
  // -------------------------------------------------------------------------
  console.log('\n2. Recent Flips');
  console.log('-'.repeat(40));

  try {
    const recentFlips = await client.analytics.getRecentFlips({
      limit: 5,
    }) as {
      flips: Array<{
        agent: string;
        topic: string;
        original: string;
        updated: string;
        timestamp: string;
        magnitude: number;
      }>;
    };

    console.log('  Recent Position Changes:\n');

    for (const flip of recentFlips.flips) {
      console.log(`  ${flip.agent} on "${flip.topic}"`);
      console.log(`    Original: ${flip.original.substring(0, 50)}...`);
      console.log(`    Updated: ${flip.updated.substring(0, 50)}...`);
      console.log(`    Magnitude: ${(flip.magnitude * 100).toFixed(1)}%`);
      console.log(`    When: ${flip.timestamp}`);
    }
  } catch (error) {
    handleError('Get recent flips', error);
  }

  // -------------------------------------------------------------------------
  // Get Agent Consistency
  // -------------------------------------------------------------------------
  console.log('\n3. Agent Consistency Scores');
  console.log('-'.repeat(40));

  try {
    const consistency = await client.analytics.getAgentConsistency() as {
      agents: Array<{
        name: string;
        consistency_score: number;
        flip_count: number;
        sample_size: number;
      }>;
    };

    console.log('  Consistency Scores:\n');

    for (const agent of consistency.agents.slice(0, 10)) {
      const bar = '='.repeat(Math.floor(agent.consistency_score * 20));
      console.log(`  ${agent.name.padEnd(12)} ${bar} ${(agent.consistency_score * 100).toFixed(1)}%`);
      console.log(`               (${agent.flip_count} flips / ${agent.sample_size} positions)`);
    }
  } catch (error) {
    handleError('Get agent consistency', error);
  }
}

// =============================================================================
// Utility Functions
// =============================================================================

function formatNumber(num: number): string {
  if (num >= 1_000_000) {
    return (num / 1_000_000).toFixed(1) + 'M';
  } else if (num >= 1_000) {
    return (num / 1_000).toFixed(1) + 'K';
  }
  return num.toLocaleString();
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function handleError(context: string, error: unknown): void {
  if (error instanceof AragoraError) {
    console.error(`  ${context}: [${error.code}] ${error.message}`);
  } else if (error instanceof Error) {
    console.error(`  ${context}: ${error.message}`);
  } else {
    console.error(`  ${context}:`, error);
  }
}

// =============================================================================
// Run Examples
// =============================================================================

async function main(): Promise<void> {
  if (!process.env.ARAGORA_API_KEY) {
    console.warn('Warning: ARAGORA_API_KEY not set. Some operations may fail.\n');
  }

  try {
    await demonstrateDashboardOverview();
    await demonstrateDebateAnalytics();
    await demonstrateCostTracking();
    await demonstrateAgentAnalytics();
    await demonstrateUsageReports();
    await demonstrateFlipDetection();

    console.log('\n=== All analytics dashboard examples completed ===');
  } catch (error) {
    if (error instanceof AragoraError) {
      console.error('\nFatal error:', error.message);
    } else {
      console.error('\nFatal error:', error);
    }
    process.exit(1);
  }
}

main();
