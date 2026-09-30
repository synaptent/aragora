'use client';

import { useAuth } from '@/context/AuthContext';

/**
 * Hook to check if the current user is an admin or owner.
 *
 * Returns true if the user has admin or owner role in their current organization.
 * Returns false if not authenticated or has member/viewer role.
 *
 * @example
 * const isAdmin = useIsAdmin();
 * if (isAdmin) {
 *   // Show admin-only content
 * }
 */
export function useIsAdmin(): boolean {
  const { user, isAuthenticated, getCurrentOrgRole } = useAuth();

  if (!isAuthenticated || !user) {
    return false;
  }

  // Check org role first (multi-org context)
  const orgRole = getCurrentOrgRole();
  if (orgRole === 'admin' || orgRole === 'owner') {
    return true;
  }

  // Fallback to user's global role
  const role = user.role?.toLowerCase();
  return role === 'admin' || role === 'owner';
}

/**
 * Hook to check if the current user has a specific role.
 *
 * @param roles - Array of roles to check against
 * @returns true if user has any of the specified roles
 *
 * @example
 * const canManageTeam = useHasRole(['admin', 'owner', 'team_lead']);
 */
export function useHasRole(roles: string[]): boolean {
  const { user, isAuthenticated, getCurrentOrgRole } = useAuth();

  if (!isAuthenticated || !user) {
    return false;
  }

  const normalizedRoles = roles.map((r) => r.toLowerCase());

  // Check org role first
  const orgRole = getCurrentOrgRole();
  if (orgRole && normalizedRoles.includes(orgRole.toLowerCase())) {
    return true;
  }

  // Fallback to user's global role
  const userRole = user.role?.toLowerCase();
  return userRole ? normalizedRoles.includes(userRole) : false;
}

/**
 * Hook to get the current user's effective role.
 *
 * Returns the organization role if available, otherwise the global user role.
 * Returns null if not authenticated.
 *
 * @example
 * const role = useCurrentRole();
 * console.log(`User role: ${role}`); // 'admin', 'member', 'owner', etc.
 */
export function useCurrentRole(): string | null {
  const { user, isAuthenticated, getCurrentOrgRole } = useAuth();

  if (!isAuthenticated || !user) {
    return null;
  }

  // Org role takes precedence
  const orgRole = getCurrentOrgRole();
  if (orgRole) {
    return orgRole;
  }

  return user.role || null;
}
