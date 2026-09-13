import { describe, expect, it } from 'vitest'
import { flatKeysToPermissionRows, permissionRowsToFlatKeys } from '../app/utils/role/permissions'
import { resolveUserPermissionKeys } from '../app/utils/auth/user-permissions'

describe('role-only authorization', () => {
  it('round-trips backend permission codes through the matrix rows', () => {
    const keys = [
      'report.sales',
      'report.finance',
      'customer.debt.pay',
      'stock.view',
      'pos.access',
      'supplier.debt.pay',
      'product.update',
    ]
    expect(permissionRowsToFlatKeys(flatKeysToPermissionRows(keys))).toEqual([...keys].sort())
  })

  it('fails closed when permissions are absent', () => {
    expect(resolveUserPermissionKeys({ name: 'No access', email: 'none@example.com' })).toEqual([])
  })

  it('uses effective permissions before compatibility fields', () => {
    expect(resolveUserPermissionKeys({
      name: 'Restricted',
      email: 'restricted@example.com',
      effectivePermissions: ['report.sales'],
      permissions: ['ALL_PAGES'],
      pageAccess: ['ALL_PAGES'],
    })).toEqual(['report.sales'])
  })
})
