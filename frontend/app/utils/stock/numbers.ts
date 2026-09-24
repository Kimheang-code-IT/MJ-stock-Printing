/**
 * Shared decimal-safe numeric helpers: values are parsed as decimal strings
 * and multiplied as scaled BigInt integers, so factors like `1.5` never
 * accumulate binary-float drift. The final conversion to a `number` happens
 * once, from an exact decimal string.
 */

const MAX_SCALE = 6

function parseDecimal(value: unknown): { negative: boolean, digits: bigint, scale: number } | null {
  const text = String(value ?? '').trim()
  if (!/^-?\d*(\.\d*)?$/.test(text) || text === '' || text === '-' || text === '.') return null
  const negative = text.startsWith('-')
  const unsigned = negative ? text.slice(1) : text
  const [intPart = '', fracPart = ''] = unsigned.split('.')
  const digits = BigInt(`${intPart || '0'}${fracPart}` || '0')
  return { negative, digits, scale: fracPart.length }
}

function scaledToNumber(digits: bigint, scale: number): number {
  // Round half-up (by magnitude) to MAX_SCALE decimals using integer math.
  let sign = 1n
  let value = digits
  if (value < 0n) {
    sign = -1n
    value = -value
  }
  if (scale > MAX_SCALE) {
    const drop = BigInt(10) ** BigInt(scale - MAX_SCALE)
    const half = drop / 2n
    value = (value + half) / drop
    scale = MAX_SCALE
  }
  const result = Number(value * sign) / 10 ** scale
  return Object.is(result, -0) ? 0 : result
}

/** Decimal-safe `a × b` — no binary-float drift (e.g. `1.1 × 3` is exactly 3.3). */
export function multiplyDecimalSafe(a: unknown, b: unknown): number {
  const da = parseDecimal(a)
  const db = parseDecimal(b)
  if (!da || !db) return 0
  const negative = da.negative !== db.negative
  const digits = da.digits * db.digits * (negative ? -1n : 1n)
  return scaledToNumber(digits, da.scale + db.scale)
}

/** Decimal-safe `a ÷ b` — exact while the quotient fits MAX_SCALE decimals. */
export function divideDecimalSafe(a: unknown, b: unknown): number {
  const da = parseDecimal(a)
  const db = parseDecimal(b)
  if (!da || !db || db.digits === 0n) return 0
  const negative = da.negative !== db.negative
  // Scale the dividend up enough to keep MAX_SCALE decimals of quotient.
  const scaleBoost = Math.max(0, MAX_SCALE + db.scale - da.scale)
  const digits = (da.digits * BigInt(10) ** BigInt(scaleBoost)) / db.digits
  return scaledToNumber(negative ? -digits : digits, da.scale + scaleBoost - db.scale)
}

/** Quantize a value to the shared decimal scale (trims float noise, e.g. 24.000000001 → 24). */
export function roundQty(value: unknown): number {
  return multiplyDecimalSafe(value, 1)
}
