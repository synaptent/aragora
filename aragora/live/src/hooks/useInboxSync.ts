'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { logger } from '@/utils/logger';

export type SyncStatus = 'idle' | 'connecting' | 'syncing' | 'completed' | 'error';

export interface SyncProgress {
  status: SyncStatus;
  progress: number; // 0-100
  messagesSynced: number;
  totalMessages: number;
  currentPhase: string;
  error?: string;
  startedAt?: string;
  completedAt?: string;
}

export interface InboxSyncEvent {
  type:
    | 'inbox_sync_start'
    | 'inbox_sync_progress'
    | 'inbox_sync_complete'
    | 'inbox_sync_error'
    | 'new_priority_email';
  user_id: string;
  data: {
    progress?: number;
    messages_synced?: number;
    total_messages?: number;
    phase?: string;
    error?: string;
    email?: { id: string; subject: string; from_address: string; priority: string };
  };
}

interface UseInboxSyncOptions {
  wsUrl: string;
  userId: string;
  authToken?: string;
  onNewPriorityEmail?: (email: InboxSyncEvent['data']['email']) => void;
  autoReconnect?: boolean;
  reconnectInterval?: number;
}

export function useInboxSync({
  wsUrl,
  userId,
  authToken,
  onNewPriorityEmail,
  autoReconnect = true,
  reconnectInterval = 5000,
}: UseInboxSyncOptions) {
  const [syncProgress, setSyncProgress] = useState<SyncProgress>({
    status: 'idle',
    progress: 0,
    messagesSynced: 0,
    totalMessages: 0,
    currentPhase: '',
  });
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const connect = useCallback(() => {
    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    // Clear any pending reconnect
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    setSyncProgress((prev) => ({ ...prev, status: 'connecting' }));

    try {
      // Build WebSocket URL with auth
      const url = new URL(`${wsUrl}/ws/inbox`);
      url.searchParams.set('user_id', userId);
      if (authToken) {
        url.searchParams.set('token', authToken);
      }

      const ws = new WebSocket(url.toString());
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setSyncProgress((prev) => ({
          ...prev,
          status: prev.status === 'connecting' ? 'idle' : prev.status,
        }));
      };

      ws.onmessage = (event) => {
        try {
          const data: InboxSyncEvent = JSON.parse(event.data);

          // Only process events for this user
          if (data.user_id !== userId) return;

          switch (data.type) {
            case 'inbox_sync_start':
              setSyncProgress({
                status: 'syncing',
                progress: 0,
                messagesSynced: 0,
                totalMessages: data.data.total_messages || 0,
                currentPhase: data.data.phase || 'Starting sync...',
                startedAt: new Date().toISOString(),
              });
              break;

            case 'inbox_sync_progress':
              setSyncProgress((prev) => ({
                ...prev,
                status: 'syncing',
                progress: data.data.progress || prev.progress,
                messagesSynced: data.data.messages_synced || prev.messagesSynced,
                totalMessages: data.data.total_messages || prev.totalMessages,
                currentPhase: data.data.phase || prev.currentPhase,
              }));
              break;

            case 'inbox_sync_complete':
              setSyncProgress((prev) => ({
                ...prev,
                status: 'completed',
                progress: 100,
                messagesSynced: data.data.messages_synced || prev.messagesSynced,
                completedAt: new Date().toISOString(),
                currentPhase: 'Sync complete',
              }));
              break;

            case 'inbox_sync_error':
              setSyncProgress((prev) => ({
                ...prev,
                status: 'error',
                error: data.data.error || 'Unknown error',
                currentPhase: 'Sync failed',
              }));
              break;

            case 'new_priority_email':
              if (data.data.email && onNewPriorityEmail) {
                onNewPriorityEmail(data.data.email);
              }
              break;
          }
        } catch (err) {
          logger.error('Failed to parse inbox sync event:', err);
        }
      };

      ws.onerror = (error) => {
        logger.error('Inbox WebSocket error:', error);
        setIsConnected(false);
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;

        // Auto-reconnect if enabled
        if (autoReconnect) {
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectInterval);
        }
      };
    } catch (err) {
      logger.error('Failed to connect to inbox WebSocket:', err);
      setSyncProgress((prev) => ({ ...prev, status: 'error', error: 'Failed to connect' }));
    }
  }, [wsUrl, userId, authToken, autoReconnect, reconnectInterval, onNewPriorityEmail]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const resetProgress = useCallback(() => {
    setSyncProgress({
      status: 'idle',
      progress: 0,
      messagesSynced: 0,
      totalMessages: 0,
      currentPhase: '',
    });
  }, []);

  // Connect on mount
  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return { syncProgress, isConnected, connect, disconnect, resetProgress };
}

// Toast notification helper for new priority emails
export function usePriorityEmailNotifications(
  onNotification?: (email: InboxSyncEvent['data']['email']) => void,
) {
  const [notifications, setNotifications] = useState<InboxSyncEvent['data']['email'][]>([]);

  const handleNewEmail = useCallback(
    (email: InboxSyncEvent['data']['email']) => {
      if (!email) return;

      setNotifications((prev) => [email, ...prev].slice(0, 10)); // Keep last 10
      onNotification?.(email);

      // Browser notification if permitted
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(`${email.priority?.toUpperCase()} Priority Email`, {
          body: `From: ${email.from_address}\n${email.subject}`,
          icon: '/icons/mail.png',
        });
      }
    },
    [onNotification],
  );

  const dismissNotification = useCallback((emailId: string) => {
    setNotifications((prev) => prev.filter((n) => n?.id !== emailId));
  }, []);

  const clearAll = useCallback(() => {
    setNotifications([]);
  }, []);

  // Request notification permission on mount
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, []);

  return { notifications, handleNewEmail, dismissNotification, clearAll };
}
