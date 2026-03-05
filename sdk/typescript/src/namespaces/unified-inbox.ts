/**
 * Unified Inbox Namespace API
 *
 * Provides a namespaced interface for multi-account email management.
 * Supports Gmail and Outlook with priority scoring, triage, and analytics.
 */
import type { PaginationParams } from '../types';
// =============================================================================
// Types
// =============================================================================

/** Supported email providers */
export type EmailProvider = 'gmail' | 'outlook';

/** Account connection status */
export type AccountStatus = 'pending' | 'connected' | 'syncing' | 'error' | 'disconnected';

/** Available triage actions */
export type TriageAction =
  | 'respond_urgent'
  | 'respond_normal'
  | 'delegate'
  | 'schedule'
  | 'archive'
  | 'delete'
  | 'flag'
  | 'defer';

/** Priority tier levels */
export type PriorityTier = 'critical' | 'high' | 'medium' | 'low';

/** Connected email account */
export interface ConnectedAccount {
  id: string;
  provider: EmailProvider;
  email_address: string;
  display_name: string;
  status: AccountStatus;
  connected_at: string;
  last_sync: string | null;
  total_messages: number;
  unread_count: number;
  sync_errors: number;
}

/** Unified message across providers */
export interface UnifiedMessage {
  id: string;
  account_id: string;
  provider: EmailProvider;
  external_id: string;
  subject: string;
  sender: {
    email: string;
    name: string;
  };
  recipients: string[];
  cc: string[];
  received_at: string;
  snippet: string;
  is_read: boolean;
  is_starred: boolean;
  has_attachments: boolean;
  labels: string[];
  thread_id: string | null;
  priority: {
    score: number;
    tier: PriorityTier;
    reasons: string[];
  };
  triage: {
    action: TriageAction | null;
    rationale: string | null;
  } | null;
}

/** Triage result from multi-agent analysis */
export interface TriageResult {
  message_id: string;
  recommended_action: TriageAction;
  confidence: number;
  rationale: string;
  suggested_response: string | null;
  delegate_to: string | null;
  schedule_for: string | null;
  agents_involved: string[];
  debate_summary: string | null;
}

/** Inbox health statistics */
export interface InboxStats {
  total_accounts: number;
  total_messages: number;
  unread_count: number;
  messages_by_priority: Record<PriorityTier, number>;
  messages_by_provider: Record<EmailProvider, number>;
  avg_response_time_hours: number;
  pending_triage: number;
  sync_health: {
    accounts_healthy: number;
    accounts_error: number;
    total_sync_errors: number;
  };
  top_senders: Array<{ email: string; count: number }>;
  hourly_volume: Array<{ hour: number; count: number }>;
}

/** Priority trends over time */
export interface InboxTrends {
  period_days: number;
  priority_trends: Record<PriorityTier, {
    current: number;
    previous: number;
    change_pct: number;
  }>;
  volume_trend: {
    current_daily_avg: number;
    previous_daily_avg: number;
    change_pct: number;
  };
  response_time_trend: {
    current_avg_hours: number;
    previous_avg_hours: number;
    change_pct: number;
  };
}

/** OAuth URL response */
export interface OAuthUrlResponse {
  auth_url: string;
  provider: EmailProvider;
  state: string;
}

/** Connect account request */
export interface ConnectAccountRequest {
  provider: EmailProvider;
  auth_code: string;
  redirect_uri: string;
}

/** Message listing parameters */
export interface ListMessagesParams extends PaginationParams {
  priority?: PriorityTier;
  account_id?: string;
  unread_only?: boolean;
  search?: string;
}

/** Triage request */
export interface TriageRequest {
  message_ids: string[];
  context?: {
    urgency_keywords?: string[];
    delegate_options?: string[];
  };
}

/** Bulk action types */
export type BulkAction = 'archive' | 'mark_read' | 'mark_unread' | 'star' | 'delete';

/** Bulk action request */
export interface BulkActionRequest {
  message_ids: string[];
  action: BulkAction;
}

// =============================================================================
// Unified Inbox API
// =============================================================================

/**
 * Client interface for unified inbox operations.
 */
interface UnifiedInboxClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Unified Inbox namespace API for multi-account email management.
 *
 * Provides a single interface for Gmail and Outlook accounts with:
 * - Cross-account message retrieval with priority scoring
 * - Multi-agent triage for complex messages
 * - Inbox health metrics and analytics
 */
export class UnifiedInboxAPI {
  constructor(private client: UnifiedInboxClientInterface) {}

  // ===========================================================================
  // OAuth Flow
  // ===========================================================================

  /**
   * Get Gmail OAuth authorization URL.
   *
   * @param redirectUri - URL to redirect after authorization
   * @param state - Optional CSRF state parameter
   * @returns OAuth URL and state
   */
  async getGmailOAuthUrl(redirectUri: string, state?: string): Promise<OAuthUrlResponse> {
    const params: Record<string, string> = { redirect_uri: redirectUri };
    if (state) params.state = state;
    return this.client.request('GET', '/inbox/oauth/gmail', { params });
  }

  /**
   * Get Outlook OAuth authorization URL.
   *
   * @param redirectUri - URL to redirect after authorization
   * @param state - Optional CSRF state parameter
   * @returns OAuth URL and state
   */
  async getOutlookOAuthUrl(redirectUri: string, state?: string): Promise<OAuthUrlResponse> {
    const params: Record<string, string> = { redirect_uri: redirectUri };
    if (state) params.state = state;
    return this.client.request('GET', '/inbox/oauth/outlook', { params });
  }

