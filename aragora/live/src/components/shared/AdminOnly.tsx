'use client';

import { ReactNode } from 'react';
import { useIsAdmin } from '@/hooks/usePermission';

interface AdminOnlyProps {
  /** Content to render when user is admin or owner */
  children: ReactNode;
  /** Optional fallback when user is not admin (defaults to null) */
  fallback?: ReactNode;
}

/**
 * Guard component that only renders children for admin/owner users.
 *
 * Use this to hide admin-only UI elements from regular users,
 * preventing unnecessary 401 errors from admin-only API endpoints.
 *
 * @example
 * // Basic usage - hides content for non-admins
 * <AdminOnly>
 *   <BreakpointsPanel />
 * </AdminOnly>
 *
 * @example
 * // With custom fallback
 * <AdminOnly fallback={<p>Admin access required</p>}>
 *   <MetricsPanel />
 * </AdminOnly>
 */
export function AdminOnly({ children, fallback = null }: AdminOnlyProps) {
  const isAdmin = useIsAdmin();

  if (isAdmin) {
    return <>{children}</>;
  }

  return <>{fallback}</>;
}

/**
 * HOC to wrap any component with AdminOnly guard
 *
 * @example
 * const AdminBreakpointsPanel = withAdminOnly(BreakpointsPanel);
 */
export function withAdminOnly<P extends object>(
  WrappedComponent: React.ComponentType<P>,
  options: { fallback?: ReactNode } = {},
) {
  return function WithAdminOnly(props: P) {
    return (
      <AdminOnly fallback={options.fallback}>
        <WrappedComponent {...props} />
      </AdminOnly>
    );
  };
}
