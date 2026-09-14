import { describe, expect, it } from 'vitest'
import { systemSettingsTabs } from '../app/config/settings-schemas'
import { MOCK_APP_CONFIG } from './support/repositories-mock/settings'
import { applyAdminSettingsGroups, toAdminSettingsValues } from '../app/repositories/http/admin-settings'
import type { AppConfig } from '../app/types/stock-pos/settings'

describe('telegram notifications settings (Administration → Settings)', () => {
  const telegramTab = systemSettingsTabs.find(tab => tab.id === 'telegram')
  const sections = telegramTab?.sections ?? []
  const notificationFields = sections
    .find(section => section.id === 'telegram-notifications')
    ?.fields ?? []

  it('exposes the Telegram Notifications section with every approved toggle', () => {
    const keys = notificationFields.map(field => field.key)
    expect(keys).toEqual([
      'telegram.expiryAlertsEnabled',
      'telegram.saleNotificationsEnabled',
      'telegram.purchaseNotificationsEnabled',
      'telegram.dailySummaryEnabled',
      'telegram.dailySummaryTime',
      'telegram.notificationLanguage',
    ])
    const byKey = new Map(notificationFields.map(field => [field.key, field]))
    for (const key of [
      'telegram.expiryAlertsEnabled',
      'telegram.saleNotificationsEnabled',
      'telegram.purchaseNotificationsEnabled',
      'telegram.dailySummaryEnabled',
    ]) {
      expect(byKey.get(key)?.type).toBe('boolean')
    }
    expect(byKey.get('telegram.dailySummaryTime')?.type).toBe('text')
    expect(byKey.get('telegram.notificationLanguage')?.type).toBe('select')
  })

  it('keeps the master connection controls and Test Telegram on the same tab', () => {
    const connectionSection = sections.find(section => section.id === 'telegram')
    const keys = connectionSection?.fields.map(field => field.key) ?? []
    expect(keys).toContain('telegram.enabled')
    expect(keys).toContain('__telegramConnection')
    // No separate Telegram sidebar page — everything lives in Settings.
    expect(telegramTab).toBeTruthy()
  })

  it('maps the notification toggles to the backend settings groups', () => {
    const base = structuredClone(MOCK_APP_CONFIG) as AppConfig
    const values = toAdminSettingsValues({
      telegram: {
        ...base.telegram,
        enabled: true,
        saleNotificationsEnabled: true,
        purchaseNotificationsEnabled: false,
        dailySummaryEnabled: true,
        dailySummaryTime: '08:30',
        messageLanguage: 'km',
      },
    })
    expect(values.telegram).toMatchObject({
      enabled: true,
      sale_enabled: true,
      purchase_enabled: false,
      daily_summary_enabled: true,
      daily_summary_time: '08:30',
      notification_language: 'km',
    })
  })

  it('never sends the bot token and never writes an empty summary time', () => {
    const base = structuredClone(MOCK_APP_CONFIG) as AppConfig
    const values = toAdminSettingsValues({
      telegram: { ...base.telegram, dailySummaryTime: '   ' },
    }) as Record<string, Record<string, unknown>>
    expect(JSON.stringify(values)).not.toContain('bot_token')
    expect(values.telegram?.daily_summary_time).toBeUndefined()
  })

  it('applies backend groups back onto the form model (including expiry + language)', () => {
    const next = applyAdminSettingsGroups(structuredClone(MOCK_APP_CONFIG) as AppConfig, {
      telegram: {
        expiry_alerts_enabled: false,
        sale_enabled: true,
        purchase_enabled: true,
        daily_summary_enabled: true,
        daily_summary_time: '09:15',
        notification_language: 'km',
      },
    })
    expect(next.telegram.expiryAlertsEnabled).toBe(false)
    expect(next.stock.telegramExpiryAlertsEnabled).toBe(false)
    expect(next.telegram.saleNotificationsEnabled).toBe(true)
    expect(next.telegram.purchaseNotificationsEnabled).toBe(true)
    expect(next.telegram.dailySummaryEnabled).toBe(true)
    expect(next.telegram.dailySummaryTime).toBe('09:15')
    expect(next.telegram.messageLanguage).toBe('km')
  })

  it('mock defaults mirror the backend catalog (sale/purchase/summary off)', () => {
    expect(MOCK_APP_CONFIG.telegram.saleNotificationsEnabled).toBe(false)
    expect(MOCK_APP_CONFIG.telegram.purchaseNotificationsEnabled).toBe(false)
    expect(MOCK_APP_CONFIG.telegram.dailySummaryEnabled).toBe(false)
    expect(MOCK_APP_CONFIG.telegram.dailySummaryTime).toBe('07:00')
  })
})