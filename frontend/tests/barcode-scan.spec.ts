import { describe, expect, it } from 'vitest'
import {
  createScanBuffer,
  feedScanKey,
  resolveExactBarcode,
  SCAN_MAX_KEY_GAP_MS,
} from '../app/utils/pos/barcode-scan'

describe('barcode wedge burst detection (USB/HID scanner)', () => {
  it('emits the code when fast keystrokes end with Enter', () => {
    const state = createScanBuffer()
    let now = 1000
    for (const char of '8801001234501') {
      feedScanKey(state, char, now)
      now += 10
    }
    const result = feedScanKey(state, 'Enter', now)
    expect(result.scanned).toBe('8801001234501')
    // The buffer is cleared after a terminator, ready for the next scan.
    expect(state.buffer).toBe('')
  })

  it('rejects a slow sequence (human typing, not a scanner burst)', () => {
    const state = createScanBuffer()
    let now = 1000
    for (const char of '123') {
      feedScanKey(state, char, now)
      now += 300
    }
    expect(feedScanKey(state, 'Enter', now).scanned).toBeNull()
  })

  it('ignores a lone/short Enter and non-printable keys', () => {
    const state = createScanBuffer()
    expect(feedScanKey(state, 'Enter', 1000).scanned).toBeNull()
    expect(feedScanKey(state, 'Shift', 1001).consumed).toBe(false)
    expect(feedScanKey(state, 'Enter', 1002).scanned).toBeNull()
  })

  it('claims only keys that continue a burst (first key is never hijacked)', () => {
    const state = createScanBuffer()
    expect(feedScanKey(state, '8', 1000).consumed).toBe(false)
    expect(feedScanKey(state, '8', 1000 + SCAN_MAX_KEY_GAP_MS).consumed).toBe(true)
  })
})

describe('resolveExactBarcode', () => {
  it('matches an exact barcode and ignores blank/unknown codes', () => {
    const products = [
      { id: 'p1', barcode: '8801001234501' },
      { id: 'p2', barcode: '8801001234502' },
    ]
    expect(resolveExactBarcode(products, ' 8801001234502 ')?.id).toBe('p2')
    expect(resolveExactBarcode(products, '')).toBeNull()
    expect(resolveExactBarcode(products, 'nope')).toBeNull()
  })
})
