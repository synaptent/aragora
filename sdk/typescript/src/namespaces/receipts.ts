/**
 * Receipts Namespace API
 *
 * Provides a namespaced interface for decision receipt management.
 * Critical for SME compliance, audit trails, and defensible decision-making.
 */

import type {
  DecisionReceipt,
  GauntletReceiptExport,
  PaginationParams,
} from '../types';

// Re-export types from ../types for convenience
export type { DecisionReceipt, GauntletReceiptExport } from '../types';

/**
 * Interface for the internal client methods used by ReceiptsAPI.
 */
interface ReceiptsClientInterface {
  request<T = unknown>(method: string, path: string, options?: Record<string, unknown>): Promise<T>;
  listGauntletReceipts(params?: { verdict?: string } & PaginationParams): Promise<{ receipts: DecisionReceipt[] }>;
  getGauntletReceipt(receiptId: string): Promise<DecisionReceipt>;
  verifyGauntletReceipt(receiptId: string): Promise<{ valid: boolean; hash: string }>;
  exportGauntletReceipt(receiptId: string, format: 'json' | 'html' | 'markdown' | 'sarif'): Promise<GauntletReceiptExport>;
}

/**
 * Receipts API namespace.
 *
 * Provides methods for managing decision receipts:
 * - Gauntlet receipt listing and retrieval
 * - Verify receipt integrity (cryptographic hash)
 * - Export receipts in various formats
 * - Access findings and dissenting views
 *
 * Decision receipts provide audit-ready documentation of AI decisions,
 * essential for compliance, governance, and defensible decision-making.
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'your-key' });
 *
 * // List gauntlet receipts
 * const { receipts } = await client.receipts.listGauntlet();
 *
 * // Get a specific gauntlet receipt
 * const receipt = await client.receipts.getGauntlet('receipt-123');
 *
 * // Verify receipt integrity
 * const { valid, hash } = await client.receipts.verifyGauntlet('receipt-123');
 *
 * // Export as HTML for stakeholder review
 * const html = await client.receipts.exportGauntlet('receipt-123', 'html');
 * ```
 */
export class ReceiptsAPI {
  constructor(private client: ReceiptsClientInterface) {}

  // ===========================================================================
  // v2 Receipt Methods
  // ===========================================================================

