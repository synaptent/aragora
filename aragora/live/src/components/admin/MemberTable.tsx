'use client';

import React, { useState, useMemo } from 'react';

export interface Member {
  id: string;
  name: string;
  email: string;
  role: string;
  status: 'active' | 'inactive' | 'pending';
  joinedAt: string;
  lastActive?: string;
  avatar?: string;
}

export interface Column<T> {
  key: keyof T | string;
  label: string;
  sortable?: boolean;
  render?: (value: T[keyof T], row: T) => React.ReactNode;
  width?: string;
}

export type SortDirection = 'asc' | 'desc';

interface MemberTableProps<T extends Member> {
  data: T[];
  columns?: Column<T>[];
  loading?: boolean;
  pageSize?: number;
  currentPage?: number;
  totalItems?: number;
  onPageChange?: (page: number) => void;
  onSort?: (key: string, direction: SortDirection) => void;
  onRowClick?: (row: T) => void;
  onAction?: (action: string, row: T) => void;
  actions?: Array<{ label: string; value: string; variant?: 'default' | 'danger' | 'success' }>;
  selectable?: boolean;
  selectedIds?: string[];
  onSelectionChange?: (ids: string[]) => void;
  className?: string;
}

function RoleBadge({ role }: { role: string }) {
  const colors: Record<string, string> = {
    owner: 'bg-acid-magenta/20 text-[var(--acid-magenta)] border-acid-magenta/40',
    admin: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
    member: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    viewer: 'bg-text-muted/20 text-text-muted border-text-muted/40',
  };

  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[role] || colors.member}`}
    >
      {role.toUpperCase()}
    </span>
  );
}

function StatusBadge({ status }: { status: 'active' | 'inactive' | 'pending' }) {
  const colors: Record<string, string> = {
    active: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    inactive: 'bg-acid-red/20 text-acid-red border-acid-red/40',
    pending: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
  };

  return (
    <span className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[status]}`}>
      {status.toUpperCase()}
    </span>
  );
}

const defaultColumns: Column<Member>[] = [
  {
    key: 'name',
    label: 'Member',
    sortable: true,
    render: (_, row) => (
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-[var(--accent)]/20 flex items-center justify-center font-theme-data text-[var(--accent)] text-sm">
          {row.name?.charAt(0).toUpperCase() || row.email?.charAt(0).toUpperCase() || '?'}
        </div>
        <div>
          <div className="font-theme-data text-sm text-text">{row.name || 'Unknown'}</div>
          <div className="font-theme-data text-xs text-[var(--acid-cyan)]">{row.email}</div>
        </div>
      </div>
    ),
  },
  {
    key: 'role',
    label: 'Role',
    sortable: true,
    render: (value) => <RoleBadge role={value as string} />,
    width: '120px',
  },
  {
    key: 'status',
    label: 'Status',
    sortable: true,
    render: (value) => <StatusBadge status={value as 'active' | 'inactive' | 'pending'} />,
    width: '120px',
  },
  {
    key: 'joinedAt',
    label: 'Joined',
    sortable: true,
    render: (value) => (
      <span className="font-theme-data text-xs text-text-muted">
        {value ? new Date(value as string).toLocaleDateString() : '-'}
      </span>
    ),
    width: '120px',
  },
  {
    key: 'lastActive',
    label: 'Last Active',
    sortable: true,
    render: (value) => (
      <span className="font-theme-data text-xs text-text-muted">
        {value ? new Date(value as string).toLocaleDateString() : 'Never'}
      </span>
    ),
    width: '120px',
  },
];

