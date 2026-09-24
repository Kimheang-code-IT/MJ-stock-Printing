import type { PrintPaperSize } from '~/utils/print/html'
import { printSaleInvoice, saleReceiptPrintInput, type SaleInvoicePrintInput } from '~/utils/print/invoice'
import { usePosCommands, useSettingsRepositories } from '~/repositories/index'
import { apiErrorMessage, isApiErrorHandled } from '~/utils/api/errors'

/**
 * Shared "print sale invoice" flow for list screens (Sales Report, customer
 * history): a print action opens the A4/A5 chooser for one sale, then the
 * stored receipt snapshot is rendered and printed — in the sale's OWN
 * currency/rate, never re-converted at the shop's live rate.
 */
export function useSaleInvoicePrint() {
  const posCommands = usePosCommands()
  const { appInfo } = useSettingsRepositories()
  const { t } = useI18n()
  const toast = useToast()

  /** A4/A5 chooser visibility. */
  const open = ref(false)
  /** True while the receipt is fetched + printed — blocks duplicate picks. */
  const busy = ref(false)
  const saleId = ref('')

  /** Open the paper-size chooser for one sale row. */
  function request(id: unknown) {
    const value = String(id ?? '').trim()
    if (!value) return
    saleId.value = value
    open.value = true
  }

  function cancel() {
    open.value = false
    saleId.value = ''
  }

  /** Print the requested sale on the chosen paper size. */
  async function confirm(size: PrintPaperSize) {
    if (!saleId.value || busy.value) return
    busy.value = true
    try {
      const [receipt, info] = await Promise.all([
        posCommands.getSaleReceipt(saleId.value),
        appInfo.get().catch(() => null),
      ])
      const shopName = String(info?.businessName || info?.applicationName || '').trim() || 'MJ Printing'
      const input: SaleInvoicePrintInput = saleReceiptPrintInput(receipt, shopName)
      if (info) {
        input.logoUrl = String(info.branding?.mainLogoUrl || '').trim() || undefined
        input.businessName = shopName
        input.businessAddress = String(info.address || '').trim() || undefined
        input.businessPhone = String(info.supportPhone || '').trim() || undefined
      }
      await printSaleInvoice(input, size)
    }
    catch (error: unknown) {
      if (!isApiErrorHandled(error)) {
        toast.add({
          title: t('app.pos.printInvoiceFailed'),
          description: apiErrorMessage(error, t('app.pos.printInvoiceFailed')),
          color: 'error',
        })
      }
    }
    finally {
      busy.value = false
      open.value = false
      saleId.value = ''
    }
  }

  return { open, busy, request, confirm, cancel }
}
