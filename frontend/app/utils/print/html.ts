/** Escape user-facing values before inserting them into a print document. */
export function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** Print paper sizes offered by the POS invoice chooser (spec: A4 or A5). */
export type PrintPaperSize = 'A4' | 'A5'

/** Hidden-iframe dimensions per paper size (portrait). */
export const PRINT_IFRAME_SIZES: Record<PrintPaperSize, { width: string, height: string }> = {
  A4: { width: '210mm', height: '297mm' },
  A5: { width: '148mm', height: '210mm' },
}

/** Khmer-first stack so invoice Khmer (and Latin) use a Khmer font, not Arial. */
const PRINT_FONT_STACK = '"Khmer OS Content", "Khmer OS", "Noto Sans Khmer", "Hanuman", sans-serif'

/** Load Khmer fonts inside the print iframe (main app fonts are not inherited). */
export const PRINT_FONT_LINKS = `<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Khmer:wght@400;600;700&display=swap" rel="stylesheet">`

/**
 * Print paper metrics. There is **one** invoice style; A5 is the same style
 * scaled down (px metrics × scalePx) on a smaller printable area. Each size
 * also carries its own mm layout budget so filler rows are computed for that
 * exact paper — never one hardcoded row count for both.
 */
export const PAPER_STYLES: Record<PrintPaperSize, {
  page: 'A4' | 'A5'
  marginMm: number
  /** px metric scale (A5 keeps the A4 look, slightly smaller to stay legible). */
  scalePx: number
  /** Printable height after @page margins (mm). */
  printableMm: number
  /** Product/filler line-row height on paper (mm). */
  rowMm: number
  /** Estimated table-header row height (mm). */
  tableHeadMm: number
  /** Estimated title + customer/cashier meta block (mm). */
  headerMm: number
  /** Estimated totals + signatures block, kept together as one unit (mm). */
  footerMm: number
  /** Page-1 slack so rounding never spills the footer onto page 2 (mm). */
  safetyMm: number
}> = {
  // A4: 297mm page − 2 × 8mm margins. rowMm includes a little extra padding.
  A4: {
    page: 'A4',
    marginMm: 8,
    scalePx: 1,
    printableMm: 281,
    rowMm: 8.5,
    tableHeadMm: 14,
    headerMm: 90,
    footerMm: 82,
    safetyMm: 5,
  },
  // A5: 210mm page − 2 × 6mm margins. Independent budget from A4.
  A5: {
    page: 'A5',
    marginMm: 6,
    scalePx: 0.8,
    printableMm: 198,
    rowMm: 6.8,
    tableHeadMm: 11,
    headerMm: 63,
    footerMm: 58,
    safetyMm: 4,
  },
}

/** Base (A4-scale) invoice px metrics used by printPageCss. */
const BASE_PX = {
  font: 13,
  title: 20,
  meta: 16,
  padX: 3,
  padY: 3,
  signsTop: 24,
  signsGap: 24,
} as const

/**
 * Page CSS for a paper size. Shop-form invoice: underlined title, larger
 * meta, gray header, empty filler rows sized to the page-1 budget left after
 * the fixed blocks, totals aligned to Price | Amount (no top border
 * on summary cells).
 */
