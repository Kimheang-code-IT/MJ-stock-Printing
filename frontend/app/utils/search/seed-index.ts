import type { IndexedDocument } from '~/types/mj/search'
import {
  isSearchIndexSeeded,
  markSearchIndexSeeded,
  upsertIndexedDocuments,
} from '~/utils/search/search-index'

export function ensureSearchIndexSeeded() {
  if (!import.meta.client) return
  if (isSearchIndexSeeded()) return
  upsertIndexedDocuments([] as IndexedDocument[])
  markSearchIndexSeeded()
}
