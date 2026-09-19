import type { MaybeRefOrGetter } from 'vue'
import { createScanBuffer, feedScanKey } from '~/utils/pos/barcode-scan'

const EDITABLE_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

/** True for inputs the cashier is intentionally typing in (cart qty/price,
 *  checkout fields, dialogs). Scans landing there are left to the field itself. */
function isEditableTarget(target: EventTarget | null): boolean {
  const element = target as (HTMLElement & { isContentEditable?: boolean }) | null
  if (!element || typeof element.tagName !== 'string') return false
  if (EDITABLE_TAGS.has(element.tagName)) return true
  return element.isContentEditable === true
}

/**
 * Global capture for a USB/HID barcode scanner on the POS cart screen.
 *
 * A scanner "types" the code then Enter. We buffer non-editable keystrokes and
 * emit the code when a fast burst ends with Enter, so scanning works even when
 * the product search box has lost focus. Editable fields are never hijacked —
 * the search box handles its own scans through `onSearchEnter`.
 */
export function usePosScanner(options: {
  /** Only listen while the cart workspace is active and allowed. */
  enabled: MaybeRefOrGetter<boolean>
  onScan: (code: string) => void
}) {
  const buffer = createScanBuffer()

  function reset() {
    buffer.buffer = ''
    buffer.lastAt = 0
  }

  function onKeydown(event: KeyboardEvent) {
    if (!toValue(options.enabled)) return
    if (event.ctrlKey || event.metaKey || event.altKey) return
    if (isEditableTarget(event.target)) return
    const result = feedScanKey(buffer, event.key, Date.now())
    if (result.consumed) event.preventDefault()
    if (result.scanned) options.onScan(result.scanned)
  }

  onMounted(() => document.addEventListener('keydown', onKeydown))
  onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))

  return { reset }
}