export function printPageCss(size: PrintPaperSize): string {
  const style = PAPER_STYLES[size]
  const px = (value: number) => `${Math.round(value * style.scalePx * 100) / 100}px`
  const pad = `${px(BASE_PX.padY)} ${px(BASE_PX.padX)}`
  return `
@page { size: ${style.page}; margin: ${style.marginMm}mm; }
html, body, table, th, td, p, span, strong {
  margin: 0;
  font-family: ${PRINT_FONT_STACK};
}
html, body {
  padding: 0;
  background: #fff;
  color: #000;
  font-size: ${px(BASE_PX.font)};
  line-height: 1.3;
  font-weight: 400;
}
.doc { width: 100%; }
.invoice-page {
  position: relative;
  box-sizing: border-box;
  width: 100%;
  height: ${style.printableMm}mm;
  overflow: hidden;
  break-after: page;
  page-break-after: always;
}
.invoice-page.last {
  break-after: auto;
  page-break-after: auto;
}
.page-number {
  position: absolute;
  top: 0;
  right: 0;
  font-size: ${px(BASE_PX.font - 2)};
  font-weight: 400;
}
/* Letterhead: equal side columns keep the company block truly centred even
   when a logo is present only on the left, like the supplied invoice form.
   A thin rule closes the header before the customer / invoice info block. */
.inv-letterhead {
  display: grid;
  grid-template-columns: 24% 52% 24%;
  align-items: center;
  height: ${px(108)};
  margin: ${px(8)} 0 ${px(12)};
  padding-bottom: ${px(8)};
  border-bottom: 1px solid #000;
}
.inv-logo {
  width: 100%;
  padding-right: ${px(10)};
}
.inv-logo img {
  display: block;
  width: 100%;
  max-height: ${px(108)};
  object-fit: contain;
  object-position: left center;
}
.inv-company {
  grid-column: 2;
  text-align: center;
}
.inv-company-name {
  font-size: ${px(BASE_PX.title + 6)};
  font-weight: 700;
  line-height: 1.25;
}
.inv-company-line {
  font-size: ${px(BASE_PX.font - 1)};
  line-height: 1.35;
}
/* Customer block (left) + invoice meta (right). */
.inv-info {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  margin: 0 ${px(2)} ${px(14)};
}
.inv-info-left {
  flex: 1 1 57%;
  font-size: ${px(BASE_PX.font)};
  line-height: 1.5;
}
.inv-info-right {
  flex: 0 1 41%;
  text-align: left;
  font-size: ${px(BASE_PX.font)};
  line-height: 1.5;
}
.inv-info p { margin: 0 0 2px; }
/* Field names read as the underlined captions on the supplied invoice form. */
.inv-label { font-weight: 400; text-decoration: underline; text-underline-offset: 2px; }
.inv-info strong { font-weight: 700; }
/* Invoice number is the one highlighted value on the form (red). */
.inv-no { color: #d81e26; }
.inv-title {
  font-size: ${px(BASE_PX.title - 1)};
  font-weight: 700;
  margin: 0 0 ${px(7)} !important;
  text-align: center;
}
.inv-title span { display: block; }
.inv-title span:last-child {
  margin-top: ${px(1)};
  font-size: ${px(BASE_PX.title - 3)};
  font-weight: 400;
  letter-spacing: 0.02em;
}
.title {
  text-align: center;
  font-size: ${px(BASE_PX.title)};
  font-weight: 700;
  margin: 0 0 10px;
  text-decoration: underline;
  text-underline-offset: 4px;
}
.meta {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
  font-size: ${px(BASE_PX.meta)};
  font-weight: 700;
}
.meta p {
  margin: 0 0 5px;
  font-weight: 700;
  font-size: ${px(BASE_PX.meta)};
  line-height: 1.45;
}
.meta strong { font-weight: 700; }
.meta .right { text-align: right; }
table { width: 100%; border-collapse: collapse; }
table.lines {
  table-layout: fixed;
  border: 0.5px solid #000;
}
/* Multi-page sales: repeat the header row and never split an item row. */
table.lines thead { display: table-header-group; }
table.lines tbody tr {
  /* Uniform line height for product AND filler rows so the layout budget
     (rowMm) matches what the printer renders. */
  height: ${style.rowMm}mm;
  page-break-inside: avoid;
  break-inside: avoid;
}
th, td {
  border: 0.5px solid #000;
  padding: ${pad};
  vertical-align: middle;
  font-weight: 400;
}
th {
  background: #e8e8e8;
  font-weight: 700;
  text-align: center;
  line-height: 1.2;
}
th.num { text-align: center; }
td.num { text-align: right; }
/* Unit / Qty / Price read centred on the product lines. */
td.center, th.center { text-align: center; }
td.product { text-align: center; font-weight: 600; word-wrap: break-word; overflow-wrap: anywhere; }
/* Product lines: slightly taller + bigger for easier reading, still compact
   enough that the page-1 budget holds many rows. */
table.lines th, table.lines td {
  padding: ${px(BASE_PX.padY + 3)} ${px(BASE_PX.padX)};
  font-size: ${px(BASE_PX.font + 1)};
}
table.lines thead th {
  padding: ${px(2)} ${px(BASE_PX.padX)};
  line-height: 1.15;
}
table.lines thead .head-en th {
  font-size: ${px(BASE_PX.font - 2)};
  font-family: Georgia, "Times New Roman", serif;
  font-weight: 400;
}
table.lines tbody td {
  border-top: 0;
  border-bottom: 0;
  vertical-align: top;
}
table.lines tbody tr:first-child td { padding-top: ${px(5)}; }
tr.empty.stretch td {
  padding: 0;
  vertical-align: top;
}
.num { white-space: nowrap; }
.col-no { width: 4.5%; }
.col-product { width: 46.5%; }
.col-height { width: 6.5%; }
.col-width { width: 6.5%; }
.col-area { width: 6.5%; }
.col-qty { width: 6.5%; }
.col-price { width: 8%; }
.col-amount { width: 15%; }
/* Totals + signatures are one atomic block: never split, never orphaned
   onto an extra page. Short sales keep them on page 1 (filler rows reserve
   the space); long sales push the whole block to the last page. */
.doc-footer {
  break-inside: avoid;
  page-break-inside: avoid;
}
.totals { margin: 0; width: 100%; }
/* Reference totals box: right-aligned label/amount grid under the lines. */
table.inv-summary {
  width: 25%;
  table-layout: fixed;
  border-collapse: collapse;
}
.inv-footer-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0;
}
.inv-thanks {
  flex: 1;
  padding: ${px(18)} ${px(26)} 0;
  font-size: ${px(BASE_PX.font)};
  line-height: 1.55;
}
.inv-thanks p:first-child { font-weight: 700; }
table.inv-summary td {
  padding: ${pad};
  vertical-align: middle;
  border: 0.5px solid #000;
}
table.inv-summary td.label { text-align: left; font-weight: 400; }
table.inv-summary td.num { text-align: right; white-space: nowrap; }
table.inv-summary tr.grand td.label {
  font-weight: 700;
  border-top: 0.5px solid #000;
}
table.inv-summary tr.grand td.label span { margin-right: 8px; }
table.inv-summary tr.grand td.label strong { float: right; }
.signs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: ${px(BASE_PX.signsGap)};
  width: 55%;
  margin-top: ${px(BASE_PX.signsTop + 66)};
  text-align: center;
}
.signs .sign { min-width: 0; }
.signs .line {
  border-top: 0.5px solid #000;
  margin: 28px auto 6px;
  width: 85%;
}
.signs p { margin: 0; font-weight: 700; }
.note { margin-top: 8px; }
`
}

