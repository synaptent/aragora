/**
 * Audience Namespace API
 *
 * Audience suggestion submission and retrieval for debates.
 */

interface AudienceClientInterface {
  request<T = unknown>(method: string, path: string, options?: {
    params?: Record<string, unknown>;
    json?: Record<string, unknown>;
    body?: Record<string, unknown>;
  }): Promise<T>;
}

export class AudienceAPI {
  constructor(private client: AudienceClientInterface) {}

  /**
   * @deprecated Not served: no handler dispatches
   * GET /api/v1/debates/{id}/audience/suggestions — the request falls through
   * to DebatesHandler's slug lookup and returns 404. Use
   * {@link listSuggestions} (documented GET /api/v1/audience/suggestions with
   * a debate_id query param) instead.
   */
  async getSuggestions(debateId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/debates/${encodeURIComponent(debateId)}/audience/suggestions`);
  }

  /**
   * @deprecated Not served: no handler dispatches
   * POST /api/v1/debates/{id}/audience/suggestions — the request falls through
   * to DebatesHandler's slug lookup and returns 404. Use
   * {@link createSuggestion} (POST /api/v1/audience/suggestions, dispatched by
   * AudienceSuggestionsHandler) instead.
   */
  async submitSuggestion(debateId: string, suggestion: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/debates/${encodeURIComponent(debateId)}/audience/suggestions`, { body: suggestion });
  }

  async listSuggestions(debateId: string, options?: { maxClusters?: number; threshold?: number }): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/audience/suggestions', {
      params: { debate_id: debateId, max_clusters: options?.maxClusters ?? 5, threshold: options?.threshold ?? 0.6 },
    });
  }

  async createSuggestion(debateId: string, suggestion: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/audience/suggestions', { body: { ...suggestion, debate_id: debateId } });
  }
}
