<script setup>
import { Braces, Check, MousePointer2, Sparkles } from '@lucide/vue'
import { useAppI18n } from '@/i18n/useAppI18n.js'

const mode = defineModel({ type: String, default: 'manual' })
defineProps({ disabled: { type: Boolean, default: false } })
const { t } = useAppI18n()
const modes = [
  { id: 'manual', icon: Braces },
  { id: 'visual', icon: MousePointer2 },
  { id: 'ai', icon: Sparkles },
]
</script>

<template>
  <div class="scout-modes" :aria-label="t('scout.workspace.modeLabel')">
    <button
      v-for="(item, index) in modes"
      :key="item.id"
      type="button"
      class="scout-mode"
      :class="{ 'scout-mode--selected': mode === item.id }"
      :aria-pressed="mode === item.id"
      :disabled="disabled"
      @click="mode = item.id"
    >
      <span class="scout-mode__icon"
        ><component :is="item.icon" :size="21" aria-hidden="true"
      /></span>
      <span class="scout-mode__copy">
        <span class="scout-mode__title">{{ t(`scout.workspace.modes.${item.id}.title`) }}</span>
        <span class="scout-mode__description">{{
          t(`scout.workspace.modes.${item.id}.description`)
        }}</span>
        <span v-if="item.id !== 'manual'" class="scout-availability">{{
          t('scout.workspace.notAvailable')
        }}</span>
      </span>
      <Check v-if="mode === item.id" :size="18" class="scout-mode__check" aria-hidden="true" />
      <span v-else class="scout-mode__number" aria-hidden="true">{{ index + 1 }}</span>
    </button>
  </div>
</template>
