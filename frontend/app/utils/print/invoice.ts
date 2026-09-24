import { formatMoney, formatNumber, formatDate, formatDateTime } from '~/utils/format/format-service'
import { cartTotal, lineAreaM2, lineNet, roundMoney, type PosCartLine } from '~/utils/pos/cart'
import { escapeHtml, PAPER_STYLES, printHtmlDocument, type PrintPaperSize } from '~/utils/print/html'
import type { SaleReceipt } from '~/repositories/contracts/entities'

export type SaleInvoicePrintLine = Pick<
  PosCartLine,
  'name' | 'quantity' | 'unitPrice' | 'height' | 'width' | 'areaM2'
>

export type SaleInvoicePrintInput = {
  shopName: string
  invoiceNo: string
  dateLabel: string
  customerName: string
  cashier: string
  currency: string
  lines: SaleInvoicePrintLine[]
  deliveryPrice: number
  /** Customer's open (unpaid) debt before this sale — printed as ខ្វះមុន. */
  previousDebtAmount: number
  /** Cash received at checkout (covers this sale + any settled previous debt). */
  depositAmount: number
  /** Amount still owed after this sale, including previous debt not settled now. */
  outstandingAmount: number
  /** Currency to render the printed document in (defaults to `currency`). */
  displayCurrency?: string
  /** Exchange rate as **1 USD = X KHR**; required when `displayCurrency` differs. */
  exchangeRate?: number
  /** Letterhead (App Info branding): logo, business name, address, phone. */
  logoUrl?: string
  businessName?: string
  businessAddress?: string
  businessPhone?: string
  /** Customer contact shown in the info block. */
  customerAddress?: string
  customerPhone?: string
  /** Free-text amount in words (printed as an empty line when omitted). */
  amountInWords?: string
}

/**
 * Print-currency choice made in the document print chooser: the paper
 * currency (USD/KHR, defaulting to the record currency) plus the exchange
 * rate applied when the print currency differs from the record currency.
 */
export type PrintCurrencyChoice = {
  currency: string
  exchangeRate?: number
}

/**
 * Format an amount for the printed document, converting between the record
 * currency and the print currency when they differ. Rate is always stated as
 * **1 USD = X KHR**; KHR amounts are rounded to whole riel (no decimals).
 */
function formatPrintMoney(
  value: unknown,
  recordCurrency: string,
  displayCurrency: string,
  exchangeRate: number,
): string {
  const amount = Number(value || 0)
  const converting = displayCurrency !== recordCurrency && exchangeRate > 0
  const converted = converting
    ? (displayCurrency === 'KHR' ? amount * exchangeRate : amount / exchangeRate)
    : amount
  const code = converting ? displayCurrency : recordCurrency
  if (code === 'KHR') {
    // Whole riel, symbol after the amount (1,019,000៛).
    return `${formatNumber(Math.round(converted), { maximumFractionDigits: 0 })}៛`
  }
  return formatMoney(converted, code)
}

function asCartLine(line: SaleInvoicePrintLine): PosCartLine {
  return {
    productId: '',
    imageUrl: null,
    availableStock: 0,
    ...line,
  }
}

/** Physical-sheet layout decision for an invoice, derived from the paper budget. */
export type InvoiceLayout = {
  paperSize: PrintPaperSize
  /** Actual product rows in the invoice. */
  productRows: number
  /** Rows (products + blank grid) that fit on the final page above the footer. */
  firstPageCapacity: number
  /** Blank grid-row budget on a one-page invoice (0 for multi-page invoices). */
  fillerRows: number
  /** Product-row capacity on pages that do not carry totals/signatures. */
  continuationPageCapacity: number
  /** Actual product rows assigned to each physical sheet. */
  pageRows: number[]
  /** Blank grid-row budget on each sheet. */
  pageFillerRows: number[]
  /** Estimated printed pages (>= 1). */
  pages: number
  /** True when product rows overflow past page 1. */
  multipage: boolean
}

