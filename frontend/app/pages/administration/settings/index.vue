<script setup lang="ts">
import SystemSettingsPage from '~/components/settings/SystemSettingsPage.vue'

definePageMeta({ titleKey: 'app.pages.settings', permission: 'settings.manage' })
</script>

<template>
  <SystemSettingsPage />
</template>
