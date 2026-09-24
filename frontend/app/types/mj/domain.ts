/** JWT user permission contract types for the Stock & POS API. */

/** Permission codes carried by the authenticated user's JWT claims. */
export const SOURCE_PERMISSIONS = [
  'settings.view',
  'settings.update',
  'user.view',
  'user.create',
  'user.update',
  'user.delete',
  'role.view',
  'role.create',
  'role.update',
  'role.delete',
  'attachment.read',
  'attachment.upload',
  'attachment.delete',
  'audit.view',
  'report.sales',
] as const

export type SourcePermission = typeof SOURCE_PERMISSIONS[number]
