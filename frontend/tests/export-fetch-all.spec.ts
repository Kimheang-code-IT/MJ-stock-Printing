import { describe, expect, it, vi } from 'vitest'
import { fetchAllListRows } from '../app/utils/export/fetch-all'

describe('fetchAllListRows', () => {
  it('pages until the reported total is collected', async () => {
    const dataset = Array.from({ length: 1200 }, (_, i) => ({ id: i }))
    const fetchPage = vi.fn(async ({ page, limit }: { page: number, limit: number }) => ({
      items: dataset.slice((page - 1) * limit, (page - 1) * limit + limit),
      total: dataset.length,
    }))

    const rows = await fetchAllListRows(fetchPage, { pageSize: 500 })
    expect(rows).toHaveLength(1200)
    expect(fetchPage).toHaveBeenCalledTimes(3)
    expect(rows[0]).toEqual({ id: 0 })
    expect(rows[1199]).toEqual({ id: 1199 })
  })

  it('never exceeds the hard row cap', async () => {
    const fetchPage = vi.fn(async ({ page, limit }: { page: number, limit: number }) => ({
      items: Array.from({ length: limit }, (_, i) => ({ id: (page - 1) * limit + i })),
      total: 1000,
    }))

    const rows = await fetchAllListRows(fetchPage, { pageSize: 10, maxRows: 12 })
    expect(rows).toHaveLength(12)
    expect(rows[11]).toEqual({ id: 11 })
  })

  it('stops on an empty page even when the total is unknown', async () => {
    const fetchPage = vi.fn(async () => ({ items: [], total: null }))
    const rows = await fetchAllListRows(fetchPage)
    expect(rows).toEqual([])
    expect(fetchPage).toHaveBeenCalledTimes(1)
  })
})
