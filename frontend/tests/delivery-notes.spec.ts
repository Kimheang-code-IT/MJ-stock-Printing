import { describe, expect, it } from 'vitest'
import { createMockDeliveryRepository } from './support/repositories-mock/delivery'
import { createMockPosRepository } from './support/repositories-mock/entities'
import { mockRecords } from './support/mocks/db'
import {
  DELIVERY_STATUSES,
  canTransitionDelivery,
  deliverableLines,
  deliveryItemCount,
  isDeliveryEditable,
  saleHasDeliverableLines,
  saleItemReservedQty,
} from '../app/utils/delivery/notes'

/** Complete a fresh 3-unit sale so the tests own its full deliverable quantity. */
async function freshSale() {
  const pos = createMockPosRepository()
  const product = mockRecords('products')[0]!
  const sale = await pos.completeSale({
    customerId: null,
    customerName: null,
    items: [{ productId: String(product.id), quantity: 3 }],
    paymentMethod: 'Cash',
    paidAmount: Number(product.salePrice) * 3,
  })
  const items = Array.isArray(sale.items) ? sale.items : []
  return { sale, saleItem: items[0] as Record<string, unknown>, productId: String(product.id) }
}

describe('delivery note status rules', () => {
  it('exposes the simplified Processing/Completed statuses', () => {
    expect(DELIVERY_STATUSES).toEqual(['Processing', 'Completed'])
  })

  it('allows only the Processing → Completed / Cancelled flow', () => {
    // Processing → Completed|Cancelled; Completed/Cancelled are terminal.
    const processing = { id: 'n1', status: 'Processing' }
    expect(canTransitionDelivery(processing, 'deliver')).toBe(true)
    expect(canTransitionDelivery(processing, 'cancel')).toBe(true)
    expect(canTransitionDelivery(processing, 'confirm')).toBe(false)

    // Backend enum dialects collapse onto the same simplified statuses.
    expect(canTransitionDelivery({ id: 'n1', status: 'PREPARING' }, 'deliver')).toBe(true)
    expect(canTransitionDelivery({ id: 'n1', status: 'OUT_FOR_DELIVERY' }, 'deliver')).toBe(true)

    // Completed / Cancelled (and their backend enums) are terminal.
    for (const status of ['Completed', 'Cancelled', 'DELIVERED', 'RETURNED']) {
      const terminal = { id: 'n1', status }
      expect(canTransitionDelivery(terminal, 'deliver')).toBe(false)
      expect(canTransitionDelivery(terminal, 'cancel')).toBe(false)
    }
  })

  it('completes directly from Processing', async () => {
    const { sale, saleItem, productId } = await freshSale()
    const commands = createMockDeliveryRepository()
    const movementsBefore = mockRecords('stockMovements').length

    const note = await commands.createDeliveryNote({
      saleId: String(sale.id),
      lines: [{ saleItemId: String(saleItem.id), productId, qtyToDeliver: 3 }],
    })
    expect(note.status).toBe('Processing')

    const delivered = await commands.setDeliveryStatus(String(note.id), 'deliver')
    expect(delivered.status).toBe('Completed')
    expect(delivered.deliveredAt).toBeTruthy()
    // Delivery never mutates stock.
    expect(mockRecords('stockMovements')).toHaveLength(movementsBefore)
  })

  it('treats only processing notes as editable', () => {
    expect(isDeliveryEditable({ id: 'n1', status: 'Processing' })).toBe(true)
    expect(isDeliveryEditable({ id: 'n1', status: 'PENDING' })).toBe(true)
    expect(isDeliveryEditable({ id: 'n1', status: 'Completed' })).toBe(false)
  })
})

describe('deliverable quantity pool per sale line', () => {
  it('reserves across non-cancelled notes and releases cancelled ones', () => {
    const sale = { id: 's1', items: [{ id: 'line1', quantity: 5 }] }
    const notes = [
      { id: 'dn1', saleId: 's1', status: 'Confirmed', items: [{ saleItemId: 'line1', qtyToDeliver: 2 }] },
      { id: 'dn2', saleId: 's1', status: 'Delivered', items: [{ saleItemId: 'line1', qtyToDeliver: 1 }] },
      // Cancelled notes release their reserved quantity.
      { id: 'dn3', saleId: 's1', status: 'Cancelled', items: [{ saleItemId: 'line1', qtyToDeliver: 10 }] },
      // Other sale lines and sales must not leak into the pool.
      { id: 'dn4', saleId: 's2', status: 'Confirmed', items: [{ saleItemId: 'line1', qtyToDeliver: 10 }] },
    ]
    expect(saleItemReservedQty('s1', 'line1', notes)).toBe(3)
    expect(saleItemReservedQty('s1', 'line1', notes, 'dn1')).toBe(1)
    const lines = deliverableLines(sale, notes)
    expect(lines[0]).toMatchObject({ qtyOrdered: 5, qtyReserved: 3, qtyRemaining: 2 })
    expect(saleHasDeliverableLines(sale, notes)).toBe(true)

    const exhausted = deliverableLines(
      { id: 's1', items: [{ id: 'line1', quantity: 3 }] },
      notes.slice(0, 2),
    )
    expect(exhausted[0]?.qtyRemaining).toBe(0)
    expect(saleHasDeliverableLines({ id: 's1', items: [{ id: 'line1', quantity: 3 }] }, notes.slice(0, 2))).toBe(false)
  })

  it('counts lines for the list column', () => {
    expect(deliveryItemCount({ id: 'n1', status: 'Draft', items: [{}, {}] })).toBe(2)
    expect(deliveryItemCount({ id: 'n1', status: 'Draft' })).toBe(0)
  })
})

