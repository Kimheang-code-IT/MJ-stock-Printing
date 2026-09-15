export type ExportScope = 'all_matching' | 'current_page' | 'selected'

export interface ExportFieldOption {
  label: string
  value: string
}

export interface ExportRequest {
  startDate?: string
  endDate?: string
  scope: ExportScope
  fieldCodes: string[]
}
