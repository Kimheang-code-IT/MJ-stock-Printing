import type { AppConfig } from '~/types/mj/settings'

/**
 * Mapping between the frontend settings form model (AppConfig) and the
 * grouped backend settings payload served by `PATCH/GET /api/v1/admin/settings`
 * (`{ values: { <group>: { <key>: value } } }`).
 *
 * Only keys that exist in the backend `SETTING_GROUPS` catalog are mapped;
 * unknown keys would be rejected by the API. Secret placeholders returned by
 * the API are never written back; only a newly entered token (or an explicit
 * empty value used to clear it) is sent.
 */

export type AdminSettingsGroups = Record<string, Record<string, unknown>>

export function toAdminSettingsValues(input: Partial<AppConfig>): AdminSettingsGroups {
  const values: AdminSettingsGroups = {}

  const telegram: Record<string, unknown> = {}
  const telegramInput = input.telegram
  if (telegramInput) {
    if (telegramInput.enabled !== undefined) telegram.enabled = telegramInput.enabled
    if (telegramInput.botToken !== undefined && telegramInput.botToken !== '********') {
      telegram.bot_token = String(telegramInput.botToken).trim()
    }
    if (telegramInput.chatId !== undefined) telegram.chat_id = String(telegramInput.chatId).trim()
    if (telegramInput.passwordResetEnabled !== undefined) telegram.enable_password_reset = telegramInput.passwordResetEnabled
    if (telegramInput.paymentInvoiceNotifyEnabled !== undefined) telegram.payment_invoice_notify_enabled = telegramInput.paymentInvoiceNotifyEnabled
    if (telegramInput.stockInquiryEnabled !== undefined) telegram.stock_inquiry_enabled = telegramInput.stockInquiryEnabled
    if (telegramInput.saleNotificationsEnabled !== undefined) telegram.sale_enabled = telegramInput.saleNotificationsEnabled
    if (telegramInput.purchaseNotificationsEnabled !== undefined) telegram.purchase_enabled = telegramInput.purchaseNotificationsEnabled
    if (telegramInput.dailySummaryEnabled !== undefined) telegram.daily_summary_enabled = telegramInput.dailySummaryEnabled
    // Never write an empty/blank summary time.
    if (telegramInput.dailySummaryTime !== undefined && String(telegramInput.dailySummaryTime).trim()) {
      telegram.daily_summary_time = String(telegramInput.dailySummaryTime).trim()
    }
    if (telegramInput.messageLanguage !== undefined) telegram.notification_language = telegramInput.messageLanguage
  }
  if (Object.keys(telegram).length > 0) values.telegram = telegram

  const backup: Record<string, unknown> = {}
  const backupInput = input.backup
  if (backupInput) {
    if (backupInput.enabled !== undefined) backup.enabled = backupInput.enabled
    if (backupInput.intervalHours !== undefined) backup.interval_hours = Number(backupInput.intervalHours)
    if (backupInput.spreadsheetId !== undefined) backup.spreadsheet_id = String(backupInput.spreadsheetId).trim()
    // Never write the masked placeholder back; only a newly entered key clears/sets it.
    if (backupInput.serviceAccountJson !== undefined && backupInput.serviceAccountJson !== '********') {
      backup.service_account_json = String(backupInput.serviceAccountJson).trim()
    }
  }
  if (Object.keys(backup).length > 0) values.backup = backup

  return values
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

/** Overlay backend settings groups onto a config model (returns a new object). */
export function applyAdminSettingsGroups(config: AppConfig, groups: AdminSettingsGroups): AppConfig {
  const next: AppConfig = {
    ...config,
    stock: { ...config.stock },
    telegram: { ...config.telegram },
    backup: { ...config.backup },
  }

  const telegram = groups.telegram
  if (telegram) {
    if (telegram.bot_token !== undefined) next.telegram.botToken = String(telegram.bot_token)
    if (telegram.chat_id !== undefined) next.telegram.chatId = String(telegram.chat_id)
    if (telegram.enable_password_reset !== undefined) next.telegram.passwordResetEnabled = asBoolean(telegram.enable_password_reset, next.telegram.passwordResetEnabled)
    if (telegram.payment_invoice_notify_enabled !== undefined) next.telegram.paymentInvoiceNotifyEnabled = asBoolean(telegram.payment_invoice_notify_enabled, next.telegram.paymentInvoiceNotifyEnabled)
    if (telegram.stock_inquiry_enabled !== undefined) next.telegram.stockInquiryEnabled = asBoolean(telegram.stock_inquiry_enabled, next.telegram.stockInquiryEnabled)
    if (telegram.sale_enabled !== undefined) next.telegram.saleNotificationsEnabled = asBoolean(telegram.sale_enabled, next.telegram.saleNotificationsEnabled)
    if (telegram.purchase_enabled !== undefined) next.telegram.purchaseNotificationsEnabled = asBoolean(telegram.purchase_enabled, next.telegram.purchaseNotificationsEnabled)
    if (telegram.daily_summary_enabled !== undefined) next.telegram.dailySummaryEnabled = asBoolean(telegram.daily_summary_enabled, next.telegram.dailySummaryEnabled)
    if (telegram.daily_summary_time !== undefined) next.telegram.dailySummaryTime = String(telegram.daily_summary_time)
    if (telegram.notification_language !== undefined) {
      const language = String(telegram.notification_language)
      if (language === 'en' || language === 'km') next.telegram.messageLanguage = language
    }
  }

  const backup = groups.backup
  if (backup) {
    if (backup.enabled !== undefined) next.backup.enabled = asBoolean(backup.enabled, next.backup.enabled)
    if (backup.interval_hours !== undefined) {
      const hours = Number(backup.interval_hours)
      if (hours === 1 || hours === 3 || hours === 6 || hours === 12 || hours === 24) {
        next.backup.intervalHours = hours
      }
    }
    if (backup.spreadsheet_id !== undefined) next.backup.spreadsheetId = String(backup.spreadsheet_id)
    if (backup.service_account_json !== undefined) {
      next.backup.serviceAccountJson = String(backup.service_account_json)
    }
  }

  return next
}
