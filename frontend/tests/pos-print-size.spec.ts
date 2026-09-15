import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { usePosPrintSizeDialog } from '../app/composables/pos/usePosPrintSizeDialog'

type Payload = { invoiceNo: string }
type Size = 'A4' | 'A5'

interface Deferred {
  promise: Promise<void>
  resolve: () => void
}

function deferred(): Deferred {
  let resolve!: () => void
  const promise = new Promise<void>((res) => { resolve = res })
  return { promise, resolve }
}

describe('usePosPrintSizeDialog (POS post-sale invoice chooser)', () => {
  it('A4 → prints once → dialog closes and completed-sale state clears', async () => {
    const print = vi.fn<(payload: Payload, size: Size) => void>()
    const onClose = vi.fn()
    const dialog = usePosPrintSizeDialog<Payload, Size>({ print, onClose })

    dialog.requestPrint({ invoiceNo: 'INV-A4' })
    expect(dialog.open.value).toBe(true)
    expect(dialog.printing.value).toBe(false)

    await dialog.confirm('A4')

    expect(print).toHaveBeenCalledTimes(1)
    expect(print).toHaveBeenCalledWith({ invoiceNo: 'INV-A4' }, 'A4')
    expect(dialog.open.value).toBe(false)
    expect(dialog.printing.value).toBe(false)
    expect(onClose).toHaveBeenCalledWith(true)
  })

  it('A5 → prints once → dialog closes', async () => {
    const print = vi.fn<(payload: Payload, size: Size) => void>()
    const onClose = vi.fn()
    const dialog = usePosPrintSizeDialog<Payload, Size>({ print, onClose })

    dialog.requestPrint({ invoiceNo: 'INV-A5' })
    await dialog.confirm('A5')

    expect(print).toHaveBeenCalledTimes(1)
    expect(print).toHaveBeenCalledWith({ invoiceNo: 'INV-A5' }, 'A5')
    expect(dialog.open.value).toBe(false)
    expect(onClose).toHaveBeenCalledWith(true)
  })

  it('Cancel → closes without printing and never re-submits', async () => {
    const print = vi.fn()
    const onClose = vi.fn()
    const dialog = usePosPrintSizeDialog<Payload, Size>({ print, onClose })

    dialog.requestPrint({ invoiceNo: 'INV-CANCEL' })
    dialog.cancel()
    await nextTick()

    expect(print).not.toHaveBeenCalled()
    expect(dialog.open.value).toBe(false)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith(false)
  })

  it('X close (model → false) closes without printing', async () => {
    const print = vi.fn()
    const onClose = vi.fn()
    const dialog = usePosPrintSizeDialog<Payload, Size>({ print, onClose })

    dialog.requestPrint({ invoiceNo: 'INV-X' })
    // The dialog's X / Esc / overlay only flips the model to false.
    dialog.open.value = false
    await nextTick()

    expect(print).not.toHaveBeenCalled()
    expect(dialog.open.value).toBe(false)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith(false)
  })

  it('cart can start a new sale after the chooser closes', async () => {
    const print = vi.fn<(payload: Payload, size: Size) => void>()
    const onClose = vi.fn()
    const dialog = usePosPrintSizeDialog<Payload, Size>({ print, onClose })

    dialog.requestPrint({ invoiceNo: 'INV-1' })
    await dialog.confirm('A4')
    expect(dialog.open.value).toBe(false)
    expect(dialog.printing.value).toBe(false)
    expect(onClose).toHaveBeenLastCalledWith(true)

    // Second sale: a fresh payload opens the chooser again.
    dialog.requestPrint({ invoiceNo: 'INV-2' })
    expect(dialog.open.value).toBe(true)
    await dialog.confirm('A5')

    expect(print).toHaveBeenCalledTimes(2)
    expect(print).toHaveBeenLastCalledWith({ invoiceNo: 'INV-2' }, 'A5')
  })

  it('ignores duplicate A4/A5 clicks while a print is in flight', async () => {
    const gate = deferred()
    const print = vi.fn<(payload: Payload, size: Size) => Promise<void>>(() => gate.promise)
    const onClose = vi.fn()
    const dialog = usePosPrintSizeDialog<Payload, Size>({ print, onClose })

    dialog.requestPrint({ invoiceNo: 'INV-BUSY' })
    const first = dialog.confirm('A4')
    expect(dialog.printing.value).toBe(true)
    expect(dialog.open.value).toBe(false)

    await dialog.confirm('A5')
    dialog.cancel()
    expect(print).toHaveBeenCalledTimes(1)

    gate.resolve()
    await first
    expect(print).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith(true)
  })

  it('closes and clears state even when printing throws', async () => {
    const print = vi.fn(() => { throw new Error('printer offline') })
    const onClose = vi.fn()
    const dialog = usePosPrintSizeDialog<Payload, Size>({ print, onClose })

    dialog.requestPrint({ invoiceNo: 'INV-ERR' })
    await expect(dialog.confirm('A4')).rejects.toThrow('printer offline')

    expect(dialog.open.value).toBe(false)
    expect(dialog.printing.value).toBe(false)
    expect(onClose).toHaveBeenCalledWith(true)
  })
})
