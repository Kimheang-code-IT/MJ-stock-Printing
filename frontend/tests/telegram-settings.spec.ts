import { describe, expect, it } from 'vitest'
import { systemSettingsTabs } from '../app/config/settings-schemas'
import { MOCK_APP_CONFIG } from './support/repositories-mock/settings'
import { applyAdminSettingsGroups, toAdminSettingsValues } from '../app/repositories/http/admin-settings'
import type { AppConfig } from '../app/types/stock-pos/settings'

describe('telegram settings', () => {
  const telegramFields = systemSettingsTabs
    .find(tab => tab.id === 'telegram')
    ?.sections.flatMap(section => section.fields) ?? []

  it('configures the Stock & POS password-reset Telegram bot connection', () => {
    const keys = telegramFields.map(field => field.key)
    expect(keys).toContain('telegram.enabled')
    expect(keys).toContain('telegram.botToken')
    expect(keys).toContain('telegram.chatId')
    expect(keys).not.toContain('__telegramConnection')
  })

  it('omits the Telegram feature toggles from Settings', () => {
    const keys = telegramFields.map(field => field.key)
    expect(keys).not.toContain('telegram.passwordResetEnabled')
    expect(keys).not.toContain('telegram.paymentInvoiceNotifyEnabled')
    expect(keys).not.toContain('telegram.stockInquiryEnabled')
  })

  it('exposes the bot token as an editable secret input', () => {
    const tokenField = telegramFields.find(field => field.key === 'telegram.botToken')
    expect(tokenField).toBeDefined()
    expect(tokenField?.type).toBe('secret')
    expect(tokenField?.readOnly).not.toBe(true)
  })

  it('does not expose legacy rental notification settings', () => {
    const keys = telegramFields.map(field => field.key)
    expect(keys).not.toContain('telegram.notifyNewRental')
    expect(keys).not.toContain('telegram.deadlineReminderEnabled')
    expect(keys).not.toContain('telegram.deadlineReminderDuration')
    expect(keys).not.toContain('telegram.userAccess')
  })

  it('keeps the mock Telegram config free of rental/motorcycle state', () => {
    const telegram = MOCK_APP_CONFIG.telegram as Record<string, unknown>
    for (const key of Object.keys(telegram)) {
      expect(key.toLowerCase()).not.toContain('rental')
      expect(key.toLowerCase()).not.toContain('motorcycle')
    }
    expect(telegram.passwordResetEnabled).toBe(true)
    expect(telegram.paymentInvoiceNotifyEnabled).toBe(true)
    expect(telegram.stockInquiryEnabled).toBe(true)
  })
})

describe('stock settings (spec section 3.6)', () => {
  const stockTab = systemSettingsTabs.find(tab => tab.id === 'stock')
  const stockFields = stockTab?.sections.flatMap(section => section.fields) ?? []

  it('has a Stock tab with the two expiry-alert lead times', () => {
    expect(stockTab).toBeDefined()
    const byKey = new Map(stockFields.map(field => [field.key, field]))
    expect(byKey.get('stock.expiryAlert1Days')?.type).toBe('number')
    expect(byKey.get('stock.expiryAlert2Days')?.type).toBe('number')
  })

  it('toggles Telegram expiry alerts from the Stock tab', () => {
    const byKey = new Map(stockFields.map(field => [field.key, field]))
    expect(byKey.get('stock.telegramExpiryAlertsEnabled')?.type).toBe('boolean')
  })

  it('mock defaults match the spec examples (90 / 7, alerts on)', () => {
    expect(MOCK_APP_CONFIG.stock.expiryAlert1Days).toBe(90)
    expect(MOCK_APP_CONFIG.stock.expiryAlert2Days).toBe(7)
    expect(MOCK_APP_CONFIG.stock.telegramExpiryAlertsEnabled).toBe(true)
  })
})

describe('security settings', () => {
  const securityFields = systemSettingsTabs
    .find(tab => tab.id === 'security')
    ?.sections.flatMap(section => section.fields) ?? []

  it('keeps password-reset delivery on Telegram with a code expiry window', () => {
    const byKey = new Map(securityFields.map(field => [field.key, field]))
    const channel = byKey.get('security.passwordResetChannel')
    expect(channel?.type).toBe('select')
    expect(channel?.options?.map(option => option.value)).toEqual(['telegram'])
    expect(byKey.has('security.passwordResetCodeExpiryMinutes')).toBe(true)
  })
})

describe('admin settings mapping (PATCH /api/v1/admin/settings)', () => {
  const base = structuredClone(MOCK_APP_CONFIG) as AppConfig

  it('maps the Stock tab lead times and expiry toggle to backend groups', () => {
    const values = toAdminSettingsValues({
      stock: { ...base.stock, expiryAlert1Days: 60, expiryAlert2Days: 3, telegramExpiryAlertsEnabled: false },
    })
    expect(values).toEqual({
      stock: { expiry_alert_1_days: 60, expiry_alert_2_days: 3 },
      telegram: { expiry_alerts_enabled: false },
    })
  })

  it('maps the Telegram feature toggles to backend keys', () => {
    const values = toAdminSettingsValues({
      telegram: { ...base.telegram, passwordResetEnabled: false, paymentInvoiceNotifyEnabled: false, stockInquiryEnabled: false },
    })
    // The full backend catalog maps from the form model (spec section 3.6):
    // feature toggles + expiry/sale/purchase/summary notification toggles.
    expect(values).toEqual({
      telegram: {
        enabled: false,
        chat_id: '',
        enable_password_reset: false,
        payment_invoice_notify_enabled: false,
        stock_inquiry_enabled: false,
        expiry_alerts_enabled: true,
        sale_enabled: false,
        purchase_enabled: false,
        daily_summary_enabled: false,
        daily_summary_time: '07:00',
        notification_language: 'en',
      },
    })
  })

  it('does not send the masked token placeholder', () => {
    const values = toAdminSettingsValues(base) as Record<string, Record<string, unknown>>
    expect(values.telegram?.bot_token).toBeUndefined()
    expect(JSON.stringify(values)).not.toContain('bot_token')
  })

  it('sends a newly entered token and Chat ID', () => {
    const values = toAdminSettingsValues({
      telegram: {
        ...base.telegram,
        botToken: '123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd',
        chatId: '-1001234567890',
      },
    })
    expect(values.telegram).toMatchObject({
      bot_token: '123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd',
      chat_id: '-1001234567890',
    })
  })

  it('applies returned backend groups back onto the form model', () => {
    const next = applyAdminSettingsGroups(base, {
      stock: { expiry_alert_1_days: 45, expiry_alert_2_days: 5 },
      telegram: { enable_password_reset: false, expiry_alerts_enabled: false },
    })
    expect(next.stock.expiryAlert1Days).toBe(45)
    expect(next.stock.expiryAlert2Days).toBe(5)
    expect(next.stock.telegramExpiryAlertsEnabled).toBe(false)
    expect(next.telegram.passwordResetEnabled).toBe(false)
    // Unmapped sections are untouched.
    expect(next.localization).toEqual(base.localization)
  })

  it('applies masked token and Chat ID returned by the backend', () => {
    const next = applyAdminSettingsGroups(base, {
      telegram: { bot_token: '********', chat_id: '-100998877' },
    })
    expect(next.telegram.botToken).toBe('********')
    expect(next.telegram.chatId).toBe('-100998877')
  })

  it('returns an empty patch when no mappable sections change', () => {
    expect(toAdminSettingsValues({ localization: { ...base.localization } })).toEqual({})
  })
})
