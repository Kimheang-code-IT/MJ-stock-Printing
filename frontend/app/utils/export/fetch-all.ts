/** Largest page the report endpoints accept (backend `max_page_size`). */
export const EXPORT_FETCH_PAGE_SIZE = 500

/** Upper bound on exported rows (mirrors the backend `EXPORT_ROW_LIMIT`). */
export const EXPORT_FETCH_MAX_ROWS = 20000

export interface FetchAllPage<T> {
  items: T[]
  total: number | null
}

/**
 * Collect every row matching a list query by paging through the API.
 *
 * Report exports must cover ALL matching documents, not just the first page
 * cached on screen, so callers pass a page fetcher and this walks it until the
 * reported total (or the hard row cap) is reached.
 */
export async function fetchAllListRows<T>(
  fetchPage: (query: { page: number, limit: number }) => Promise<FetchAllPage<T>>,
  options: { pageSize?: number, maxRows?: number } = {},
): Promise<T[]> {
  const pageSize = Math.max(1, options.pageSize ?? EXPORT_FETCH_PAGE_SIZE)
  const maxRows = Math.max(1, options.maxRows ?? EXPORT_FETCH_MAX_ROWS)
  const rows: T[] = []
  let page = 1
  let total = Number.POSITIVE_INFINITY

  while (rows.length < Math.min(total, maxRows)) {
    const result = await fetchPage({ page, limit: pageSize })
    rows.push(...result.items)
    total = Number(result.total ?? rows.length)
    // An empty page means we have walked past the end; stop to avoid a loop.
    if (!result.items.length) break
    page += 1
  }

  return rows.slice(0, maxRows)
}
