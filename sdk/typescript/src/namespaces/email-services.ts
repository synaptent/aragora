/**
 * Email Services Namespace API
 *
 * Provides advanced email management:
 * - Follow-up tracking
 * - Snooze recommendations
 * - Category learning
 */

/**
 * Follow-up status.
 */
export type FollowUpStatus = 'awaiting' | 'overdue' | 'received' | 'resolved' | 'cancelled';

/**
 * Follow-up priority.
 */
export type FollowUpPriority = 'urgent' | 'high' | 'normal' | 'low';

/**
 * Snooze reason.
 */
export type SnoozeReason =
  | 'calendar_free'
  | 'sender_pattern'
  | 'work_hours'
  | 'priority_decay'
  | 'weekend_skip'
  | 'end_of_day'
  | 'tomorrow_morning';

/**
 * Email category.
 */
export type EmailServiceCategory =
  | 'invoices'
  | 'hr'
  | 'newsletters'
  | 'projects'
  | 'meetings'
  | 'support'
  | 'security'
  | 'receipts'
  | 'social'
  | 'personal'
  | 'uncategorized';

/**
 * Follow-up item.
 */
export interface FollowUpItem {
  followup_id: string;
  email_id: string;
  thread_id: string;
  subject: string;
  recipient: string;
  sent_at: string;
  expected_by?: string;
  status: FollowUpStatus;
  days_waiting: number;
  urgency_score?: number;
  reminder_count: number;
  resolved_at?: string;
  notes?: string;
}

/**
 * Mark follow-up request.
 */
export interface MarkFollowUpRequest {
  email_id: string;
  thread_id: string;
  subject?: string;
  recipient?: string;
  sent_at?: string;
  expected_reply_days?: number;
}

/**
 * Pending follow-ups options.
 */
export interface PendingFollowUpsOptions {
  include_resolved?: boolean;
  sort_by?: 'days_waiting' | 'expected_by' | 'urgency_score';
}

/**
 * Pending follow-ups response.
 */
export interface PendingFollowUpsResponse {
  followups: FollowUpItem[];
  total: number;
  overdue_count: number;
}

/**
 * Resolve follow-up request.
 */
export interface ResolveFollowUpRequest {
  status: 'received' | 'resolved' | 'cancelled';
  notes?: string;
}

/**
 * Resolve follow-up response.
 */
export interface ResolveFollowUpResponse {
  followup_id: string;
  status: FollowUpStatus;
  resolved_at: string;
  notes?: string;
}

/**
 * Check replies response.
 */
export interface CheckRepliesResponse {
  replied: FollowUpItem[];
  still_pending: number;
}

/**
 * Auto-detect follow-ups response.
 */
export interface AutoDetectResponse {
  detected: FollowUpItem[];
  total_detected: number;
}

/**
 * Snooze suggestion.
 */
export interface SnoozeSuggestion {
  snooze_until: string;
  label: string;
  reason: SnoozeReason;
  confidence: number;
  source?: string;
}

/**
 * Snooze suggestions options.
 */
export interface SnoozeSuggestionsOptions {
  subject: string;
  sender: string;
  priority?: string;
  max_suggestions?: number;
}

/**
 * Snooze suggestions response.
 */
export interface SnoozeSuggestionsResponse {
  email_id: string;
  suggestions: SnoozeSuggestion[];
  recommended?: SnoozeSuggestion;
}

/**
 * Snooze email response.
 */
export interface SnoozeEmailResponse {
  email_id: string;
  snooze_until: string;
  label: string;
  status: string;
}

/**
 * Snoozed email.
 */
export interface SnoozedEmail {
  email_id: string;
  snooze_until: string;
  label: string;
  snoozed_at: string;
  is_due: boolean;
}

/**
 * Snoozed emails response.
 */
export interface SnoozedEmailsResponse {
  snoozed: SnoozedEmail[];
  total: number;
  due_now: number;
}

/**
 * Process due snoozes response.
 */
export interface ProcessDueSnoozesResponse {
  processed: SnoozedEmail[];
  count: number;
}

/**
 * Category info.
 */
export interface CategoryInfo {
  id: string;
  name: string;
  description: string;
}

/**
 * Category feedback request.
 */
export interface CategoryFeedbackRequest {
  email_id: string;
  predicted_category: EmailServiceCategory;
  correct_category: EmailServiceCategory;
  email_metadata?: Record<string, unknown>;
}

/**
 * Category feedback response.
 */
export interface CategoryFeedbackResponse {
  email_id: string;
  feedback_recorded: boolean;
  predicted: EmailServiceCategory;
  correct: EmailServiceCategory;
}

/**
 * Client interface for email services operations.
 */
