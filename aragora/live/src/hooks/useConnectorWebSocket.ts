'use client';

/**
 * Connector WebSocket hook for real-time connector sync updates.
 *
 * @status PENDING_UI_INTEGRATION - This hook is fully implemented but not yet
 * wired to any UI component. Intended for use with ConnectorDashboard when
 * connector sync UI is built.
 *
 * Provides:
 * - Sync progress tracking
 * - Document ingestion events
 * - Connector status updates
 * - Error notifications
 *
 * @see aragora/live/src/components/control-plane/ConnectorDashboard/ for target integration
 */

import { useState, useCallback, useMemo } from 'react';
import { useWebSocketBase, WebSocketConnectionStatus } from './useWebSocketBase';
import { useBackend } from '@/components/BackendSelector';

// Event types from the connector stream
export type ConnectorEventType =
  | 'sync_started'
  | 'sync_progress'
  | 'sync_completed'
  | 'sync_failed'
  | 'sync_cancelled'
  | 'document_ingested'
  | 'document_failed'
  | 'connector_status'
  | 'rate_limit_warning'
  | 'connection_test';

export interface ConnectorSyncState {
  id: string;
  connector_id: string;
  connector_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  phase?: 'discovery' | 'fetching' | 'processing' | 'indexing';
  total_documents: number;
  documents_processed: number;
  documents_failed: number;
  bytes_processed: number;
  started_at?: string;
  completed_at?: string;
  estimated_remaining_ms?: number;
  error_message?: string;
}

export interface ConnectorStatusState {
  id: string;
  name: string;
  type: 'google_drive' | 'sharepoint' | 'confluence' | 'notion' | 'dropbox' | 's3' | 'custom';
  status: 'connected' | 'disconnected' | 'syncing' | 'error';
  last_sync?: string;
  next_sync?: string;
  documents_indexed: number;
  health_score?: number;
  error_message?: string;
}

export interface DocumentIngestEvent {
  connector_id: string;
  sync_id: string;
  document_id: string;
  document_name: string;
  document_type: string;
  size_bytes: number;
  status: 'success' | 'failed' | 'skipped';
  error_message?: string;
  processing_time_ms?: number;
}

export interface RateLimitWarning {
  connector_id: string;
  limit_type: 'api' | 'bandwidth' | 'storage';
  current_usage: number;
  limit: number;
  reset_at?: string;
  message: string;
}

export interface ConnectorEvent {
  type: ConnectorEventType;
  timestamp: string;
  connector_id: string;
  seq?: number;
  data: ConnectorSyncState | ConnectorStatusState | DocumentIngestEvent | RateLimitWarning;
}

export interface UseConnectorWebSocketOptions {
  /** Connector ID to monitor (if not provided, monitors all connectors) */
  connectorId?: string;
  /** Sync ID to monitor (for specific sync operation) */
  syncId?: string;
  /** Whether the connection is enabled */
  enabled?: boolean;
  /** Whether to automatically reconnect on disconnection */
  autoReconnect?: boolean;
  /** Callback when sync status changes */
  onSyncUpdate?: (sync: ConnectorSyncState) => void;
  /** Callback when connector status changes */
  onConnectorStatusChange?: (status: ConnectorStatusState) => void;
  /** Callback when a document is ingested */
  onDocumentIngested?: (doc: DocumentIngestEvent) => void;
  /** Callback when rate limit warning is received */
  onRateLimitWarning?: (warning: RateLimitWarning) => void;
}

export interface UseConnectorWebSocketReturn {
  /** Current WebSocket connection status */
  status: WebSocketConnectionStatus;
  /** Whether connected to the connector stream */
  isConnected: boolean;
  /** Connection error message if any */
  error: string | null;
  /** Current reconnection attempt */
  reconnectAttempt: number;
  /** Current sync operations */
  syncs: ConnectorSyncState[];
  /** Current connector statuses */
  connectors: ConnectorStatusState[];
  /** Recent document events (last 50) */
  recentDocuments: DocumentIngestEvent[];
  /** Active rate limit warnings */
  rateLimitWarnings: RateLimitWarning[];
  /** Manually reconnect */
  reconnect: () => void;
  /** Manually disconnect */
  disconnect: () => void;
  /** Cancel a sync operation */
  cancelSync: (syncId: string) => void;
  /** Trigger a sync */
  triggerSync: (connectorId: string) => void;
}

/**
 * Hook for connecting to the Connector WebSocket stream.
 *
 * @example
 * ```tsx
 * const {
 *   status,
 *   isConnected,
 *   syncs,
 *   connectors,
 *   recentDocuments,
 * } = useConnectorWebSocket({
 *   connectorId: 'google-drive-1',
 *   enabled: true,
 *   onSyncUpdate: (sync) => {
 *     setProgress(sync.progress);
 *   },
 * });
 * ```
 */
