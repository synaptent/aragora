/**
 * AccessGrantsList Component
 *
 * Displays and manages the list of access grants for a knowledge item.
 * Allows viewing who has access and revoking grants.
 */

import React, { useCallback } from 'react';

export type GranteeType = 'user' | 'workspace' | 'organization' | 'role';

export interface AccessGrant {
  id: string;
  granteeType: GranteeType;
  granteeId: string;
  granteeName: string;
  permissions: string[];
  grantedBy?: string;
  grantedAt: Date;
  expiresAt?: Date;
}

export interface AccessGrantsListProps {
  /** List of access grants */
  grants: AccessGrant[];
  /** Whether grants are loading */
  isLoading?: boolean;
  /** Whether user can revoke grants */
  canRevoke?: boolean;
  /** Callback when a grant is revoked */
  onRevoke?: (grantId: string) => void;
  /** Callback to add a new grant */
  onAddGrant?: () => void;
  /** Error message */
  error?: string;
}

const granteeIcons: Record<GranteeType, string> = {
  user: '👤',
  workspace: '👥',
  organization: '🏢',
  role: '🔑',
};

const formatDate = (date: Date): string => {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date);
};

const isExpired = (expiresAt?: Date): boolean => {
  if (!expiresAt) return false;
  return expiresAt <= new Date();
};

const isExpiringSoon = (expiresAt?: Date): boolean => {
  if (!expiresAt) return false;
  const now = new Date();
  const threeDaysFromNow = new Date(now.getTime() + 3 * 24 * 60 * 60 * 1000);
  return expiresAt <= threeDaysFromNow && expiresAt > now;
};

export const AccessGrantsList: React.FC<AccessGrantsListProps> = ({
  grants,
  isLoading = false,
  canRevoke = false,
  onRevoke,
  onAddGrant,
  error,
}) => {
  const handleRevoke = useCallback(
    (grantId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      if (onRevoke) {
        onRevoke(grantId);
      }
    },
    [onRevoke],
  );

  if (error) {
    return (
      <div className="p-4 text-center">
        <div className="text-red-500 text-sm">{error}</div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-4 flex items-center justify-center">
        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
        <span className="ml-2 text-sm text-gray-600">Loading grants...</span>
      </div>
    );
  }

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-50 border-b border-gray-200">
        <h4 className="text-sm font-medium text-gray-700">Access Grants</h4>
        {onAddGrant && (
          <button
            onClick={onAddGrant}
            className="px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 rounded"
          >
            + Add
          </button>
        )}
      </div>

      {/* Grants list */}
      {grants.length === 0 ? (
        <div className="p-4 text-center text-sm text-gray-500">No explicit access grants</div>
      ) : (
        <ul className="divide-y divide-gray-100">
          {grants.map((grant) => {
            const expired = isExpired(grant.expiresAt);
            const expiringSoon = isExpiringSoon(grant.expiresAt);

            return (
              <li key={grant.id} className={`px-3 py-2 ${expired ? 'opacity-50 bg-gray-50' : ''}`}>
                <div className="flex items-center gap-2">
                  {/* Grantee icon */}
                  <span className="text-base">{granteeIcons[grant.granteeType]}</span>

                  {/* Grantee info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-900 truncate">
                        {grant.granteeName}
                      </span>
                      {expired && (
                        <span className="px-1 py-0.5 text-xs bg-red-100 text-red-600 rounded">
                          Expired
                        </span>
                      )}
                      {expiringSoon && !expired && (
                        <span className="px-1 py-0.5 text-xs bg-yellow-100 text-yellow-600 rounded">
                          Expiring
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500">
                      <span className="capitalize">{grant.granteeType}</span>
                      {grant.grantedBy && <span> • Granted by {grant.grantedBy}</span>}
                      {grant.expiresAt && <span> • Expires {formatDate(grant.expiresAt)}</span>}
                    </div>
                  </div>

                  {/* Permissions */}
                  <div className="flex gap-1">
                    {grant.permissions.map((perm) => (
                      <span
                        key={perm}
                        className="px-1.5 py-0.5 text-xs bg-gray-100 text-gray-600 rounded"
                      >
                        {perm}
                      </span>
                    ))}
                  </div>

                  {/* Revoke button */}
                  {canRevoke && onRevoke && !expired && (
                    <button
                      onClick={(e) => handleRevoke(grant.id, e)}
                      className="px-2 py-1 text-xs text-red-600 hover:bg-red-50 rounded"
                      title="Revoke access"
                    >
                      Revoke
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Footer stats */}
      {grants.length > 0 && (
        <div className="px-3 py-1.5 bg-gray-50 border-t border-gray-200 text-xs text-gray-500">
          {grants.filter((g) => !isExpired(g.expiresAt)).length} active grant
          {grants.filter((g) => !isExpired(g.expiresAt)).length !== 1 ? 's' : ''}
          {grants.filter((g) => isExpired(g.expiresAt)).length > 0 && (
            <span className="ml-1">
              ({grants.filter((g) => isExpired(g.expiresAt)).length} expired)
            </span>
          )}
        </div>
      )}
    </div>
  );
};

export default AccessGrantsList;
