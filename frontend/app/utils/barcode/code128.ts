/**
 * Minimal, dependency-free CODE128-B barcode encoder.
 *
 * Auto-issued barcodes are digits-only, but a product may carry a custom
 * alphanumeric code, so CODE128-B is the right symbology: it covers the full
 * printable ASCII range and scans reliably. The module renders an inline SVG —
 * no canvas, no external library.
 */

/** CODE128 bar/space module patterns, index 0…106 (103=StartA, 104=StartB, 105=StartC, 106=Stop). */
const CODE128_PATTERNS: readonly string[] = [
  '11011001100', '11001101100', '11001100110', '10010011000', '10010001100',
  '10001001100', '10011001000', '10011000100', '10001100100', '11001001000',
  '11001000100', '11000100100', '10110011100', '10011011100', '10011001110',
  '10111001100', '10011101100', '10011100110', '11001110010', '11001011100',
  '11001001110', '11011100100', '11001110100', '11101101110', '11101001100',
  '11100101100', '11100100110', '11101100100', '11100110100', '11100110010',
  '11011011000', '11011000110', '11000110110', '10100011000', '10001011000',
  '10001000110', '10110001000', '10001101000', '10001100010', '11010001000',
  '11000101000', '11000100010', '10110111000', '10110001110', '10001101110',
  '10111011000', '10111000110', '10001110110', '11101110110', '11010001110',
  '11000101110', '11011101000', '11011100010', '11011101110', '11101011000',
  '11101000110', '11100010110', '11101101000', '11101100010', '11100011010',
  '11101111010', '11001000010', '11110001010', '10100110000', '10100001100',
  '10010110000', '10010000110', '10000101100', '10000100110', '10110010000',
  '10110000100', '10011010000', '10011000010', '10000110100', '10000110010',
  '11000010010', '11001010000', '11110111010', '11000010100', '10001111010',
  '10100111100', '10010111100', '10010011110', '10111100100', '10011110100',
  '10011110010', '11110100100', '11110010100', '11110010010', '11011011110',
  '11011110110', '11110110110', '10101111000', '10100011110', '10001011110',
  '10111101000', '10111100010', '11110101000', '11110100010', '10111011110',
  '10111101110', '11101011110', '11110101110', '11010000100', '11010010000',
  '11010011100', '1100011101011',
]

const START_B = 104
const STOP = 106
const MODULO = 103

/**
 * Encode a value as a CODE128-B module bit string (1 = bar, 0 = space).
 * Characters outside printable ASCII (32…126) are dropped — empty input
 * yields an empty string so callers can show a placeholder.
 */
export function encodeCode128B(value: string): string {
  const codes: number[] = [START_B]
  let checksum = START_B
  let position = 1
  for (const char of value) {
    const code = char.charCodeAt(0) - 32
    if (code < 0 || code > 94) continue
    codes.push(code)
    checksum += code * position
    position += 1
  }
  if (codes.length === 1) return ''
  codes.push(checksum % MODULO)
  codes.push(STOP)
  return codes.map(code => CODE128_PATTERNS[code]).join('')
}

export interface BarcodeSvgOptions {
  /** Width of one module in px (default 2). */
  moduleWidth?: number
  /** Bar height in px (default 60). */
  height?: number
  /** Quiet-zone padding in px on each side (default 10). */
  quietZone?: number
}

/** Render a value as an inline SVG string (white background, black bars). */
export function barcodeSvg(value: string, options: BarcodeSvgOptions = {}): string {
  const bits = encodeCode128B(String(value ?? '').trim())
  if (!bits) return ''

  const moduleWidth = options.moduleWidth ?? 2
  const height = options.height ?? 60
  const quiet = options.quietZone ?? 10
  const barsWidth = bits.length * moduleWidth
  const width = barsWidth + quiet * 2

  const bars: string[] = []
  let x = quiet
  let index = 0
  while (index < bits.length) {
    if (bits[index] === '1') {
      let run = 1
      while (bits[index + run] === '1') run += 1
      bars.push(`<rect x="${x}" y="0" width="${run * moduleWidth}" height="${height}"/>`)
      x += run * moduleWidth
      index += run
    }
    else {
      x += moduleWidth
      index += 1
    }
  }

  const label = escapeXml(value)
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${label}" preserveAspectRatio="none"><rect width="${width}" height="${height}" fill="#ffffff"/><g fill="#000000">${bars.join('')}</g></svg>`
}

function escapeXml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
