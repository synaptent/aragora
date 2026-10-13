/**
 * Documents Namespace API
 *
 * Provides access to document management for debates and knowledge.
 * Supports various document formats and upload capabilities.
 */

/**
 * Document metadata
 */
export interface Document {
  id: string;
  name: string;
  format: string;
  size_bytes: number;
  mime_type: string;
  uploaded_at: string;
  updated_at: string;
  debate_id?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Supported document format
 */
export interface DocumentFormat {
  extension: string;
  mime_types: string[];
  description: string;
  max_size_mb: number;
}

/**
 * Upload result
 */
export interface UploadResult {
  document: Document;
  extracted_text?: string;
  page_count?: number;
}

/**
 * Internal client interface
 */
interface DocumentsClientInterface {
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Documents API namespace.
 *
 * Provides methods for document management:
 * - List documents
 * - Get supported formats
 * - Upload documents
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai', apiKey: 'your-key' });
 *
 * // List documents
 * const docs = await client.documents.list();
 *
 * // Get supported formats
 * const formats = await client.documents.getFormats();
 *
 * // Upload a document
 * const result = await client.documents.upload({
 *   name: 'report.pdf',
 *   content: base64Data,
 *   debate_id: 'debate-123'
 * });
 * ```
 */
export class DocumentsAPI {
  constructor(private client: DocumentsClientInterface) {}

  /**
   * List documents.
   */
  async list(options?: { debate_id?: string; limit?: number; offset?: number }): Promise<{ documents: Document[]; total: number }> {
    return this.client.request('GET', '/api/v1/documents', {
      params: options as Record<string, unknown> | undefined,
    });
  }

  /**
   * Get supported document formats.
   */
  async getFormats(): Promise<{ formats: DocumentFormat[] }> {
    return this.client.get('/api/v1/documents/formats');
  }

  /**
   * Upload a document.
   */
  async upload(body: {
    name: string;
    content: string;
    format?: string;
    debate_id?: string;
    metadata?: Record<string, unknown>;
  }): Promise<UploadResult> {
    return this.client.post('/api/v1/documents/upload', body);
  }

  /**
   * Get document metadata by ID.
   */
  async get(documentId: string): Promise<Document> {
    return this.client.request('GET', `/api/v1/documents/${encodeURIComponent(documentId)}`);
  }

  /**
   * Get chunked representation for a document.
   */
  async getChunks(
    documentId: string,
    options?: { limit?: number; offset?: number },
  ): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/documents/${encodeURIComponent(documentId)}/chunks`, {
      params: options as Record<string, unknown> | undefined,
    });
  }

  /**
   * Search document contents.
   *
   * @param query - Search query string.
   * @param options - Optional search parameters.
   */
  async search(query: string, options?: { limit?: number; offset?: number }): Promise<{ results: unknown[]; total: number }> {
    return this.client.request('GET', '/api/v1/documents/search', {
      params: { query, ...options } as Record<string, unknown>,
    });
  }
}