/**
 * Print a standalone HTML document from a hidden iframe.
 * Modal/page print CSS cannot see Teleport/dialog content, which produced a blank preview.
 * The OS print dialog still appears — browsers do not allow silent printing from a website.
 */
export function printHtmlDocument(
  html: string,
  title = 'Print',
  options?: { paperSize?: PrintPaperSize, css?: string },
): Promise<void> {
  return new Promise((resolve) => {
    if (typeof document === 'undefined') {
      resolve()
      return
    }

    const paperSize = options?.paperSize ?? 'A4'
    const iframeSize = PRINT_IFRAME_SIZES[paperSize]
    const iframe = document.createElement('iframe')
    iframe.setAttribute('title', title)
    iframe.setAttribute('aria-hidden', 'true')
    Object.assign(iframe.style, {
      position: 'fixed',
      left: '-10000px',
      top: '0',
      width: iframeSize.width,
      height: iframeSize.height,
      border: '0',
      pointerEvents: 'none',
    })
    document.body.appendChild(iframe)

    const frameWindow = iframe.contentWindow
    const frameDoc = iframe.contentDocument || frameWindow?.document
    if (!frameWindow || !frameDoc) {
      iframe.remove()
      resolve()
      return
    }

    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      window.setTimeout(() => iframe.remove(), 500)
      resolve()
    }

    frameWindow.addEventListener('afterprint', finish, { once: true })
    frameDoc.open()
    frameDoc.write(`<!DOCTYPE html>
<html lang="km">
<head>
  <meta charset="utf-8">
  <title>${escapeHtml(title)}</title>
  ${PRINT_FONT_LINKS}
  <style>${options?.css ?? printPageCss(paperSize)}</style>
</head>
<body>${html}</body>
</html>`)
    frameDoc.close()

    const trigger = () => {
      try {
        frameWindow.focus()
        // Most browsers block until the OS print dialog closes; iframe
        // `afterprint` is unreliable, so resolve as soon as print() returns.
        frameWindow.print()
      }
      catch {
        // ignore — still finish below
      }
      finish()
      // Non-blocking print() engines: short fallback if neither return nor afterprint ran.
      window.setTimeout(finish, 2000)
    }

    const startPrint = () => {
      const fonts = frameDoc.fonts
      if (fonts?.ready) {
        void fonts.ready.then(() => window.setTimeout(trigger, 50)).catch(() => window.setTimeout(trigger, 80))
        return
      }
      window.setTimeout(trigger, 80)
    }

    if (frameDoc.readyState === 'complete') startPrint()
    else iframe.addEventListener('load', startPrint, { once: true })
  })
}
