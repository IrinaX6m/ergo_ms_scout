<script setup>
import { useAppI18n } from '@/i18n/useAppI18n.js'
import messages from '../js/retentionLocales.js'
defineProps({ problem: { type: Object, default: null } })
const { t } = useAppI18n()
</script>
<template>
  <div v-if="problem" class="alert alert-warning" role="alert">
    <p class="mb-0">
      {{
        t(
          `scout.retention.errors.${Object.hasOwn(messages.ru.errors, problem.key) ? problem.key : 'requestFailed'}`,
        )
      }}
    </p>
    <p v-if="problem.detail" class="small mb-0">{{ problem.detail }}</p>
  </div>
</template>
