import type {
  AppConfig,
  AppInfo,
  ConnectionStatus,
  CreateStorageProviderInput,
  StorageProvider,
  UpdateStorageProviderInput,
} from '~/types/mj/settings'

export interface AppInfoRepository {
  get: () => Promise<AppInfo>
  update: (input: Partial<AppInfo>) => Promise<AppInfo>
  reset: () => Promise<AppInfo>
}

export interface ResetAllDataResult {
  message: string
  requiresReauth?: boolean
}

export interface ClearTransactionsResult {
  cleared: boolean
  message: string
}

/** Result of a manual Google Sheets backup run. */
export interface BackupRunResult {
  id: string
  trigger: string
  status: string
  tables_total: number
  tables_succeeded: number
  tables_failed: number
  rows_backed_up: number
  error_message: string | null
}

export interface AppConfigRepository {
  get: () => Promise<AppConfig>
  update: (input: Partial<AppConfig>) => Promise<AppConfig>
  resetAllData: () => Promise<ResetAllDataResult>
  /** Delete all sales + purchases and zero stock (master data kept). */
  clearTransactions: () => Promise<ClearTransactionsResult>
  /** Trigger an immediate Google Sheets backup (administrator action). */
  runBackupNow: () => Promise<BackupRunResult>
  testEmailConnection: () => Promise<{ status: ConnectionStatus, message: string }>
  sendTestEmail: (to: string) => Promise<{ status: ConnectionStatus, message: string }>
  testTelegramConnection: () => Promise<{ status: ConnectionStatus, message: string }>
  sendTestTelegramMessage: (destinationId?: string) => Promise<{ status: ConnectionStatus, message: string }>
}

export interface StorageRepository {
  list: () => Promise<StorageProvider[]>
  getById: (id: string) => Promise<StorageProvider>
  create: (input: CreateStorageProviderInput) => Promise<StorageProvider>
  update: (id: string, input: UpdateStorageProviderInput) => Promise<StorageProvider>
  setDefault: (id: string) => Promise<StorageProvider>
  setActive: (id: string, active: boolean) => Promise<StorageProvider>
  testConnection: (id: string) => Promise<{ status: ConnectionStatus, message: string }>
  remove: (id: string) => Promise<void>
}
