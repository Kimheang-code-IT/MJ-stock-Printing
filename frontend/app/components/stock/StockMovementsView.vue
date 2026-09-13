<script setup lang="ts">
/**
 * Stock Movements workspace body, reused by the Stock page's Movements tab
 * and the direct /stock/movements route. Kept as a named component so the
 * Stock page can mount it after the tab strip.
 */
defineOptions({ name: 'StockMovementsView' })
</script>

<template>
  <ModuleWorkspaceView />
</template>