describe('mock delivery commands', () => {
  it('creates a partial delivery note with DN sequence, audit entry and no stock movement', async () => {
    const { sale, saleItem, productId } = await freshSale()
    const commands = createMockDeliveryRepository()
    const movementsBefore = mockRecords('stockMovements').length
    const auditBefore = mockRecords('auditLogs').length
    const notesBefore = mockRecords('deliveryNotes').length

    const note = await commands.createDeliveryNote({
      saleId: String(sale.id),
      deliveryName: 'Test Receiver',
      deliveryPhone: '012345678',
      deliveryAddress: 'Phnom Penh',
      scheduledDate: '2030-01-01',
      confirm: true,
      lines: [{ saleItemId: String(saleItem.id), productId, qtyToDeliver: 2 }],
    })

    expect(String(note.deliveryNo)).toMatch(/^DN-\d{6}$/)
    expect(note.status).toBe('Processing')
    expect(String(note.invoiceNo || note.saleNo)).toBe(String(sale.invoiceNo || sale.saleNo))
    expect(note.items).toHaveLength(1)
    expect(mockRecords('deliveryNotes')).toHaveLength(notesBefore + 1)
    // No second stock-out: delivery never touches stock movements.
    expect(mockRecords('stockMovements')).toHaveLength(movementsBefore)
    expect(mockRecords('auditLogs')).toHaveLength(auditBefore + 1)
  })

  it('enforces remaining quantity per sale line and allows multiple partial notes', async () => {
    const { sale, saleItem, productId } = await freshSale()
    const commands = createMockDeliveryRepository()

    // 2 of 3 reserved by the first note.
    const first = await commands.createDeliveryNote({
      saleId: String(sale.id),
      lines: [{ saleItemId: String(saleItem.id), productId, qtyToDeliver: 2 }],
    })

    // Partial delivery: the last unit still fits a second note.
    const second = await commands.createDeliveryNote({
      saleId: String(sale.id),
      lines: [{ saleItemId: String(saleItem.id), productId, qtyToDeliver: 1 }],
    })
    expect(second.id).not.toBe(first.id)

    // Pool exhausted — over-delivery must be rejected.
    await expect(commands.createDeliveryNote({
      saleId: String(sale.id),
      lines: [{ saleItemId: String(saleItem.id), productId, qtyToDeliver: 1 }],
    })).rejects.toThrow(/remaining/i)
  })

  it('releases reserved quantities back when a note is cancelled', async () => {
    const { sale, saleItem, productId } = await freshSale()
    const commands = createMockDeliveryRepository()

    const note = await commands.createDeliveryNote({
      saleId: String(sale.id),
      lines: [{ saleItemId: String(saleItem.id), productId, qtyToDeliver: 3 }],
    })
    const notes = mockRecords('deliveryNotes')
    const saleId = String(sale.id)
    const lineId = String(saleItem.id)
    expect(saleItemReservedQty(saleId, lineId, notes)).toBe(3)
    expect(saleHasDeliverableLines(sale, notes)).toBe(false)

    await commands.setDeliveryStatus(String(note.id), 'cancel', 'Customer changed address')
    expect(saleItemReservedQty(saleId, lineId, mockRecords('deliveryNotes'))).toBe(0)
    expect(saleHasDeliverableLines(sale, mockRecords('deliveryNotes'))).toBe(true)
  })

  it('walks Processing → Completed and freezes quantities', async () => {
    const { sale, saleItem, productId } = await freshSale()
    const commands = createMockDeliveryRepository()

    const note = await commands.createDeliveryNote({
      saleId: String(sale.id),
      lines: [{ saleItemId: String(saleItem.id), productId, qtyToDeliver: 2 }],
    })
    expect(note.status).toBe('Processing')

    const id = String(note.id)
    // Legacy verb aliases are still accepted and collapse to the same statuses.
    await commands.setDeliveryStatus(id, 'confirm')
    await commands.setDeliveryStatus(id, 'out_for_delivery')
    const delivered = await commands.setDeliveryStatus(id, 'deliver')
    expect(delivered.status).toBe('Completed')
    expect(delivered.deliveredAt).toBeTruthy()
    expect((delivered.items as Array<{ qtyDelivered: number }>)[0]!.qtyDelivered).toBe(2)

    // Delivered is terminal.
    await expect(commands.setDeliveryStatus(id, 'cancel', 'late')).rejects.toThrow(/cannot move/i)
  })

  it('requires a reason to cancel', async () => {
    const { sale, saleItem, productId } = await freshSale()
    const commands = createMockDeliveryRepository()
    const note = await commands.createDeliveryNote({
      saleId: String(sale.id),
      lines: [{ saleItemId: String(saleItem.id), productId, qtyToDeliver: 1 }],
    })
    await expect(commands.setDeliveryStatus(String(note.id), 'cancel', '')).rejects.toThrow(/reason/i)
    await expect(commands.setDeliveryStatus(String(note.id), 'cancel', '   ')).rejects.toThrow(/reason/i)
  })
})
