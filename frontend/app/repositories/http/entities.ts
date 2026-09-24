import type { AppRecord } from '~/config/admin-seed'
import type { ApiMeta, ApiResponse } from '~/types/mj/common'
import type { AppRolePermissionRow } from '~/types/mj/entities'
import type {
  DashboardSummary,
  EntityListQuery,
  EntityListResult,
  EntityRepository,
  FinanceEntry,
  FinanceRepository,
  FinanceSummary,
  PosCommandRepository,
  PosCompleteSaleInput,
  ProductCostHistoryRow,
  ProductHistoryRow,
  SaleDetail,
  SaleReceipt,
  SearchRepository,
  SearchHitItem,
  StockHistoryKind,
  StockQueryRepository,
} from '~/repositories/contracts/entities'
import { ApiEndpoints, CollectionEndpoints, type ApiCollection } from '~/utils/constants/api-endpoints'
import { documentSequencePreview } from '~/utils/document-sequences'
import { normalizeDeliveryStatusInput } from '~/utils/delivery/notes'
import { flatKeysToPermissionRows, permissionRowsToFlatKeys } from '~/utils/role/permissions'
import { mediaObjectKey } from '~/utils/security/url'

export function metaOf(response: unknown): ApiMeta | null {
  const meta = (response as ApiResponse<unknown>)?.meta
  return meta ? { ...meta } : null
}

export function unwrap<T>(response: unknown): T {
  if (response && typeof response === 'object' && 'data' in (response as object)) {
    return (response as ApiResponse<T>).data
  }
  return response as T
}

/** Fields the UI keeps locally but the backend does not accept on writes. */
const UI_ONLY_FIELDS = new Set([
  'nextNumberPreview',
  'resetRule',
  'userCount',
  'permissionCount',
  'permissionRows',
  'telegramUsername',
  'telegramChatId',
  'lastLogin',
  'telegramLinked',
])

function stripUiOnlyFields(input: Record<string, unknown>): Record<string, unknown> {
  const output: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(input)) {
    if (!UI_ONLY_FIELDS.has(key)) output[key] = value
  }
  return output
}

/** Flat backend permission keys are grouped into matrix rows by module. */
function permissionRowsFromFlatKeys(keys: string[] | null | undefined): AppRolePermissionRow[] {
  return flatKeysToPermissionRows(keys || [])
}

function asRecordId(value: unknown): string {
  return value == null ? '' : String(value)
}

/** Map backend user fields to the UI column keys (no fabricated data). */
function adaptUserOut(user: Record<string, unknown>): Record<string, unknown> {
  const effectivePermissions = Array.isArray(user.effectivePermissions)
    ? user.effectivePermissions.map(String)
    : []
  const roleId = user.roleId ?? user.role_id
  const fullName = String(user.full_name ?? user.displayName ?? '').trim()
  const telegramLinked = Boolean(user.telegramLinked ?? user.telegram_chat_id ?? user.telegramChatId)
  return {
    ...user,
    id: asRecordId(user.id),
    // Backend users have no username; derive a display value from the email.
    username: String(user.username ?? user.email ?? '').split('@')[0],
    displayName: fullName,
    roleId: roleId != null && roleId !== '' ? String(roleId) : '',
    effectivePermissions,
    permissionRows: permissionRowsFromFlatKeys(effectivePermissions),
    lastLogin: user.lastLoginAt ?? user.last_login_at ?? user.lastLogin ?? null,
    // Admin-editable Telegram label + private Chat ID (Users form).
    telegramName: String(user.telegram_name ?? user.telegramName ?? '') || '',
    telegramChatId: String(user.telegram_chat_id ?? user.telegramChatId ?? '') || '',
    telegramUsername: telegramLinked
      ? String(user.telegram_name ?? user.telegram_chat_id ?? 'Linked')
      : '',
  }
}

/** Only the fields UserCreate / UserUpdate accept (`full_name`, `role_id`). */
function adaptUserIn(input: Record<string, unknown>): Record<string, unknown> {
  const output: Record<string, unknown> = {}
  const fullName = String(input.fullName ?? input.full_name ?? input.displayName ?? '').trim()
  const email = String(input.email ?? '').trim()
  const status = String(input.status ?? '').trim()
  const password = String(input.password ?? '')
  const roleId = input.roleId ?? input.role_id
  const telegramName = input.telegramName ?? input.telegram_name
  const chatId = input.telegramChatId ?? input.telegram_chat_id

  if (fullName) output.full_name = fullName
  if (email) output.email = email
  if (status) output.status = /^(inactive|disabled)$/i.test(status) ? 'DISABLED' : 'ACTIVE'
  if (roleId != null && roleId !== '') output.role_id = String(roleId)
  if (password.trim()) output.password = password
  // Telegram name / Chat ID are admin-editable; an empty value clears them.
  if (telegramName !== undefined) output.telegram_name = String(telegramName ?? '').trim() || null
  if (chatId !== undefined) output.telegram_chat_id = String(chatId ?? '').trim() || null
  return output
}

/** Map backend role fields onto the permission-matrix UI shape. */
function adaptRoleOut(role: Record<string, unknown>): Record<string, unknown> {
  const permissions = Array.isArray(role.permissions) ? role.permissions.map(String) : []
  return {
    ...role,
    id: asRecordId(role.id),
    permissions,
    permissionRows: permissionRowsFromFlatKeys(permissions),
    permissionCount: Number(role.permissionCount ?? permissions.length),
    // Backend serializes `is_system`; the UI reads the camelCase flag.
    isSystem: Boolean(role.isSystem ?? role.is_system),
    // Roles carry ACTIVE/DISABLED server-side; the list uses Active/Inactive.
    status: String(role.status ?? 'ACTIVE').toUpperCase() === 'DISABLED' ? 'Inactive' : 'Active',
  }
}

/** UI permission-matrix rows â†’ flat backend permission keys. */
function adaptRoleIn(input: Record<string, unknown>): Record<string, unknown> {
  const output = stripUiOnlyFields(input)
  // Role status uses the ACTIVE/DISABLED dialect on the backend.
  if (output.status != null) {
    const status = String(output.status).toUpperCase()
    output.status = status === 'INACTIVE' || status === 'DISABLED' ? 'DISABLED' : 'ACTIVE'
  }
  if (Array.isArray(input.permissionRows)) {
    output.permissions = permissionRowsToFlatKeys(input.permissionRows as AppRolePermissionRow[])
  }
  return output
}

/** Backend audit log fields â†’ the audit-logs UI template fields. */
function adaptAuditLogOut(row: Record<string, unknown>): Record<string, unknown> {
  return {
    ...row,
    // Backend returns created_at / entity_type / old_values / new_values.
    occurredAt: row.occurredAt ?? row.created_at ?? null,
    user: row.userName ?? row.user ?? row.user_name ?? null,
    eventType: row.eventType ?? row.action ?? '',
    entity: row.entityLabel ?? row.entityId ?? row.entity_id ?? '',
    ipDevice: row.ipAddress ?? row.ip_address ?? row.ipDevice ?? '',
    beforeData: row.beforeData ?? row.old_values ?? '',
    afterData: row.afterData ?? row.new_values ?? '',
  }
}

function adaptProductOut(row: Record<string, unknown>): Record<string, unknown> {
  return {
    ...row,
    id: asRecordId(row.id),
    code: row.code ?? row.sku ?? '',
    sku: row.sku ?? row.code ?? '',
    categoryId: asRecordId(row.categoryId ?? row.category_id) || null,
    brandId: asRecordId(row.brandId ?? row.brand_id) || null,
    supplierId: asRecordId(row.supplierId ?? row.supplier_id) || null,
    category: row.category ?? row.category_name ?? '',
    brand: row.brand ?? row.brand_name ?? '',
    supplier: row.supplier ?? row.supplier_name ?? '',
    costPrice: row.costPrice ?? row.cost_price,
    salePrice: row.salePrice ?? row.selling_price,
    minimumStock: row.minimumStock ?? row.minimum_stock,
    stockInQty: row.stockInQty ?? row.stock_in_qty,
    stockOutQty: row.stockOutQty ?? row.stock_out_qty,
    damageQty: row.damageQty ?? row.damage_qty,
    imageUrl: row.imageUrl ?? row.image_url ?? null,
    imageObjectKey: row.imageObjectKey ?? row.image_object_key ?? null,
    // UI status dialect (module filters use Active/Inactive).
    status: row.status === 'ACTIVE' ? 'Active' : row.status === 'INACTIVE' ? 'Inactive' : row.status,
  }
}

