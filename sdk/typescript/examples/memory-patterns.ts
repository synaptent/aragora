/**
 * Memory Patterns Example
 *
 * Demonstrates memory tier usage patterns with the Aragora SDK:
 * - Storing to different memory tiers
 * - Consolidation and tier promotion
 * - Context management
 * - Memory retrieval and search
 *
 * Usage:
 *   npx ts-node examples/memory-patterns.ts
 *
 * Environment:
 *   ARAGORA_API_KEY - Your API key
 *   ARAGORA_API_URL - API URL (default: https://api.aragora.ai)
 */

import {
  createClient,
  AragoraError,
  type AragoraConfig,
  type MemoryTier,
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
// Memory Tier Overview
// =============================================================================

/**
 * Memory Tiers in Aragora:
 *
 * - FAST (TTL: 1 min)     - Immediate context, hot data
 * - MEDIUM (TTL: 1 hour)  - Session memory, recent interactions
 * - SLOW (TTL: 1 day)     - Cross-session learning
 * - GLACIAL (TTL: 1 week) - Long-term patterns, institutional knowledge
 *
 * Data automatically flows from fast to glacial tiers based on
 * importance and consolidation patterns.
 */

// =============================================================================
// Basic Memory Operations
// =============================================================================

async function demonstrateBasicOperations(): Promise<void> {
  console.log('=== Basic Memory Operations ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Store to Different Tiers
  // -------------------------------------------------------------------------
  console.log('1. Store to Different Tiers');
  console.log('-'.repeat(40));

  const tiers: MemoryTier[] = ['fast', 'medium', 'slow', 'glacial'];

  for (const tier of tiers) {
    try {
      const result = await client.memory.store(
        `demo-key-${tier}`,
        {
          message: `This is ${tier} tier data`,
          timestamp: new Date().toISOString(),
          tier: tier,
        },
        {
          tier: tier,
          importance: tier === 'glacial' ? 0.9 : tier === 'slow' ? 0.7 : 0.5,
          tags: ['demo', `tier-${tier}`],
        }
      );

      console.log(`  Stored to ${tier}: ${result.stored ? 'success' : 'failed'}`);
    } catch (error) {
      handleError(`Store to ${tier}`, error);
    }
  }

  // -------------------------------------------------------------------------
  // Retrieve from Specific Tier
  // -------------------------------------------------------------------------
  console.log('\n2. Retrieve from Specific Tier');
  console.log('-'.repeat(40));

  for (const tier of tiers) {
    try {
      const result = await client.memory.retrieve(`demo-key-${tier}`, { tier });

      if (result) {
        console.log(`  ${tier}: Found in tier "${result.tier}"`);
        console.log(`    Value: ${JSON.stringify(result.value)}`);
      } else {
        console.log(`  ${tier}: Not found`);
      }
    } catch (error) {
      handleError(`Retrieve from ${tier}`, error);
    }
  }

  // -------------------------------------------------------------------------
  // Store with TTL
  // -------------------------------------------------------------------------
  console.log('\n3. Store with TTL (Time-to-Live)');
  console.log('-'.repeat(40));

  try {
    const result = await client.memory.store(
      'session-token',
      { token: 'abc123', user_id: 'user-456' },
      {
        tier: 'fast',
        ttl_seconds: 300, // Expire in 5 minutes
        tags: ['auth', 'session'],
      }
    );

    console.log(`  Stored session token with 5 min TTL: ${result.stored}`);
  } catch (error) {
    handleError('Store with TTL', error);
  }

  // -------------------------------------------------------------------------
  // Update Existing Entry
  // -------------------------------------------------------------------------
  console.log('\n4. Update Existing Entry');
  console.log('-'.repeat(40));

  try {
    const updateResult = await client.memory.update(
      'demo-key-medium',
      {
        message: 'Updated medium tier data',
        timestamp: new Date().toISOString(),
        version: 2,
      },
      {
        tier: 'medium',
        merge: true, // Merge with existing data
        tags: ['demo', 'tier-medium', 'updated'],
      }
    );

    console.log(`  Updated: ${updateResult.updated ? 'success' : 'failed'}`);
    console.log(`  Tier: ${updateResult.tier}`);
  } catch (error) {
    handleError('Update', error);
  }

  // -------------------------------------------------------------------------
  // Delete Entry
  // -------------------------------------------------------------------------
  console.log('\n5. Delete Entry');
  console.log('-'.repeat(40));

  try {
    const deleteResult = await client.memory.delete('demo-key-fast', 'fast');
    console.log(`  Deleted demo-key-fast: ${deleteResult.deleted}`);
  } catch (error) {
    handleError('Delete', error);
  }
}

// =============================================================================
// Memory Tier Statistics
// =============================================================================

async function demonstrateTierStatistics(): Promise<void> {
  console.log('\n=== Memory Tier Statistics ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Get Tier Stats
  // -------------------------------------------------------------------------
  console.log('1. Tier Statistics');
  console.log('-'.repeat(40));

  try {
    const tierStats = await client.memory.getTierStats();

    for (const [tier, stats] of Object.entries(tierStats)) {
      console.log(`  ${tier.toUpperCase()}:`);
      console.log(`    Count: ${stats.count}`);
      console.log(`    Size: ${formatBytes(stats.size_bytes)}`);
      if (stats.oldest) {
        console.log(`    Oldest: ${stats.oldest}`);
      }
    }
  } catch (error) {
    handleError('Get tier stats', error);
  }

  // -------------------------------------------------------------------------
  // Get Archive Stats
  // -------------------------------------------------------------------------
  console.log('\n2. Archive Statistics');
  console.log('-'.repeat(40));

  try {
    const archiveStats = await client.memory.getArchiveStats();

    console.log(`  Total archived: ${archiveStats.total_archived}`);
    console.log(`  Archive size: ${formatBytes(archiveStats.archive_size_bytes)}`);
    if (archiveStats.oldest_entry) {
      console.log(`  Oldest entry: ${archiveStats.oldest_entry}`);
    }
    if (archiveStats.compression_ratio) {
      console.log(`  Compression ratio: ${(archiveStats.compression_ratio * 100).toFixed(1)}%`);
    }
  } catch (error) {
    handleError('Get archive stats', error);
  }

  // -------------------------------------------------------------------------
  // Get Memory Pressure
  // -------------------------------------------------------------------------
  console.log('\n3. Memory Pressure');
  console.log('-'.repeat(40));

  try {
    const pressure = await client.memory.getPressure();

    console.log(`  Utilization: ${(pressure.utilization * 100).toFixed(1)}%`);
    console.log(`  Pressure level: ${pressure.pressure_level}`);

    if (pressure.recommendations?.length) {
      console.log('  Recommendations:');
      for (const rec of pressure.recommendations) {
        console.log(`    - ${rec}`);
      }
    }

    if (pressure.by_tier) {
      console.log('  By tier:');
      for (const [tier, info] of Object.entries(pressure.by_tier)) {
        console.log(`    ${tier}: ${(info.utilization * 100).toFixed(1)}% (${info.entries} entries)`);
      }
    }
  } catch (error) {
    handleError('Get memory pressure', error);
  }

  // -------------------------------------------------------------------------
  // List All Tiers
  // -------------------------------------------------------------------------
  console.log('\n4. List All Tiers');
  console.log('-'.repeat(40));

  try {
    const { tiers } = await client.memory.listTiers();

    for (const tier of tiers) {
      console.log(`  ${tier.tier.toUpperCase()}:`);
      console.log(`    Entries: ${tier.entry_count}`);
      console.log(`    Avg importance: ${tier.avg_importance.toFixed(2)}`);
      console.log(`    Utilization: ${tier.utilization_pct.toFixed(1)}%`);
    }
  } catch (error) {
    handleError('List tiers', error);
  }
}

// =============================================================================
// Consolidation Patterns
// =============================================================================

async function demonstrateConsolidation(): Promise<void> {
  console.log('\n=== Consolidation Patterns ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Trigger Consolidation
  // -------------------------------------------------------------------------
  console.log('1. Trigger Consolidation');
  console.log('-'.repeat(40));

  try {
    const result = await client.memory.consolidate();
    console.log(`  Consolidation: ${result.success ? 'success' : 'failed'}`);
  } catch (error) {
    handleError('Consolidate', error);
  }

  // -------------------------------------------------------------------------
  // Compact Memory
  // -------------------------------------------------------------------------
  console.log('\n2. Compact Memory');
  console.log('-'.repeat(40));

  try {
    const compactResult = await client.memory.compact({
      tier: 'slow',
      merge_threshold: 0.9, // Merge entries with 90%+ similarity
    });

    console.log(`  Compacted: ${compactResult.compacted}`);
    console.log(`  Entries merged: ${compactResult.entries_merged}`);
    console.log(`  Space saved: ${formatBytes(compactResult.space_saved_bytes)}`);
  } catch (error) {
    handleError('Compact', error);
  }

  // -------------------------------------------------------------------------
  // Move Between Tiers
  // -------------------------------------------------------------------------
  console.log('\n3. Move Between Tiers');
  console.log('-'.repeat(40));

  try {
    // First, store a test entry
    await client.memory.store('promotion-test', { data: 'test' }, { tier: 'medium' });

    // Now promote it to slow tier
    const moveResult = await client.memory.moveTier(
      'promotion-test',
      'medium',
      'slow'
    );

    console.log(`  Moved: ${moveResult.moved}`);
    console.log(`  From: ${moveResult.from_tier} -> To: ${moveResult.to_tier}`);
  } catch (error) {
    handleError('Move tier', error);
  }

  // -------------------------------------------------------------------------
  // Prune Old/Low-Importance Entries
  // -------------------------------------------------------------------------
  console.log('\n4. Prune Old Entries');
  console.log('-'.repeat(40));

  try {
    const pruneResult = await client.memory.prune({
      older_than_days: 30,
      min_importance: 0.1,
      tiers: ['fast', 'medium'],
      dry_run: true, // Just preview, don't actually delete
    });

    console.log(`  Would prune: ${pruneResult.pruned_count} entries`);
    console.log(`  Would free: ${formatBytes(pruneResult.freed_bytes)}`);
    console.log(`  Affected tiers: ${pruneResult.tiers_affected.join(', ')}`);
  } catch (error) {
    handleError('Prune', error);
  }

  // -------------------------------------------------------------------------
  // Sync Across Systems
  // -------------------------------------------------------------------------
  console.log('\n5. Sync Memory');
  console.log('-'.repeat(40));

  try {
    const syncResult = await client.memory.sync({
      target: 'all',
      conflict_resolution: 'latest_wins',
      tiers: ['slow', 'glacial'],
    });

    console.log(`  Synced: ${syncResult.synced}`);
    console.log(`  Entries synced: ${syncResult.entries_synced}`);
    console.log(`  Conflicts resolved: ${syncResult.conflicts_resolved}`);
    console.log(`  Last sync: ${syncResult.last_sync_at}`);
  } catch (error) {
    handleError('Sync', error);
  }
}

// =============================================================================
// Context Management
// =============================================================================

async function demonstrateContextManagement(): Promise<void> {
  console.log('\n=== Context Management ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Set Context
  // -------------------------------------------------------------------------
  console.log('1. Set Memory Context');
  console.log('-'.repeat(40));

  try {
    const context = await client.memory.setContext(
      {
        user_id: 'user-123',
        session_id: 'session-abc',
        workspace: 'engineering',
        preferences: {
          theme: 'dark',
          language: 'en',
        },
      },
      {
        ttl_seconds: 3600, // 1 hour
      }
    );

    console.log(`  Context ID: ${context.context_id}`);
    console.log(`  Created at: ${context.created_at}`);
    console.log(`  Expires at: ${context.expires_at}`);
  } catch (error) {
    handleError('Set context', error);
  }

  // -------------------------------------------------------------------------
  // Get Current Context
  // -------------------------------------------------------------------------
  console.log('\n2. Get Current Context');
  console.log('-'.repeat(40));

  try {
    const context = await client.memory.getContext();

    console.log(`  Context ID: ${context.context_id}`);
    console.log(`  Data: ${JSON.stringify(context.data, null, 2)}`);
  } catch (error) {
    handleError('Get context', error);
  }

  // -------------------------------------------------------------------------
  // Update Context
  // -------------------------------------------------------------------------
  console.log('\n3. Update Context');
  console.log('-'.repeat(40));

  try {
    const updatedContext = await client.memory.setContext(
      {
        last_activity: new Date().toISOString(),
        actions: ['viewed_dashboard', 'created_debate'],
      },
      {
        ttl_seconds: 3600,
      }
    );

    console.log(`  Updated context: ${updatedContext.context_id}`);
    console.log(`  Updated at: ${updatedContext.updated_at}`);
  } catch (error) {
    handleError('Update context', error);
  }
}

// =============================================================================
// Continuum Memory Operations
// =============================================================================

async function demonstrateContinuumMemory(): Promise<void> {
  console.log('\n=== Continuum Memory ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Store to Continuum
  // -------------------------------------------------------------------------
  console.log('1. Store to Continuum');
  console.log('-'.repeat(40));

  try {
    const storeResult = await client.memory.storeToContinuum(
      'The debate concluded that microservices architecture is preferred for scalable systems.',
      {
        tier: 'medium',
        tags: ['debate-outcome', 'architecture'],
        metadata: {
          debate_id: 'debate-123',
          consensus_confidence: 0.85,
        },
      }
    );

    console.log(`  Stored ID: ${storeResult.id}`);
    console.log(`  Tier: ${storeResult.tier}`);
    console.log(`  Created at: ${storeResult.created_at}`);
  } catch (error) {
    handleError('Store to continuum', error);
  }

  // -------------------------------------------------------------------------
  // Retrieve from Continuum
  // -------------------------------------------------------------------------
  console.log('\n2. Retrieve from Continuum');
  console.log('-'.repeat(40));

  try {
    const retrieveResult = await client.memory.retrieveContinuum(
      'architecture decisions',
      {
        tiers: ['medium', 'slow', 'glacial'],
        limit: 5,
        min_importance: 0.5,
      }
    );

    console.log(`  Found ${retrieveResult.memories.length} entries (count: ${retrieveResult.count})`);

    for (const entry of retrieveResult.memories.slice(0, 3)) {
      console.log(`\n  [${entry.tier}] ${entry.content.substring(0, 60)}...`);
      console.log(`    Importance: ${entry.importance}`);
      console.log(`    Tags: ${entry.tags?.join(', ') || 'none'}`);
    }
  } catch (error) {
    handleError('Retrieve from continuum', error);
  }

  // -------------------------------------------------------------------------
  // Get Continuum Stats
  // -------------------------------------------------------------------------
  console.log('\n3. Continuum Statistics');
  console.log('-'.repeat(40));

  try {
    const stats = await client.memory.continuumStats();

    console.log(`  Total entries: ${stats.total_entries}`);
    console.log(`  Storage: ${formatBytes(stats.storage_bytes)}`);
    console.log(`  Consolidation rate: ${(stats.consolidation_rate * 100).toFixed(1)}%`);
    console.log(`  Average importance: ${stats.avg_importance.toFixed(2)}`);
    console.log(`  Cache hit rate: ${(stats.cache_hit_rate * 100).toFixed(1)}%`);
    console.log(`  Health: ${stats.health_status}`);

    console.log('  By tier:');
    for (const [tier, count] of Object.entries(stats.tier_counts)) {
      console.log(`    ${tier}: ${count}`);
    }
  } catch (error) {
    handleError('Get continuum stats', error);
  }
}

// =============================================================================
// Search and Query
// =============================================================================

async function demonstrateSearchAndQuery(): Promise<void> {
  console.log('\n=== Search and Query ===\n');

  const client = createClient(config);

  // -------------------------------------------------------------------------
  // Search Memory
  // -------------------------------------------------------------------------
  console.log('1. Search Memory');
  console.log('-'.repeat(40));

  try {
    const searchResult = await client.memory.search({
      query: 'debate outcomes architecture',
      tiers: ['medium', 'slow'],
      limit: 10,
      min_importance: 0.3,
    });

    console.log(`  Found ${searchResult.entries.length} matches`);

    for (const entry of searchResult.entries.slice(0, 3)) {
      console.log(`\n  [${entry.tier}] ${entry.content.substring(0, 50)}...`);
      console.log(`    ID: ${entry.id}`);
      console.log(`    Importance: ${entry.importance}`);
    }
  } catch (error) {
    handleError('Search', error);
  }

  // -------------------------------------------------------------------------
  // Query with Filters
  // -------------------------------------------------------------------------
  console.log('\n2. Query with Filters');
  console.log('-'.repeat(40));

  try {
    const queryResult = await client.memory.query({
      filter: {
        tags: ['architecture'],
        created_after: '2024-01-01T00:00:00Z',
      },
      sort_by: 'importance',
      sort_order: 'desc',
      limit: 10,
      include_metadata: true,
    });

    console.log(`  Total: ${queryResult.total} matching entries`);
    console.log(`  Returned: ${queryResult.entries.length}`);

    for (const entry of queryResult.entries.slice(0, 3)) {
      console.log(`\n  ID: ${entry.id}`);
      console.log(`  Content: ${entry.content.substring(0, 50)}...`);
      if (entry.metadata) {
        console.log(`  Metadata: ${JSON.stringify(entry.metadata)}`);
      }
    }
  } catch (error) {
    handleError('Query', error);
  }

  // -------------------------------------------------------------------------
  // Get Tier Contents
  // -------------------------------------------------------------------------
  console.log('\n3. Get Tier Contents');
  console.log('-'.repeat(40));

  try {
    for (const tier of ['fast', 'medium'] as const) {
      const tierContents = await client.memory.getTier(tier, { limit: 5 });

      console.log(`\n  ${tier.toUpperCase()} tier: ${tierContents.total} entries`);
      for (const entry of tierContents.entries.slice(0, 2)) {
        console.log(`    - ${entry.content.substring(0, 40)}...`);
      }
    }
  } catch (error) {
    handleError('Get tier contents', error);
  }

  // -------------------------------------------------------------------------
  // List Critiques
  // -------------------------------------------------------------------------
  console.log('\n4. List Stored Critiques');
  console.log('-'.repeat(40));

  try {
    const { critiques } = await client.memory.listCritiques({
      limit: 5,
    });

    console.log(`  Found ${critiques.length} critiques`);

    for (const critique of critiques.slice(0, 2)) {
      console.log(`\n  Debate: ${critique.debate_id}`);
      console.log(`  ${critique.critic_agent} -> ${critique.target_agent}`);
      console.log(`  Severity: ${critique.severity}`);
      console.log(`  Addressed: ${critique.was_addressed ? 'Yes' : 'No'}`);
    }
  } catch (error) {
    handleError('List critiques', error);
  }
}

// =============================================================================
// Utility Functions
// =============================================================================

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
    await demonstrateBasicOperations();
    await demonstrateTierStatistics();
    await demonstrateConsolidation();
    await demonstrateContextManagement();
    await demonstrateContinuumMemory();
    await demonstrateSearchAndQuery();

    console.log('\n=== All memory pattern examples completed ===');
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
