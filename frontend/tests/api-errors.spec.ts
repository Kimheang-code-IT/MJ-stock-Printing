import { describe, expect, it } from 'vitest'
import {
  apiErrorMessage,
  apiFieldErrors,
  camelCaseFieldKey,
  hasInlineFieldErrorConsumer,
  isApiErrorHandled,
  markApiErrorHandled,
  normalizeApiError,
  registerInlineFieldErrorConsumer,
} from '../app/utils/api/errors'

describe('normalizeApiError', () => {
  it('normalizes FastAPI nested detail payloads', () => {
    const error = normalizeApiError({
      detail: {
        code: 'AUTH_REQUIRED',
        message: 'Missing bearer token',
      },
    }, 401)

    expect(error.statusCode).toBe(401)
    expect(error.code).toBe('AUTH_REQUIRED')
    expect(error.message).toBe('Missing bearer token')
    expect(error.fieldErrors).toEqual({})
  })

  it('extracts field errors from the nested payload', () => {
    const error = normalizeApiError({
      detail: {
        code: 'VALIDATION_ERROR',
        message: 'Validation failed',
        field_errors: { currentPassword: 'Incorrect password' },
      },
    }, 422)

    expect(error.code).toBe('VALIDATION_ERROR')
    expect(error.fieldErrors.currentPassword).toBe('Incorrect password')
  })

  it('normalizes ordinary FastAPI validation arrays', () => {
    const error = normalizeApiError({
      detail: [
        { loc: ['body', 'email'], msg: 'value is not a valid email address', type: 'value_error' },
        { loc: ['body', 'password'], msg: 'min length is 6', type: 'value_error' },
      ],
    }, 422)

    expect(error.statusCode).toBe(422)
    expect(error.code).toBe('VALIDATION_ERROR')
    expect(error.message).toContain('email')
    expect(error.message).toContain('password')
    expect(error.fieldErrors.email).toBe('value is not a valid email address')
    expect(error.fieldErrors.password).toBe('min length is 6')
  })

  it('handles string details', () => {
    const error = normalizeApiError({ detail: 'Not found' }, 404)
    expect(error.statusCode).toBe(404)
    expect(error.message).toBe('Not found')
  })

  it('falls back to a generic message for unknown payloads', () => {
    const error = normalizeApiError({ unexpected: true }, 500)
    expect(error.statusCode).toBe(500)
    expect(error.message).toContain('Something went wrong')
  })
})

describe('apiErrorMessage', () => {
  it('prefers the backend detail message over the raw ofetch string', () => {
    const fetchError = Object.assign(new Error('[DELETE] "http://127.0.0.1/api/v1/customers/1": 409 Conflict'), {
      statusCode: 409,
      data: {
        detail: {
          code: 'CONFLICT',
          message: 'Cannot delete this customer because sales history exists. Deactivate it instead.',
        },
      },
    })

    expect(apiErrorMessage(fetchError, 'Could not delete'))
      .toBe('Cannot delete this customer because sales history exists. Deactivate it instead.')
  })

  it('never surfaces the raw [METHOD] "url": status string', () => {
    const fetchError = Object.assign(new Error('[DELETE] "http://127.0.0.1/api/v1/customers/1": 409 Conflict'), {
      statusCode: 409,
    })

    expect(apiErrorMessage(fetchError, 'Could not delete')).toBe('Could not delete')
  })

  it('keeps plain client-side error messages', () => {
    expect(apiErrorMessage(new Error('Factor must be greater than 0'), 'Invalid')).toBe('Factor must be greater than 0')
  })

  it('uses the fallback for unknown values', () => {
    expect(apiErrorMessage('boom', 'Could not save')).toBe('Could not save')
  })
})

describe('apiFieldErrors', () => {
  it('returns field errors from a thrown ofetch error', () => {
    const fetchError = Object.assign(new Error('422'), {
      statusCode: 422,
      data: {
        detail: {
          code: 'VALIDATION_ERROR',
          message: 'Validation failed',
          field_errors: { items: 'Duplicate product' },
        },
      },
    })
    expect(apiFieldErrors(fetchError)).toEqual({ items: 'Duplicate product' })
  })

  it('is empty for errors without a payload', () => {
    expect(apiFieldErrors(new Error('boom'))).toEqual({})
    expect(apiFieldErrors('boom')).toEqual({})
  })
})

describe('inline field error consumer registry', () => {
  it('tracks mounted consumers until released', () => {
    expect(hasInlineFieldErrorConsumer()).toBe(false)
    const release = registerInlineFieldErrorConsumer()
    expect(hasInlineFieldErrorConsumer()).toBe(true)
    release()
    release()
    expect(hasInlineFieldErrorConsumer()).toBe(false)
  })

  it('maps backend snake_case keys to camelCase UI keys', () => {
    expect(camelCaseFieldKey('current_password')).toBe('currentPassword')
    expect(camelCaseFieldKey('exchange_rate')).toBe('exchangeRate')
    expect(camelCaseFieldKey('items')).toBe('items')
  })
})

describe('handled API error marker', () => {
  it('is false until marked', () => {
    const error = new Error('nope')
    expect(isApiErrorHandled(error)).toBe(false)
    markApiErrorHandled(error)
    expect(isApiErrorHandled(error)).toBe(true)
  })

  it('is false for non-object values', () => {
    expect(isApiErrorHandled(undefined)).toBe(false)
    expect(isApiErrorHandled('nope')).toBe(false)
  })
})