/**
 * Product create/update payload: UI camelCase → ProductCreate/ProductUpdate.
 * Only present keys are forwarded (PATCH is partial). SKU is generated when
 * the UI did not capture one (backend requires a unique sku).
 */
function adaptProductIn(input: Record<string, unknown>): Record<string, unknown> {
  const output: Record<string, unknown> = {}
  const text = (value: unknown): string => String(value ?? '').trim()
  const sku = text(input.sku ?? input.code)
  if (sku) output.sku = sku
  else if (input.id == null && input.name != null) {
    // Unique-enough fallback: normalized name + timestamp (server re-checks).
    const base = (text(input.name) || 'PRD')
      .toUpperCase().replace(/[^A-Z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)
    output.sku = `${base || 'PRD'}-${Date.now().toString(36).toUpperCase()}`
  }
  if (input.name != null) output.name = text(input.name)
  if (input.categoryId != null) output.category_id = asRecordId(input.categoryId) || null
  if (input.brandId != null) output.brand_id = asRecordId(input.brandId) || null
  if (input.supplierId != null) output.supplier_id = asRecordId(input.supplierId) || null
  if (input.costPrice != null) output.cost_price = Number(input.costPrice)
  if (input.salePrice != null) output.salePrice = Number(input.salePrice)
  if (input.minimumStock != null) output.minimum_stock = Number(input.minimumStock)
  if (input.note != null) output.note = input.note
  // imageObjectKey is the stored object key; the form's image field (imageUrl)
  // holds the uploaded key or the resolved media URL. data:/http: URLs are
  // UI-only previews. Prefer the form field, which reflects the latest upload.
  const hasImageField = 'imageUrl' in input || 'imageObjectKey' in input
  const rawImage = text(input.imageUrl ?? input.imageObjectKey)
  if (rawImage) {
    output.image_object_key = mediaObjectKey(rawImage)
  }
  else if (hasImageField) {
    // The image field was cleared — clear the stored image.
    output.image_object_key = null
  }
  if (input.status != null) {
    const status = text(input.status).toUpperCase()
    output.status = status === 'INACTIVE' ? 'INACTIVE' : 'ACTIVE'
  }
  return output
}

/** UI payment labels → canonical POS tender methods (one mapping, both sides).
 *  Cash→CASH; Card / Mobile Payment / Bank Transfer→BANK_QR (cashless);
 *  Credit→CUSTOMER_DEBT (documented on the backend SaleCreateRequest). */
const POS_PAYMENT_METHOD_MAP: Record<string, string> = {
  Cash: 'CASH',
  Card: 'BANK_QR',
  'Mobile Payment': 'BANK_QR',
  'Bank Transfer': 'BANK_QR',
  Credit: 'CUSTOMER_DEBT',
}

function canonicalPaymentMethod(method: unknown): string {
  return POS_PAYMENT_METHOD_MAP[String(method ?? '').trim()] || String(method ?? 'CASH')
}

/** UI payment labels → canonical Finance expense methods (CASH|BANK_QR|CARD|OTHER). */
const EXPENSE_PAYMENT_METHOD_MAP: Record<string, string> = {
  Cash: 'CASH',
  Card: 'CARD',
  'Mobile Payment': 'BANK_QR',
  'Bank Transfer': 'OTHER',
}

function canonicalExpenseMethod(method: unknown): string {
  return EXPENSE_PAYMENT_METHOD_MAP[String(method ?? '').trim()] || 'OTHER'
}

/** Backend ACTIVE/INACTIVE → the config-driven forms' Active/Inactive dialect. */
function statusToUiDialect(value: unknown): unknown {
  if (value === 'ACTIVE') return 'Active'
  if (value === 'INACTIVE') return 'Inactive'
  return value
}

function adaptEntityOut(collection: ApiCollection, row: Record<string, unknown>): Record<string, unknown> {
  if (collection === 'users') return adaptUserOut(row)
  if (collection === 'roles') return adaptRoleOut(row)
  if (collection === 'auditLogs') return adaptAuditLogOut(row)
  if (collection === 'products') return adaptProductOut(row)
  if (collection === 'categories' || collection === 'brands') {
    return { ...row, status: statusToUiDialect(row.status) }
  }
  if (collection === 'customers' || collection === 'suppliers') return adaptPartyLocationOut(row)
  if (collection === 'customerDebts') return adaptCustomerDebtOut(row)
  if (collection === 'supplierDebts') return adaptSupplierDebtOut(row)
  if (collection === 'deliveryNotes') return adaptDeliveryNoteOut(row)
  if (collection === 'stockMovements') return adaptStockMovementOut(row)
  if (collection === 'sales') return adaptSalesReportLine(row)
  if (collection === 'stockIns') return adaptPurchaseReportLine(row)
  if (collection === 'saleReturns') return adaptSaleReturnRow(row)
  if (collection === 'purchaseReturns') return adaptPurchaseReturnRow(row)
  if (collection === 'documentSequences') return adaptDocumentSequenceOut(row)
  return row
}

/**
 * Backend SequenceOut → UI camelCase. `next_number` is the number to allocate
 * next, so the UI's `lastValue` (last issued) is `next_number - 1`.
 */
function adaptDocumentSequenceOut(row: Record<string, unknown>): Record<string, unknown> {
  const nextNumber = Math.max(1, Number(row.next_number ?? row.nextNumber ?? 1))
  const lastValue = Math.max(0, nextNumber - 1)
  const paddingLength = Math.max(1, Number(row.number_length ?? row.paddingLength ?? 6))
  const normalized: AppRecord = {
    ...(row as AppRecord),
    documentType: String(row.document_type ?? row.documentType ?? ''),
    prefix: String(row.prefix ?? ''),
    lastValue,
    paddingLength,
  }
  return {
    ...row,
    documentType: normalized.documentType,
    prefix: normalized.prefix,
    lastValue,
    paddingLength,
    resetType: row.reset_type ?? row.resetType ?? null,
    nextNumberPreview: documentSequencePreview(normalized),
  }
}

/** Backend SaleReturnRow → UI camelCase customer-return history row. */
function adaptSaleReturnRow(row: Record<string, unknown>): Record<string, unknown> {
  return {
    id: asRecordId(row.return_id ?? row.returnId),
    returnNo: String(row.return_no ?? row.returnNo ?? ''),
    saleId: asRecordId(row.sale_id ?? row.saleId),
    saleNo: String(row.sale_no ?? row.saleNo ?? ''),
    date: row.return_date ?? row.returnDate ?? null,
    createdAt: row.return_date ?? row.returnDate ?? null,
    customer: String(row.customer_name ?? row.customer ?? ''),
    itemCount: Number(row.item_count ?? row.itemCount ?? 0),
    refundAmount: q2(row.refund_amount ?? row.refundAmount),
    restockedQuantity: q4(row.restocked_quantity ?? row.restockedQuantity),
    reason: String(row.reason ?? ''),
    user: String(row.user_name ?? row.user ?? ''),
  }
}

/** Backend PurchaseReturnRow → UI camelCase supplier-return history row. */
function adaptPurchaseReturnRow(row: Record<string, unknown>): Record<string, unknown> {
  return {
    id: asRecordId(row.return_id ?? row.returnId),
    returnNo: String(row.return_no ?? row.returnNo ?? ''),
    stockInId: asRecordId(row.stock_transaction_id ?? row.stockTransactionId),
    purchaseNo: String(row.document_no ?? row.documentNo ?? ''),
    date: row.return_date ?? row.returnDate ?? null,
    createdAt: row.return_date ?? row.returnDate ?? null,
    supplier: String(row.supplier_name ?? row.supplier ?? ''),
    itemCount: Number(row.item_count ?? row.itemCount ?? 0),
    refundAmount: q2(row.refund_amount ?? row.refundAmount),
    debtReduction: q2(row.debt_reduction ?? row.debtReduction),
    creditAmount: q2(row.credit_amount ?? row.creditAmount),
    reason: String(row.reason ?? ''),
    user: String(row.user_name ?? row.user ?? ''),
  }
}

/** Backend DeliveryNoteOut → UI camelCase note shape (multi-invoice, spec §2.1.9). */
function adaptDeliveryNoteOut(row: Record<string, unknown>): Record<string, unknown> {
  const links = Array.isArray(row.sales) ? row.sales as Record<string, unknown>[] : []
  const items = Array.isArray(row.items) ? row.items as Record<string, unknown>[] : []
  const invoiceNos = links.map(link => String(link.invoice_no ?? link.invoiceNo ?? '')).filter(Boolean)
  return {
    ...row,
    id: asRecordId(row.id),
    deliveryNo: row.deliveryNo ?? row.delivery_no ?? '',
    customerId: asRecordId(row.customerId ?? row.customer_id) || null,
    customer: row.customer ?? row.customer_name ?? '',
    // Linked invoices: [{ saleId, invoiceNo, saleDate }] + joined display keys.
    sales: links.map(link => ({
      saleId: asRecordId(link.saleId ?? link.sale_id),
      invoiceNo: String(link.invoice_no ?? link.invoiceNo ?? ''),
      saleDate: link.saleDate ?? link.sale_date ?? null,
    })),
    invoiceNos,
    invoiceNo: invoiceNos.join(', '),
    // Delivery list Invoice Date = earliest linked invoice sale date.
    invoiceDate: links
      .map(link => link.saleDate ?? link.sale_date)
      .filter(Boolean)
      .map(value => String(value))
      .sort()[0] ?? null,
    saleId: invoiceNos.length === 1 ? String(links[0]?.sale_id ?? links[0]?.saleId ?? '') : '',
    deliveryPhone: row.deliveryPhone ?? row.delivery_phone ?? '',
    deliveryLocation: row.deliveryLocation ?? row.delivery_location ?? '',
    deliveryDate: row.deliveryDate ?? row.delivery_date ?? null,
    deliveryFee: row.deliveryFee ?? row.delivery_fee ?? null,
    deliveredAt: row.deliveredAt ?? row.delivered_at ?? null,
    // Collapse the backend lifecycle into the simplified Processing/Completed;
    // keep the raw backend enum so editability (PENDING only) stays accurate.
    status: normalizeDeliveryStatusInput(row.status),
    statusRaw: String(row.status ?? ''),
    note: row.note ?? null,
    cancelReason: row.cancelReason ?? row.cancel_reason ?? null,
    createdBy: asRecordId(row.createdBy ?? row.created_by),
    createdAt: row.created_at ?? row.createdAt ?? null,
    itemCount: row.itemCount ?? items.length,
    items: items.map(line => ({
      id: asRecordId(line.id),
      saleId: asRecordId(line.saleId ?? line.sale_id),
      saleItemId: asRecordId(line.saleItemId ?? line.sale_item_id),
      productId: asRecordId(line.productId ?? line.product_id),
      product: String(line.product ?? line.product_name ?? ''),
      qtyOrdered: q4(line.qtyOrdered ?? line.qty_ordered),
      qtyToDeliver: q4(line.qtyToDeliver ?? line.qty_to_deliver),
      qtyDelivered: q4(line.qtyDelivered ?? line.qty_delivered),
    })),
  }
}

/** Backend movement row → UI camelCase (Stock Movements page + history dialogs). */
function adaptStockMovementOut(row: Record<string, unknown>): Record<string, unknown> {
  const movementType = String(row.movement_type ?? row.type ?? '')
  const labels: Record<string, string> = {
    STOCK_IN: 'Stock In',
    SALE: 'Sale',
    SALE_RETURN: 'Sale Return',
    PURCHASE_RETURN: 'Purchase Return',
    ADJUSTMENT_IN: 'Adjustment Increase',
    ADJUSTMENT_OUT: 'Adjustment Decrease',
    DAMAGE: 'Damage',
  }
  return {
    ...row,
    id: asRecordId(row.id),
    productId: asRecordId(row.productId ?? row.product_id),
    product: row.product ?? row.product_name ?? '',
    productName: row.productName ?? row.product_name ?? '',
    type: labels[movementType] ?? movementType,
    movementType,
    quantity: Number(row.quantity ?? row.quantity_delta ?? 0),
    quantityDelta: row.quantityDelta ?? row.quantity_delta ?? 0,
    // Backend MovementOut projects the signed delta into qty_in / qty_out.
    qtyIn: Number(row.qty_in ?? row.qtyIn ?? 0),
    qtyOut: Number(row.qty_out ?? row.qtyOut ?? 0),
    // Source business document number (PIN / INV / SRT / PRT / ADJ / DMG / EXP).
    documentNo: String(row.document_no ?? row.documentNo ?? row.reference ?? ''),
    unitCost: row.unit_cost ?? row.unitCost ?? null,
    balanceBefore: Number(row.balance_before ?? row.balanceBefore ?? 0),
    balanceAfter: Number(row.balance_after ?? row.balanceAfter ?? null),
    reference: row.reference ?? row.document_no ?? '',
    referenceType: row.referenceType ?? row.reference_type ?? '',
    user: row.user ?? row.created_by_name ?? '',
    date: row.date ?? row.created_at ?? null,
    createdAt: row.createdAt ?? row.created_at ?? null,
  }
}

/** UI `location` maps to backend `address`; email is not used on parties. */
function adaptPartyLocationOut(row: Record<string, unknown>): Record<string, unknown> {
  const location = String(row.location ?? row.address ?? '').trim()
  return {
    ...row,
    id: asRecordId(row.id),
    location,
    address: location,
    status: statusToUiDialect(row.status),
  }
}

function adaptPartyLocationIn(input: Record<string, unknown>): Record<string, unknown> {
  const output = stripUiOnlyFields(input)
  const location = String(input.location ?? input.address ?? '').trim()
  output.location = location || null
  output.address = location || null
  delete output.email
  delete output.debtBalance
  delete output.totalDebt
  return output
}

/** Backend customer-debt report row → UI keys (spec 2.1.10 Customer Debt Report). */
function adaptCustomerDebtOut(row: Record<string, unknown>): Record<string, unknown> {
  return {
    id: asRecordId(row.debt_id ?? row.id),
    saleId: row.sale_id ?? null,
    customerId: asRecordId(row.customer_id),
    customer: String(row.customer_name ?? ''),
    customerCode: String(row.customer_code ?? ''),
    invoiceNo: String(row.invoice_no ?? ''),
    date: row.date ?? row.invoice_date ?? row.created_at ?? null,
    invoiceTotal: row.invoice_total ?? row.original_amount ?? null,
    paidAmount: row.paid_amount ?? null,
    remainingAmount: row.remaining_amount ?? null,
    dueDate: row.due_date ?? null,
    status: String(row.status ?? ''),
    // Staff (cashier) who created the source sale — export/report user filter.
    userId: row.user_id != null ? String(row.user_id) : '',
    user: String(row.user_name ?? row.user ?? ''),
    // Debt inherits the source sale currency + saved exchange rate; historical
    // debts must never be re-converted with the current rate.
    currency: String(row.currency ?? 'USD'),
    exchangeRate: Number(row.exchange_rate ?? 1),
    createdAt: row.created_at ?? null,
  }
}

/** Backend supplier-debt report row → UI keys (spec 2.1.10 Supplier Debt Report). */
function adaptSupplierDebtOut(row: Record<string, unknown>): Record<string, unknown> {
  return {
    id: asRecordId(row.debt_id ?? row.id),
    stockTransactionId: row.stock_transaction_id ?? null,
    supplierId: asRecordId(row.supplier_id),
    supplier: String(row.supplier_name ?? ''),
    supplierCode: String(row.supplier_code ?? ''),
    purchaseNo: String(row.document_no ?? ''),
    date: row.date ?? row.transaction_date ?? row.created_at ?? null,
    totalAmount: row.total_amount ?? row.original_amount ?? null,
    paidAmount: row.paid_amount ?? null,
    remainingAmount: row.remaining_amount ?? null,
    dueDate: row.due_date ?? null,
    status: String(row.status ?? ''),
    // Staff who created the source Stock In — export/report user filter.
    userId: row.user_id != null ? String(row.user_id) : '',
    user: String(row.user_name ?? row.user ?? ''),
    currency: String(row.currency ?? 'USD'),
    exchangeRate: Number(row.exchange_rate ?? 1),
    createdAt: row.created_at ?? null,
  }
}

/**
 * The config-driven forms use the Active/Inactive status dialect, but the
 * setup/master-data APIs store canonical uppercase ACTIVE/INACTIVE (users and
 * roles use ACTIVE/DISABLED). Normalize every write so a selected "Active"
 * never trips the backend status pattern.
 */
function normalizeStatusValue(output: Record<string, unknown>): Record<string, unknown> {
  const status = typeof output.status === 'string' ? output.status.trim() : ''
  if (status) output.status = status.toUpperCase()
  return output
}

function adaptEntityIn(collection: ApiCollection, input: Record<string, unknown>): Record<string, unknown> {
  let output: Record<string, unknown>
  if (collection === 'roles') output = adaptRoleIn(input)
  else if (collection === 'users') output = adaptUserIn(input)
  else if (collection === 'customers' || collection === 'suppliers') output = adaptPartyLocationIn(input)
  else if (collection === 'products') output = adaptProductIn(input)
  else output = stripUiOnlyFields(input)
  return normalizeStatusValue(output)
}

/** Round a numeric-ish value to 4 dp (report grouping math). */
function q4(value: unknown): number {
  return Math.round((Number(value ?? 0) + Number.EPSILON) * 10000) / 10000
}

function q2(value: unknown): number {
  return Math.round((Number(value ?? 0) + Number.EPSILON) * 100) / 100
}

/** Canonical tender method → Sales Report display label. The row keeps the
 *  canonical `paymentMethod` so the filter still matches; the table renders
 *  `paymentMethodLabel`. */
const SALES_PAYMENT_LABELS: Record<string, string> = {
  CASH: 'Cash',
  BANK_QR: 'Bank/QR',
  CUSTOMER_DEBT: 'Credit',
  UNPAID: 'Unpaid',
}

function salesPaymentLabel(method: unknown): string {
  const value = String(method ?? '')
  return SALES_PAYMENT_LABELS[value] || value
}

/** Backend payment_status → report status label (Paid/Partial/Unpaid). */
function salesStatusFromPayment(status: unknown): string | null {
  const value = String(status ?? '').toUpperCase()
  if (value === 'PAID') return 'Paid'
  if (value === 'PARTIAL') return 'Partial'
  if (value === 'UNPAID') return 'Unpaid'
  return null
}

/** One backend sales-report line row → camelCase for grouping. */
function adaptSalesReportLine(row: Record<string, unknown>): Record<string, unknown> {
  return {
    saleId: asRecordId(row.sale_id ?? row.saleId),
    saleItemId: asRecordId(row.sale_item_id ?? row.saleItemId),
    productId: asRecordId(row.product_id ?? row.productId) || null,
    date: row.sale_date ?? row.saleDate ?? null,
    invoiceNo: String(row.invoice_no ?? row.invoiceNo ?? ''),
    customer: String(row.customer_name ?? row.customer ?? ''),
    product: String(row.product_name ?? row.product ?? ''),
    quantity: q4(row.quantity),
    returnedQuantity: q4(row.returned_quantity ?? row.returnedQuantity),
    returnableQuantity: q4(row.returnable_quantity ?? row.returnableQuantity),
    height: row.height == null ? null : q4(row.height),
    width: row.width == null ? null : q4(row.width),
    areaM2: row.area_m2 == null ? null : q4(row.area_m2),
    price: q2(row.selling_price ?? row.sellingPrice),
    total: q2(row.sales_amount ?? row.salesAmount),
    returnAmount: q2(row.return_amount ?? row.returnAmount),
    debtAmount: q2(row.debt_amount ?? row.debtAmount),
    paymentMethod: String(row.payment_method ?? row.paymentMethod ?? ''),
    cashier: String(row.cashier_name ?? row.cashier ?? ''),
    // Saved sale header (repeated per line): authoritative checkout values so
    // the report never recomputes from current prices.
    saleSubtotal: q2(row.subtotal ?? row.saleSubtotal),
    deliveryPrice: q2(row.delivery_price ?? row.deliveryPrice),
    grandTotal: q2(row.grand_total ?? row.grandTotal),
    paidAmount: q2(row.paid_amount ?? row.paidAmount),
    paymentStatus: row.payment_status ?? row.paymentStatus ?? null,
    note: row.note ?? null,
    dueDate: row.due_date ?? row.dueDate ?? null,
    // Document currency snapshot (historical sales render in their own currency).
    currency: String(row.currency ?? 'USD'),
    exchangeRate: Number(row.exchange_rate ?? row.exchangeRate ?? 1) || 1,
  }
}

/**
 * Group line-level GET /reports/sales rows into document rows matching the
 * UI sale shape (id, saleNo, items[] with returnable quantities) so the
 * Sales Report table AND the customer Return dialog share one contract.
 *
 * Rows arrive raw from the report endpoint — adapt exactly once here. The
 * saved sale header (subtotal/delivery/grand_total/paid/debt) is the
 * source of truth; line sums are only a fallback for legacy rows.
 */
function groupSalesReportRows(rows: Record<string, unknown>[]): AppRecord[] {
  const bySale = new Map<string, Record<string, unknown>>()
  for (const raw of rows) {
    const line = adaptSalesReportLine(raw)
    const key = line.saleId as string
    let doc = bySale.get(key)
    if (!doc) {
      doc = {
        id: key,
        saleNo: line.invoiceNo,
        invoiceNo: line.invoiceNo,
        date: line.date,
        createdAt: line.date,
        customer: line.customer,
        customerId: null,
        currency: line.currency || 'USD',
        exchangeRate: Number(line.exchangeRate) || 1,
        note: line.note ?? null,
        dueDate: line.dueDate ?? null,
        items: [],
        lineCount: 0,
        // Saved header values (repeat per line) + line-sum fallbacks.
        subtotal: 0,
        lineGross: 0,
        deliveryPrice: 0,
        total: 0,
        returnAmount: 0,
        paidAmount: 0,
        debtAmount: 0,
        remaining: 0,
        areaM2: 0,
        paymentStatus: line.paymentStatus,
        paymentMethod: '',
        cashier: '',
      }
      bySale.set(key, doc)
    }
    const items = doc.items as Record<string, unknown>[]
    items.push({
      id: line.saleItemId,
      productId: line.productId,
      name: line.product,
      quantity: line.quantity,
      returnedQuantity: line.returnedQuantity,
      returnableQuantity: line.returnableQuantity,
      price: line.price,
      total: line.total,
    })
    doc.lineCount = items.length
    doc.lineGross = q2(Number(doc.lineGross) + Number(line.total))
    doc.returnAmount = q2(Number(doc.returnAmount) + Number(line.returnAmount))
    // Document m² = sum of the sold-by-area line areas (0 for count sales).
    doc.areaM2 = q4(Number(doc.areaM2) + Number(line.areaM2 || 0))
    // Header fields repeat per line — take the first non-empty value.
    if (!doc.paymentMethod && line.paymentMethod) doc.paymentMethod = String(line.paymentMethod)
    if (!doc.cashier && line.cashier) doc.cashier = line.cashier
    if (!doc.note && line.note) doc.note = line.note
    if (!doc.dueDate && line.dueDate) doc.dueDate = line.dueDate
    if (!doc.paymentStatus && line.paymentStatus) doc.paymentStatus = line.paymentStatus
    // Saved header values are identical on every line — assign directly.
    doc.subtotal = Number(line.saleSubtotal) || 0
    doc.deliveryPrice = Number(line.deliveryPrice) || 0
    doc.total = Number(line.grandTotal) || 0
    doc.paidAmount = Number(line.paidAmount) || 0
    doc.debtAmount = Number(line.debtAmount) || 0
    if (line.currency) doc.currency = line.currency
    if (line.exchangeRate) doc.exchangeRate = Number(line.exchangeRate)
  }
  const docs = [...bySale.values()] as AppRecord[]
  for (const doc of docs) {
    // Prefer the saved header; fall back to the line sums only when absent.
    const subtotal = Number(doc.subtotal) || Number(doc.lineGross)
    const deliveryPrice = Number(doc.deliveryPrice) || 0
    const grandTotal = Number(doc.total) || q2(subtotal + deliveryPrice)
    const remaining = Number(doc.debtAmount) || 0
    doc.subtotal = q2(subtotal)
    doc.deliveryPrice = q2(deliveryPrice)
    doc.total = q2(grandTotal)
    doc.remaining = q2(remaining)
    doc.remainingAmount = q2(remaining)
    doc.paidAmount = q2(Number(doc.paidAmount) || (grandTotal - remaining))
    const allReturned = (doc.items as Record<string, unknown>[]).length > 0
      && (doc.items as Record<string, unknown>[]).every(line => q4(line.returnableQuantity) <= 0)
    const statusFromPayment = salesStatusFromPayment(doc.paymentStatus)
    doc.status = allReturned
      ? 'Returned'
      : (statusFromPayment || (remaining > 0
        ? (Number(doc.paidAmount) > 0 ? 'Partial' : 'Unpaid')
        : 'Paid'))
    doc.areaM2 = Number(doc.areaM2) > 0 ? q4(doc.areaM2) : null
    doc.paymentMethodLabel = salesPaymentLabel(doc.paymentMethod)
  }
  // Newest sale first (report rows arrive newest-first already; grouping
  // preserves that order per document).
  return docs
}

/** One backend purchase-report line row → camelCase for grouping. */
function adaptPurchaseReportLine(row: Record<string, unknown>): Record<string, unknown> {
  return {
    transactionId: asRecordId(row.transaction_id ?? row.transactionId),
    itemId: asRecordId(row.stock_transaction_item_id ?? row.stockTransactionItemId),
    productId: asRecordId(row.product_id ?? row.productId) || null,
    date: row.transaction_date ?? row.transactionDate ?? null,
    purchaseNo: String(row.document_no ?? row.documentNo ?? ''),
    supplier: String(row.supplier_name ?? row.supplier ?? ''),
    supplierId: asRecordId(row.supplier_id ?? row.supplierId) || null,
    product: String(row.product_name ?? row.product ?? ''),
    quantity: q4(row.quantity),
    returnedQuantity: q4(row.returned_quantity ?? row.returnedQuantity),
    returnableQuantity: q4(row.returnable_quantity ?? row.returnableQuantity),
    // Sold-by-area purchase line dimensions (null for count-based lines).
    height: row.height == null ? null : q4(row.height),
    width: row.width == null ? null : q4(row.width),
    areaM2: row.area_m2 == null ? null : q4(row.area_m2),
    price: q2(row.cost_price ?? row.costPrice),
    total: q2(row.total_cost ?? row.totalCost),
    remaining: q2(row.remaining_debt ?? row.remainingDebt),
    status: String(row.status ?? ''),
    currency: String(row.currency ?? 'USD'),
    exchangeRate: Number(row.exchange_rate ?? row.exchangeRate ?? 1) || 1,
    // Header fields the Edit form reloads (repeated per line).
    note: row.note ?? null,
    tax: q2(row.tax_amount ?? row.taxAmount),
    // Tender recorded for the stock-in (Purchase Report Payment Method).
    paymentMethod: String(row.payment_method ?? row.paymentMethod ?? ''),
  }
}

/**
 * Group line-level GET /reports/purchases rows into document rows matching
 * the UI purchase shape (id, purchaseNo, items[] with returnable qty)
 * so the Purchase Report table AND the supplier Return dialog share one
 * contract. Return lines reference stock_transaction_item_id.
 */
function groupPurchaseReportRows(rows: Record<string, unknown>[]): AppRecord[] {
  const byTx = new Map<string, Record<string, unknown>>()
  for (const raw of rows) {
    const line = adaptPurchaseReportLine(raw)
    const key = line.transactionId as string
    let doc = byTx.get(key)
    if (!doc) {
      doc = {
        id: key,
        purchaseNo: line.purchaseNo,
        date: line.date,
        createdAt: line.date,
        supplier: line.supplier,
        supplierId: line.supplierId,
        currency: line.currency,
        exchangeRate: line.exchangeRate,
        items: [],
        lineCount: 0,
        total: 0,
        paidAmount: 0,
        remaining: 0,
        areaM2: 0,
        status: 'Completed',
        note: line.note,
        tax: line.tax,
        paymentMethod: line.paymentMethod,
      }
      byTx.set(key, doc)
    }
    const items = doc.items as Record<string, unknown>[]
    items.push({
      id: line.itemId,
      productId: line.productId,
      name: line.product,
      quantity: line.quantity,
      returnedQuantity: line.returnedQuantity,
      returnableQuantity: line.returnableQuantity,
      height: line.height,
      width: line.width,
      areaM2: line.areaM2,
      price: line.price,
      total: line.total,
    })
    doc.lineCount = items.length
    doc.total = q2(Number(doc.total) + Number(line.total))
    doc.remaining = Math.max(Number(doc.remaining), Number(line.remaining))
    // Document m² = sum of the sold-by-area line areas (0 for count purchases).
    doc.areaM2 = q4(Number(doc.areaM2) + Number(line.areaM2 || 0))
    if (!doc.supplier && line.supplier) doc.supplier = line.supplier
    if (!doc.paymentMethod && line.paymentMethod) doc.paymentMethod = line.paymentMethod
  }
  return [...byTx.values()].map((doc) => {
    doc.paidAmount = q2(Number(doc.total) - Number(doc.remaining))
    doc.status = Number(doc.remaining) > 0 ? 'Partial' : 'Completed'
    doc.areaM2 = Number(doc.areaM2) > 0 ? q4(doc.areaM2) : null
    doc.paymentMethodLabel = salesPaymentLabel(doc.paymentMethod)
    return doc as AppRecord
  })
}

function statusEndpoint(collection: ApiCollection, id: string): string | null {
  if (collection === 'products') return ApiEndpoints.PRODUCT(id)
  if (collection === 'categories') return ApiEndpoints.CATEGORY(id)
  return null
}

/** UI camelCase list filters → the backend's snake_case query parameter names. */
const LIST_QUERY_PARAM_MAP: Record<string, string> = {
  customerId: 'customer_id',
  supplierId: 'supplier_id',
  productId: 'product_id',
  paymentMethod: 'payment_method',
  userId: 'user_id',
}

export function createHttpEntityRepository(): EntityRepository {
  const api = useApi()

  /** Report collections are grouped into documents client-side, so fetch a
   *  wide page (line-level rows collapse ~5:1 into document rows). */
  const REPORT_COLLECTIONS = new Set<ApiCollection>(['sales', 'stockIns'])

  async function list(collection: string, query: EntityListQuery = {}): Promise<EntityListResult> {
    const endpoint = CollectionEndpoints[collection as ApiCollection]
    if (!endpoint) return { items: [], meta: null }
    const key = collection as ApiCollection
    // UI camelCase list filters → the backend's snake_case query names. The
    // backend never accepts camelCase for these, so unmapped keys were silently
    // ignored (debt party/user filters are applied server-side).
    const params: Record<string, unknown> = {}
    for (const [param, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue
      params[LIST_QUERY_PARAM_MAP[param] ?? param] = value
    }
    params.limit = query.limit ?? (REPORT_COLLECTIONS.has(key) ? 500 : 100)
    const response = await api.get<unknown>(endpoint, {
      query: params,
      requestKey: `entity-list:${collection}`,
    })
    const items = unwrap<Record<string, unknown>[]>(response)
    const raw = (Array.isArray(items) ? items : []) as Record<string, unknown>[]
    // Report endpoints return line-level rows; the group functions adapt each
    // row exactly ONCE. Pre-mapping here would re-adapt camelCase keys and
    // zero out the money/payment/date fields (sales + purchase reports).
    if (key === 'sales') return { items: groupSalesReportRows(raw), meta: metaOf(response) }
    if (key === 'stockIns') return { items: groupPurchaseReportRows(raw), meta: metaOf(response) }
    const mapped = raw.map(row => adaptEntityOut(key, row)) as AppRecord[]
    return { items: mapped, meta: metaOf(response) }
  }

  async function get(collection: string, id: string): Promise<AppRecord | null> {
    const endpoint = CollectionEndpoints[collection as ApiCollection]
    if (!endpoint) return null
    try {
      const response = await api.get<unknown>(`${endpoint}/${id}`, {
        suppressErrorToast: true,
        cancelPrevious: false,
        requestKey: `entity-get:${collection}:${id}`,
      })
      return adaptEntityOut(collection as ApiCollection, unwrap<Record<string, unknown>>(response)) as AppRecord
    }
    catch {
      return null
    }
  }

  async function create(collection: string, input: Record<string, unknown>): Promise<AppRecord> {
    const endpoint = CollectionEndpoints[collection as ApiCollection]
    const response = await api.post<unknown>(endpoint, adaptEntityIn(collection as ApiCollection, input))
    return adaptEntityOut(collection as ApiCollection, unwrap<Record<string, unknown>>(response)) as AppRecord
  }

  async function update(collection: string, id: string, input: Record<string, unknown>): Promise<AppRecord> {
    const endpoint = CollectionEndpoints[collection as ApiCollection]
    // Spec §7: the backend uses PATCH for partial updates (no PUT endpoints).
    const response = await api.patch<unknown>(`${endpoint}/${id}`, adaptEntityIn(collection as ApiCollection, input))
    return adaptEntityOut(collection as ApiCollection, unwrap<Record<string, unknown>>(response)) as AppRecord
  }

  async function remove(collection: string, id: string): Promise<void> {
    const endpoint = CollectionEndpoints[collection as ApiCollection]
    // Delete conflicts (e.g. 409 "record in use") carry a business explanation;
    // callers show that message themselves instead of the raw "API Error: 409"
    // toast from useApi.
    await api.delete(`${endpoint}/${id}`, { suppressErrorToast: true })
  }

  async function setStatus(collection: string, id: string, status: string): Promise<AppRecord> {
    const endpoint = statusEndpoint(collection as ApiCollection, id)
    if (!endpoint) throw new Error(`Status updates are not supported for ${collection}`)
    const response = await api.patch<unknown>(endpoint, { status })
    return adaptEntityOut(collection as ApiCollection, unwrap<Record<string, unknown>>(response)) as AppRecord
  }

  return { list, get, create, update, remove, setStatus }
}

export function createHttpPosCommandRepository(): PosCommandRepository {
  const api = useApi()

  /** camelCase checkout input → POST /pos/sales body (spec §7 POS).
   *  Payment labels map to canonical tender methods: Cash→CASH, Card /
   *  Mobile Payment / Bank Transfer→BANK_QR, Credit→CUSTOMER_DEBT. */
  function saleItemsBody(items: PosCompleteSaleInput['items']): Record<string, unknown>[] {
    return (items || []).map(item => ({
      product_id: item.productId,
      quantity: item.quantity,
      ...(item.height != null ? { height: item.height } : {}),
      ...(item.width != null ? { width: item.width } : {}),
      ...(item.unitPrice != null ? { unit_price: item.unitPrice } : {}),
    }))
  }

  function saleBody(input: PosCompleteSaleInput): Record<string, unknown> {
    return {
      customer_id: input.customerId || null,
      items: saleItemsBody(input.items),
      payment_method: canonicalPaymentMethod(input.paymentMethod),
      amount_received: input.paidAmount,
      note: input.note ?? null,
      included_debt_ids: input.includedDebtIds ?? [],
      delivery_price: input.deliveryPrice ?? 0,
      deposit: input.deposit ?? 0,
      currency: input.currency ?? 'USD',
      exchange_rate: input.exchangeRate ?? 1,
    }
  }

  async function completeSale(input: PosCompleteSaleInput): Promise<AppRecord> {
    // Spec §7: checkout posts POST /pos/sales (no /complete suffix).
    return unwrap<Record<string, unknown>>(await api.post<unknown>(
      ApiEndpoints.POS_SALE_COMPLETE,
      saleBody(input),
    )) as AppRecord
  }

  async function updateSale(input: PosCompleteSaleInput & { saleId: string }): Promise<AppRecord> {
    const { saleId, ...rest } = input
    // SaleUpdateRequest only accepts the re-applied order fields; customer,
    // tender and payments stay untouched on edit. Never send keys the schema
    // silently ignores.
    return unwrap<Record<string, unknown>>(await api.patch<unknown>(
      ApiEndpoints.SALE_DETAIL(saleId),
      {
        items: saleItemsBody(rest.items),
        delivery_price: rest.deliveryPrice ?? 0,
        note: rest.note ?? null,
        currency: rest.currency ?? 'USD',
        exchange_rate: rest.exchangeRate ?? 1,
      },
    )) as AppRecord
  }

  /**
   * Complete purchase (Stock In): ONE POST /stock/in carrying every product
   * line. The server stores all items on the stock-in document, creates the
   * supplier debt for any unpaid balance and the payment row, appends
   * movements, allocates the STI number and audits — all in one transaction.
   */
  async function createPurchase(input: Parameters<PosCommandRepository['createPurchase']>[0]): Promise<AppRecord> {
    const paymentMethod = canonicalPaymentMethod(input.paymentMethod ?? 'Cash')
    return unwrap<Record<string, unknown>>(await api.post<unknown>(ApiEndpoints.STOCK_IN, {
      ...(input.supplierId ? { supplier_id: input.supplierId } : {}),
      paid_amount: Math.max(0, Number(input.paidAmount ?? 0)),
      payment_method: paymentMethod === 'CUSTOMER_DEBT' ? 'CASH' : paymentMethod,
      tax_amount: Math.max(0, Number(input.taxAmount ?? 0)),
      currency: input.currency ?? 'USD',
      exchange_rate: input.exchangeRate ?? 1,
      note: input.note ?? null,
      ...(input.transactionDate ? { transaction_date: input.transactionDate } : {}),
      items: input.lines.map(line => ({
        product_id: line.productId,
        quantity: Number(line.quantity || 0),
        ...(line.unitCost != null ? { unit_cost: Number(line.unitCost) } : {}),
        ...(Number(line.height) > 0 ? { height: Number(line.height) } : {}),
        ...(Number(line.width) > 0 ? { width: Number(line.width) } : {}),
      })),
    })) as AppRecord
  }

  async function updatePurchase(input: Parameters<PosCommandRepository['updatePurchase']>[0]): Promise<AppRecord> {
    return unwrap<Record<string, unknown>>(await api.patch<unknown>(
      ApiEndpoints.STOCK_IN_DOC(input.stockInId),
      {
        tax_amount: Math.max(0, Number(input.taxAmount ?? 0)),
        currency: input.currency ?? 'USD',
        exchange_rate: input.exchangeRate ?? 1,
        note: input.note ?? null,
        ...(input.referenceNo != null ? { reference_no: input.referenceNo } : {}),
        ...(input.transactionDate != null ? { transaction_date: input.transactionDate } : {}),
        items: input.lines.map(line => ({
          product_id: line.productId,
          quantity: Number(line.quantity || 0),
          ...(line.unitCost != null ? { unit_cost: Number(line.unitCost) } : {}),
          ...(Number(line.height) > 0 ? { height: Number(line.height) } : {}),
          ...(Number(line.width) > 0 ? { width: Number(line.width) } : {}),
        })),
      },
    )) as AppRecord
  }

  async function createStockOperation(input: Parameters<PosCommandRepository['createStockOperation']>[0]): Promise<AppRecord> {
    // Spec §7 Stock: one create path per operation — never /stock/operations.
    const endpointByType = {
      stock_in: ApiEndpoints.STOCK_IN,
      adjustment: ApiEndpoints.STOCK_ADJUST,
      damage: ApiEndpoints.STOCK_DAMAGE,
    } as const
    if (input.type === 'adjustment') {
      // Adjustment is a signed delta (+/-); the quick-operation endpoint
      // computes the actual counted quantity from the locked balance.
      return unwrap<Record<string, unknown>>(await api.post<unknown>(ApiEndpoints.STOCK_OPERATIONS, {
        type: 'adjustment',
        product_id: input.productId,
        quantity: input.quantity,
        note: input.note ?? null,
      })) as AppRecord
    }
    if (input.type === 'damage') {
      // Damage is an absolute quantity and the backend expects an `items[]`
      // envelope with a non-empty `reason`.
      const item: Record<string, unknown> = {
        product_id: input.productId,
        quantity: input.quantity,
        reason: input.note?.trim() || 'Damaged',
      }
      return unwrap<Record<string, unknown>>(await api.post<unknown>(ApiEndpoints.STOCK_DAMAGE, {
        note: input.note ?? null,
        items: [item],
      })) as AppRecord
    }
    const endpoint = endpointByType[input.type]
    // Stock In = purchase (POST /stock/in): one line per call; unpaid
    // balance becomes supplier debt in the same transaction.
    const quantity = Number(input.quantity || 0)
    const unitCost = Number(input.unitCost ?? 0)
    const lineTotal = Math.round(quantity * unitCost * 100) / 100
    const paidAmount = input.paidAmount == null ? lineTotal : Math.max(0, Number(input.paidAmount))
    return unwrap<Record<string, unknown>>(await api.post<unknown>(endpoint, {
      ...(input.supplierId ? { supplier_id: input.supplierId } : {}),
      paid_amount: paidAmount,
      payment_method: canonicalPaymentMethod(input.paymentMethod ?? 'Cash') === 'CUSTOMER_DEBT'
        ? 'CASH'
        : canonicalPaymentMethod(input.paymentMethod ?? 'Cash'),
      note: input.note ?? null,
      items: [{
        product_id: input.productId,
        quantity,
        unit_cost: unitCost,
      }],
    })) as AppRecord
  }

  async function payCustomerDebt(input: Parameters<PosCommandRepository['payCustomerDebt']>[0]): Promise<AppRecord> {
    // Spec §7: POST /customers/{id}/debts/{debt_id}/payments. When the caller
    // has no debt id, the customer-level service endpoint settles open rows.
    const endpoint = input.debtId
      ? ApiEndpoints.CUSTOMER_DEBT_PAYMENTS(input.customerId, input.debtId)
      : ApiEndpoints.CUSTOMER_PAYMENTS(input.customerId)
    return unwrap<Record<string, unknown>>(await api.post<unknown>(endpoint, {
      amount: input.amount,
      payment_method: canonicalPaymentMethod(input.paymentMethod),
      reference_no: input.reference ?? null,
    })) as AppRecord
  }

  async function paySupplierDebt(input: Parameters<PosCommandRepository['paySupplierDebt']>[0]): Promise<AppRecord> {
    // Spec §7: POST /suppliers/{id}/debts/{debt_id}/payments (same fallback).
    const endpoint = input.debtId
      ? ApiEndpoints.SUPPLIER_DEBT_PAYMENTS(input.supplierId, input.debtId)
      : ApiEndpoints.SUPPLIER_PAYMENTS(input.supplierId)
    return unwrap<Record<string, unknown>>(await api.post<unknown>(endpoint, {
      amount: input.amount,
      payment_method: canonicalPaymentMethod(input.paymentMethod),
      reference_no: input.reference ?? null,
    })) as AppRecord
  }

  async function getSaleReceipt(saleId: string): Promise<SaleReceipt> {
    const data = unwrap<Record<string, unknown>>(await api.get<unknown>(
      ApiEndpoints.POS_RECEIPT(saleId),
      { requestKey: `pos-receipt:${saleId}`, cancelPrevious: true },
    ))
    return adaptSaleReceiptOut(data, saleId)
  }

  async function getSale(saleId: string): Promise<SaleDetail> {
    const data = unwrap<Record<string, unknown>>(await api.get<unknown>(
      ApiEndpoints.SALE_DETAIL(saleId),
      { requestKey: `pos-sale:${saleId}`, cancelPrevious: true },
    ))
    return adaptSaleDetailOut(data, saleId)
  }

  async function returnSale(input: Parameters<PosCommandRepository['returnSale']>[0]): Promise<AppRecord> {
    return unwrap<Record<string, unknown>>(await api.post<unknown>(
      ApiEndpoints.SALE_RETURN(input.saleId),
      {
        reason: input.reason,
        // `items` is the canonical body key; the backend also accepts `lines`.
        items: input.lines.map(line => ({
          sale_item_id: line.lineId,
          quantity: line.quantity,
          restock: line.restock,
        })),
      },
    )) as AppRecord
  }

  async function returnPurchase(input: Parameters<PosCommandRepository['returnPurchase']>[0]): Promise<AppRecord> {
    return unwrap<Record<string, unknown>>(await api.post<unknown>(
      ApiEndpoints.STOCK_IN_RETURN(input.stockInId),
      {
        reason: input.reason,
        lines: input.lines.map(line => ({
          stock_transaction_item_id: line.lineId,
          quantity: line.quantity,
        })),
      },
    )) as AppRecord
  }

  return { completeSale, updateSale, createPurchase, updatePurchase, createStockOperation, payCustomerDebt, paySupplierDebt, getSaleReceipt, getSale, returnSale, returnPurchase }
}

/** Backend product-history row → UI camelCase (kind derived from type). */
function adaptProductHistoryOut(row: Record<string, unknown>, kind: StockHistoryKind): ProductHistoryRow {
  return {
    id: String(row.id ?? ''),
    date: String(row.date ?? row.created_at ?? '').slice(0, 10),
    type: String(row.type ?? ''),
    quantity: Number(row.qty ?? row.quantity ?? 0),
    product: String(row.product ?? row.product_name ?? ''),
    unitPrice: Number(row.unit_price ?? row.unitPrice ?? 0),
    reference: String(row.reference ?? row.document_no ?? ''),
    referenceType: String(row.reference_type ?? row.referenceType ?? ''),
    referenceId: String(row.reference_id ?? row.referenceId ?? ''),
    user: String(row.user ?? row.created_by_name ?? ''),
    note: String(row.note ?? ''),
    kind: (row.kind as StockHistoryKind) ?? kind,
  }
}

/** Backend sale detail (GET /pos/sales/{id}) → POS return-mode source. */
function adaptSaleDetailOut(data: Record<string, unknown>, fallbackSaleId: string): SaleDetail {
  const items = (Array.isArray(data.items) ? data.items : []) as Array<Record<string, unknown>>
  return {
    id: String(data.id ?? fallbackSaleId),
    invoiceNo: String(data.invoice_no ?? data.invoiceNo ?? data.sale_no ?? ''),
    customerId: data.customer_id != null ? String(data.customer_id) : null,
    customerName: String(data.customer_name ?? data.customer ?? ''),
    currency: String(data.currency ?? 'USD') === 'KHR' ? 'KHR' : 'USD',
    exchangeRate: Number(data.exchange_rate ?? data.exchangeRate ?? 1) || 1,
    // Saved checkout fields so POS edit never zeroes the original amounts.
    paymentMethod: String(data.payment_method ?? data.paymentMethod ?? ''),
    paymentStatus: String(data.payment_status ?? data.paymentStatus ?? ''),
    subtotal: Number(data.subtotal ?? 0),
    deliveryPrice: Number(data.delivery_price ?? data.deliveryPrice ?? 0),
    paidAmount: Number(data.paid_amount ?? data.paidAmount ?? 0),
    debtAmount: Number(data.debt_amount ?? data.debtAmount ?? 0),
    note: String(data.note ?? ''),
    dueDate: data.due_date != null || data.dueDate != null
      ? String(data.due_date ?? data.dueDate).slice(0, 10)
      : null,
    items: items.map((item) => {
      const quantity = Number(item.quantity ?? 0)
      const unitPrice = Number(item.unit_price ?? item.unitPrice ?? item.price ?? 0)
      return {
        id: String(item.id ?? item.sale_item_id ?? ''),
        productId: String(item.product_id ?? item.productId ?? ''),
        name: String(item.product_name ?? item.name ?? ''),
        height: Number(item.height ?? 0) || undefined,
        width: Number(item.width ?? 0) || undefined,
        areaM2: Number(item.area_m2 ?? item.areaM2 ?? 0) || undefined,
        quantity,
        returnedQuantity: Number(item.returned_quantity ?? item.returnedQuantity ?? 0),
        unitPrice,
        lineTotal: Number(item.line_total ?? item.lineTotal ?? item.total ?? (unitPrice * quantity)),
      }
    }),
  }
}

/** Backend receipt payload (print + Stock Out invoice detail dialog) → UI camelCase. */
function adaptSaleReceiptOut(data: Record<string, unknown>, fallbackSaleId: string): SaleReceipt {
  const items = (Array.isArray(data.items) ? data.items : []) as Array<Record<string, unknown>>
  return {
    saleId: String(data.sale_id ?? data.saleId ?? fallbackSaleId),
    saleNo: String(data.sale_no ?? data.saleNo ?? data.invoice_no ?? ''),
    invoiceNo: String(data.invoice_no ?? data.invoiceNo ?? ''),
    date: String(data.sale_date ?? data.date ?? '').slice(0, 10),
    customer: String(data.customer_name ?? data.customer ?? 'Walk-in customer'),
    cashier: String(data.cashier ?? data.created_by_name ?? ''),
    paymentMethod: String(data.payment_method ?? data.paymentMethod ?? ''),
    note: String(data.note ?? ''),
    items: items.map(item => ({
      name: String(item.name ?? item.product_name ?? ''),
      quantity: Number(item.quantity ?? item.qty ?? 0),
      height: Number(item.height ?? 0) || undefined,
      width: Number(item.width ?? 0) || undefined,
      areaM2: Number(item.area_m2 ?? item.areaM2 ?? 0) || undefined,
      unitPrice: Number(item.unit_price ?? item.price ?? 0),
      total: Number(item.total ?? item.line_total ?? 0),
    })),
    subtotal: Number(data.subtotal ?? 0),
    deliveryPrice: Number(data.delivery_price ?? data.deliveryPrice ?? 0),
    deposit: Number(data.deposit ?? 0),
    total: Number(data.grand_total ?? data.total ?? 0),
    paidAmount: Number(data.paid_amount ?? data.paid ?? data.paidAmount ?? 0),
    remaining: Number(data.debt_remaining ?? data.remaining ?? data.remaining_amount ?? 0),
  }
}

/** Backend cost-history lot → UI camelCase. */
function adaptCostHistoryOut(row: Record<string, unknown>): ProductCostHistoryRow {
  return {
    id: String(row.id ?? ''),
    date: String(row.date ?? row.created_at ?? '').slice(0, 10),
    product: String(row.product ?? row.product_name ?? ''),
    unitCost: Number(row.unit_cost ?? row.unitCost ?? 0),
    quantity: Number(row.quantity ?? 0),
    amount: Number(row.amount ?? row.line_amount ?? 0),
    version: Number(row.version ?? 0),
    documentNo: String(row.document_no ?? row.documentNo ?? ''),
  }
}

/**
 * HTTP implementation of the product-scoped dialog queries. Each method hits
 * the product-scoped /api/v1 URL so HTTP mode never downloads unrelated
 * collections (spec §7 Stock).
 */
export function createHttpStockQueryRepository(): StockQueryRepository {
  const api = useApi()

  return {
    async listProductHistory(productId, query = {}): Promise<EntityListResult<ProductHistoryRow>> {
      const kind: StockHistoryKind = query.type ?? 'stock_in'
      const response = await api.get<unknown>(ApiEndpoints.PRODUCT_HISTORY(productId), {
        query: {
          // Backend expects snake_case movement kinds.
          type: kind,
          q: query.q,
          start_date: query.startDate,
          end_date: query.endDate,
          page: query.page,
          limit: query.limit,
        },
        requestKey: `product-history:${productId}`,
        cancelPrevious: true,
      })
      const rows = unwrap<Record<string, unknown>[]>(response)
      return {
        items: (Array.isArray(rows) ? rows : []).map(row => adaptProductHistoryOut(row, kind)),
        meta: metaOf(response),
      }
    },

    async listProductCostHistory(productId, query = {}): Promise<EntityListResult<ProductCostHistoryRow>> {
      const response = await api.get<unknown>(ApiEndpoints.PRODUCT_COST_HISTORY(productId), {
        query: {
          q: query.q,
          start_date: query.startDate,
          end_date: query.endDate,
          page: query.page,
          limit: query.limit,
        },
        requestKey: `product-cost-history:${productId}`,
        cancelPrevious: true,
      })
      const rows = unwrap<Record<string, unknown>[]>(response)
      return {
        items: (Array.isArray(rows) ? rows : []).map(adaptCostHistoryOut),
        meta: metaOf(response),
      }
    },

    async getMovementInvoice(movementId): Promise<SaleReceipt | null> {
      try {
        const data = unwrap<Record<string, unknown>>(await api.get<unknown>(
          ApiEndpoints.MOVEMENT_INVOICE(movementId),
          { requestKey: `movement-invoice:${movementId}`, cancelPrevious: true },
        ))
        return adaptSaleReceiptOut(data, movementId)
      }
      catch {
        // Not a sale movement (or the invoice is gone) — nothing to show.
        return null
      }
    },
  }
}

export function createHttpFinanceRepository(): FinanceRepository {
  const api = useApi()

  return {
    /**
     * Maps the GET /api/v1/dashboard/summary payload (nested `cards`,
     * `chart`, `summary`, `extras` blocks) into the flat DashboardSummary
     * contract. Passes `period=custom` so the backend honors the requested
     * date range; without dates the backend defaults to the last 7 days.
     */
    async dashboard(startDate?: string, endDate?: string, requestKey = 'dashboard'): Promise<DashboardSummary> {
      const data = unwrap<Record<string, unknown>>(await api.get<unknown>(ApiEndpoints.DASHBOARD, {
        query: {
          period: startDate && endDate ? 'custom' : undefined,
          startDate,
          endDate,
        },
        requestKey,
        cancelPrevious: true,
      }))
      const cards = (data.cards ?? {}) as Record<string, unknown>
      const summary = (data.summary ?? {}) as Record<string, unknown>
      const extras = (data.extras ?? {}) as Record<string, unknown>
      const chart = (Array.isArray(data.chart) ? data.chart : []) as Array<Record<string, unknown>>
      const num = (value: unknown): number => Number(value ?? 0)
      const numOrNull = (value: unknown): number | null => (value === null || value === undefined ? null : Number(value))
      const day = (value: unknown): string => String(value ?? '').slice(0, 10)
      return {
        productsTotal: num(cards.total_products),
        lowStockCount: num(extras.low_stock_count),
        outOfStockCount: num(extras.out_of_stock_count),
        salesToday: num(cards.today_sales_count),
        salesTodayAmount: num(cards.today_sales),
        salesThisMonth: num(summary.sales_this_month_count),
        salesThisMonthAmount: num(summary.sales_this_month_amount),
        income: num(summary.total_income),
        expense: num(summary.total_expense),
        grossProfit: numOrNull(summary.gross_profit),
        netIncome: numOrNull(summary.net_income),
        customerDebt: num(summary.customer_debt),
        supplierDebt: num(summary.supplier_debt),
        damageLoss: num(summary.damage_loss),
        pendingDeliveryNotes: num(summary.pending_delivery_notes_count),
        salesByDay: chart.map(row => ({ date: day(row.date), count: num(row.sales_count) })),
        incomeByDay: chart.map(row => ({ date: day(row.date), amount: num(row.income) })),
        expenseByDay: chart.map(row => ({ date: day(row.date), amount: num(row.expense) })),
        startDate: data.period_start ? day(data.period_start) : startDate ?? null,
        endDate: data.period_end ? day(data.period_end) : endDate ?? null,
      }
    },
    async financeSummary(startDate?: string, endDate?: string): Promise<FinanceSummary> {
      // Canonical spec path GET /reports/finance; fall back to the /summary
      // alias for backends that still expose it.
      let data: Record<string, unknown>
      try {
        data = unwrap<Record<string, unknown>>(await api.get<unknown>(ApiEndpoints.FINANCE, {
          query: { startDate, endDate },
          requestKey: 'finance-summary',
          cancelPrevious: true,
          suppressErrorToast: true,
        }))
      }
      catch (error: unknown) {
        if ((error as { statusCode?: number })?.statusCode !== 404) throw error
        data = unwrap<Record<string, unknown>>(await api.get<unknown>(ApiEndpoints.FINANCE_SUMMARY, {
          query: { startDate, endDate },
          requestKey: 'finance-summary',
          cancelPrevious: true,
        }))
      }
      return {
        income: Number(data.income ?? data.total_income ?? 0),
        expense: Number(data.expense ?? data.total_expense ?? 0),
        net: Number(data.net ?? data.net_result ?? 0),
        outstanding: Number(data.outstanding ?? data.outstanding_debt ?? 0),
        startDate: (data.startDate ?? data.start_date ?? startDate) ? String(data.startDate ?? data.start_date ?? startDate).slice(0, 10) : null,
        endDate: (data.endDate ?? data.end_date ?? endDate) ? String(data.endDate ?? data.end_date ?? endDate).slice(0, 10) : null,
      }
    },
    async entries(startDate?: string, endDate?: string): Promise<FinanceEntry[]> {
      const data = unwrap<unknown[]>(await api.get<unknown>(ApiEndpoints.FINANCE_ENTRIES, {
        // The Finance page derives its Income/Expense/Net cards from these
        // rows, so load the whole period (backend caps at max_page_size=500)
        // instead of the default first page of 20.
        query: { startDate, endDate, limit: 500 },
        requestKey: 'finance-entries',
        cancelPrevious: true,
      }))
      return (Array.isArray(data) ? data : []).map(row => normalizeFinanceEntry(row as Record<string, unknown>))
    },
    async createExpense(input: Parameters<FinanceRepository['createExpense']>[0]): Promise<FinanceEntry> {
      const data = unwrap<Record<string, unknown>>(await api.post<unknown>(
        ApiEndpoints.FINANCE_EXPENSES,
        {
          date: input.date,
          category: input.category,
          description: input.description,
          amount: input.amount,
          payment_method: canonicalExpenseMethod(input.paymentMethod),
          reference: input.reference ?? null,
          currency: input.currency ?? 'USD',
          exchange_rate: input.exchangeRate ?? 1,
        },
      ))
      return normalizeFinanceEntry(data)
    },
  }
}

function normalizeFinanceEntry(row: Record<string, unknown>): FinanceEntry {
  const rawType = String(row.type ?? '').toLowerCase()
  return {
    id: String(row.id || ''),
    date: String(row.date || row.entry_date || '').slice(0, 10),
    type: rawType === 'expense' ? 'expense' : 'income',
    reference: String(row.reference || row.document_no || ''),
    category: String(row.category || ''),
    description: String(row.description || ''),
    amount: Number(row.amount || 0),
    paymentMethod: String(row.paymentMethod || row.payment_method || ''),
    currency: String(row.currency || 'USD'),
    exchangeRate: Number(row.exchange_rate ?? row.exchangeRate ?? 1),
    user: String(row.user || row.created_by_name || ''),
  }
}

export function createHttpSearchRepository(): SearchRepository {
  const api = useApi()

  return {
    async search(q: string, limit = 12): Promise<SearchHitItem[]> {
      const data = unwrap<{ hits?: SearchHitItem[], total?: number }>(await api.get<unknown>(ApiEndpoints.SEARCH, {
        query: { q, limit },
        requestKey: 'search-keyword',
        cancelPrevious: true,
      }))
      return (data?.hits || []).map(hit => ({
        id: String(hit.id),
        type: String(hit.type),
        title: String(hit.title),
        subtitle: hit.subtitle ?? null,
        url: String(hit.url),
      }))
    },
  }
}
