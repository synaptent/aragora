/**
 * NotificationBell Component for Knowledge Mound Sharing Notifications.
 *
 * Displays a notification bell icon with unread count badge and dropdown
 * for viewing and managing sharing notifications.
 */

import React, { useCallback, useEffect, useState } from 'react';

interface SharingNotification {
  id: string;
  user_id: string;
  notification_type: 'item_shared' | 'item_unshared' | 'permission_changed' | 'share_expiring';
  title: string;
  message: string;
  item_id?: string;
  item_title?: string;
  from_user_id?: string;
  from_user_name?: string;
  status: 'unread' | 'read' | 'dismissed';
  created_at: string;
  read_at?: string;
}

interface NotificationBellProps {
  /** API base URL */
  apiUrl?: string;
  /** Polling interval in ms (default: 30000) */
  pollInterval?: number;
  /** Callback when notification is clicked */
  onNotificationClick?: (notification: SharingNotification) => void;
  /** Custom class name */
  className?: string;
}

export const NotificationBell: React.FC<NotificationBellProps> = ({
  apiUrl = '/api/knowledge/notifications',
  pollInterval = 30000,
  onNotificationClick,
  className = '',
}) => {
  const [notifications, setNotifications] = useState<SharingNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch notifications
  const fetchNotifications = useCallback(async () => {
    try {
      const response = await fetch(`${apiUrl}?limit=20`, { credentials: 'include' });
      if (!response.ok) throw new Error('Failed to fetch notifications');
      const data = await response.json();
      setNotifications(data.notifications || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, [apiUrl]);

  // Fetch unread count
  const fetchUnreadCount = useCallback(async () => {
    try {
      const response = await fetch(`${apiUrl}/count`, { credentials: 'include' });
      if (!response.ok) throw new Error('Failed to fetch count');
      const data = await response.json();
      setUnreadCount(data.unread_count || 0);
    } catch {
      // Silently fail for count updates
    }
  }, [apiUrl]);

  // Mark notification as read
  const markAsRead = useCallback(
    async (notificationId: string) => {
      try {
        await fetch(`${apiUrl}/${notificationId}/read`, { method: 'POST', credentials: 'include' });
        setNotifications((prev) =>
          prev.map((n) => (n.id === notificationId ? { ...n, status: 'read' as const } : n)),
        );
        setUnreadCount((prev) => Math.max(0, prev - 1));
      } catch {
        // Silently fail
      }
    },
    [apiUrl],
  );

  // Mark all as read
  const markAllAsRead = useCallback(async () => {
    try {
      await fetch(`${apiUrl}/read-all`, { method: 'POST', credentials: 'include' });
      setNotifications((prev) => prev.map((n) => ({ ...n, status: 'read' as const })));
      setUnreadCount(0);
    } catch {
      // Silently fail
    }
  }, [apiUrl]);

  // Dismiss notification
  const dismissNotification = useCallback(
    async (notificationId: string) => {
      try {
        await fetch(`${apiUrl}/${notificationId}/dismiss`, {
          method: 'POST',
          credentials: 'include',
        });
        setNotifications((prev) => prev.filter((n) => n.id !== notificationId));
      } catch {
        // Silently fail
      }
    },
    [apiUrl],
  );

  // Handle notification click
  const handleNotificationClick = useCallback(
    (notification: SharingNotification) => {
      if (notification.status === 'unread') {
        markAsRead(notification.id);
      }
      onNotificationClick?.(notification);
    },
    [markAsRead, onNotificationClick],
  );

  // Initial fetch and polling
  useEffect(() => {
    fetchUnreadCount();
    const interval = setInterval(fetchUnreadCount, pollInterval);
    return () => clearInterval(interval);
  }, [fetchUnreadCount, pollInterval]);

  // Fetch full list when dropdown opens
  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      fetchNotifications().finally(() => setLoading(false));
    }
  }, [isOpen, fetchNotifications]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (!target.closest('.notification-bell-container')) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('click', handleClickOutside);
      return () => document.removeEventListener('click', handleClickOutside);
    }
  }, [isOpen]);

  // Get icon based on notification type
  const getNotificationIcon = (type: string) => {
    switch (type) {
      case 'item_shared':
        return '\u{1F4E4}'; // outbox tray
      case 'item_unshared':
        return '\u{1F6AB}'; // prohibited
      case 'permission_changed':
        return '\u{1F511}'; // key
      case 'share_expiring':
        return '\u{23F0}'; // alarm clock
      default:
        return '\u{1F514}'; // bell
    }
  };

  // Format relative time
  const formatRelativeTime = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className={`notification-bell-container ${className}`} style={{ position: 'relative' }}>
      {/* Bell Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="notification-bell-button"
        aria-label={`Notifications (${unreadCount} unread)`}
        style={{
          background: 'transparent',
          border: '1px solid #333',
          borderRadius: '4px',
          padding: '8px 12px',
          cursor: 'pointer',
          position: 'relative',
          color: '#00ff00',
          fontFamily: 'monospace',
        }}
      >
        <span style={{ fontSize: '18px' }}>{'\u{1F514}'}</span>
        {unreadCount > 0 && (
          <span
            className="notification-badge"
            style={{
              position: 'absolute',
              top: '-4px',
              right: '-4px',
              background: '#ff4444',
              color: '#fff',
              borderRadius: '50%',
              minWidth: '18px',
              height: '18px',
              fontSize: '11px',
              fontWeight: 'bold',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div
          className="notification-dropdown"
          style={{
            position: 'absolute',
            top: '100%',
            right: '0',
            marginTop: '8px',
            width: '360px',
            maxHeight: '480px',
            overflowY: 'auto',
            background: '#0a0a0a',
            border: '1px solid #00ff00',
            borderRadius: '4px',
            zIndex: 1000,
            boxShadow: '0 4px 12px rgba(0, 255, 0, 0.2)',
          }}
        >
          {/* Header */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '12px 16px',
              borderBottom: '1px solid #333',
            }}
          >
            <span style={{ color: '#00ff00', fontWeight: 'bold', fontFamily: 'monospace' }}>
              Notifications
            </span>
            {unreadCount > 0 && (
              <button
                onClick={markAllAsRead}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: '#00ffff',
                  cursor: 'pointer',
                  fontSize: '12px',
                  fontFamily: 'monospace',
                }}
              >
                Mark all read
              </button>
            )}
          </div>

          {/* Notifications List */}
          <div style={{ padding: '8px' }}>
            {loading ? (
              <div
                style={{
                  padding: '20px',
                  textAlign: 'center',
                  color: '#666',
                  fontFamily: 'monospace',
                }}
              >
                Loading...
              </div>
            ) : error ? (
              <div
                style={{
                  padding: '20px',
                  textAlign: 'center',
                  color: '#ff4444',
                  fontFamily: 'monospace',
                }}
              >
                {error}
              </div>
            ) : notifications.length === 0 ? (
              <div
                style={{
                  padding: '20px',
                  textAlign: 'center',
                  color: '#666',
                  fontFamily: 'monospace',
                }}
              >
                No notifications
              </div>
            ) : (
              notifications.map((notification) => (
                <div
                  key={notification.id}
                  onClick={() => handleNotificationClick(notification)}
                  style={{
                    padding: '12px',
                    borderRadius: '4px',
                    marginBottom: '4px',
                    cursor: 'pointer',
                    background:
                      notification.status === 'unread' ? 'rgba(0, 255, 0, 0.1)' : 'transparent',
                    borderLeft:
                      notification.status === 'unread'
                        ? '3px solid #00ff00'
                        : '3px solid transparent',
                  }}
                >
                  <div style={{ display: 'flex', gap: '12px' }}>
                    <span style={{ fontSize: '20px' }}>
                      {getNotificationIcon(notification.notification_type)}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          fontFamily: 'monospace',
                          fontSize: '13px',
                          color: notification.status === 'unread' ? '#00ff00' : '#aaa',
                          fontWeight: notification.status === 'unread' ? 'bold' : 'normal',
                        }}
                      >
                        {notification.title}
                      </div>
                      <div
                        style={{
                          fontFamily: 'monospace',
                          fontSize: '12px',
                          color: '#888',
                          marginTop: '4px',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {notification.message}
                      </div>
                      <div
                        style={{
                          fontFamily: 'monospace',
                          fontSize: '11px',
                          color: '#666',
                          marginTop: '4px',
                        }}
                      >
                        {formatRelativeTime(notification.created_at)}
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        dismissNotification(notification.id);
                      }}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: '#666',
                        cursor: 'pointer',
                        padding: '4px',
                        fontSize: '14px',
                      }}
                      aria-label="Dismiss"
                    >
                      {'\u{2715}'}
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Footer */}
          {notifications.length > 0 && (
            <div style={{ padding: '12px 16px', borderTop: '1px solid #333', textAlign: 'center' }}>
              <a
                href="/knowledge/notifications"
                style={{
                  color: '#00ffff',
                  fontSize: '12px',
                  fontFamily: 'monospace',
                  textDecoration: 'none',
                }}
              >
                View all notifications
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default NotificationBell;
