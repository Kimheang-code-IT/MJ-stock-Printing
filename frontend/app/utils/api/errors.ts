/**
 * Central normalization of FastAPI error payloads.
 *
 * Backend errors look like:
 *   { detail: { code, message, field_errors? } }
 * Ordinary FastAPI validation errors look like:
 *   { detail: Array<{ msg, loc, type }> } or { detail: string }
 */

export interface NormalizedApiError {
  statusCode: number
  code: string
  message: string
  fieldErrors: Record<string, string>
  payload: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

// Marker attached to a thrown fetch error once `useApi` has already surfaced it
// (generic toast, permission alert, or session-expired alert). Callers check it
// to avoid showing a second, raw `[METHOD] "url": 409 Conflict` toast.
const HANDLED_API_ERROR = Symbol.for('mj.apiErrorHandled')

export function markApiErrorHandled(error: unknown): void {
  if (error && (typeof error === 'object' || typeof error === 'function')) {
    ;(error as Record<symbol, unknown>)[HANDLED_API_ERROR] = true
  }
}

export function isApiErrorHandled(error: unknown): boolean {
  return Boolean(
    error
    && (typeof error === 'object' || typeof error === 'function')
    && (error as Record<symbol, unknown>)[HANDLED_API_ERROR],
  )
}

/** True when a request was cancelled (e.g. cancelPrevious) — callers should not toast. */
export function isRequestAborted(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const err = error as { name?: string, message?: string, cause?: unknown }
  if (err.name === 'AbortError') return true
  const message = String(err.message || '').toLowerCase()
  if (message.includes('aborted') || message.includes('abort')) return true
  if (err.cause) return isRequestAborted(err.cause)
  return false
}

/**
 * Human-readable message for any thrown error.
 *
 * Prefers the backend `{ detail: { message } }` envelope over ofetch's raw
 * `[DELETE] "http://...": 409 Conflict` string, and falls back otherwise.
 */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (isRecord(error)) {
    const status = (error as { statusCode?: number }).statusCode
    if ((error as { data?: unknown }).data !== undefined) {
      const message = normalizeApiError((error as { data?: unknown }).data, status ?? 500).message
      if (message) return message
    }
  }
  if (error instanceof Error && error.message && !/^\[(GET|POST|PUT|PATCH|DELETE)\]/.test(error.message)) {
    return error.message
  }
  return fallback
}

// Number of currently-mounted forms that render backend field errors inline.
// While at least one is active, `useApi` suppresses the generic validation
// toast so the form shows the message on the offending field instead. Flows
// without such a form (dialogs, POS, auth) keep the toast.
let inlineFieldErrorConsumers = 0

/** Register an inline-field-error form; returns a release function. */
export function registerInlineFieldErrorConsumer(): () => void {
  inlineFieldErrorConsumers += 1
  let released = false
  return () => {
    if (released) return
    released = true
    inlineFieldErrorConsumers = Math.max(0, inlineFieldErrorConsumers - 1)
  }
}

export function hasInlineFieldErrorConsumer(): boolean {
  return inlineFieldErrorConsumers > 0
}

/** snake_case → camelCase (backend field_errors → UI field keys). */
export function camelCaseFieldKey(key: string): string {
  return key.replace(/_([a-z0-9])/g, (_, char: string) => char.toUpperCase())
}

/**
 * Field-level errors from a thrown API error (empty when none).
 *
 * Forms use this in their `catch` to render inline errors on the offending
 * fields instead of a generic toast. The thrown ofetch error keeps `.data`
 * and `.statusCode`, so this works even after `useApi` re-throws.
 */
export function apiFieldErrors(error: unknown): Record<string, string> {
  if (!isRecord(error)) return {}
  if ((error as { data?: unknown }).data === undefined) return {}
  const status = (error as { statusCode?: number }).statusCode
  return normalizeApiError((error as { data?: unknown }).data, status ?? 500).fieldErrors
}

export function normalizeApiError(payload: unknown, statusCode = 500): NormalizedApiError {
  const detail = isRecord(payload) ? payload.detail : undefined

  if (isRecord(detail)) {
    const fieldErrors: Record<string, string> = {}
    const rawFieldErrors = detail.field_errors
    if (isRecord(rawFieldErrors)) {
      for (const [key, value] of Object.entries(rawFieldErrors)) {
        fieldErrors[key] = String(value)
      }
    }
    return {
      statusCode,
      code: String(detail.code || 'ERROR'),
      message: String(detail.message || 'Request failed'),
      fieldErrors,
      payload,
    }
  }

  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (isRecord(item)) {
        const loc = Array.isArray(item.loc) ? item.loc.filter(part => part !== 'body').join('.') : ''
        const msg = String(item.msg || 'Invalid value')
        return loc ? `${loc}: ${msg}` : msg
      }
      return String(item)
    })
    const fieldErrors: Record<string, string> = {}
    for (const item of detail) {
      if (isRecord(item) && Array.isArray(item.loc) && item.loc.length > 1) {
        fieldErrors[String(item.loc.at(-1))] = String(item.msg || 'Invalid value')
      }
    }
    return {
      statusCode,
      code: 'VALIDATION_ERROR',
      message: parts.join('; ') || 'Validation failed',
      fieldErrors,
      payload,
    }
  }

  if (typeof detail === 'string' && detail.trim()) {
    return { statusCode, code: 'ERROR', message: detail, fieldErrors: {}, payload }
  }

  if (isRecord(payload) && typeof payload.message === 'string' && payload.message.trim()) {
    return { statusCode, code: 'ERROR', message: payload.message, fieldErrors: {}, payload }
  }

  return {
    statusCode,
    code: 'ERROR',
    message: 'Something went wrong. Please try again.',
    fieldErrors: {},
    payload,
  }
}
