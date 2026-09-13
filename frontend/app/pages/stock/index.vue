<script setup lang="ts">
// The Stock module now lives at /stock/products; keep the legacy path
// working as a redirect (bookmarks, cached links).
definePageMeta({
  middleware: [
    () => navigateTo('/stock/products', { replace: true }),
  ],
})
</script>

<template>
  <div />
</template>
