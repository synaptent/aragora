/**
 * Aragora SDK Core Namespace API Tests
 *
 * Tests for core namespaces: billing, budgets, receipts, gauntlet, analytics,
 * memory, knowledge, tournaments, auth, verification, marketplace, codebase.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createClient } from '../client';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('Core Namespace APIs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('billing namespace', () => {
    it('should expose billing namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.billing).toBeDefined();
      expect(typeof client.billing.listPlans).toBe('function');
      expect(typeof client.billing.getUsage).toBe('function');
      expect(typeof client.billing.getSubscription).toBe('function');
    });

    it('should list plans via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          plans: [{ id: 'pro', name: 'Pro Plan', price_cents: 9900 }]
        })),
      });

      const result = await client.billing.listPlans();
      expect(result.plans).toBeDefined();
    });

    it('should get subscription via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          plan_id: 'pro',
          status: 'active',
          current_period_end: '2024-02-01'
        })),
      });

      const subscription = await client.billing.getSubscription();
      expect(subscription.plan_id).toBe('pro');
    });

    it('should get usage via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          debates_used: 150,
          api_calls: 5000,
          storage_bytes: 1024000
        })),
      });

      const usage = await client.billing.getUsage();
      expect(usage.debates_used).toBe(150);
    });

    it('should list invoices via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          invoices: [{ id: 'inv-123', amount_cents: 9900, status: 'paid' }]
        })),
      });

      const result = await client.billing.listInvoices();
      expect(result.invoices).toHaveLength(1);
    });

    it('should get forecast via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          projected_monthly_cost: 150,
          projected_debates: 200
        })),
      });

      const forecast = await client.billing.getForecast();
      expect(forecast.projected_monthly_cost).toBe(150);
    });
  });

  describe('budgets namespace', () => {
    it('should expose budgets namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.budgets).toBeDefined();
      expect(typeof client.budgets.list).toBe('function');
      expect(typeof client.budgets.create).toBe('function');
    });

    it('should list budgets via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          budgets: [{ id: 'b1', name: 'Monthly API', limit_cents: 50000 }]
        })),
      });

      const result = await client.budgets.list();
      expect(result.budgets).toHaveLength(1);
    });

    it('should create budget via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'budget-123',
          name: 'Q1 Budget',
          limit_cents: 100000
        })),
      });

      const result = await client.budgets.create({
        name: 'Q1 Budget',
        limit_cents: 100000
      });
      expect(result.id).toBe('budget-123');
    });
  });

  describe('receipts namespace', () => {
    it('should expose receipts namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.receipts).toBeDefined();
      expect(typeof client.receipts.list).toBe('function');
      expect(typeof client.receipts.get).toBe('function');
      expect(typeof client.receipts.verifyFull).toBe('function');
    });

    it('should list receipts via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          receipts: [{ id: 'r1', debate_id: 'd1', verdict: 'APPROVED' }]
        })),
      });

      const result = await client.receipts.list();
      expect(result.receipts).toHaveLength(1);
    });

    it('should get receipt by ID via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'receipt-123',
          debate_id: 'debate-456',
          verdict: 'APPROVED'
        })),
      });

      const receipt = await client.receipts.get('receipt-123');
      expect(receipt.id).toBe('receipt-123');
    });

    it('should verify receipt via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          valid: true,
          hash: 'sha256:abc123'
        })),
      });

      const result = await client.receipts.verify('receipt-123');
      expect(result.valid).toBe(true);
    });

    it('should verify receipt with signature via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          receipt_id: 'receipt-123',
          signature: { signature_valid: true },
          integrity: { integrity_valid: true },
        })),
      });

      const result = await client.receipts.verifyFull('receipt-123');
      expect(result.signature.signature_valid).toBe(true);
      expect(result.integrity.integrity_valid).toBe(true);
    });

    it('should return the signing key PEM from the well-known text endpoint', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      const pem = '-----BEGIN PUBLIC KEY-----\nreal-key\n-----END PUBLIC KEY-----\n';

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(pem),
      });

      await expect(client.receipts.signingKeyPem()).resolves.toBe(pem);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.example.com/.well-known/aragora-odr-signing-key',
        expect.objectContaining({
          method: 'GET',
          headers: expect.objectContaining({ Accept: 'application/x-pem-file' }),
        })
      );
    });

    it('should keep the text contract on empty text responses (string, not {})', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(''),
      });

      await expect(client.receipts.signingKeyPem()).resolves.toBe('');
    });
  });

  describe('gauntlet namespace', () => {
    it('should expose gauntlet namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.gauntlet).toBeDefined();
      expect(typeof client.gauntlet.run).toBe('function');
      expect(typeof client.gauntlet.get).toBe('function');
      expect(typeof client.gauntlet.verify).toBe('function');
    });

    it('should run gauntlet via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          gauntlet_id: 'gauntlet-123',
          status: 'pending'
        })),
      });

      const result = await client.gauntlet.run({ input: 'Test input', profile: 'comprehensive' });
      expect(result.gauntlet_id).toBe('gauntlet-123');
    });

    it('should get gauntlet receipt via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'receipt-123',
          verdict: 'APPROVED',
          confidence: 0.92
        })),
      });

      const receipt = await client.gauntlet.get('receipt-123');
      expect(receipt.id).toBe('receipt-123');
    });

    it('should verify gauntlet receipt via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          valid: true,
          hash: 'sha256:xyz789'
        })),
      });

      const result = await client.gauntlet.verify('receipt-123');
      expect(result.valid).toBe(true);
    });

    it('should list gauntlet results via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          results: [{ id: 'r1', status: 'completed' }]
        })),
      });

      const result = await client.gauntlet.listResults();
      expect(result.results).toHaveLength(1);
    });
  });

  describe('analytics namespace', () => {
    it('should expose analytics namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.analytics).toBeDefined();
      expect(typeof client.analytics.getDebatesOverview).toBe('function');
      expect(typeof client.analytics.getAgentLeaderboard).toBe('function');
    });

    it('should get debates overview via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          total: 500,
          consensus_rate: 0.85,
          average_rounds: 3.2
        })),
      });

      const overview = await client.analytics.getDebatesOverview();
      expect(overview.total).toBe(500);
      expect(overview.consensus_rate).toBe(0.85);
    });

    it('should get agent leaderboard via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          agents: [{ name: 'claude', wins: 100, elo: 1650 }]
        })),
      });

      const leaderboard = await client.analytics.getAgentLeaderboard();
      expect(leaderboard).toBeDefined();
    });

    it('should get debate trends via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          data_points: [{ date: '2024-01-08', debates: 50 }]
        })),
      });

      const trends = await client.analytics.getDebateTrends();
      expect(trends).toBeDefined();
    });

    it('should get consensus quality via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          quality_score: 0.85,
          breakdown: {}
        })),
      });

      const quality = await client.analytics.consensusQuality();
      expect(quality.quality_score).toBe(0.85);
    });
  });

  describe('memory namespace', () => {
    it('should expose memory namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.memory).toBeDefined();
      expect(typeof client.memory.store).toBe('function');
      expect(typeof client.memory.retrieve).toBe('function');
    });

    it('should store memory via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          stored: true,
          tier: 'fast'
        })),
      });

      const result = await client.memory.store('mem-123', { data: 'test' });
      expect(result.stored).toBe(true);
    });

    it('should retrieve memory via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          entries: [{ key: 'mem-123', value: { data: 'test' } }]
        })),
      });

      const result = await client.memory.retrieve({ keys: ['mem-123'] });
      expect(result.entries).toHaveLength(1);
    });

    it('should search memory via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          entries: [{ key: 'mem-1', content: 'test' }]
        })),
      });

      const result = await client.memory.search({ query: 'test' });
      expect(result.entries).toHaveLength(1);
    });
  });

  describe('knowledge namespace', () => {
    it('should expose knowledge namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.knowledge).toBeDefined();
      expect(typeof client.knowledge.search).toBe('function');
      expect(typeof client.knowledge.add).toBe('function');
    });

    it('should search knowledge via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          results: [{ id: 'k1', content: 'Knowledge content' }]
        })),
      });

      const result = await client.knowledge.search({ query: 'test query' });
      expect(result.results).toHaveLength(1);
    });

    it('should add knowledge via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'knowledge-123',
          created_at: '2024-01-15'
        })),
      });

      const result = await client.knowledge.add({ content: 'New knowledge', tags: ['test'] });
      expect(result.id).toBe('knowledge-123');
    });

    it('should get knowledge stats via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          total_entries: 1000,
          storage_bytes: 5000000
        })),
      });

      const stats = await client.knowledge.stats();
      expect(stats.total_entries).toBe(1000);
    });
  });

  describe('tournaments namespace', () => {
    it('should expose tournaments namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.tournaments).toBeDefined();
      expect(typeof client.tournaments.list).toBe('function');
      expect(typeof client.tournaments.create).toBe('function');
    });

    it('should list tournaments via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          tournaments: [{ id: 't1', name: 'Q1 Tournament', status: 'active' }]
        })),
      });

      const result = await client.tournaments.list();
      expect(result.tournaments).toHaveLength(1);
    });

    it('should create tournament via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'tournament-123',
          name: 'New Tournament'
        })),
      });

      const result = await client.tournaments.create({ name: 'New Tournament' });
      expect(result.id).toBe('tournament-123');
    });

    it('should get tournament standings via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          rankings: [{ agent: 'claude', wins: 10, elo: 1650 }]
        })),
      });

      const result = await client.tournaments.getStandings('tournament-123');
      expect(result.rankings).toHaveLength(1);
    });
  });

  describe('auth namespace', () => {
    it('should expose auth namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.auth).toBeDefined();
      expect(typeof client.auth.me).toBe('function');
      expect(typeof client.auth.listApiKeys).toBe('function');
    });

    it('should get current user via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'user-123',
          email: 'user@example.com',
          roles: ['admin']
        })),
      });

      const user = await client.auth.me();
      expect(user.id).toBe('user-123');
    });

    it('should list API keys via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          keys: [{ id: 'key-1', name: 'Production', prefix: 'ak_prod_' }]
        })),
      });

      const result = await client.auth.listApiKeys();
      expect(result.keys).toHaveLength(1);
    });

    it('should create API key via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'key-new',
          prefix: 'ak_test_',
          key: 'ak_test_xxx'
        })),
      });

      const result = await client.auth.createApiKey('New Key');
      expect(result.key).toBeDefined();
    });
  });

  describe('verification namespace', () => {
    it('should expose verification namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.verification).toBeDefined();
      expect(typeof client.verification.verifyConclusion).toBe('function');
      expect(typeof client.verification.getReport).toBe('function');
    });

    it('should verify conclusion via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          verified: true,
          confidence: 0.92
        })),
      });

      const result = await client.verification.verifyConclusion('debate-123');
      expect(result.verified).toBe(true);
    });

    it('should get verification report via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          debate_id: 'debate-123',
          verified: true,
          details: {}
        })),
      });

      const result = await client.verification.getReport('debate-123');
      expect(result.verified).toBe(true);
    });
  });

  describe('marketplace namespace', () => {
    it('should expose marketplace namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.marketplace).toBeDefined();
      expect(typeof client.marketplace.list).toBe('function');
      expect(typeof client.marketplace.get).toBe('function');
    });

    it('should list marketplace templates via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          templates: [{ id: 't1', name: 'PR Review', category: 'development' }]
        })),
      });

      const result = await client.marketplace.list();
      expect(result.templates).toHaveLength(1);
    });

    it('should call legacy marketplace listing aliases via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ templates: [] })),
      });

      await client.marketplace.listListingsLegacy({ category: 'ops', limit: 5, offset: 2 });
      await client.marketplace.getFeaturedListingsLegacy();
      await client.marketplace.getListingStatsLegacy();
      await client.marketplace.getListingLegacy('template-123');

      expect(mockFetch).toHaveBeenNthCalledWith(
        1,
        'https://api.example.com/api/marketplace/listings?category=ops&limit=5&offset=2',
        expect.objectContaining({ method: 'GET' })
      );
      expect(mockFetch).toHaveBeenNthCalledWith(
        2,
        'https://api.example.com/api/marketplace/listings/featured',
        expect.objectContaining({ method: 'GET' })
      );
      expect(mockFetch).toHaveBeenNthCalledWith(
        3,
        'https://api.example.com/api/marketplace/listings/stats',
        expect.objectContaining({ method: 'GET' })
      );
      expect(mockFetch).toHaveBeenNthCalledWith(
        4,
        'https://api.example.com/api/marketplace/listings/template-123',
        expect.objectContaining({ method: 'GET' })
      );
    });

    it('should get template via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'template-123',
          name: 'PR Review Template'
        })),
      });

      const template = await client.marketplace.get('template-123');
      expect(template.name).toBe('PR Review Template');
    });

    it('should rate template via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          new_rating: 4.6
        })),
      });

      const result = await client.marketplace.rate('template-123', 5);
      expect(result.new_rating).toBe(4.6);
    });

    it('should import template via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          imported_id: 'local-template-123'
        })),
      });

      const result = await client.marketplace.import('template-123');
      expect(result.imported_id).toBe('local-template-123');
    });
  });

  describe('codebase namespace', () => {
    it('should expose codebase namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.codebase).toBeDefined();
      expect(typeof client.codebase.startScan).toBe('function');
      expect(typeof client.codebase.listVulnerabilities).toBe('function');
    });

    it('should start codebase scan via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          scan_id: 'scan-123',
          status: 'in_progress'
        })),
      });

      const result = await client.codebase.startScan('my-repo', { repo_path: '/path/to/repo' });
      expect(result.scan_id).toBe('scan-123');
    });

    it('should list vulnerabilities via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          vulnerabilities: [{ id: 'v1', severity: 'critical' }],
          total: 1
        })),
      });

      const result = await client.codebase.listVulnerabilities('my-repo');
      expect(result.vulnerabilities).toHaveLength(1);
    });

    it('should generate SBOM via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          format: 'cyclonedx',
          components: 150
        })),
      });

      const result = await client.codebase.generateSbom({ repo_path: '/path/to/repo', format: 'cyclonedx' });
      expect(result.format).toBe('cyclonedx');
    });

    it('should analyze metrics via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          total_lines: 50000,
          complexity_avg: 5.2
        })),
      });

      const result = await client.codebase.analyzeMetrics('my-repo', { repo_path: '/path/to/repo' });
      expect(result.total_lines).toBe(50000);
    });

    it('should get dead code report via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          dead_code: [{ file: 'utils.py', line: 45 }],
          total_dead_lines: 150
        })),
      });

      const result = await client.codebase.getDeadcode('my-repo');
      expect(result.dead_code).toHaveLength(1);
    });
  });

  describe('explainability namespace', () => {
    it('should expose explainability namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.explainability).toBeDefined();
      expect(typeof client.explainability.get).toBe('function');
      expect(typeof client.explainability.getFactors).toBe('function');
    });

    it('should get explanation via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          debate_id: 'debate-123',
          summary: 'The decision was made based on evidence'
        })),
      });

      const result = await client.explainability.get('debate-123');
      expect(result.summary).toContain('decision');
    });

    it('should get factors via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      // Mock the actual API response format (confidence_attribution, not factors)
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          confidence_attribution: [{ factor: 'evidence_quality', contribution: 0.4, explanation: 'Strong evidence' }]
        })),
      });

      const result = await client.explainability.getFactors('debate-123');
      expect(result.factors).toHaveLength(1);
      expect(result.factors[0].name).toBe('evidence_quality');
    });

    it('should get counterfactuals via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          counterfactuals: [{ scenario: 'If evidence was stronger', outcome: 'different' }]
        })),
      });

      const result = await client.explainability.getCounterfactuals('debate-123');
      expect(result.counterfactuals).toHaveLength(1);
    });
  });
});