interface EmailServicesClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Email Services API namespace.
 *
 * Provides methods for advanced email management:
 * - Track follow-ups and awaiting replies
 * - Get smart snooze recommendations
 * - Learn from category corrections
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Mark an email for follow-up
 * const followup = await client.emailServices.markFollowUp({
 *   email_id: 'msg_123',
 *   thread_id: 'thread_456',
 *   expected_reply_days: 3,
 * });
 *
 * // Get snooze suggestions
 * const suggestions = await client.emailServices.getSnoozeSuggestions('msg_123', {
 *   subject: 'Q4 Report',
 *   sender: 'boss@company.com',
 * });
 * ```
 */
export class EmailServicesAPI {
  constructor(private client: EmailServicesClientInterface) {}

  // =========================================================================
  // Follow-up Tracking
  // =========================================================================

  /**
   * Mark an email for follow-up tracking.
   */
  async markFollowUp(request: MarkFollowUpRequest): Promise<FollowUpItem> {
    return this.client.request('POST', '/api/v1/email/followups/mark', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Get pending follow-ups.
   */
  async getPendingFollowUps(options?: PendingFollowUpsOptions): Promise<PendingFollowUpsResponse> {
    return this.client.request('GET', '/api/v1/email/followups/pending', {
      params: options as Record<string, unknown>,
    });
  }

  /**
   * Resolve a follow-up.
   */
  async resolveFollowUp(
    followupId: string,
    status: 'received' | 'resolved' | 'cancelled',
    notes?: string
  ): Promise<ResolveFollowUpResponse> {
    return this.client.request('POST', `/api/v1/email/followups/${followupId}/resolve`, {
      json: { status, notes },
    });
  }

  /**
   * Check for replies to tracked follow-ups.
   */
  async checkReplies(): Promise<CheckRepliesResponse> {
    return this.client.request('POST', '/api/v1/email/followups/check-replies');
  }

  /**
   * Auto-detect emails needing follow-up.
   */
  async autoDetectFollowUps(daysBack?: number): Promise<AutoDetectResponse> {
    return this.client.request('POST', '/api/v1/email/followups/auto-detect', {
      json: daysBack ? { days_back: daysBack } : undefined,
    });
  }

  // =========================================================================
  // Snooze Management
  // =========================================================================

  /**
   * Get snooze suggestions for an email.
   */
  async getSnoozeSuggestions(
    emailId: string,
    options: SnoozeSuggestionsOptions
  ): Promise<SnoozeSuggestionsResponse> {
    return this.client.request('GET', `/api/v1/email/${emailId}/snooze-suggestions`, {
      params: options as unknown as Record<string, unknown>,
    });
  }

  /**
   * Snooze an email.
   */
  async snoozeEmail(
    emailId: string,
    snoozeUntil: string,
    label?: string
  ): Promise<SnoozeEmailResponse> {
    return this.client.request('POST', `/api/v1/email/${emailId}/snooze`, {
      json: { snooze_until: snoozeUntil, label },
    });
  }

  /**
   * Unsnooze an email.
   */
  async unsnoozeEmail(emailId: string): Promise<{ email_id: string; status: string }> {
    return this.client.request('DELETE', `/api/v1/email/${emailId}/snooze`);
  }

  /**
   * Get all snoozed emails.
   */
  async getSnoozedEmails(): Promise<SnoozedEmailsResponse> {
    return this.client.request('GET', '/api/v1/email/snoozed');
  }

  /**
   * Process due snoozes (un-snooze emails that are due).
   */
  async processDueSnoozes(): Promise<ProcessDueSnoozesResponse> {
    return this.client.request('POST', '/api/v1/email/snooze/process-due');
  }

  // =========================================================================
  // Category Management
  // =========================================================================

  /**
   * Get available email categories.
   */
  async getCategories(): Promise<{ categories: CategoryInfo[] }> {
    return this.client.request('GET', '/api/v1/email/categories');
  }

  /**
   * Submit category feedback for learning.
   */
  async learnCategory(feedback: CategoryFeedbackRequest): Promise<CategoryFeedbackResponse> {
    return this.client.request('POST', '/api/v1/email/categories/learn', {
      json: feedback as unknown as Record<string, unknown>,
    });
  }

  // --- Email Triage ---

  /**
   * Update the triage rules document.
   *
   * @deprecated The server exposes triage rules as a single GET/PUT
   * document; POST /api/v1/email/triage/rules was never served. Use
   * {@link updateTriageRule} with the full rules document instead.
   *
   * @throws Error if the payload is not a full rules document — a
   * single-rule payload sent to the full-document PUT would silently
   * reset the server's triage rules to defaults, so this shim fails
   * closed instead of delegating blindly.
   */
  async createTriageRule(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    if (!('rules' in data)) {
      throw new Error(
        'createTriageRule cannot translate a single-rule payload: ' +
          'PUT /api/v1/email/triage/rules replaces the whole document, and a ' +
          "payload without 'rules' would reset the server config to defaults. " +
          'Call updateTriageRule with the full document ' +
          "({ rules: [...], escalation_keywords: [...], ... })."
      );
    }
    return this.updateTriageRule(data);
  }

  /**
   * Update the email triage rules.
   *
   * The server exposes triage rules as a single document: GET/PUT
   * /api/v1/email/triage/rules (there is no POST-create operation).
   */
  async updateTriageRule(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('PUT', '/api/v1/email/triage/rules', { json: data });
  }

  /**
   * Test a message against the triage rules.
   *
   * The server serves POST /api/v1/email/triage/test only (tests are
   * stateless; there is no PUT-update operation).
   */
  async createTriageTest(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/email/triage/test', { json: data });
  }

  /**
   * Test a message against the triage rules.
   *
   * @deprecated Triage tests are stateless; PUT /api/v1/email/triage/test
   * was never served. Use {@link createTriageTest} instead — this shim
   * delegates to it.
   */
  async updateTriageTest(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.createTriageTest(data);
  }
}
