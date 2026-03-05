/**
 * Inbox Command Center Namespace API
 *
 * Provides methods for inbox management:
 * - Prioritized email fetching
 * - Quick actions (archive, snooze, reply, forward)
 * - Bulk operations
 * - Sender profiles
 * - Daily digest statistics
 *
 * Endpoints:
 *   GET  /api/v1/inbox/command        - Fetch prioritized inbox
 *   POST /api/v1/inbox/actions        - Execute quick action
 *   POST /api/v1/inbox/bulk-actions   - Execute bulk action
 *   GET  /api/v1/inbox/sender-profile - Get sender profile
 *   GET  /api/v1/inbox/daily-digest   - Get daily digest
 *   POST /api/v1/inbox/reprioritize   - Trigger AI re-prioritization
 */

/**
 * Email priority levels.
 */
export type Priority = 'critical' | 'high' | 'medium' | 'low' | 'defer';

/**
 * Quick action types.
 */
export type Action =
  | 'archive'
  | 'snooze'
  | 'reply'
  | 'forward'
  | 'spam'
  | 'mark_important'
  | 'mark_vip'
  | 'block'
  | 'delete';

/**
 * Bulk action filter types.
 */
export type BulkFilter = 'low' | 'deferred' | 'spam' | 'read' | 'all';

/**
 * Prioritization tier options.
 */
export type ForceTier = 'tier_1_rules' | 'tier_2_lightweight' | 'tier_3_debate';

/**
 * Prioritized email information.
 */
export interface InboxEmail {
  email_id: string;
  subject: string;
  sender: string;
  sender_email: string;
  preview: string;
  priority: Priority;
  received_at: string;
  is_read: boolean;
  is_starred: boolean;
  labels?: string[];
  thread_id?: string;
}

/**
 * Inbox statistics.
 */
export interface InboxStats {
  total: number;
  unread: number;
  by_priority: Record<Priority, number>;
}

/**
 * Sender profile information.
 */
export interface SenderProfile {
  email: string;
  name?: string;
  domain: string;
  is_vip: boolean;
  response_rate: number;
  average_response_time_hours?: number;
  first_contact?: string;
  last_contact?: string;
  total_emails: number;
  tags?: string[];
}

/**
 * Daily digest statistics.
 */
export interface DailyDigest {
  emails_received: number;
  emails_processed: number;
  critical_handled: number;
  time_saved_minutes: number;
  top_senders: Array<{ email: string; count: number }>;
  priority_distribution: Record<Priority, number>;
  date: string;
}

/**
 * Options for fetching inbox.
 */
export interface GetInboxOptions {
  /** Max emails to return (default 50, max 1000) */
  limit?: number;
  /** Pagination offset */
  offset?: number;
  /** Filter by priority level */
  priority?: Priority;
  /** Only return unread emails */
  unreadOnly?: boolean;
}

/**
 * Options for quick actions.
 */
export interface QuickActionOptions {
  /** Action to perform */
  action: Action;
  /** List of email IDs to act on */
  emailIds: string[];
  /** Optional action-specific parameters */
  params?: Record<string, unknown>;
}

/**
 * Options for bulk actions.
 */
export interface BulkActionOptions {
  /** Action to perform */
  action: Action;
  /** Filter to apply */
  filter: BulkFilter;
  /** Optional action-specific parameters */
  params?: Record<string, unknown>;
}

/**
 * Options for reprioritization.
 */
export interface ReprioritizeOptions {
  /** Optional list of specific email IDs to reprioritize */
  emailIds?: string[];
  /** Optional tier to force */
  forceTier?: ForceTier;
}

/**
 * Client interface for making HTTP requests.
 */