/**
 * Decide the invoice layout for a paper size.
 *
 * The final-page budget is the printable height minus the header (title + meta),
 * the table header and the totals/signatures block, plus a small safety
 * margin. When the products fit that budget, the leftover space is filled with
 * blank grid area so the table reaches the footer — but never so much that the
 * footer is pushed to another sheet. Larger invoices are explicitly divided
 * into physical sheets; continuation sheets use the space otherwise reserved
 * for totals and signatures.
 */
export function planInvoiceLayout(
  productRows: number,
  paperSize: PrintPaperSize = 'A4',
): InvoiceLayout {
  const style = PAPER_STYLES[paperSize]
  const rows = Math.max(0, Math.floor(productRows))
  const reservedMm = style.headerMm + style.tableHeadMm + style.footerMm + style.safetyMm
  const bodyMm = Math.max(0, style.printableMm - reservedMm)
  const firstPageCapacity = Math.max(1, Math.floor(bodyMm / style.rowMm))
  const continuationPageCapacity = Math.max(
    1,
    Math.floor(
      (style.printableMm - style.headerMm - style.tableHeadMm - style.safetyMm)
      / style.rowMm,
    ),
  )

  if (rows <= firstPageCapacity) {
    return {
      paperSize,
      productRows: rows,
      firstPageCapacity,
      fillerRows: firstPageCapacity - rows,
      continuationPageCapacity,
      pageRows: [rows],
      pageFillerRows: [firstPageCapacity - rows],
      pages: 1,
      multipage: false,
    }
  }

  // Every physical sheet repeats the title/meta/table header. Only the final
  // one reserves space for totals and signatures. Find the smallest sheet
  // count that can hold every item without truncation (three sheets is a
  // normal supported outcome, not a hard limit).
  const pages = 1 + Math.ceil((rows - firstPageCapacity) / continuationPageCapacity)
  const pageRows: number[] = []
  let remaining = rows
  for (let index = 0; index < pages; index += 1) {
    const remainingPages = pages - index
    const capacity = index === pages - 1 ? firstPageCapacity : continuationPageCapacity
    const capacityAfter = remainingPages <= 1
      ? 0
      : ((remainingPages - 2) * continuationPageCapacity) + firstPageCapacity
    const balanced = Math.ceil(remaining / remainingPages)
    const requiredNow = Math.max(1, remaining - capacityAfter)
    const take = Math.min(capacity, Math.max(balanced, requiredNow))
    pageRows.push(take)
    remaining -= take
  }
  const pageFillerRows = pageRows.map((count, index) => {
    const capacity = index === pages - 1 ? firstPageCapacity : continuationPageCapacity
    return Math.max(0, capacity - count)
  })
  return {
    paperSize,
    productRows: rows,
    firstPageCapacity,
    fillerRows: 0,
    continuationPageCapacity,
    pageRows,
    pageFillerRows,
    pages,
    multipage: true,
  }
}

/**
 * One continuous blank grid row so unused paper keeps the photographed form
 * appearance without adding many horizontal lines. Its height represents the
 * unused row budget calculated by `planInvoiceLayout`.
 */
function emptyInvoiceRows(fillerRows: number, rowMm: number): string {
  if (fillerRows <= 0) return ''
  return `
    <tr class="empty stretch" data-filler-rows="${fillerRows}" style="height:${fillerRows * rowMm}mm">
      <td class="num">&nbsp;</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>`
}

/** Absolute URL for a logo asset so it resolves inside the print iframe. */
function absoluteAssetUrl(url?: string): string {
  const raw = String(url || '').trim()
  if (!raw) return ''
  if (/^(https?:|data:|blob:)/i.test(raw)) return raw
  if (typeof window !== 'undefined' && raw.startsWith('/')) return `${window.location.origin}${raw}`
  return raw
}

/** Positive dimension/area value for the invoice grid, else blank. */
function dimensionCell(value: unknown): string {
  const amount = Number(value)
  if (!Number.isFinite(amount) || amount <= 0) return ''
  return escapeHtml(formatNumber(amount, { maximumFractionDigits: 4 }))
}

/** KHR amount (whole riel, symbol after) for the grand-total row. */
function khrMoney(value: unknown): string {
  return escapeHtml(formatPrintMoney(value, 'KHR', 'KHR', 0))
}

