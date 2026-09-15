import { nextTick, ref, watch } from 'vue'

/** Macrotask gap so the closed modal can paint before print() blocks the UI. */
const CLOSE_PAINT_MS = 150

/**
 * Parent-owned state machine for the post-sale invoice print-size dialog.
 *
 * Choosing A4/A5 closes the chooser immediately, waits for the close to paint,
 * then triggers print. That way a blocking `window.print()` cannot freeze the
 * modal on screen. X/Cancel skips printing; the sale is already saved and is
 * never re-submitted.
 */
export function usePosPrintSizeDialog<TPayload, TSize>(options: {
  /** Trigger the print. May reject; the dialog still closes and state clears. */
  print: (payload: TPayload, size: TSize) => void | Promise<void>
  /** Runs once the dialog closes. `printed` is false for X/Cancel. */
  onClose?: (printed: boolean) => void
}) {
  const open = ref(false)
  const printing = ref(false)
  let pending: TPayload | null = null
  /** No queued sale between requests; guards `onClose` against running twice. */
  let settled = true

  /** Queue a completed sale for printing and open the chooser. */
  function requestPrint(payload: TPayload) {
    if (open.value || printing.value) return
    pending = payload
    settled = false
    open.value = true
  }

  /** Close + clear state exactly once, reporting whether a print was triggered. */
  function finish(printed: boolean) {
    if (settled) return
    settled = true
    pending = null
    printing.value = false
    open.value = false
    options.onClose?.(printed)
  }

  /**
   * Wait until the browser has painted the closed modal (before print blocks).
   * nextTick + rAF covers Vue/DOM; the short timeout covers modal leave / compositor.
   */
  async function waitForClosePaint() {
    await nextTick()
    if (typeof requestAnimationFrame === 'function') {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => resolve())
        })
      })
    }
    await new Promise<void>((resolve) => {
      setTimeout(resolve, CLOSE_PAINT_MS)
    })
  }

  /** A4/A5 chosen: close the chooser immediately, then print once. */
  async function confirm(size: TSize) {
    if (printing.value || pending === null) return
    const payload = pending
    // Mark printing first so the open→false watch does not treat this as Cancel.
    printing.value = true
    open.value = false
    await waitForClosePaint()
    try {
      await options.print(payload, size)
    }
    finally {
      finish(true)
    }
  }

  /**
   * X / Cancel / Esc / overlay. While a confirm-close is in flight, only keep
   * the dialog shut — confirm owns finish(true). Otherwise clear without print.
   */
  function cancel() {
    if (printing.value) {
      open.value = false
      return
    }
    if (settled && !open.value) return
    finish(false)
  }

  // Any close that did not go through `confirm` clears the state without
  // printing. Sync so an X/Esc/overlay close is handled in the same tick.
  watch(open, (value) => {
    if (!value && !settled && !printing.value) finish(false)
  }, { flush: 'sync' })

  return { open, printing, requestPrint, confirm, cancel }
}
