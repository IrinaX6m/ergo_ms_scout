<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { apiClient } from '@/js/api/manager'
import { useAppI18n } from '@/i18n/useAppI18n.js'
import ScoutAiExample from './ScoutAiExample.vue'
import ScoutPlanSummary from './ScoutPlanSummary.vue'
const form = defineModel({ type: Object, required: true })
defineProps({ disabled: Boolean })
const emit = defineEmits(['apply', 'manual'])
const { t } = useAppI18n()
let nextKey = 1
const pages = ref([
  {
    key: nextKey++,
    url: form.value.url,
    snapshotId: '',
    id: 'catalog',
    action: 'extract',
    pattern: '/',
  },
])
const busy = ref(false),
  error = ref(''),
  suggestion = ref(null)
let generation = 0,
  request = 0
const stamp = computed(() =>
  JSON.stringify({ pages: pages.value, goal: form.value.aiGoal, proxy: form.value.proxyRevision }),
)
watch(
  stamp,
  () => {
    generation++
    suggestion.value = null
    error.value = ''
  },
  { flush: 'sync' },
)
watch(
  () => form.value.proxyRevision,
  () => {
    pages.value.forEach((page) => {
      page.snapshotId = ''
    })
  },
  { flush: 'sync' },
)
watch(
  () => pages.value[0]?.url,
  (url) => {
    if (url) form.value.url = url
  },
)
onUnmounted(() => {
  generation++
  request++
})
async function suggest() {
  if (busy.value || pages.value.some((page) => !page.snapshotId) || !form.value.aiGoal.trim())
    return
  const owner = generation,
    token = ++request
  busy.value = true
  error.value = ''
  suggestion.value = null
  const examples = pages.value.map((page) => ({
    snapshot_public_id: page.snapshotId,
    id: page.id,
    action: page.action,
    match: [{ kind: 'prefix', pattern: page.pattern }],
  }))
  try {
    const response = await apiClient.post(
      'scout/plan-suggestions/',
      {
        goal: form.value.aiGoal.trim(),
        ...(examples.length === 1
          ? { snapshot_public_id: examples[0].snapshot_public_id }
          : { pages: examples }),
      },
      true,
      { quietStatuses: [400, 403, 404, 409, 422, 429, 500, 502, 503] },
    )
    if (owner !== generation || token !== request) return
    if (response.success && response.data.draft?.fields?.length)
      suggestion.value = response.data.draft
    else error.value = response.data?.detail || response.message || t('scout.product.failed')
  } catch {
    if (owner === generation && token === request) error.value = t('scout.product.failed')
  } finally {
    if (token === request) busy.value = false
  }
}
function addPage() {
  pages.value.push({
    key: nextKey++,
    url: '',
    snapshotId: '',
    id: `type_${nextKey}`,
    action: 'extract',
    pattern: '/',
  })
}
</script>
<template>
  <section class="scout-section">
    <h2 class="h5">{{ t('scout.product.sourcePages') }}</h2>
    <p class="scout-muted">{{ t('scout.product.aiHint') }}</p>
    <ScoutAiExample
      v-for="(page, index) in pages"
      :key="page.key"
      v-model="pages[index]"
      :proxy-revision="form.proxyRevision"
      :disabled="disabled || busy"
      :multiple="pages.length > 1"
      @remove="pages.splice(index, 1)"
    /><button
      type="button"
      class="btn btn-outline-secondary"
      :disabled="disabled || busy || pages.length >= 5"
      @click="addPage"
    >
      {{ t('scout.product.addPage') }}</button
    ><label class="scout-input-label mt-3" for="scout-goal"
      >{{ t('scout.product.goal')
      }}<textarea
        id="scout-goal"
        v-model="form.aiGoal"
        class="form-control"
        rows="4"
        maxlength="2000"
        :disabled="disabled || busy"
      />
    </label>
    <p v-if="error" class="alert alert-warning" role="alert">{{ error }}</p>
    <div class="scout-actions mt-3">
      <button
        type="button"
        class="btn btn-outline-secondary"
        :disabled="disabled || busy"
        @click="emit('manual')"
      >
        {{ t('scout.workspace.useManual') }}</button
      ><button
        type="button"
        class="btn btn-primary"
        :disabled="
          disabled || busy || !form.aiGoal?.trim() || pages.some((page) => !page.snapshotId)
        "
        @click="suggest"
      >
        {{ t(busy ? 'scout.product.suggesting' : 'scout.product.suggest') }}
      </button>
    </div>
    <section v-if="suggestion" class="mt-3">
      <ScoutPlanSummary :plan="suggestion" mode="ai" expanded /><button
        type="button"
        class="btn btn-primary"
        :disabled="disabled"
        @click="emit('apply', suggestion)"
      >
        {{ t('scout.product.applySuggestion') }}
      </button>
    </section>
    <p v-else class="small scout-muted">{{ t('scout.product.noSuggestion') }}</p>
  </section>
</template>
