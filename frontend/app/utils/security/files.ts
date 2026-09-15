export const SAFE_RASTER_IMAGE_TYPES = [
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
] as const

export const SAFE_RASTER_IMAGE_ACCEPT = SAFE_RASTER_IMAGE_TYPES.join(',')

export function isSafeRasterImage(file: Pick<File, 'type' | 'size'>, maxSizeMb: number): boolean {
  return SAFE_RASTER_IMAGE_TYPES.includes(file.type as (typeof SAFE_RASTER_IMAGE_TYPES)[number])
    && file.size <= maxSizeMb * 1024 * 1024
}
