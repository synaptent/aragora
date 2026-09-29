'use client';

import React, { useState, useMemo } from 'react';

export interface Permission {
  id: string;
  resource: string;
  action: string;
  description?: string;
}

export interface Role {
  id: string;
  name: string;
  description: string;
  permissions: string[];
  isBuiltin?: boolean;
  parentRole?: string;
}

interface RoleMatrixViewerProps {
  roles: Role[];
  permissions: Permission[];
  loading?: boolean;
  onRoleClick?: (role: Role) => void;
  onPermissionClick?: (permission: Permission) => void;
  groupByResource?: boolean;
  className?: string;
}

// Permission categories with colors
const RESOURCE_COLORS: Record<string, string> = {
  debates: 'acid-green',
  agents: 'acid-cyan',
  users: 'acid-magenta',
  admin: 'acid-yellow',
  billing: 'acid-red',
  workflows: 'acid-green',
  knowledge: 'acid-cyan',
  analytics: 'acid-magenta',
  documents: 'acid-yellow',
  compliance: 'acid-red',
  default: 'text-muted',
};

function getResourceColor(resource: string): string {
  return RESOURCE_COLORS[resource] || RESOURCE_COLORS.default;
}

export function RoleMatrixViewer({
  roles,
  permissions,
  loading = false,
  onRoleClick,
  onPermissionClick,
  groupByResource = true,
  className = '',
}: RoleMatrixViewerProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedResource, setSelectedResource] = useState<string | null>(null);
  const [hoveredCell, setHoveredCell] = useState<{ role: string; permission: string } | null>(null);

  // Get unique resources
  const resources = useMemo(() => {
    const resourceSet = new Set(permissions.map((p) => p.resource));
    return Array.from(resourceSet).sort();
  }, [permissions]);

  // Filter permissions by search and resource
  const filteredPermissions = useMemo(() => {
    let filtered = permissions;

    if (selectedResource) {
      filtered = filtered.filter((p) => p.resource === selectedResource);
    }

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (p) =>
          p.id.toLowerCase().includes(query) ||
          p.resource.toLowerCase().includes(query) ||
          p.action.toLowerCase().includes(query) ||
          p.description?.toLowerCase().includes(query),
      );
    }

    return filtered;
  }, [permissions, selectedResource, searchQuery]);

  // Group permissions by resource if enabled
  const groupedPermissions = useMemo(() => {
    if (!groupByResource) return { '': filteredPermissions };

    const groups: Record<string, Permission[]> = {};
    filteredPermissions.forEach((p) => {
      if (!groups[p.resource]) groups[p.resource] = [];
      groups[p.resource].push(p);
    });
    return groups;
  }, [filteredPermissions, groupByResource]);

  const hasPermission = (role: Role, permissionId: string): boolean => {
    return role.permissions.includes(permissionId);
  };

  const getInheritedPermission = (role: Role, permissionId: string): Role | null => {
    if (!role.parentRole) return null;
    const parent = roles.find((r) => r.id === role.parentRole);
    if (!parent) return null;
    if (parent.permissions.includes(permissionId)) return parent;
    return getInheritedPermission(parent, permissionId);
  };

  if (loading) {
    return (
      <div className={`card p-8 ${className}`}>
        <div className="flex items-center justify-center">
          <div className="font-theme-data text-text-muted animate-pulse">
            Loading permission matrix...
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`card overflow-hidden ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-[var(--accent)]/20">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-theme-data text-lg text-[var(--accent)]">PERMISSION MATRIX</h3>
          <div className="flex items-center gap-2">
            <span className="font-theme-data text-xs text-text-muted">
              {roles.length} roles / {permissions.length} permissions
            </span>
          </div>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-4">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search permissions..."
            className="flex-1 max-w-xs px-3 py-2 bg-surface-elevated border border-[var(--accent)]/30 rounded font-theme-data text-sm text-text placeholder-text-muted focus:border-[var(--accent)] focus:outline-none"
          />
          <div className="flex items-center gap-1">
            <button
              onClick={() => setSelectedResource(null)}
              className={`px-2 py-1 font-theme-data text-xs rounded transition-colors ${
                !selectedResource
                  ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              ALL
            </button>
            {resources.slice(0, 6).map((resource) => (
              <button
                key={resource}
                onClick={() => setSelectedResource(selectedResource === resource ? null : resource)}
                className={`px-2 py-1 font-theme-data text-xs rounded transition-colors ${
                  selectedResource === resource
                    ? `bg-${getResourceColor(resource)}/20 text-${getResourceColor(resource)} border border-${getResourceColor(resource)}/40`
                    : 'text-text-muted hover:text-text'
                }`}
              >
                {resource.toUpperCase()}
              </button>
            ))}
            {resources.length > 6 && (
              <span className="font-theme-data text-xs text-text-muted">
                +{resources.length - 6}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Matrix */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead className="bg-surface sticky top-0 z-10">
            <tr>
              <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted border-b border-[var(--accent)]/20 min-w-[200px]">
                PERMISSION
              </th>
              {roles.map((role) => (
                <th
                  key={role.id}
                  className="px-3 py-3 font-theme-data text-xs text-text-muted border-b border-[var(--accent)]/20 text-center cursor-pointer hover:text-[var(--accent)] transition-colors min-w-[80px]"
                  onClick={() => onRoleClick?.(role)}
                  title={role.description}
                >
                  <div className="flex flex-col items-center gap-1">
                    <span>{role.name.toUpperCase()}</span>
                    {role.isBuiltin && (
                      <span className="text-[10px] text-[var(--acid-cyan)]">BUILTIN</span>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(groupedPermissions).map(([resource, perms]) => (
              <React.Fragment key={resource}>
                {groupByResource && resource && (
                  <tr className="bg-surface-elevated/50">
                    <td
                      colSpan={roles.length + 1}
                      className={`px-4 py-2 font-theme-data text-xs text-${getResourceColor(resource)} border-b border-[var(--accent)]/10`}
                    >
                      {resource.toUpperCase()} ({perms.length})
                    </td>
                  </tr>
                )}
                {perms.map((permission) => (
                  <tr
                    key={permission.id}
                    className="border-b border-[var(--accent)]/5 hover:bg-surface/50"
                  >
                    <td
                      className="px-4 py-2 font-theme-data text-sm cursor-pointer hover:text-[var(--accent)] transition-colors"
                      onClick={() => onPermissionClick?.(permission)}
                      title={permission.description}
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-1.5 h-1.5 rounded-full bg-${getResourceColor(permission.resource)}`}
                        />
                        <span className="text-text">{permission.resource}:</span>
                        <span className="text-[var(--acid-cyan)]">{permission.action}</span>
                      </div>
                    </td>
                    {roles.map((role) => {
                      const has = hasPermission(role, permission.id);
                      const inherited = !has ? getInheritedPermission(role, permission.id) : null;
                      const isHovered =
                        hoveredCell?.role === role.id && hoveredCell?.permission === permission.id;

                      return (
                        <td
                          key={role.id}
                          className="px-3 py-2 text-center"
                          onMouseEnter={() =>
                            setHoveredCell({ role: role.id, permission: permission.id })
                          }
                          onMouseLeave={() => setHoveredCell(null)}
                        >
                          {has ? (
                            <span
                              className={`inline-block w-6 h-6 rounded bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] text-xs leading-6 ${
                                isHovered ? 'ring-2 ring-acid-green/60' : ''
                              }`}
                              title="Has permission"
                            >
                              Y
                            </span>
                          ) : inherited ? (
                            <span
                              className={`inline-block w-6 h-6 rounded bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] text-xs leading-6 ${
                                isHovered ? 'ring-2 ring-acid-cyan/60' : ''
                              }`}
                              title={`Inherited from ${inherited.name}`}
                            >
                              ^
                            </span>
                          ) : (
                            <span
                              className={`inline-block w-6 h-6 rounded bg-surface-elevated border border-[var(--accent)]/10 text-text-muted text-xs leading-6 ${
                                isHovered ? 'ring-2 ring-acid-green/20' : ''
                              }`}
                              title="No permission"
                            >
                              -
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="p-4 border-t border-[var(--accent)]/20 bg-surface">
        <div className="flex items-center gap-6 font-theme-data text-xs">
          <span className="text-text-muted">LEGEND:</span>
          <div className="flex items-center gap-2">
            <span className="inline-block w-5 h-5 rounded bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] text-[10px] leading-5 text-center">
              Y
            </span>
            <span className="text-text-muted">Direct</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block w-5 h-5 rounded bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] text-[10px] leading-5 text-center">
              ^
            </span>
            <span className="text-text-muted">Inherited</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block w-5 h-5 rounded bg-surface-elevated border border-[var(--accent)]/10 text-text-muted text-[10px] leading-5 text-center">
              -
            </span>
            <span className="text-text-muted">None</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default RoleMatrixViewer;