/**
 * Build invoice HTML. Product rows are assigned to explicit physical sheets;
 * every sheet repeats the letterhead, the customer/invoice info block and the
 * table header, while only the last carries totals and signatures. This
 * prevents a short invoice from creating a blank page 2 and makes two/three
 * page invoices deterministic.
 */
export function buildSaleInvoiceHtml(
  input: SaleInvoicePrintInput,
  paperSize: PrintPaperSize = 'A4',
): string {
  const displayCurrency = input.displayCurrency || input.currency
  const exchangeRate = Number(input.exchangeRate || 0)
  const converting = displayCurrency !== input.currency && exchangeRate > 0
  const money = (value: unknown) => escapeHtml(formatPrintMoney(value, input.currency, displayCurrency, exchangeRate))
  const lines = input.lines.map(asCartLine)
  const subtotal = cartTotal(lines)
  // The checkout grand total includes delivery. Keep the printed invoice in
  // lockstep with the amount saved by POS instead of showing item lines only.
  const deliveryPrice = Math.max(0, Number(input.deliveryPrice || 0))
  const total = roundMoney(subtotal + deliveryPrice)
  const layout = planInvoiceLayout(lines.length, paperSize)

  const businessName = String(input.businessName || input.shopName || '').trim()
  // MJ Printing's supplied logo is the invoice default. App Info can still
  // override it, but an empty setting must never produce a blank letterhead
  // (especially on historical reprints that only carry the shop name).
  const logoUrl = absoluteAssetUrl(input.logoUrl || '/logo.png')
  const businessAddress = String(input.businessAddress || '').trim()
  const businessPhone = String(input.businessPhone || '').trim()
  const customerAddress = String(input.customerAddress || '').trim()
  const customerPhone = String(input.customerPhone || '').trim()
  // The reference form shows a USD total plus the equivalent grand total in
  // riel; that second line only exists when we know the USD→KHR rate.
  const showKhr = displayCurrency !== 'KHR' && exchangeRate > 0

  const letterhead = (logoUrl || businessName) ? `
  <div class="inv-letterhead">
    ${logoUrl ? `<div class="inv-logo"><img src="${escapeHtml(logoUrl)}" alt=""></div>` : ''}
    <div class="inv-company">
      ${businessName ? `<p class="inv-company-name">${escapeHtml(businessName)}</p>` : ''}
      ${businessAddress ? `<p class="inv-company-line">${escapeHtml(businessAddress)}</p>` : ''}
      ${businessPhone ? `<p class="inv-company-line">${escapeHtml(businessPhone)}</p>` : ''}
    </div>
  </div>` : ''

  const infoBlock = `
  <div class="inv-info">
    <div class="inv-info-left">
      <p><span class="inv-label">ឈ្មោះសហគ្រាស ឬអតិថិជន / Enterprise name/Customer</span> : <strong>${escapeHtml(input.customerName || '—')}</strong></p>
      <p><span class="inv-label">អាសយដ្ឋាន / Address</span> : <strong>${escapeHtml(customerAddress || '—')}</strong></p>
      <p><span class="inv-label">ទូរស័ព្ទលេខ / Telephone No</span> : <strong>${escapeHtml(customerPhone || '—')}</strong></p>
    </div>
    <div class="inv-info-right">
      <p class="inv-title"><span>វិក្កយបត្រ</span><span>INVOICE</span></p>
      <p><span class="inv-label">លេខវិក្កយបត្រ / Invoice No</span> : <strong class="inv-no">${escapeHtml(input.invoiceNo)}</strong></p>
      <p><span class="inv-label">កាលបរិច្ឆេទ / Date</span> : <strong>${escapeHtml(input.dateLabel)}</strong></p>
      <p><span class="inv-label">អ្នកលក់ / Seller</span> : <strong>${escapeHtml(input.cashier || '—')}</strong></p>
      <p><span class="inv-label">លុយ ជាអក្សរ / Amount in words</span> : <strong>${escapeHtml(input.amountInWords || '')}</strong></p>${converting ? `\n      <p><span class="inv-label">អត្រាប្តូរប្រាក់ / Exchange rate</span> : <strong>1 USD = ${escapeHtml(formatNumber(Math.round(exchangeRate)))} KHR</strong></p>` : ''}
    </div>
  </div>`

  const lineRows = (pageLines: PosCartLine[], offset: number) => pageLines.map((line, index) => {
    const area = line.areaM2 ?? lineAreaM2(line)
    return `
    <tr>
      <td class="num">${offset + index + 1}</td>
      <td class="product">${escapeHtml(line.name)}</td>
      <td class="num center">${dimensionCell(line.height)}</td>
      <td class="num center">${dimensionCell(line.width)}</td>
      <td class="num center">${area == null ? '' : dimensionCell(area)}</td>
      <td class="num center">${escapeHtml(line.quantity)}</td>
      <td class="num center">${money(line.unitPrice)}</td>
      <td class="num">${money(lineNet(line))}</td>
    </tr>`
  }).join('')

  const colgroup = `
    <colgroup>
      <col class="col-no">
      <col class="col-product">
      <col class="col-height">
      <col class="col-width">
      <col class="col-area">
      <col class="col-qty">
      <col class="col-price">
      <col class="col-amount">
    </colgroup>`

  let offset = 0
  const pages = layout.pageRows.map((rowCount, pageIndex) => {
    const pageLines = lines.slice(offset, offset + rowCount)
    const pageOffset = offset
    offset += rowCount
    const isLast = pageIndex === layout.pages - 1
    const pageLabel = layout.pages > 1
      ? `<p class="page-number">Page ${pageIndex + 1} / ${layout.pages}</p>`
      : ''
    const footer = !isLast ? '' : `
  <div class="doc-footer">
    <div class="inv-footer-row">
      <div class="inv-thanks">
        <p>សូមអរគុណចំពោះការគាំទ្រ!</p>
        <p>Thank you for your business!</p>
      </div>
      <table class="inv-summary">
        ${deliveryPrice > 0 ? `<tr><td class="label">សរុបរង / Subtotal</td><td class="num">${money(subtotal)}</td></tr>\n        <tr><td class="label">ថ្លៃដឹកជញ្ជូន / Delivery</td><td class="num">${money(deliveryPrice)}</td></tr>` : ''}
        <tr><td class="label">សរុប / Total (${escapeHtml(displayCurrency)})</td><td class="num">${money(total)}</td></tr>
        ${input.previousDebtAmount > 0 ? `<tr><td class="label">ខ្វះមុន / Previous debt</td><td class="num">${money(input.previousDebtAmount)}</td></tr>` : ''}
        <tr><td class="label">ប្រាក់កក់ / Deposit</td><td class="num">${money(input.depositAmount)}</td></tr>
        <tr><td class="label">សមតុល្យ / Balance</td><td class="num">${money(input.outstandingAmount)}</td></tr>
        ${showKhr ? `<tr class="grand"><td class="label" colspan="2"><span>សរុបជារៀល / Total in KHR</span><strong>${khrMoney(total * exchangeRate)}</strong></td></tr>` : ''}
      </table>
    </div>
    <div class="signs">
      <div class="sign">
        <div class="line"></div>
        <p>ហត្ថលេខា និងឈ្មោះ:អតិថិជន / Customer&#39;s Signature &amp; Name</p>
      </div>
      <div class="sign">
        <div class="line"></div>
        <p>ហត្ថលេខា និងឈ្មោះ:អ្នកលក់ / Seller&#39;s Signature &amp; Name</p>
      </div>
    </div>
  </div>`
    return `
<section class="invoice-page${isLast ? ' last' : ''}">
  ${pageLabel}
  ${letterhead}
  ${infoBlock}
  <table class="lines">
    ${colgroup}
    <thead>
      <tr class="head-km">
        <th class="center">ល.រ</th>
        <th>បរិយាយមុខទំនិញ ឬសេវាកម្ម</th>
        <th class="num center">កម្ពស់</th>
        <th class="num center">ទទឹង</th>
        <th class="num center">ម៉ែត្រ</th>
        <th class="num center">ចំនួន</th>
        <th class="num center">តម្លៃ/m²</th>
        <th class="num">ទឹកប្រាក់</th>
      </tr>
      <tr class="head-en">
        <th class="center">No</th>
        <th>Description of Goods or Services</th>
        <th class="num center">Height</th>
        <th class="num center">Width</th>
        <th class="num center">m</th>
        <th class="num center">Qty</th>
        <th class="num center">Price/m²</th>
        <th class="num">Amount</th>
      </tr>
    </thead>
    <tbody>${lineRows(pageLines, pageOffset)}${emptyInvoiceRows(layout.pageFillerRows[pageIndex] || 0, PAPER_STYLES[paperSize].rowMm)}</tbody>
  </table>
  ${footer}
</section>`
  }).join('')

  return `<article class="doc">${pages}</article>`
}

