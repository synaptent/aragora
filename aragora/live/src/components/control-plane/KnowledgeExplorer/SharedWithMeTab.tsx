/**
 * SharedWithMeTab Component
 *
 * Displays knowledge items that have been shared with the current user or workspace.
 * Shows the sharer, permissions, and expiration status.
 */

import React, { useState, useCallback } from 'react';

export interface SharedItem {
  id: string;
  title: string;
  content: string;
  sharedBy: { id: string; name: string; type: 'user' | 'workspace' };
  sharedAt: Date;
  expiresAt?: Date;
  permissions: string[];
  sourceWorkspace: { id: string; name: string };
}

export interface SharedWithMeTabProps {
  /** List of shared items */
  items: SharedItem[];
  /** Whether items are loading */
  isLoading?: boolean;
  /** Callback when an item is clicked */
  onItemClick?: (item: SharedItem) => void;
  /** Callback to accept/add to workspace */
  onAccept?: (item: SharedItem) => void;
  /** Callback to decline/hide from list */
  onDecline?: (item: SharedItem) => void;
  /** Error message to display */
  error?: string;
}

const formatDate = (date: Date): string => {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
};

const isExpiringSoon = (expiresAt?: Date): boolean => {
  if (!expiresAt) return false;
  const now = new Date();
  const threeDaysFromNow = new Date(now.getTime() + 3 * 24 * 60 * 60 * 1000);
  return expiresAt <= threeDaysFromNow && expiresAt > now;
};

const isExpired = (expiresAt?: Date): boolean => {
  if (!expiresAt) return false;
  return expiresAt <= new Date();
};

export const SharedWithMeTab: React.FC<SharedWithMeTabProps> = ({
  items,
  isLoading = false,
  onItemClick,
  onAccept,
  onDecline,
  error,
}) => {
  const [filter, setFilter] = useState<'all' | 'active' | 'expired'>('all');

  const filteredItems = items.filter((item) => {
    if (filter === 'all') return true;
    if (filter === 'active') return !isExpired(item.expiresAt);
    if (filter === 'expired') return isExpired(item.expiresAt);
    return true;
  });

  const handleItemClick = useCallback(
    (item: SharedItem) => {
      if (isExpired(item.expiresAt)) return;
      onItemClick?.(item);
    },
    [onItemClick],
  );

  if (error) {
    return (
      <div className="p-6 text-center">
        <div className="text-red-500 mb-2">Error loading shared items</div>
        <p className="text-sm text-gray-600">{error}</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        <span className="ml-2 text-gray-600">Loading shared items...</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header with filter */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
        <h3 className="text-sm font-medium text-gray-900">Shared With Me</h3>
        <div className="flex gap-1">
          {(['all', 'active', 'expired'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`
                px-2 py-1 text-xs font-medium rounded
                ${filter === f ? 'bg-blue-100 text-blue-700' : 'text-gray-600 hover:bg-gray-100'}
              `}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Items list */}
      <div className="flex-1 overflow-auto">
        {filteredItems.length === 0 ? (
          <div className="p-6 text-center text-gray-500">
            {filter === 'all'
              ? 'No items have been shared with you yet'
              : `No ${filter} shared items`}
          </div>
        ) : (
          <ul className="divide-y divide-gray-200">
            {filteredItems.map((item) => {
              const expired = isExpired(item.expiresAt);
              const expiringSoon = isExpiringSoon(item.expiresAt);

              return (
                <li
                  key={item.id}
                  className={`
                    p-4 hover:bg-gray-50 transition-colors
                    ${expired ? 'opacity-50' : 'cursor-pointer'}
                  `}
                  onClick={() => handleItemClick(item)}
                >
                  <div className="flex items-start gap-3">
                    {/* Icon */}
                    <div
                      className={`
                        flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center
                        ${expired ? 'bg-gray-100' : 'bg-blue-100'}
                      `}
                    >
                      <span className="text-lg">
                        {item.sharedBy.type === 'workspace' ? '👥' : '👤'}
                      </span>
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h4 className="text-sm font-medium text-gray-900 truncate">{item.title}</h4>
                        {expired && (
                          <span className="px-1.5 py-0.5 text-xs bg-red-100 text-red-700 rounded">
                            Expired
                          </span>
                        )}
                        {expiringSoon && !expired && (
                          <span className="px-1.5 py-0.5 text-xs bg-yellow-100 text-yellow-700 rounded">
                            Expires soon
                          </span>
                        )}
                      </div>

                      <p className="text-xs text-gray-600 mt-0.5 line-clamp-2">{item.content}</p>

                      <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
                        <span>
                          From: <strong>{item.sharedBy.name}</strong>
                        </span>
                        <span>({item.sourceWorkspace.name})</span>
                        <span>{formatDate(item.sharedAt)}</span>
                      </div>

                      {/* Permissions badges */}
                      <div className="flex gap-1 mt-2">
                        {item.permissions.map((perm) => (
                          <span
                            key={perm}
                            className="px-1.5 py-0.5 text-xs bg-gray-100 text-gray-600 rounded"
                          >
                            {perm}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Actions */}
                    {!expired && (onAccept || onDecline) && (
                      <div className="flex-shrink-0 flex gap-2">
                        {onAccept && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onAccept(item);
                            }}
                            className="px-2 py-1 text-xs font-medium text-white bg-blue-600 rounded hover:bg-blue-700"
                            title="Add to workspace"
                          >
                            Accept
                          </button>
                        )}
                        {onDecline && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onDecline(item);
                            }}
                            className="px-2 py-1 text-xs font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200"
                            title="Hide from list"
                          >
                            Decline
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Footer stats */}
      <div className="px-4 py-2 border-t border-gray-200 bg-gray-50 text-xs text-gray-600">
        {items.length} shared item{items.length !== 1 ? 's' : ''} total
        {items.filter((i) => isExpired(i.expiresAt)).length > 0 && (
          <span className="ml-2">
            ({items.filter((i) => isExpired(i.expiresAt)).length} expired)
          </span>
        )}
      </div>
    </div>
  );
};

export default SharedWithMeTab;
