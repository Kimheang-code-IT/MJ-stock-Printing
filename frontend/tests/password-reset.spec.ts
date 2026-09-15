import { describe, expect, it } from 'vitest'
import { parsePasswordResetStart } from '../app/utils/auth/password-reset'

describe('parsePasswordResetStart (forgot-password response)', () => {
  it('reads a linked-Telegram result (code already delivered)', () => {
    const result = parsePasswordResetStart({
      message: 'If the email exists...',
      channel: 'telegram',
      link_code: null,
      expires_in: 0,
    })
    expect(result.channel).toBe('telegram')
    expect(result.linkCode).toBeNull()
    expect(result.expiresIn).toBe(0)
  })

  it('reads an unlinked result and exposes the bot /link code', () => {
    const result = parsePasswordResetStart({
      message: 'If the email exists...',
      channel: 'telegram_link',
      link_code: 'ABCD2345',
      expires_in: 600,
    })
    expect(result.channel).toBe('telegram_link')
    expect(result.linkCode).toBe('ABCD2345')
    expect(result.expiresIn).toBe(600)
  })

  it('accepts camelCase aliases from the API', () => {
    const result = parsePasswordResetStart({
      channel: 'telegram_link',
      linkCode: 'WXYZ6789',
      expiresIn: 300,
    })
    expect(result.channel).toBe('telegram_link')
    expect(result.linkCode).toBe('WXYZ6789')
    expect(result.expiresIn).toBe(300)
  })

  it('falls back to telegram for unknown/empty payloads', () => {
    expect(parsePasswordResetStart(undefined).channel).toBe('telegram')
    expect(parsePasswordResetStart({}).linkCode).toBeNull()
    expect(parsePasswordResetStart({ channel: 'something-else' }).channel).toBe('telegram')
  })
})
