import { describe, expect, it } from 'vitest'
import {
  applyListTableSort,
  compareListTableValues,
  deriveListTableSortOptions,
  listTablePageSummary,
  listTableSelectedIds,
  listTableVirtualize,
} from '../app/utils/table/list-table'

const t = (key: string, values?: Record<string, unknown>) => {
  if (key === 'app.ui.ofZero') return '0 of 0'
  if (key === 'app.ui.of') return `${values?.shown} of ${values?.total}`
  return key
}

describe('list table helpers', () => {
  it('summarizes the visible page', () => {
    expect(listTablePageSummary(t, 0, { pageIndex: 0, pageSize: 20 })).toBe('0 of 0')
    expect(listTablePageSummary(t, 6, { pageIndex: 0, pageSize: 20 })).toBe('6 of 6')
    expect(listTablePageSummary(t, 45, { pageIndex: 1, pageSize: 20 })).toBe('20 of 45')
  })

  it('lists selected row ids', () => {
    expect(listTableSelectedIds({ a: true, b: false, c: true })).toEqual(['a', 'c'])
  })

  it('virtualizes only large lists', () => {
    expect(listTableVirtualize(10, 20)).toBe(false)
    expect(listTableVirtualize(200, 20)).toMatchObject({ estimateSize: 48, overscan: 12 })
  })
})

describe('list table sorting', () => {
  const rows = [
    { id: '1', date: '2026-02-01', saleNo: 'INV-00010' },
    { id: '2', date: '2026-01-01', saleNo: 'INV-00002' },
    { id: '3', date: '2026-03-01', saleNo: 'INV-0001' },
  ]

  it('derives the first date + document-number columns', () => {
    expect(deriveListTableSortOptions([
      { accessorKey: 'saleNo' },
      { accessorKey: 'date' },
      { accessorKey: 'total' },
    ])).toEqual([
      { key: 'date', kind: 'date' },
      { key: 'saleNo', kind: 'number' },
    ])
  })

  it('ignores hidden (__) and label/action columns', () => {
    expect(deriveListTableSortOptions([
      { id: 'select' },
      { accessorKey: '__no' },
      { accessorKey: 'name' },
      { id: 'actions' },
    ])).toEqual([])
  })

  it('sorts dates old → new and new → old', () => {
    const asc = applyListTableSort(rows, { key: 'date', dir: 'asc', kind: 'date' })
    expect(asc.map(row => row.id)).toEqual(['2', '1', '3'])
    const desc = applyListTableSort(rows, { key: 'date', dir: 'desc', kind: 'date' })
    expect(desc.map(row => row.id)).toEqual(['3', '1', '2'])
  })

  it('sorts document numbers naturally (small → large / large → small)', () => {
    const asc = applyListTableSort(rows, { key: 'saleNo', dir: 'asc', kind: 'number' })
    expect(asc.map(row => row.saleNo)).toEqual(['INV-0001', 'INV-00002', 'INV-00010'])
    const desc = applyListTableSort(rows, { key: 'saleNo', dir: 'desc', kind: 'number' })
    expect(desc.map(row => row.saleNo)).toEqual(['INV-00010', 'INV-00002', 'INV-0001'])
  })

  it('keeps the original order when no sort is set and does not mutate input', () => {
    const source = [...rows]
    expect(applyListTableSort(source, null)).toBe(source)
    applyListTableSort(source, { key: 'date', dir: 'asc', kind: 'date' })
    expect(source.map(row => row.id)).toEqual(['1', '2', '3'])
  })

  it('compares mixed values without throwing', () => {
    expect(compareListTableValues(undefined, undefined, 'text')).toBe(0)
    expect(compareListTableValues('b', 'a', 'text')).toBeGreaterThan(0)
  })
})
