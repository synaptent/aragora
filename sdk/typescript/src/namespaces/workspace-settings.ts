/**
 * Workspace Settings Namespace API
 *
 * Provides endpoints for managing workspace configuration
 * including preferences, feature flags, and integrations.
 */

import type { AragoraClient } from '../client';

/** Workspace settings */
export interface WorkspaceSettingsData {
  workspace_id: string;
  name: string;
  timezone: string;
  language: string;
  features: Record<string, boolean>;
  integrations: Record<string, IntegrationConfig>;
  notification_preferences: NotificationPreferences;
  updated_at: string;
}

/** Integration configuration */
export interface IntegrationConfig {
  enabled: boolean;
  config: Record<string, unknown>;
  connected_at?: string;
}

/** Notification preferences */
export interface NotificationPreferences {
  email: boolean;
  slack: boolean;
  in_app: boolean;
  digest_frequency: 'realtime' | 'hourly' | 'daily' | 'weekly';
}

/** Update settings request */
export interface UpdateSettingsRequest {
  name?: string;
  timezone?: string;
  language?: string;
  features?: Record<string, boolean>;
  notification_preferences?: Partial<NotificationPreferences>;
}

/**
 * Workspace Settings namespace for workspace configuration.
 *
 * @example
 * ```typescript
 * const settings = await client.workspaceSettings.get('ws_123');
 * await client.workspaceSettings.update('ws_123', { timezone: 'UTC' });
 * ```
 */
export class WorkspaceSettingsNamespace {
  constructor(private client: AragoraClient) {}

  /** Get workspace settings. */
  async get(workspaceId: string): Promise<WorkspaceSettingsData> {
    return this.client.request<WorkspaceSettingsData>(
      'GET',
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/settings`
    );
  }

  /** Update workspace settings. */
  async update(
    workspaceId: string,
    updates: UpdateSettingsRequest
  ): Promise<WorkspaceSettingsData> {
    return this.client.request<WorkspaceSettingsData>(
      'PUT',
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/settings`,
      { body: updates }
    );
  }

  /** Reset workspace settings to defaults. */
  async reset(workspaceId: string): Promise<WorkspaceSettingsData> {
    return this.client.request<WorkspaceSettingsData>(
      'POST',
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/settings/reset`
    );
  }

  /** Get feature flags for the workspace. */
  async getFeatureFlags(workspaceId: string): Promise<Record<string, boolean>> {
    const response = await this.client.request<{ features: Record<string, boolean> }>(
      'GET',
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/settings/features`
    );
    return response.features;
  }

  /** Update a feature flag. */
  async setFeatureFlag(
    workspaceId: string,
    feature: string,
    enabled: boolean
  ): Promise<{ success: boolean }> {
    return this.client.request<{ success: boolean }>(
      'PUT',
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/settings/features/${encodeURIComponent(feature)}`,
      { body: { enabled } }
    );
  }

  /** List all invites for a workspace. */
  async listInvites(workspaceId: string): Promise<{ invites: Record<string, unknown>[]; count: number }> {
    return this.client.request('GET', `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/invites`);
  }

  /** Create a workspace invite. */
  async createInvite(workspaceId: string, email: string, role: string, options?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/invites`, { body: { email, role, ...options } });
  }

  /** Revoke a workspace invite. */
  async revokeInvite(workspaceId: string, inviteId: string): Promise<{ success: boolean }> {
    return this.client.request('DELETE', `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/invites/${encodeURIComponent(inviteId)}`);
  }

  /** Resend a pending workspace invite. */
  async resendInvite(workspaceId: string, inviteId: string): Promise<{ success: boolean; message: string }> {
    return this.client.request('POST', `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/invites/${encodeURIComponent(inviteId)}/resend`);
  }
}
