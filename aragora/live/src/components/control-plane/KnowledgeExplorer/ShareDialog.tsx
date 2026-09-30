/**
 * ShareDialog Component
 *
 * A modal dialog for sharing knowledge items with other workspaces or users.
 * Supports granting read/write permissions and setting expiration dates.
 */

import React, { useState, useCallback } from 'react';

export type GranteeType = 'user' | 'workspace' | 'organization' | 'role';
export type Permission = 'read' | 'write' | 'admin';

export interface ShareGrant {
  granteeType: GranteeType;
  granteeId: string;
  granteeName: string;
  permissions: Permission[];
  expiresAt?: Date;
}

export interface ShareDialogProps {
  /** Whether the dialog is open */
  isOpen: boolean;
  /** Callback when dialog is closed */
  onClose: () => void;
  /** Callback when share is confirmed */
  onShare: (grant: ShareGrant) => void;
  /** Item ID being shared */
  itemId: string;
  /** Item title for display */
  itemTitle?: string;
  /** Available workspaces to share with */
  availableWorkspaces?: Array<{ id: string; name: string }>;
  /** Available users to share with */
  availableUsers?: Array<{ id: string; name: string; email?: string }>;
}

interface GranteeOption {
  type: GranteeType;
  id: string;
  name: string;
  subtitle?: string;
}

export const ShareDialog: React.FC<ShareDialogProps> = ({
  isOpen,
  onClose,
  onShare,
  itemId: _itemId,
  itemTitle,
  availableWorkspaces = [],
  availableUsers = [],
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedGrantee, setSelectedGrantee] = useState<GranteeOption | null>(null);
  const [permissions, setPermissions] = useState<Permission[]>(['read']);
  const [expiresAt, setExpiresAt] = useState<string>('');
  const [showDropdown, setShowDropdown] = useState(false);

  // Combine workspaces and users into searchable options
  const allOptions: GranteeOption[] = [
    ...availableWorkspaces.map((ws) => ({
      type: 'workspace' as GranteeType,
      id: ws.id,
      name: ws.name,
      subtitle: 'Workspace',
    })),
    ...availableUsers.map((u) => ({
      type: 'user' as GranteeType,
      id: u.id,
      name: u.name,
      subtitle: u.email,
    })),
  ];

  const filteredOptions = allOptions.filter(
    (opt) =>
      opt.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      opt.subtitle?.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const handlePermissionToggle = useCallback((perm: Permission) => {
    setPermissions((prev) => {
      if (prev.includes(perm)) {
        return prev.filter((p) => p !== perm);
      }
      return [...prev, perm];
    });
  }, []);

  const handleShare = useCallback(() => {
    if (!selectedGrantee || permissions.length === 0) return;

    onShare({
      granteeType: selectedGrantee.type,
      granteeId: selectedGrantee.id,
      granteeName: selectedGrantee.name,
      permissions,
      expiresAt: expiresAt ? new Date(expiresAt) : undefined,
    });

    // Reset form
    setSelectedGrantee(null);
    setPermissions(['read']);
    setExpiresAt('');
    setSearchQuery('');
    onClose();
  }, [selectedGrantee, permissions, expiresAt, onShare, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black bg-opacity-50"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Dialog */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="share-dialog-title"
        className="relative bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-6"
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h2 id="share-dialog-title" className="text-lg font-semibold text-gray-900">
            Share Knowledge Item
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
            aria-label="Close"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Item info */}
        {itemTitle && (
          <div className="mb-4 p-3 bg-gray-50 rounded-md">
            <p className="text-sm text-gray-600">Sharing:</p>
            <p className="text-sm font-medium text-gray-900 truncate">{itemTitle}</p>
          </div>
        )}

        {/* Grantee search */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">Share with</label>
          <div className="relative">
            <input
              type="text"
              value={selectedGrantee ? selectedGrantee.name : searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setSelectedGrantee(null);
                setShowDropdown(true);
              }}
              onFocus={() => setShowDropdown(true)}
              placeholder="Search workspaces or users..."
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />

            {showDropdown && filteredOptions.length > 0 && !selectedGrantee && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowDropdown(false)} />
                <ul className="absolute z-20 w-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg max-h-48 overflow-auto">
                  {filteredOptions.map((opt) => (
                    <li
                      key={`${opt.type}-${opt.id}`}
                      className="px-3 py-2 hover:bg-gray-50 cursor-pointer"
                      onClick={() => {
                        setSelectedGrantee(opt);
                        setShowDropdown(false);
                      }}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{opt.type === 'workspace' ? '👥' : '👤'}</span>
                        <div>
                          <div className="text-sm font-medium text-gray-900">{opt.name}</div>
                          {opt.subtitle && (
                            <div className="text-xs text-gray-500">{opt.subtitle}</div>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>

        {/* Permissions */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">Permissions</label>
          <div className="flex gap-3">
            {(['read', 'write', 'admin'] as Permission[]).map((perm) => (
              <label
                key={perm}
                className={`
                  flex items-center gap-2 px-3 py-2 rounded-md border cursor-pointer
                  ${
                    permissions.includes(perm)
                      ? 'bg-blue-50 border-blue-300 text-blue-700'
                      : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
                  }
                `}
              >
                <input
                  type="checkbox"
                  checked={permissions.includes(perm)}
                  onChange={() => handlePermissionToggle(perm)}
                  className="sr-only"
                />
                <span className="text-sm font-medium capitalize">{perm}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Expiration */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-1">Expires (optional)</label>
          <input
            type="datetime-local"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleShare}
            disabled={!selectedGrantee || permissions.length === 0}
            className={`
              px-4 py-2 text-sm font-medium text-white rounded-md
              ${
                selectedGrantee && permissions.length > 0
                  ? 'bg-blue-600 hover:bg-blue-700'
                  : 'bg-gray-300 cursor-not-allowed'
              }
            `}
          >
            Share
          </button>
        </div>
      </div>
    </div>
  );
};

export default ShareDialog;