export function MemberTable<T extends Member>({
  data,
  columns = defaultColumns as unknown as Column<T>[],
  loading = false,
  pageSize = 10,
  currentPage = 1,
  totalItems,
  onPageChange,
  onSort,
  onRowClick,
  onAction,
  actions = [
    { label: 'Edit', value: 'edit' },
    { label: 'Deactivate', value: 'deactivate', variant: 'danger' },
  ],
  selectable = false,
  selectedIds = [],
  onSelectionChange,
  className = '',
}: MemberTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [openActionMenu, setOpenActionMenu] = useState<string | null>(null);

  const totalPages = totalItems
    ? Math.ceil(totalItems / pageSize)
    : Math.ceil(data.length / pageSize);

  const handleSort = (key: string) => {
    const newDirection = sortKey === key && sortDirection === 'asc' ? 'desc' : 'asc';
    setSortKey(key);
    setSortDirection(newDirection);
    onSort?.(key, newDirection);
  };

  const sortedData = useMemo(() => {
    if (!sortKey || onSort) return data;

    return [...data].sort((a, b) => {
      const aVal = a[sortKey as keyof T];
      const bVal = b[sortKey as keyof T];

      if (aVal === undefined || aVal === null) return sortDirection === 'asc' ? 1 : -1;
      if (bVal === undefined || bVal === null) return sortDirection === 'asc' ? -1 : 1;

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortDirection === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      }

      return sortDirection === 'asc'
        ? (aVal as number) - (bVal as number)
        : (bVal as number) - (aVal as number);
    });
  }, [data, sortKey, sortDirection, onSort]);

  const paginatedData = useMemo(() => {
    if (onPageChange) return sortedData;
    const start = (currentPage - 1) * pageSize;
    return sortedData.slice(start, start + pageSize);
  }, [sortedData, currentPage, pageSize, onPageChange]);

  const handleSelectAll = () => {
    if (selectedIds.length === paginatedData.length) {
      onSelectionChange?.([]);
    } else {
      onSelectionChange?.(paginatedData.map((row) => row.id));
    }
  };

  const handleSelectRow = (id: string) => {
    if (selectedIds.includes(id)) {
      onSelectionChange?.(selectedIds.filter((i) => i !== id));
    } else {
      onSelectionChange?.([...selectedIds, id]);
    }
  };

  const getActionButtonClass = (variant?: string) => {
    switch (variant) {
      case 'danger':
        return 'text-acid-red hover:bg-acid-red/10';
      case 'success':
        return 'text-[var(--accent)] hover:bg-[var(--accent)]/10';
      default:
        return 'text-text hover:bg-surface-elevated';
    }
  };

  return (
    <div className={`card overflow-hidden ${className}`}>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-surface border-b border-[var(--accent)]/20">
            <tr>
              {selectable && (
                <th className="w-12 px-4 py-3">
                  <input
                    type="checkbox"
                    checked={
                      paginatedData.length > 0 && selectedIds.length === paginatedData.length
                    }
                    onChange={handleSelectAll}
                    className="w-4 h-4 accent-acid-green"
                  />
                </th>
              )}
              {columns.map((col) => (
                <th
                  key={String(col.key)}
                  className={`text-left px-4 py-3 font-theme-data text-xs text-text-muted ${
                    col.sortable ? 'cursor-pointer hover:text-text transition-colors' : ''
                  }`}
                  style={{ width: col.width }}
                  onClick={() => col.sortable && handleSort(String(col.key))}
                >
                  <div className="flex items-center gap-1">
                    <span>{col.label}</span>
                    {col.sortable && sortKey === String(col.key) && (
                      <span className="text-[var(--accent)]">
                        {sortDirection === 'asc' ? '^' : 'v'}
                      </span>
                    )}
                  </div>
                </th>
              ))}
              {actions.length > 0 && (
                <th className="w-24 px-4 py-3 text-left font-theme-data text-xs text-text-muted">
                  ACTIONS
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td
                  colSpan={columns.length + (selectable ? 2 : 1)}
                  className="px-4 py-8 text-center"
                >
                  <div className="font-theme-data text-text-muted animate-pulse">Loading...</div>
                </td>
              </tr>
            )}
            {!loading && paginatedData.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length + (selectable ? 2 : 1)}
                  className="px-4 py-8 text-center"
                >
                  <div className="font-theme-data text-text-muted">No members found</div>
                </td>
              </tr>
            )}
            {!loading &&
              paginatedData.map((row) => (
                <tr
                  key={row.id}
                  className={`border-b border-[var(--accent)]/10 hover:bg-surface/50 ${
                    onRowClick ? 'cursor-pointer' : ''
                  } ${selectedIds.includes(row.id) ? 'bg-[var(--accent)]/5' : ''}`}
                  onClick={() => onRowClick?.(row)}
                >
                  {selectable && (
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(row.id)}
                        onChange={() => handleSelectRow(row.id)}
                        className="w-4 h-4 accent-acid-green"
                      />
                    </td>
                  )}
                  {columns.map((col) => (
                    <td key={String(col.key)} className="px-4 py-3">
                      {col.render
                        ? col.render(row[col.key as keyof T], row)
                        : String(row[col.key as keyof T] ?? '-')}
                    </td>
                  ))}
                  {actions.length > 0 && (
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <div className="relative">
                        <button
                          onClick={() =>
                            setOpenActionMenu(openActionMenu === row.id ? null : row.id)
                          }
                          className="px-2 py-1 font-theme-data text-xs text-text-muted hover:text-text hover:bg-surface-elevated rounded transition-colors"
                        >
                          ...
                        </button>
                        {openActionMenu === row.id && (
                          <>
                            <div
                              className="fixed inset-0 z-40"
                              onClick={() => setOpenActionMenu(null)}
                            />
                            <div className="absolute right-0 top-full mt-1 z-50 bg-surface border border-[var(--accent)]/40 rounded shadow-lg py-1 min-w-[120px]">
                              {actions.map((action) => (
                                <button
                                  key={action.value}
                                  onClick={() => {
                                    onAction?.(action.value, row);
                                    setOpenActionMenu(null);
                                  }}
                                  className={`w-full text-left px-3 py-2 font-theme-data text-xs transition-colors ${getActionButtonClass(action.variant)}`}
                                >
                                  {action.label}
                                </button>
                              ))}
                            </div>
                          </>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--accent)]/20">
          <div className="font-theme-data text-xs text-text-muted">
            Showing {(currentPage - 1) * pageSize + 1} to{' '}
            {Math.min(currentPage * pageSize, totalItems || data.length)} of{' '}
            {totalItems || data.length}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onPageChange?.(currentPage - 1)}
              disabled={currentPage <= 1}
              className="px-3 py-1 font-theme-data text-sm text-[var(--acid-cyan)] hover:text-[var(--accent)] disabled:text-text-muted disabled:cursor-not-allowed transition-colors"
            >
              &lt; PREV
            </button>
            <div className="flex items-center gap-1">
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                let pageNum: number;
                if (totalPages <= 5) {
                  pageNum = i + 1;
                } else if (currentPage <= 3) {
                  pageNum = i + 1;
                } else if (currentPage >= totalPages - 2) {
                  pageNum = totalPages - 4 + i;
                } else {
                  pageNum = currentPage - 2 + i;
                }
                return (
                  <button
                    key={pageNum}
                    onClick={() => onPageChange?.(pageNum)}
                    className={`w-8 h-8 font-theme-data text-sm rounded transition-colors ${
                      currentPage === pageNum
                        ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40'
                        : 'text-text-muted hover:text-text hover:bg-surface-elevated'
                    }`}
                  >
                    {pageNum}
                  </button>
                );
              })}
            </div>
            <button
              onClick={() => onPageChange?.(currentPage + 1)}
              disabled={currentPage >= totalPages}
              className="px-3 py-1 font-theme-data text-sm text-[var(--acid-cyan)] hover:text-[var(--accent)] disabled:text-text-muted disabled:cursor-not-allowed transition-colors"
            >
              NEXT &gt;
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default MemberTable;
