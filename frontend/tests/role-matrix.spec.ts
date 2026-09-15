import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  PERMISSION_MATRIX_PAGES,
  allFrontendPermissionCodes,
} from '../app/utils/role/permissions'
import en from '../i18n/locales/en.json'
import km from '../i18n/locales/km.json'

/**
 * The role matrix is a page/module projection of the backend permission
 * catalog. These tests keep it honest: every assignable backend code must be
 * reachable from the matrix, no code may be invented, and every page/action
 * label must exist in both locales.
 */

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '../..')

function backendAssignableCodes(): Set<string> {
  const source = readFileSync(join(repoRoot, 'backend/app/core/permissions.py'), 'utf8')
  const start = source.indexOf('PERMISSION_CATALOG')
  const end = source.indexOf('SERVICE_PERMISSIONS')
  const block = source.slice(start, end)
  const codes = new Set<string>()
  const row = /"([a-z_]+)":\s*\(([^)]*)\)/g
  let match: RegExpExecArray | null
  while ((match = row.exec(block)) !== null) {
    const module = match[1]
    for (const action of match[2].matchAll(/"([^"]+)"/g)) codes.add(`${module}.${action[1]}`)
  }
  return codes
}

function leafKeys(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return value && typeof value === 'object'
      ? leafKeys(value as Record<string, unknown>, path)
      : [path]
  })
}

describe('role permission matrix', () => {
  const backendCodes = backendAssignableCodes()
  const matrixCodes = new Set(allFrontendPermissionCodes())

  it('covers every assignable backend permission exactly', () => {
    const missing = [...backendCodes].filter(code => !matrixCodes.has(code)).sort()
    expect(missing, `backend codes missing from the matrix: ${missing.join(', ')}`).toEqual([])
  })

  it('does not invent permissions the backend does not support', () => {
    const unknown = [...matrixCodes].filter(code => !backendCodes.has(code)).sort()
    expect(unknown, `unknown matrix codes: ${unknown.join(', ')}`).toEqual([])
  })

  it('uses unique page row ids', () => {
    const ids = PERMISSION_MATRIX_PAGES.map(page => page.value)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('labels every page and action in English and Khmer', () => {
    const enKeys = new Set(leafKeys(en as Record<string, unknown>))
    const kmKeys = new Set(leafKeys(km as Record<string, unknown>))
    for (const page of PERMISSION_MATRIX_PAGES) {
      expect(enKeys.has(page.labelKey), `en ${page.labelKey}`).toBe(true)
      expect(kmKeys.has(page.labelKey), `km ${page.labelKey}`).toBe(true)
      for (const action of page.actions) {
        const key = `core.rolePermissions.actions.${action.key}`
        expect(enKeys.has(key), `en ${key}`).toBe(true)
        expect(kmKeys.has(key), `km ${key}`).toBe(true)
      }
    }
  })
})
