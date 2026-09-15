import type { AuthUser } from '~/types/auth-user'
import { allFrontendPermissionCodes } from '~/utils/role/permissions'

/** All permission keys defined by the system matrix. */
export function getAllSystemPermissionKeys(): string[] {
  return allFrontendPermissionCodes().sort()
}

/** Resolve flat permission keys for the signed-in user. */
export function resolveUserPermissionKeys(user: AuthUser | null | undefined): string[] {
  if (!user) return []
  if (user.role === 'Administrator') return getAllSystemPermissionKeys()
  const access = user.effectivePermissions ?? user.permissions ?? user.pageAccess
  if (!Array.isArray(access)) return []
  if (access.includes('ALL_PAGES')) return getAllSystemPermissionKeys()
  return [...access].sort()
}
