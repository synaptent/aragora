/**
 * Modes Namespace API
 *
 * Operational modes (Architect, Coder, Reviewer, etc.).
 */

interface ModesClientInterface {
  request<T = unknown>(method: string, path: string, options?: {
    params?: Record<string, unknown>;
    json?: Record<string, unknown>;
    body?: Record<string, unknown>;
  }): Promise<T>;
}

export class ModesAPI {
  constructor(private client: ModesClientInterface) {}

  async listModes(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/modes');
  }
}
