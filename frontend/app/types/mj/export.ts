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
  /**
   * Debt reports only: narrow the export to one party (`customerId` for the
   * Customer Debt Report, `supplierId` for the Supplier Debt Report) and/or one
   * staff user. Undefined means "all".
   */
  partyId?: string
  userId?: string
}
