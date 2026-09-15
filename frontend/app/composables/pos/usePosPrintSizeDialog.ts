import { ref, watch } from 'vue'

/**
 * Parent-owned state machine for the post-sale invoice print-size dialog.
 *
 * The POS submits a sale, stores its print payload in `pending`, opens the
 * A4/A5 chooser and returns to the normal sale screen. Confirming prints
 * exactly once, then always closes the dialog and clears the completed-sale
 * state — even when printing throws. Closing via X / Cancel / Esc / overlay
 * clears the state without printing and never re-submits the completed sale.
 *
 * `window.print()` can block and `afterprint` is not reliable across browsers,
 * so the dialog is closed as soon as the print has been triggered: `confirm`
 * closes `open` before awaiting `print`.
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
    options.onClose?.(printed)
  }

  /** A4/A5 chosen: print once, then close and clear the completed-sale state. */
  async function confirm(size: TSize) {
    if (printing.value || pending === null) return
    const payload = pending
    printing.value = true
    open.value = false
    try {
      await options.print(payload, size)
    }
    finally {
      printing.value = false
      finish(true)
    }
  }

  /** X / Cancel / Esc / overlay: clear the completed-sale state without printing. */
  function cancel() {
    if (printing.value) return
    if (pending === null) return
    open.value = false
    finish(false)
  }

  // Any close that did not go through `confirm` clears the state without
  // printing. Sync so an X/Esc/overlay close is handled in the same tick.
  watch(open, (value) => {
    if (!value && !settled && !printing.value) finish(false)
  }, { flush: 'sync' })

  return { open, printing, requestPrint, confirm, cancel }
}
