import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { CONFIRM_PRESETS, type ConfirmKind } from '../app/composables/common/useConfirm'
import en from '../i18n/locales/en.json'
import km from '../i18n/locales/km.json'

/**
 * Guards the shared dialog contract: header = icon + title only, body =
 * description/message + fields, footer = Cancel + primary action. This is a
 * source-level test (the repo has no component-test DOM environment), the same
 * approach used by `permission-catalog.spec.ts`.
 */

const here = dirname(fileURLToPath(import.meta.url))
const appRoot = resolve(here, '../app')

function walkVueFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) return walkVueFiles(full)
    return entry.name.endsWith('.vue') ? [full] : []
  })
}

const vueFiles = walkVueFiles(appRoot)
const sourceOf = (file: string) => readFileSync(file, 'utf8')
const rel = (file: string) => file.replace(appRoot, '').replaceAll('\\', '/')

function leafKeys(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return value && typeof value === 'object'
      ? leafKeys(value as Record<string, unknown>, path)
      : [path]
  })
}

const enKeys = new Set(leafKeys(en as Record<string, unknown>))
const kmKeys = new Set(leafKeys(km as Record<string, unknown>))

function bodyRegion(source: string): string {
  const start = source.indexOf('<template #body>')
  const end = source.indexOf('</template>', start)
  return start === -1 ? '' : source.slice(start, end)
}

describe('shared dialog structure', () => {
  const appDialog = sourceOf(join(appRoot, 'components/common/AppDialog.vue'))

  it('AppDialog renders the description inside the body, not the header', () => {
    expect(appDialog).toContain('<template #body>')
    expect(appDialog).not.toContain('#description')
    expect(appDialog).not.toMatch(/:description=/)
    // The description paragraph lives inside the body region.
    expect(bodyRegion(appDialog)).toContain('resolvedDescription')
  })

  it('AppDialog header slot contains the title only (icon + title)', () => {
    const start = appDialog.indexOf('<template #title>')
    const end = appDialog.indexOf('</template>', start)
    const titleRegion = appDialog.slice(start, end)
    expect(titleRegion).toContain('resolvedTitle')
    expect(titleRegion).not.toContain('resolvedDescription')
  })

  it('AppDialog body has readable spacing and wrapping', () => {
    const body = bodyRegion(appDialog)
    expect(body).toContain('space-y-4')
    expect(body).toContain('leading-relaxed')
  })

  it('no dialog puts its description in a header region', () => {
    const offenders: string[] = []
    for (const file of vueFiles) {
      const source = sourceOf(file)
      if (source.includes('<CommonAppDialog') && source.includes('#description')) {
        offenders.push(`${rel(file)} (CommonAppDialog #description)`)
      }
      for (const match of source.matchAll(/<UModal\b[^>]*>/gs)) {
        if (/\bdescription=/.test(match[0])) offenders.push(`${rel(file)} (UModal :description)`)
      }
    }
    expect(offenders, `description rendered in a header:\n${offenders.join('\n')}`).toEqual([])
  })

  it('every CommonAppDialog consumer renders footer actions', () => {
    const missing: string[] = []
    for (const file of vueFiles) {
      const source = sourceOf(file)
      if (file.endsWith('AppDialog.vue')) continue
      if (source.includes('<CommonAppDialog') && !source.includes('<template #footer>')) {
        missing.push(rel(file))
      }
    }
    expect(missing, `dialogs without a footer:\n${missing.join('\n')}`).toEqual([])
  })

  it('dialog footers right-align their actions', () => {
    const offenders: string[] = []
    for (const file of vueFiles) {
      const source = sourceOf(file)
      if (!source.includes('<CommonAppDialog')) continue
      if (source.includes('<template #footer>') && !/justify-end/.test(source)) {
        offenders.push(rel(file))
      }
    }
    expect(offenders, `footers not right-aligned:\n${offenders.join('\n')}`).toEqual([])
  })
})

describe('confirmation dialog presets', () => {
  const requiredKinds: ConfirmKind[] = ['submit', 'save', 'update', 'delete', 'activate', 'deactivate', 'unsaved', 'generic']

  it('every confirmation type defines a title, body and primary action', () => {
    for (const kind of requiredKinds) {
      const preset = CONFIRM_PRESETS[kind]
      expect(preset, kind).toBeTruthy()
      expect(preset.titleKey, `${kind}.titleKey`).toBeTruthy()
      expect(preset.descriptionKey, `${kind}.descriptionKey`).toBeTruthy()
      expect(preset.confirmLabelKey, `${kind}.confirmLabelKey`).toBeTruthy()
    }
  })

  it('destructive confirmations use error styling only for the primary action', () => {
    expect(CONFIRM_PRESETS.delete.confirmColor).toBe('error')
    expect(CONFIRM_PRESETS.deactivate.confirmColor).not.toBe('error')
    expect(CONFIRM_PRESETS.activate.confirmColor).not.toBe('error')
  })

  it('preset i18n keys exist in English and Khmer', () => {
    for (const kind of requiredKinds) {
      const preset = CONFIRM_PRESETS[kind]
      for (const key of [preset.titleKey, preset.descriptionKey, preset.confirmLabelKey, preset.cancelLabelKey]) {
        if (!key) continue
        expect(enKeys.has(key), `en ${key}`).toBe(true)
        expect(kmKeys.has(key), `km ${key}`).toBe(true)
      }
    }
  })

  it('confirm dialog cancel cannot be danger-styled and primary shows busy state', () => {
    const confirm = sourceOf(join(appRoot, 'components/common/AppConfirmDialog.vue'))
    expect(confirm).toMatch(/:color="confirmColor"/)
    const cancelBlock = confirm.slice(confirm.indexOf('resolvedCancel') - 200, confirm.indexOf('resolvedCancel'))
    expect(cancelBlock).not.toContain('error')
    expect(confirm).toContain(':loading="loading"')
    expect(confirm).toContain(':disabled="loading"')
  })
})

describe('confirmation dialog i18n copy', () => {
  it('uses the approved title/body wording', () => {
    const e = en as unknown as { core: { confirm: Record<string, string> } }
    expect(e.core.confirm.submitTitle).toBe('Submit?')
    expect(e.core.confirm.submitDescription).toBe('Do you want to submit this form?')
    expect(e.core.confirm.saveTitle).toBe('Save changes?')
    expect(e.core.confirm.saveDescription).toBe('Do you want to save your changes?')
    expect(e.core.confirm.updateTitle).toBe('Update?')
    expect(e.core.confirm.updateDescription).toBe('Do you want to apply these updates?')
    expect(e.core.confirm.deactivateTitle).toBe('Deactivate?')
    expect(e.core.confirm.activateTitle).toBe('Activate?')
  })

  it('provides non-empty Khmer translations for the new confirmations', () => {
    const k = km as unknown as { core: { confirm: Record<string, string> } }
    for (const key of [
      'activateTitle',
      'activateDescription',
      'deactivateTitle',
      'deactivateDescription',
      'deactivateSelected',
    ]) {
      const value = k.core.confirm[key]
      expect(typeof value, key).toBe('string')
      expect(value.length, key).toBeGreaterThan(0)
      // Khmer script characters must be present (not an English fallback).
      expect(/[\u1780-\u17FF]/.test(value), `km ${key} is not Khmer`).toBe(true)
    }
  })
})
