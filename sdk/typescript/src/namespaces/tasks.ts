/**
 * Tasks Namespace API
 *
 * Provides methods for task management.
 */

interface TasksClientInterface {
  request<T = unknown>(method: string, path: string, options?: Record<string, unknown>): Promise<T>;
}

export interface TaskQueueListOptions extends Record<string, unknown> {
  status?: string;
  work_type?: string;
  limit?: number;
}

export interface TaskQueueSyncOptions extends Record<string, unknown> {
  include_pending?: boolean;
  include_developer_tasks?: boolean;
  complete_missing?: boolean;
}

export interface TaskLeaseHeartbeatOptions extends Record<string, unknown> {
  ttl_hours?: number;
}

export class TasksAPI {
  constructor(private client: TasksClientInterface) {}

  /** Create a new task. */
  async create(data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v2/tasks', { body: data });
  }

  /** Get a task by ID. */
  async get(taskId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v2/tasks/${encodeURIComponent(taskId)}`);
  }

  /** List task history with optional filters. */
  async list(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/control-plane/tasks/history', { params });
  }

  /** Cancel a task by ID. */
  async delete(taskId: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/control-plane/tasks/${encodeURIComponent(taskId)}/cancel`);
  }

  /** List developer task queue items. */
  async listQueue(params?: TaskQueueListOptions): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/tasks/queue', { params });
  }

  /** Get a developer task queue item by ID. */
  async getQueueTask(taskId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/tasks/queue/${encodeURIComponent(taskId)}`);
  }

  /** Get developer task queue statistics. */
  async getQueueStats(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/tasks/queue/stats');
  }

  /** Synchronize developer coordination work into the global task queue. */
  async syncQueue(body: TaskQueueSyncOptions = {}): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/tasks/queue/sync', { body });
  }

  /** Claim a task queue item and create a lease. */
  async claimQueueTask(taskId: string, body: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/tasks/queue/${encodeURIComponent(taskId)}/claim`, { body });
  }

  /** List active task leases. */
  async listLeases(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/tasks/leases');
  }

  /** Heartbeat a task lease. */
  async heartbeatLease(leaseId: string, body: TaskLeaseHeartbeatOptions = {}): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/tasks/leases/${encodeURIComponent(leaseId)}/heartbeat`, { body });
  }

  /** Release a task lease. */
  async releaseLease(leaseId: string): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/tasks/leases/${encodeURIComponent(leaseId)}/release`);
  }

  /** Record completion for a task lease. */
  async completeLease(leaseId: string, body: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/tasks/leases/${encodeURIComponent(leaseId)}/complete`, { body });
  }

  /** List task salvage candidates. */
  async listSalvage(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/tasks/salvage');
  }
}
