import type { InjectionKey } from 'vue'
import type {
  DocumentFieldSchema,
  DocumentSectionSchema,
  DocumentTabSchema,
  FieldOption,
  FieldType,
} from '~/types/mj/common'
import type {
  ModuleField,
  ModuleFieldType,
  ModuleConfig,
  ModuleTable,
} from '~/config/modules'
import { CollectionEndpoints } from '~/utils/constants/api-endpoints'

/** Resolve a module field's reference collection to its `/options` endpoint. */
export function collectionOptionsEndpoint(collection?: string): string | undefined {
  if (!collection) return undefined
  const endpoint = (CollectionEndpoints as Record<string, string | undefined>)[collection]
  return endpoint ? `${endpoint}/options` : undefined
}

export const RELATED_FIELD_KEY = '__related'

export const moduleDocumentLineActionKey: InjectionKey<
  (action: 'view', row: Record<string, unknown>) => void
> = Symbol('moduleDocumentLineAction')

export const moduleDocumentRecordKey: InjectionKey<{
  get: (key: string) => unknown
  /** Optional setter so tab components can write record fields (e.g. the
   *  Pricing tab base-row sale price → `salePrice`). */
  set?: (key: string, value: unknown) => void
}> = Symbol('moduleDocumentRecord')

/** Per-field validation messages, provided by the document page and read by
 *  `AppDynamicFieldRenderer` to show errors inline on the field (not a toast). */
export const moduleDocumentFieldErrorsKey: InjectionKey<{
  get: (key: string) => string | undefined
}> = Symbol('moduleDocumentFieldErrors')

const TYPE_MAP: Record<ModuleFieldType, FieldType> = {
  text: 'text',
  date: 'date',
  datetime: 'datetime',
  number: 'number',
  select: 'select',
  multiselect: 'multiselect',
  textarea: 'textarea',
  file: 'file',
  image: 'image',
  password: 'secret',
  checkbox: 'boolean',
}

export type ModuleDocumentTabsOptions = {
  isCreate?: boolean
  includeRelated?: boolean
  compact?: boolean
  readOnlyKeys?: string[]
}

export function moduleSelectOptions(
  options?: ModuleField['options'],
): FieldOption[] | undefined {
  if (!options?.length) return undefined
  return [...options].map((item) => {
    if (item && typeof item === 'object' && 'value' in item) {
      return { label: String(item.label ?? item.value), value: String(item.value) }
    }
    const value = String(item)
    return { label: value, value }
  })
}

export function moduleFieldToDocumentField(
  field: ModuleField,
  extra: Partial<DocumentFieldSchema> = {},
): DocumentFieldSchema {
  const type = extra.type || TYPE_MAP[field.type || 'text'] || 'text'
  const options = extra.options || moduleSelectOptions(field.options)
  const checkboxPair = (field.type === 'checkbox' || type === 'boolean') && options && options.length >= 1
    ? {
        trueValue: options[0]!.value,
        ...(options[1] ? { falseValue: options[1].value } : {}),
      }
    : undefined
  const meta = {
    ...checkboxPair,
    ...extra.meta,
  }
  return {
    labelKey: field.labelKey || `app.fields.${field.key}`,
    label: field.label,
    required: field.required,
    colSpan: field.colSpan,
    help: field.help,
    helpKey: field.helpKey,
    rows: type === 'textarea' ? 4 : undefined,
    ...extra,
    key: field.key,
    type,
    options: type === 'boolean' ? extra.options : options,
    optionsEndpoint: field.optionsEndpoint || collectionOptionsEndpoint(field.optionsCollection),
    readOnly: Boolean(field.computed || extra.readOnly),
    meta: Object.keys(meta).length ? meta : extra.meta,
  }
}

function visibleTables(module: ModuleConfig, isCreate?: boolean): ModuleTable[] {
  if (!module.tables?.length) return []
  if (isCreate && module.hideTablesOnCreate) return []
  return module.tables
}