  /**
   * List decision receipts (v2 API).
   *
   * @param params - Pagination parameters
   * @returns List of receipts
   */
  async listV2(params?: PaginationParams): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v2/receipts', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get a receipt by ID (v2 API).
   *
   * @param receiptId - Receipt identifier
   * @returns Receipt details
   */
  async getV2(receiptId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v2/receipts/${encodeURIComponent(receiptId)}`);
  }

  /**
   * Search receipts with query and filters.
   *
   * @param params - Search parameters (query, date range, verdict, etc.)
   * @returns Search results with pagination
   */
  async search(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v2/receipts/search', { params });
  }

  /**
   * Get receipt statistics (totals, verdicts, trends).
   *
   * @returns Statistics and breakdowns
   */
  async stats(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v2/receipts/stats');
  }

  /**
   * Get the deployment's ODR signing public key (trust anchor).
   *
   * Public endpoint (no auth required). Also served as raw PEM at
   * `/.well-known/aragora-odr-signing-key`.
   *
   * @returns Object with `algorithm`, `key_id`, and `public_key_pem`
   */
  async signingKey(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v2/receipts/signing-key');
  }

  /**
   * Get the ODR signing public key as raw PEM from the well-known path.
   *
   * @returns PEM-encoded Ed25519 public key
   */
  async signingKeyPem(): Promise<string> {
    return this.client.request<string>('GET', '/.well-known/aragora-odr-signing-key', {
      headers: { Accept: 'application/x-pem-file' },
      responseType: 'text',
    });
  }

  /**
   * Export a receipt in various formats (v2 API).
   *
   * @param receiptId - Receipt identifier
   * @param format - Export format (json, html, markdown, sarif, csv, pdf)
   * @returns Exported receipt data
   */
  async exportV2(
    receiptId: string,
    format: 'json' | 'html' | 'markdown' | 'sarif' | 'csv' | 'pdf' = 'json'
  ): Promise<Record<string, unknown>> {
    const formatValue = format === 'markdown' ? 'md' : format;
    return this.client.request('GET', `/api/v2/receipts/${encodeURIComponent(receiptId)}/export`, {
      params: { format: formatValue },
    });
  }

  /**
   * Export a receipt as an Open Decision Receipt (ODR) document.
   *
   * Public endpoint (no auth required). Signed when the deployment configures a
   * signing key, `signatures: []` otherwise.
   *
   * @param receiptId - Receipt identifier
   * @param options - `odrVersion` selects the ODR profile ('0.1' or '0.2');
   *   omitted means the deployment's default
   * @returns The ODR document as JSON
   */
  async exportOdr(
    receiptId: string,
    options?: { odrVersion?: string }
  ): Promise<Record<string, unknown>> {
    const params: Record<string, unknown> = { format: 'odr' };
    if (options?.odrVersion) {
      params.odr_version = options.odrVersion;
    }
    return this.client.request('GET', `/api/v2/receipts/${encodeURIComponent(receiptId)}/export`, {
      params,
    });
  }

  /**
   * Verify an ODR document statelessly against the deployment's signing key.
   *
   * Public endpoint (no auth required). The document is not persisted.
   *
   * On a deployment that serves no signing key `verified` is always false and
   * `key_id` is null, with the signature entry in `checks` reported as `skip`
   * or `warn` rather than `fail`. A false verdict alone is not evidence of
   * tampering: read `checks`.
   *
   * @param document - An ODR document carrying `odr_version`
   * @returns Object with `verified`, `checks`, `warnings`, `dissent_trail`, `key_id`
   */
  async verifyDocument(document: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v2/receipts/verify', { body: document });
  }

  /**
   * Get a receipt formatted for a specific channel (Slack, Teams, Email, etc.).
   *
   * @param receiptId - Receipt identifier
   * @param channelType - Target channel type (slack, teams, email, discord)
   * @param options - Formatting options
   * @returns Channel-formatted receipt
   */
  async formatted(
    receiptId: string,
    channelType: string,
    options?: { compact?: boolean }
  ): Promise<Record<string, unknown>> {
    const params: Record<string, unknown> = {};
    if (options?.compact) {
      params.compact = 'true';
    }
    return this.client.request(
      'GET',
      `/api/v2/receipts/${encodeURIComponent(receiptId)}/formatted/${encodeURIComponent(channelType)}`,
      { params }
    );
  }

  /**
   * Send a receipt to a channel (Slack, Teams, Email, etc.).
   *
   * @param receiptId - Receipt identifier
   * @param channelType - Target channel type
   * @param channelId - Target channel/conversation/email ID
   * @param options - Delivery options
   * @returns Delivery confirmation
   */
  async sendToChannel(
    receiptId: string,
    channelType: string,
    channelId: string,
    options?: { workspaceId?: string; deliveryOptions?: Record<string, unknown> }
  ): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = {
      channel_type: channelType,
      channel_id: channelId,
    };
    if (options?.workspaceId) body.workspace_id = options.workspaceId;
    if (options?.deliveryOptions) body.options = options.deliveryOptions;
    return this.client.request('POST', `/api/v2/receipts/${encodeURIComponent(receiptId)}/send-to-channel`, {
      json: body,
    });
  }

  /**
   * Deliver a receipt via the legacy v1 bridge endpoint.
   *
   * Accepts both modern (channelType/channelId) and legacy
   * (channel/destination) field names.
   */
  async deliverV1(
    receiptId: string,
    options: {
      channelType?: string;
      channelId?: string;
      channel?: string;
      destination?: string;
      workspaceId?: string;
      message?: string;
      deliveryOptions?: Record<string, unknown>;
    }
  ): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = {};
    if (options.channelType) body.channel_type = options.channelType;
    if (options.channelId) body.channel_id = options.channelId;
    if (options.channel) body.channel = options.channel;
    if (options.destination) body.destination = options.destination;
    if (options.workspaceId) body.workspace_id = options.workspaceId;
    if (options.message) body.message = options.message;
    if (options.deliveryOptions) body.options = options.deliveryOptions;
    return this.client.request('POST', `/api/v1/receipts/${encodeURIComponent(receiptId)}/deliver`, {
      json: body,
    });
  }

  /**
   * List recent receipt delivery attempts.
   *
   * @param params - Optional filters and pagination
   * @returns Receipt delivery history
   */
  async listDeliveries(params?: {
    limit?: number;
    offset?: number;
    receiptId?: string;
    channelType?: string;
    status?: string;
  }): Promise<Record<string, unknown>> {
    const queryParams: Record<string, unknown> = {
      limit: params?.limit ?? 50,
      offset: params?.offset ?? 0,
    };
    if (params?.receiptId) queryParams.receipt_id = params.receiptId;
    if (params?.channelType) queryParams.channel_type = params.channelType;
    if (params?.status) queryParams.status = params.status;
    return this.client.request('GET', '/api/v1/receipts/deliveries', {
      params: queryParams,
    });
  }

  /**
   * List recently anchored receipt hashes.
   *
   * @param params - Optional limit
   * @returns Recent anchor records
   */
  async listRecentAnchors(params?: { limit?: number }): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/receipts/recent-anchors', {
      params: { limit: params?.limit ?? 10 },
    });
  }

  /**
   * Get blockchain anchor status for a receipt.
   *
   * @param receiptId - Receipt identifier
   * @returns Anchor verification status
   */
  async getAnchorStatus(receiptId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/receipts/${encodeURIComponent(receiptId)}/anchor-status`);
  }

  /**
   * Share a receipt (generate shareable link or send to recipients).
   *
   * @param receiptId - Receipt identifier
   * @param options - Share options (recipients, expiry, permissions)
   * @returns Share result
   */
  async share(receiptId: string, options?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v2/receipts/${encodeURIComponent(receiptId)}/share`, {
      json: options ?? {},
    });
  }

  /**
   * Verify a receipt's cryptographic signature (v2 API).
   *
   * @param receiptId - Receipt identifier
   * @returns Signature verification result
   */
  async verifySignature(receiptId: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v2/receipts/${encodeURIComponent(receiptId)}/verify-signature`);
  }

  // ===========================================================================
  // v1 Gauntlet Receipt Methods
  // ===========================================================================

  /**
   * List decision receipts via the v1 gauntlet API with advanced filtering.
   *
   * @param params - Filter parameters
   * @returns List of receipts
   */
  async listV1(params?: {
    debate_id?: string;
    from_date?: string;
    to_date?: string;
    consensus_reached?: boolean;
    min_confidence?: number;
    limit?: number;
    offset?: number;
  }): Promise<Record<string, unknown>> {
    const queryParams: Record<string, unknown> = {};
    if (params?.debate_id) queryParams.debate_id = params.debate_id;
    if (params?.from_date) queryParams.from_date = params.from_date;
    if (params?.to_date) queryParams.to_date = params.to_date;
    if (params?.consensus_reached !== undefined) queryParams.consensus_reached = String(params.consensus_reached);
    if (params?.min_confidence !== undefined) queryParams.min_confidence = String(params.min_confidence);
    if (params?.limit !== undefined) queryParams.limit = params.limit;
    if (params?.offset !== undefined) queryParams.offset = params.offset;
    return this.client.request('GET', '/api/v1/gauntlet/receipts', { params: queryParams });
  }

  /**
   * Get a decision receipt via the v1 gauntlet API.
   *
   * @param receiptId - Receipt identifier
   * @returns Receipt details
   */
  async getV1(receiptId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/gauntlet/receipts/${encodeURIComponent(receiptId)}`);
  }

  /**
   * Export a receipt via the v1 gauntlet API with detailed options.
   *
   * @param receiptId - Receipt identifier
   * @param options - Export options
   * @returns Exported receipt data
   */
  async exportV1(
    receiptId: string,
    options?: {
      format?: string;
      includeMetadata?: boolean;
      includeEvidence?: boolean;
      includeDissent?: boolean;
      prettyPrint?: boolean;
    }
  ): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/gauntlet/receipts/${encodeURIComponent(receiptId)}/export`, {
      params: {
        format: options?.format ?? 'json',
        include_metadata: String(options?.includeMetadata ?? true),
        include_evidence: String(options?.includeEvidence ?? false),
        include_dissent: String(options?.includeDissent ?? true),
        pretty_print: String(options?.prettyPrint ?? false),
      },
    });
  }

  /**
   * Export multiple receipts as a bundle.
   *
   * @param receiptIds - List of receipt IDs to include
   * @param options - Bundle export options
   * @returns Bundle export with all requested receipts
   */
  async exportBundle(
    receiptIds: string[],
    options?: {
      format?: string;
      includeMetadata?: boolean;
      includeEvidence?: boolean;
      includeDissent?: boolean;
    }
  ): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/gauntlet/receipts/export/bundle', {
      json: {
        receipt_ids: receiptIds,
        format: options?.format ?? 'json',
        include_metadata: options?.includeMetadata ?? true,
        include_evidence: options?.includeEvidence ?? false,
        include_dissent: options?.includeDissent ?? true,
      },
    });
  }

  /**
   * Stream receipt export data (for large receipts).
   *
   * @param receiptId - Receipt identifier
   * @returns Streamed receipt data
   */
  async stream(receiptId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/gauntlet/receipts/${encodeURIComponent(receiptId)}/stream`);
  }

  // ===========================================================================
  // Generic Receipt Methods (legacy)
  // ===========================================================================

  /**
   * List receipts with optional filtering.
   */
  async list(params?: { verdict?: string } & PaginationParams): Promise<{ receipts: DecisionReceipt[] }> {
    return this.client.listGauntletReceipts(params);
  }

  /**
   * Get a receipt by ID.
   */
  async get(receiptId: string): Promise<DecisionReceipt> {
    return this.client.getGauntletReceipt(receiptId);
  }

  /**
   * Verify a receipt's integrity.
   */
  async verify(receiptId: string): Promise<{ valid: boolean; hash: string }> {
    return this.client.verifyGauntletReceipt(receiptId);
  }

  /**
   * Verify a receipt with full signature validation.
   */
  async verifyFull(receiptId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v2/receipts/${encodeURIComponent(receiptId)}/verify`);
  }

  // ===========================================================================
  // Gauntlet Receipts
  // ===========================================================================

  /**
   * List gauntlet receipts with optional filtering.
   *
   * Gauntlet receipts are generated from attack/defend stress tests.
   */
  async listGauntlet(params?: { verdict?: string } & PaginationParams): Promise<{ receipts: DecisionReceipt[] }> {
    return this.client.listGauntletReceipts(params);
  }

  /**
   * Get a gauntlet receipt by ID.
   */
  async getGauntlet(receiptId: string): Promise<DecisionReceipt> {
    return this.client.getGauntletReceipt(receiptId);
  }

  /**
   * Verify a gauntlet receipt's integrity.
   */
  async verifyGauntlet(receiptId: string): Promise<{ valid: boolean; hash: string }> {
    return this.client.verifyGauntletReceipt(receiptId);
  }

  /**
   * Export a gauntlet receipt in various formats.
   *
   * @param receiptId - The receipt ID to export
   * @param format - Export format:
   *   - json: Machine-readable JSON
   *   - markdown: Human-readable Markdown
   *   - html: Styled HTML document
   *   - sarif: SARIF format for security tooling
   *
   * @example
   * ```typescript
   * // Export as HTML for stakeholder review
   * const html = await client.receipts.exportGauntlet('receipt-123', 'html');
   *
   * // Export as SARIF for security integration
   * const sarif = await client.receipts.exportGauntlet('receipt-123', 'sarif');
   * ```
   */
  async exportGauntlet(
    receiptId: string,
    format: 'json' | 'markdown' | 'html' | 'sarif'
  ): Promise<GauntletReceiptExport> {
    return this.client.exportGauntletReceipt(receiptId, format);
  }

  // ===========================================================================
  // Helpers
  // ===========================================================================

  /**
   * Check if a receipt has any dissenting views.
   */
  hasDissent(receipt: DecisionReceipt): boolean {
    return (receipt.dissenting_agents?.length ?? 0) > 0;
  }

  /**
   * Get the consensus status from a receipt.
   */
  getConsensusStatus(receipt: DecisionReceipt): {
    reached: boolean;
    confidence: number;
    participatingAgents: number;
    dissentingAgents: number;
  } {
    return {
      reached: receipt.consensus_reached ?? false,
      confidence: receipt.confidence ?? 0,
      participatingAgents: receipt.participating_agents?.length ?? 0,
      dissentingAgents: receipt.dissenting_agents?.length ?? 0,
    };
  }
}
