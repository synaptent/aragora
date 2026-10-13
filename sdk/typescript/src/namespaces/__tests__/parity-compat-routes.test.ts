import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { AgentsAPI } from '../agents';
import { ControlPlaneAPI } from '../control-plane';
import { DebatesAPI } from '../debates';
import { FeedbackAPI } from '../feedback';
import { GitHubNamespace } from '../github';
import { OutlookAPI } from '../outlook';
import { SkillsAPI } from '../skills';
import { SMEAPI } from '../sme';
import { SSONamespace } from '../sso';
import { WebhooksAPI } from '../webhooks';

interface MockClient {
  request: Mock;
}

describe('Parity Compatibility Routes', () => {
  let mockClient: MockClient;

  beforeEach(() => {
    mockClient = {
      request: vi.fn(),
    };
  });

  it('maps agent recommendation compatibility routes', async () => {
    const api = new AgentsAPI(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.getAgentRecommendations({ domain: 'finance', limit: 5 });
    await api.getAgentLeaderboard({ domain: 'finance', limit: 10 });

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/agents/recommend', {
      params: { domain: 'finance', limit: 5 },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'GET', '/api/agents/leaderboard', {
      params: { domain: 'finance', limit: 10 },
    });
  });

  it('maps debate stats compatibility routes', async () => {
    const api = new DebatesAPI(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.getStats('week');
    await api.getStatsAgents(25);

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/debates/stats', {
      params: { period: 'week' },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'GET', '/api/v1/debates/stats/agents', {
      params: { limit: 25 },
    });
  });

  it('maps debate share and package compatibility routes', async () => {
    const api = new DebatesAPI(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.share('debate-1');
    await api.getPublicSpectate('debate-1');
    await api.getPackage('debate-1');
    await api.getPackageMarkdown('debate/1');

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'POST', '/api/debates/debate-1/share');
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'GET', '/api/debates/debate-1/spectate/public');
    expect(mockClient.request).toHaveBeenNthCalledWith(3, 'GET', '/api/debates/debate-1/package');
    expect(mockClient.request).toHaveBeenNthCalledWith(4, 'GET', '/api/debates/debate%2F1/package/markdown');
  });

  it('maps debate diagnostics and share revoke compatibility routes', async () => {
    const api = new DebatesAPI(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.getDiagnostics('debate/1');
    await api.revokeShare('debate/1');

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/debates/debate%2F1/diagnostics');
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'POST', '/api/debates/debate%2F1/share/revoke');
  });

  it('maps github PR review compatibility route', async () => {
    const api = new GitHubNamespace(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.triggerPRReview({
      repository: 'org/repo',
      pr_number: 42,
      review_type: 'comprehensive',
    });

    expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/github/pr/review', {
      body: {
        repository: 'org/repo',
        pr_number: 42,
        review_type: 'comprehensive',
      },
    });
  });

  it('maps github audit compatibility routes', async () => {
    const api = new GitHubNamespace(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.getAuditIssues({ session_id: 'sess-1' });
    await api.createAuditIssuesBulk({ session_id: 'sess-1', finding_ids: ['f-1'] });
    await api.createAuditPR({ session_id: 'sess-1', branch_name: 'fix/security' });

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/v1/github/audit/issues', {
      params: { session_id: 'sess-1' },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'POST', '/api/v1/github/audit/issues/bulk', {
      body: { session_id: 'sess-1', finding_ids: ['f-1'] },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(3, 'POST', '/api/v1/github/audit/pr', {
      body: { session_id: 'sess-1', branch_name: 'fix/security' },
    });
  });

  it('maps control-plane compatibility routes', async () => {
    const api = new ControlPlaneAPI(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.getAgentMetrics('agent/1');
    await api.pauseAgent('agent-1');
    await api.resumeAgent('agent-1');
    await api.getAuditLogs();
    await api.getDeliberationTranscript('req-1');
    await api.getSystemMetrics();
    await api.getTaskMetrics();
    await api.listPolicies();
    await api.prioritizeQueue({ task_id: 't-1', priority: 'high' });
    await api.listSchedules();
    await api.getStreamInfo();

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/control-plane/agents/agent%2F1/metrics');
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'POST', '/api/control-plane/agents/agent-1/pause');
    expect(mockClient.request).toHaveBeenNthCalledWith(3, 'POST', '/api/control-plane/agents/agent-1/resume');
    expect(mockClient.request).toHaveBeenNthCalledWith(4, 'GET', '/api/control-plane/audit-logs');
    expect(mockClient.request).toHaveBeenNthCalledWith(5, 'GET', '/api/control-plane/deliberations/req-1/transcript');
    expect(mockClient.request).toHaveBeenNthCalledWith(6, 'GET', '/api/control-plane/metrics/system');
    expect(mockClient.request).toHaveBeenNthCalledWith(7, 'GET', '/api/control-plane/metrics/tasks');
    expect(mockClient.request).toHaveBeenNthCalledWith(8, 'GET', '/api/control-plane/policies');
    expect(mockClient.request).toHaveBeenNthCalledWith(9, 'POST', '/api/control-plane/queue/prioritize', {
      body: { task_id: 't-1', priority: 'high' },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(10, 'GET', '/api/control-plane/schedules');
    expect(mockClient.request).toHaveBeenNthCalledWith(11, 'GET', '/api/control-plane/stream');
  });

  it('maps SSO compatibility routes', async () => {
    const api = new SSONamespace(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.getStatusCompat();
    await api.loginCompat({ returnUrl: '/dashboard', prompt: 'login' });
    await api.callbackCompat({ code: 'code-1', state: 'state-1' });
    await api.logoutCompat({ everywhere: true });
    await api.getMetadataCompat();
    await api.ssoLoginCompat();

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/sso/status');
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'GET', '/api/sso/login?return_url=%2Fdashboard&prompt=login');
    expect(mockClient.request).toHaveBeenNthCalledWith(3, 'POST', '/api/sso/callback', {
      body: { code: 'code-1', state: 'state-1' },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(4, 'POST', '/api/sso/logout', {
      body: { everywhere: true },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(5, 'GET', '/api/sso/metadata');
    expect(mockClient.request).toHaveBeenNthCalledWith(6, 'GET', '/api/sso/login');
  });

  it('maps skills marketplace compatibility routes', async () => {
    const api = new SkillsAPI(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.listMarketplaceInstalled();
    await api.publishMarketplaceSkill({ skill: 'web-search' });
    await api.searchMarketplaceSkills({ q: 'security', limit: 5 });
    await api.getMarketplaceStats();

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/skills/marketplace/installed');
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'POST', '/api/skills/marketplace/publish', {
      json: { skill: 'web-search' },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(3, 'GET', '/api/skills/marketplace/search', {
      params: { q: 'security', limit: 5 },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(4, 'GET', '/api/skills/marketplace/stats');
  });

  it('maps feedback compatibility routes', async () => {
    const api = new FeedbackAPI(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.getAgentFeedbackDomains('agent/1');
    await api.getAgentFeedbackMetrics({ days: 30 });
    await api.getAgentFeedbackStates();

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/agents/agent%2F1/feedback/domains');
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'GET', '/api/agents/feedback/metrics', {
      params: { days: 30 },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(3, 'GET', '/api/agents/feedback/states');
  });

  it('maps outlook compatibility routes', async () => {
    const api = new OutlookAPI(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.sendCompat({
      to: ['a@example.com'],
      subject: 'Hello',
      body: 'World',
    });
    await api.replyCompat({
      message_id: 'msg-1',
      body: 'Thanks',
    });
    await api.searchCompat({
      query: 'invoice',
      max_results: 10,
      folder_id: 'inbox',
    });

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'POST', '/api/v1/outlook/send', {
      json: { to: ['a@example.com'], subject: 'Hello', body: 'World' },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'POST', '/api/v1/outlook/reply', {
      json: { message_id: 'msg-1', body: 'Thanks' },
    });
    expect(mockClient.request).toHaveBeenNthCalledWith(3, 'GET', '/api/v1/outlook/search', {
      params: { query: 'invoice', max_results: 10, folder_id: 'inbox' },
    });
  });

  it('maps webhook automation compatibility routes', async () => {
    const webhookClient = {
      ...mockClient,
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    };
    const api = new WebhooksAPI(webhookClient as any);
    mockClient.request.mockResolvedValue({});

    await api.listPlatforms();
    await api.dispatch({ event: 'debate.completed', payload: { debate_id: 'd-1' } });

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/v1/webhooks/platforms');
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'POST', '/api/v1/webhooks/dispatch', {
      json: { event: 'debate.completed', payload: { debate_id: 'd-1' } },
    });
  });

  it('maps SME slack channels compatibility routes', async () => {
    const api = new SMEAPI(mockClient as any);
    mockClient.request.mockResolvedValue({});

    await api.listSlackChannels();
    await api.listSlackChannels('T12345');
    await api.listSlackChannelsCompat();

    expect(mockClient.request).toHaveBeenNthCalledWith(1, 'GET', '/api/v1/sme/slack/channels');
    expect(mockClient.request).toHaveBeenNthCalledWith(2, 'GET', '/api/v1/sme/slack/channels/T12345');
    expect(mockClient.request).toHaveBeenNthCalledWith(3, 'GET', '/api/sme/slack/channels');
  });
});
