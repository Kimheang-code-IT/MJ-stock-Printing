/**
 * USB/HID barcode scanners act as a keyboard ("keyboard wedge"): they type the
 * barcode character by character, then a terminator (CR/Enter). The keys arrive
 * far faster than human typing, which is what lets us tell a scan apart from a
 * cashier using the keyboard.
 */

/** Upper bound on the gap between two keys of one scan burst. */
export const SCAN_MAX_KEY_GAP_MS = 45

/** Shortest plausible barcode; also filters a lone Enter or a stray key. */
export const SCAN_MIN_LENGTH = 4

export type ScanBufferState = {
  buffer: string
  /** Timestamp (ms) of the last character fed into the buffer. */
  lastAt: number
}

export function createScanBuffer(): ScanBufferState {
  return { buffer: '', lastAt: 0 }
}

/** A single printable character, i.e. anything a barcode could be made of. */
export function isPrintableScanKey(key: string): boolean {
  return key.length === 1
}

export type ScanKeyResult = {
  state: ScanBufferState
  /** The completed barcode when the key terminated a valid scan. */
  scanned: string | null
  /** True when the key belonged to a scan and should be preventDefault()-ed. */
  consumed: boolean
}

/**
 * Feed one keydown into the scanner buffer and report whether it completed a
 * scan. `now` is a monotonic timestamp (Date.now() / performance.now()).
 *
 * A printable key starts (or continues) a burst; a gap longer than `maxGapMs`
 * means human typing, so the buffer restarts. Enter emits the buffered code only
 * when it is at least `minLength` long; otherwise it is an ordinary keypress.
 */
export function feedScanKey(
  state: ScanBufferState,
  key: string,
  now: number,
  options: { maxGapMs?: number, minLength?: number } = {},
): ScanKeyResult {
  const maxGapMs = options.maxGapMs ?? SCAN_MAX_KEY_GAP_MS
  const minLength = options.minLength ?? SCAN_MIN_LENGTH

  if (key === 'Enter') {
    const code = state.buffer
    state.buffer = ''
    state.lastAt = now
    if (code.length >= minLength) return { state, scanned: code, consumed: true }
    return { state, scanned: null, consumed: false }
  }

  if (!isPrintableScanKey(key)) {
    // Modifiers / navigation keys are not part of a barcode; keep the buffer.
    return { state, scanned: null, consumed: false }
  }

  // Only keys that continue a fast burst are "consumed" (preventDefault); the
  // first key of a sequence is never claimed, so a plain keypress still reaches
  // the focused button/element until a scanner burst is clearly in progress.
  const continuing = state.lastAt > 0 && now - state.lastAt <= maxGapMs
  if (!continuing) state.buffer = ''
  state.buffer += key
  state.lastAt = now
  return { state, scanned: null, consumed: continuing }
}

/** Exact barcode match over a loaded product list (mirrors the backend lookup). */
export function resolveExactBarcode(
  products: Array<Record<string, unknown>>,
  code: string,
): Record<string, unknown> | null {
  const needle = String(code || '').trim()
  if (!needle) return null
  return products.find(row => String(row.barcode || '').trim() === needle) ?? null
}