  // ===========================================================================
  // Account Management
  // ===========================================================================

  /**
   * Connect an email account using OAuth authorization code.
   *
   * @param request - Connection parameters with auth code
   * @returns Connected account details
   */
  async connect(request: ConnectAccountRequest): Promise<{ account: ConnectedAccount; message: string }> {
    return this.client.request('POST', '/inbox/connect', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * List all connected email accounts.
   *
   * @returns Array of connected accounts
   */
  async listAccounts(): Promise<{ accounts: ConnectedAccount[]; total: number }> {
    return this.client.request('GET', '/inbox/accounts');
  }

  /**
   * Disconnect an email account.
   *
   * @param accountId - Account ID to disconnect
   * @returns Confirmation message
   */
  async disconnect(accountId: string): Promise<{ message: string; account_id: string }> {
    return this.client.request('DELETE', `/inbox/accounts/${accountId}`);
  }

  // ===========================================================================
  // Messages
  // ===========================================================================

  /**
   * Get prioritized messages across all accounts.
   *
   * @param params - Filtering and pagination options
   * @returns Paginated message list sorted by priority
   */
  async listMessages(params?: ListMessagesParams): Promise<{
    messages: UnifiedMessage[];
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
  }> {
    return this.client.request('GET', '/inbox/messages', {
      params: params as unknown as Record<string, unknown>,
    });
  }

  /**
   * Get details of a specific message.
   *
   * @param messageId - Message ID
   * @returns Message details with triage result if available
   */
  async getMessage(messageId: string): Promise<{
    message: UnifiedMessage;
    triage: TriageResult | null;
  }> {
    return this.client.request('GET', `/inbox/messages/${messageId}`);
  }

  // ===========================================================================
  // Triage
  // ===========================================================================

  /**
   * Run multi-agent triage on messages.
   *
   * Uses AI agents to analyze messages and recommend actions
   * based on priority, sender importance, and content analysis.
   *
   * @param request - Message IDs and optional context
   * @returns Triage results with recommendations
   */
  async triage(request: TriageRequest): Promise<{
    results: TriageResult[];
    total_triaged: number;
  }> {
    return this.client.request('POST', '/inbox/triage', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Execute bulk action on messages.
   *
   * @param request - Message IDs and action to perform
   * @returns Action results
   */
  async bulkAction(request: BulkActionRequest): Promise<{
    action: BulkAction;
    success_count: number;
    error_count: number;
    errors: Array<{ id: string; error: string }> | null;
  }> {
    return this.client.request('POST', '/inbox/bulk-action', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  // ===========================================================================
  // Analytics
  // ===========================================================================

  /**
   * Get inbox health statistics.
   *
   * @returns Comprehensive inbox metrics
   */
  async getStats(): Promise<{ stats: InboxStats }> {
    return this.client.request('GET', '/inbox/stats');
  }

  /**
   * Get priority trends over time.
   *
   * @param days - Number of days to analyze (default: 7)
   * @returns Trend analysis
   */
  async getTrends(days: number = 7): Promise<{ trends: InboxTrends }> {
    return this.client.request('GET', '/inbox/trends', { params: { days } });
  }

  // =========================================================================
  // Convenience aliases
  // =========================================================================

  /**
   * List messages (alias for listMessages).
   */
  async list(params?: ListMessagesParams): Promise<{
    messages: UnifiedMessage[];
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
  }> {
    return this.listMessages(params);
  }

  /**
   * Get message by ID (alias for getMessage).
   */
  async get(messageId: string): Promise<UnifiedMessage> {
    const result = await this.getMessage(messageId);
    return result.message;
  }

  /**
   * Send a new message.
   */
  async send(request: {
    channel: string;
    to: string;
    content: string;
    subject?: string;
  }): Promise<{
    message_id: string;
    channel: string;
    sent_at: string;
    status: string;
  }> {
    return this.client.request('POST', '/inbox/messages/send', { json: request });
  }

  /**
   * Reply to a message.
   */
  async reply(
    messageId: string,
    request: { content: string }
  ): Promise<{
    message_id: string;
    in_reply_to: string;
    channel: string;
    status: string;
  }> {
    return this.client.request('POST', `/inbox/messages/${messageId}/reply`, {
      json: request,
    });
  }

  /**
   * Start a debate on a message — trigger multi-agent analysis.
   */
  async debateMessage(
    messageId: string,
    request?: { rounds?: number; consensus?: string }
  ): Promise<{
    debate_id: string;
    message_id: string;
    status: string;
  }> {
    if (!request || Object.keys(request).length === 0) {
      return this.client.request(
        'POST',
        `/api/v1/inbox/messages/${encodeURIComponent(messageId)}/debate`
      );
    }

    return this.client.request(
      'POST',
      `/api/v1/inbox/messages/${encodeURIComponent(messageId)}/debate`,
      { json: request }
    );
  }

  /**
   * Trigger a debate workflow for a specific inbox message.
   * Backward-compatible alias for debateMessage().
   */
  async autoDebate(messageId: string): Promise<{ message_id: string; debate_id: string }> {
    const response = await this.debateMessage(messageId);
    return {
      message_id: response.message_id,
      debate_id: response.debate_id,
    };
  }
}