export function lineTableField(
  table: ModuleTable,
  options: ModuleDocumentTabsOptions = {},
): DocumentFieldSchema {
  return {
    key: table.key,
    labelKey: `app.tables.${table.key}`,
    label: table.title,
    type: 'line-table',
    colSpan: 2,
    meta: {
      table,
      compact: options.compact,
    },
  }
}

function relatedField(): DocumentFieldSchema {
  return {
    key: RELATED_FIELD_KEY,
    labelKey: 'app.ui.related',
    type: 'related-records',
    colSpan: 2,
  }
}

function relatedTab(): DocumentTabSchema {
  return {
    id: 'related',
    labelKey: 'app.ui.related',
    sections: [{ id: 'related', fields: [relatedField()] }],
  }
}

function visibleModuleFields(fields: ModuleField[], options: ModuleDocumentTabsOptions): ModuleField[] {
  return fields.filter((field) => {
    if (options.isCreate && field.hideOnCreate) return false
    if (!options.isCreate && field.createOnly) return false
    return true
  })
}

function mapFields(
  fields: ModuleField[],
  readOnlyKeys?: string[],
  options: ModuleDocumentTabsOptions = {},
): DocumentFieldSchema[] {
  return visibleModuleFields(fields, options).map(field => moduleFieldToDocumentField(field, {
    readOnly: readOnlyKeys?.includes(field.key) || undefined,
  }))
}

function i18nSlug(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'general'
}

function groupedFields(fields: ModuleField[]) {
  const groups: Array<{ title: string, titleKm?: string, fields: ModuleField[] }> = []
  for (const field of fields) {
    const title = field.section || 'General'
    const current = groups.find(group => group.title === title)
    if (current) current.fields.push(field)
    else groups.push({ title, titleKm: field.sectionKm, fields: [field] })
  }
  return groups
}

function fieldsToSections(
  fields: ModuleField[],
  readOnlyKeys?: string[],
  options: ModuleDocumentTabsOptions = {},
): DocumentSectionSchema[] {
  const visible = visibleModuleFields(fields, options)
  return groupedFields(visible).map(group => ({
    id: i18nSlug(group.title),
    titleKey: `app.sections.${i18nSlug(group.title)}`,
    title: group.title,
    fields: mapFields(group.fields, readOnlyKeys, options),
  })).filter(section => section.fields.length > 0)
}

function tableTab(table: ModuleTable, options: ModuleDocumentTabsOptions): DocumentTabSchema {
  return {
    id: table.key,
    labelKey: `app.tables.${table.key}`,
    label: table.title,
    sections: [{
      id: table.key,
      fields: [lineTableField(table, options)],
    }],
  }
}

function rolesTabs(module: ModuleConfig, options: ModuleDocumentTabsOptions): DocumentTabSchema[] {
  return [{
    id: 'general',
    labelKey: 'app.sections.general',
    sections: [
      {
        id: 'main',
        titleKey: 'core.sections.main',
        fields: mapFields(module.fields, options.readOnlyKeys, options),
      },
      {
        id: 'permissions',
        titleKey: 'core.sections.permissions',
        fields: [{
          key: 'permissionRows',
          labelKey: 'core.sections.permissions',
          type: 'permission-matrix',
          colSpan: 2,
        }],
      },
    ],
  }]
}

function recipeTabs(module: ModuleConfig, options: ModuleDocumentTabsOptions): DocumentTabSchema[] | null {
  if (module.documentForm === 'roles') return rolesTabs(module, options)
  if (module.documentForm === 'product') return productTabs(module, options)
  if (module.documentForm === 'party') return partyTabs(module, options)
  return null
}

/**
 * Customer / Supplier form tabs (spec §2.1.8 / §4): exactly **General**
 * (editable master data) and **History** (read-only party-scoped purchase /
 * sales history). Create mode keeps only General.
 */
