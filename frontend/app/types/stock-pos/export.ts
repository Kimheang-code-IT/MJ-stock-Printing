export type ExportScope = 'all_matching' | 'current_page' | 'selected'

/** File format for the server-rendered export (Python openpyxl / reportlab). */
export type ExportFormat = 'xlsx' | 'pdf'

export interface ExportFieldOption {
  label: string
  value: string
}

export interface ExportRequest {
  startDate?: string
  endDate?: string
  scope: ExportScope
  fieldCodes: string[]
  format: ExportFormat
}