interface InboxCommandClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Inbox Command API namespace.
 *
 * Provides methods for managing and prioritizing inbox emails.
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Get prioritized inbox
 * const inbox = await client.inboxCommand.getInbox({ limit: 50 });
 * for (const email of inbox.emails) {
 *   console.log(`${email.priority}: ${email.subject}`);
 * }
 *
 * // Execute quick action
 * await client.inboxCommand.quickAction({
 *   action: 'archive',
 *   emailIds: ['email_1', 'email_2'],
 * });
 *
 * // Archive low-priority emails
 * await client.inboxCommand.bulkAction({
 *   action: 'archive',
 *   filter: 'low',
 * });
 *
 * // Get sender profile
 * const profile = await client.inboxCommand.getSenderProfile('sender@example.com');
 * console.log(`VIP: ${profile.is_vip}`);
 * ```
 */
export class InboxCommandAPI {
  constructor(private client: InboxCommandClientInterface) {}

  // =========================================================================
  // Inbox
  // =========================================================================

  /**
   * Fetch prioritized inbox with stats.
   *
   * @param options - Filtering and pagination options
   * @returns Emails with stats and total count
   */
  async getInbox(options?: GetInboxOptions): Promise<{
    emails: InboxEmail[];
    stats: InboxStats;
    total: number;
  }> {
    const params: Record<string, unknown> = {
      limit: options?.limit ?? 50,
      offset: options?.offset ?? 0,
    };
    if (options?.priority) params.priority = options.priority;
    if (options?.unreadOnly) params.unread_only = 'true';

    return this.client.request('GET', '/api/v1/inbox/command', {
      params,
    });
  }

  // =========================================================================
  // Actions
  // =========================================================================

  /**
   * Execute quick action on email(s).
   *
   * @param options - Action options
   * @returns Action result with processed count
   */
  async quickAction(options: QuickActionOptions): Promise<{
    action: Action;
    processed: number;
    results: Array<{ email_id: string; success: boolean; error?: string }>;
  }> {
    const data: Record<string, unknown> = {
      action: options.action,
      emailIds: options.emailIds,
    };
    if (options.params) data.params = options.params;

    return this.client.request('POST', '/api/v1/inbox/actions', {
      json: data,
    });
  }

  /**
   * Execute bulk action based on filter.
   *
   * @param options - Bulk action options
   * @returns Bulk action result with processed count
   */
  async bulkAction(options: BulkActionOptions): Promise<{
    action: Action;
    filter: BulkFilter;
    processed: number;
    results: Array<{ email_id: string; success: boolean; error?: string }>;
  }> {
    const data: Record<string, unknown> = {
      action: options.action,
      filter: options.filter,
    };
    if (options.params) data.params = options.params;

    return this.client.request('POST', '/api/v1/inbox/bulk-actions', {
      json: data,
    });
  }

  // =========================================================================
  // Sender Profile
  // =========================================================================

  /**
   * Get profile information for a sender.
   *
   * @param email - Sender email address
   * @returns Sender profile information
   */
  async getSenderProfile(email: string): Promise<SenderProfile> {
    return this.client.request('GET', '/api/v1/inbox/sender-profile', {
      params: { email },
    });
  }

  // =========================================================================
  // Daily Digest
  // =========================================================================

  /**
   * Get daily digest statistics.
   *
   * @returns Daily digest with stats
   */
  async getDailyDigest(): Promise<DailyDigest> {
    return this.client.request('GET', '/api/v1/inbox/daily-digest');
  }

  // =========================================================================
  // Reprioritization
  // =========================================================================

  /**
   * Trigger AI re-prioritization of inbox.
   *
   * @param options - Reprioritization options
   * @returns Reprioritization result
   */
  async reprioritize(options?: ReprioritizeOptions): Promise<{
    reprioritized: number;
    changes: Array<{ email_id: string; old_priority: Priority; new_priority: Priority }>;
    tier_used: ForceTier;
  }> {
    const data: Record<string, unknown> = {};
    if (options?.emailIds) data.emailIds = options.emailIds;
    if (options?.forceTier) data.force_tier = options.forceTier;

    return this.client.request('POST', '/api/v1/inbox/reprioritize', {
      json: data,
    });
  }

  /** Acknowledge an inbox mention. */
  async acknowledgeMention(mentionId: string): Promise<{ success: boolean; mention_id: string }> {
    return this.client.request('POST', `/api/v1/inbox/mentions/${encodeURIComponent(mentionId)}/acknowledge`);
  }

  /** Send a message from the inbox. */
  async sendMessage(options: {
    to: string | string[];
    subject?: string;
    body: string;
    reply_to?: string;
    account_id?: string;
  }): Promise<{ message_id: string; status: string }> {
    return this.client.request('POST', '/api/v1/inbox/messages/send', { json: options as unknown as Record<string, unknown> });
  }

  /** Start a debate from an inbox message. */
  async debateMessage(messageId: string, options?: { agents?: string[]; rounds?: number }): Promise<{ debate_id: string; status: string }> {
    return this.client.request('POST', `/api/v1/inbox/messages/${encodeURIComponent(messageId)}/debate`, { json: options as unknown as Record<string, unknown> });
  }
}