function partyTabs(module: ModuleConfig, options: ModuleDocumentTabsOptions): DocumentTabSchema[] {
  const general: DocumentTabSchema = {
    id: 'general',
    labelKey: 'app.sections.general',
    sections: fieldsToSections(module.fields, options.readOnlyKeys, options),
  }
  if (options.isCreate) return [general]

  const supplier = module.collection === 'suppliers'
  const kind = supplier ? 'supplier' : 'customer'
  const historyType: FieldType = supplier ? 'party-purchase-history' : 'party-sales-history'

  return [
    general,
    {
      id: 'history',
      labelKey: 'app.party.tabs.history',
      sections: [{
        id: 'history',
        fields: [{
          key: '__record',
          labelKey: 'app.party.tabs.history',
          type: historyType,
          colSpan: 2,
          meta: { kind },
        }],
      }],
    },
  ]
}

/**
 * Product form tabs (spec §5.9): exactly **General** (identity fields + the
 * single editable sale price). Batch/expiry tracking and pricing history are no
 * longer part of the product document.
 *
 * Create mode keeps only the editable General inputs.
 */
function productTabs(module: ModuleConfig, options: ModuleDocumentTabsOptions): DocumentTabSchema[] {
  const generalSections: DocumentSectionSchema[] = [
    ...fieldsToSections(module.fields, options.readOnlyKeys, options),
    {
      id: 'sale-price',
      titleKey: 'app.modules.products.fields.salePrice',
      fields: [
        {
          key: 'salePrice',
          labelKey: 'app.modules.products.fields.salePrice',
          type: 'number',
          required: true,
          helpKey: 'app.stock.salePriceHint',
        },
      ],
    },
  ]

  return [
    {
      id: 'general',
      labelKey: 'app.stock.tabGeneral',
      label: 'General',
      sections: generalSections,
    },
  ]
}

function defaultTabs(module: ModuleConfig, options: ModuleDocumentTabsOptions): DocumentTabSchema[] {
  const tabs: DocumentTabSchema[] = [{
    id: 'details',
    labelKey: 'app.sections.details',
    sections: fieldsToSections(module.fields, options.readOnlyKeys, options),
  }]
  for (const table of visibleTables(module, options.isCreate)) {
    tabs.push(tableTab(table, options))
  }
  return tabs
}

function withoutLineTables(tabs: DocumentTabSchema[]): DocumentTabSchema[] {
  return tabs.filter(tab =>
    !tab.sections.some(section => section.fields.some(field => field.type === 'line-table')),
  )
}

function withRuntimeLineTables(
  tabs: DocumentTabSchema[],
  module: ModuleConfig,
  options: ModuleDocumentTabsOptions,
): DocumentTabSchema[] {
  return tabs.map(tab => ({
    ...tab,
    sections: tab.sections.map(section => ({
      ...section,
      fields: section.fields.map((field) => {
        if (field.type !== 'line-table') return field
        const table = module.tables?.find(item => item.key === field.key)
        return table ? lineTableField(table, options) : field
      }),
    })),
  }))
}

function withoutLifecycleStatus(tabs: DocumentTabSchema[]): DocumentTabSchema[] {
  return tabs
    .map(tab => ({
      ...tab,
      sections: tab.sections
        .map(section => ({
          ...section,
          fields: section.fields.filter(field => field.key !== 'status'),
        }))
        .filter(section => section.fields.length > 0),
    }))
    .filter(tab => tab.sections.length > 0)
}

export function moduleDocumentTabs(
  module: ModuleConfig,
  options: ModuleDocumentTabsOptions = {},
): DocumentTabSchema[] {
  let tabs: DocumentTabSchema[]
  if (module.tabs?.length) {
    tabs = withRuntimeLineTables(module.tabs, module, options)
  }
  else {
    tabs = recipeTabs(module, options) || defaultTabs(module, options)
  }
  if (options.isCreate && module.hideTablesOnCreate) tabs = withoutLineTables(tabs)
  if (options.includeRelated && module.related?.length && !tabs.some(tab => tab.id === 'related')) {
    tabs = [...tabs, relatedTab()]
  }
  return withoutLifecycleStatus(tabs)
}