export function useConnectorWebSocket({
  connectorId,
  syncId,
  enabled = true,
  autoReconnect = true,
  onSyncUpdate,
  onConnectorStatusChange,
  onDocumentIngested,
  onRateLimitWarning,
}: UseConnectorWebSocketOptions = {}): UseConnectorWebSocketReturn {
  const { config: backendConfig } = useBackend();

  // State
  const [syncs, setSyncs] = useState<ConnectorSyncState[]>([]);
  const [connectors, setConnectors] = useState<ConnectorStatusState[]>([]);
  const [recentDocuments, setRecentDocuments] = useState<DocumentIngestEvent[]>([]);
  const [rateLimitWarnings, setRateLimitWarnings] = useState<RateLimitWarning[]>([]);

  // Build WebSocket URL
  const wsUrl = useMemo(() => {
    if (!backendConfig?.api) return '';
    const baseUrl = backendConfig.api.replace(/^http/, 'ws');

    if (syncId) {
      return `${baseUrl}/api/connectors/sync/${syncId}/stream`;
    }
    if (connectorId) {
      return `${baseUrl}/api/connectors/${connectorId}/stream`;
    }
    return `${baseUrl}/api/connectors/stream`;
  }, [backendConfig?.api, connectorId, syncId]);

  // Handle incoming events
  const handleEvent = useCallback(
    (event: ConnectorEvent) => {
      switch (event.type) {
        case 'sync_started':
        case 'sync_progress':
        case 'sync_completed':
        case 'sync_failed':
        case 'sync_cancelled': {
          const sync = event.data as ConnectorSyncState;
          setSyncs((prev) => {
            const idx = prev.findIndex((s) => s.id === sync.id);
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = sync;
              return updated;
            }
            return [...prev, sync];
          });
          onSyncUpdate?.(sync);
          break;
        }

        case 'connector_status': {
          const connector = event.data as ConnectorStatusState;
          setConnectors((prev) => {
            const idx = prev.findIndex((c) => c.id === connector.id);
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = connector;
              return updated;
            }
            return [...prev, connector];
          });
          onConnectorStatusChange?.(connector);
          break;
        }

        case 'document_ingested':
        case 'document_failed': {
          const doc = event.data as DocumentIngestEvent;
          setRecentDocuments((prev) => [doc, ...prev].slice(0, 50)); // Keep last 50
          onDocumentIngested?.(doc);
          break;
        }

        case 'rate_limit_warning': {
          const warning = event.data as RateLimitWarning;
          setRateLimitWarnings((prev) => {
            // Replace existing warning for same connector+type, or add new
            const idx = prev.findIndex(
              (w) => w.connector_id === warning.connector_id && w.limit_type === warning.limit_type,
            );
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = warning;
              return updated;
            }
            return [...prev, warning];
          });
          onRateLimitWarning?.(warning);
          break;
        }

        case 'connection_test': {
          // Connection test result - update connector status
          const status = event.data as ConnectorStatusState;
          setConnectors((prev) => {
            const idx = prev.findIndex((c) => c.id === status.id);
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = status;
              return updated;
            }
            return [...prev, status];
          });
          break;
        }

        default:
          break;
      }
    },
    [onSyncUpdate, onConnectorStatusChange, onDocumentIngested, onRateLimitWarning],
  );

  // Build subscription message
  const subscribeMessage = useMemo(() => {
    if (syncId) {
      return { type: 'subscribe', sync_id: syncId };
    }
    if (connectorId) {
      return { type: 'subscribe', connector_id: connectorId };
    }
    return { type: 'subscribe', channels: ['syncs', 'connectors', 'documents'] };
  }, [connectorId, syncId]);

  // Use base WebSocket hook
  const { status, error, isConnected, reconnectAttempt, send, reconnect, disconnect } =
    useWebSocketBase<ConnectorEvent>({
      wsUrl,
      enabled: enabled && !!wsUrl,
      autoReconnect,
      subscribeMessage,
      onEvent: handleEvent,
      logPrefix: '[Connector]',
    });

  // Cancel a sync operation
  const cancelSync = useCallback(
    (id: string) => {
      send({ type: 'cancel_sync', sync_id: id });
    },
    [send],
  );

  // Trigger a sync
  const triggerSync = useCallback(
    (id: string) => {
      send({ type: 'trigger_sync', connector_id: id });
    },
    [send],
  );

  return {
    status,
    isConnected,
    error,
    reconnectAttempt,
    syncs,
    connectors,
    recentDocuments,
    rateLimitWarnings,
    reconnect,
    disconnect,
    cancelSync,
    triggerSync,
  };
}

export default useConnectorWebSocket;