/** Print the invoice in the chosen paper size and print currency (POS chooser). */
export function printSaleInvoice(
  input: SaleInvoicePrintInput,
  paperSize: PrintPaperSize = 'A4',
  currencyChoice?: PrintCurrencyChoice,
): Promise<void> {
  const printInput: SaleInvoicePrintInput = currencyChoice
    ? { ...input, displayCurrency: currencyChoice.currency, exchangeRate: currencyChoice.exchangeRate }
    : input
  return printHtmlDocument(buildSaleInvoiceHtml(printInput, paperSize), printInput.invoiceNo || 'Invoice', { paperSize })
}

/**
 * Reprint input from a stored sale record (movement/history dialogs).
 * Uses the record's currency/exchange-rate snapshot — never the shop's live
 * rate — so historical reprints show the amounts as sold.
 */
export function saleInvoicePrintInputFromRecord(
  record: Record<string, unknown>,
  shopName: string,
): SaleInvoicePrintInput {
  const items = Array.isArray(record.items) ? record.items as Array<Record<string, unknown>> : []
  const currency = String(record.currency || 'USD')
  return {
    shopName,
    invoiceNo: String(record.invoiceNo ?? record.saleNo ?? ''),
    dateLabel: formatDateTime(record.date),
    customerName: String(record.customer ?? ''),
    cashier: String(record.cashier ?? ''),
    currency,
    // Stored snapshot: print in the sale's own currency/rate.
    displayCurrency: String(record.displayCurrency || currency),
    exchangeRate: Number(record.exchangeRate || 0) || undefined,
    lines: items.map(item => ({
      name: String(item.name ?? ''),
      quantity: Number(item.quantity || 0),
      unitPrice: Number(item.price ?? item.unitPrice ?? 0),
      height: Number(item.height || 0) || undefined,
      width: Number(item.width || 0) || undefined,
      areaM2: Number(item.areaM2 ?? item.area_m2 ?? 0) || undefined,
    })),
    deliveryPrice: Number(record.deliveryPrice ?? 0),
    previousDebtAmount: Number(record.previousDebtAmount ?? 0),
    depositAmount: Number(record.depositAmount ?? record.deposit ?? 0),
    outstandingAmount: Number(record.remaining ?? record.outstandingAmount ?? 0),
  }
}

/**
 * Reprint input from a sale receipt payload (GET receipt of a sale /
 * movement invoice). Same snapshot rule as `saleInvoicePrintInputFromRecord`.
 */
export function saleReceiptPrintInput(
  receipt: SaleReceipt,
  shopName: string,
): SaleInvoicePrintInput {
  return {
    shopName,
    invoiceNo: receipt.invoiceNo || receipt.saleNo,
    dateLabel: formatDate(receipt.date),
    customerName: receipt.customer,
    cashier: receipt.cashier,
    currency: receipt.currency || 'USD',
    displayCurrency: receipt.currency || 'USD',
    exchangeRate: Number(receipt.exchangeRate || 0) || undefined,
    lines: receipt.items.map(item => ({
      name: item.name,
      quantity: Number(item.quantity || 0),
      unitPrice: Number(item.unitPrice || 0),
      height: Number(item.height || 0) || undefined,
      width: Number(item.width || 0) || undefined,
      areaM2: Number(item.areaM2 ?? 0) || undefined,
    })),
    deliveryPrice: Number(receipt.deliveryPrice || 0),
    previousDebtAmount: 0,
    depositAmount: Number(receipt.deposit || 0),
    outstandingAmount: Number(receipt.remaining || 0),
  }
}
