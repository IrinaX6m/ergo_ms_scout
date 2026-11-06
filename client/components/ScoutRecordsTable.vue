<script setup>
import { computed, ref, watch } from 'vue'
import { X } from '@lucide/vue'
import DataTable from '@/components/DataTable.vue'
import { useRouteQueryState } from '@/composables/useRouteQueryState.js'
import { useAppI18n } from '@/i18n/useAppI18n.js'
import { displayValue } from '../js/recordTable.js'

const props = defineProps({
  records: { type: Array, default: () => [] },
  preview: { type: Boolean, default: false },
})
const { t } = useAppI18n()
const selected = ref(null)
const { state: query, patchState } = useRouteQueryState(
  { page: { default: 1, type: 'number' } },
  { preserveKeys: ['job', 'run', 'mode'] },
)
const page = computed({
  get: () =>
    Math.max(1, Math.min(Number(query.value.page) || 1, Math.ceil(props.records.length / 10) || 1)),
  set: (value) => patchState({ page: value }),
})
const items = computed(() =>
  props.records.map((record, index) => ({ key: record.public_id || index, record })),
)
const columns = computed(() =>
  [...new Set(props.records.flatMap((record) => Object.keys(record.values || {})))].map((key) => ({
    key,
    label: key,
  })),
)
const evidence = computed(() =>
  (selected.value?.record.evidence || []).filter(
    (item) => item.field_path === selected.value?.field,
  ),
)
watch(
  () => props.preview,
  () => {
    selected.value = null
    patchState({ page: 1 })
  },
)

function selectCell(item, field) {
  selected.value = { record: item.record, field }
}
</script>

<template>
  <div class="scout-records">
    <DataTable
      v-model:current-page="page"
      :items="items"
      :columns="columns"
      :get-item-key="(item) => item.key"
      :empty-text="t('scout.empty')"
      :enable-pagination="!preview"
      :items-per-page="10"
    >
      <template v-for="column in columns" :key="column.key" #[`cell-${column.key}`]="{ item }">
        <button
          type="button"
          class="scout-value"
          :aria-label="
            t('scout.workspace.valueOrigin', {
              field: column.label,
              value: displayValue(item.record.values?.[column.key], t('scout.flow.notFound')),
            })
          "
          @click="selectCell(item, column.key)"
        >
          {{ displayValue(item.record.values?.[column.key], t('scout.flow.notFound')) }}
        </button>
      </template>
    </DataTable>
    <section
      v-if="selected"
      class="scout-evidence"
      :aria-label="t('scout.flow.evidence')"
      aria-live="polite"
    >
      <div class="scout-section-heading">
        <h3 class="h6 mb-0">{{ t('scout.flow.evidence') }}: {{ selected.field }}</h3>
        <button
          type="button"
          class="btn btn-sm btn-outline-secondary"
          :aria-label="t('scout.workspace.closeEvidence')"
          @click="selected = null"
        >
          <X :size="16" aria-hidden="true" />
        </button>
      </div>
      <dl v-for="(item, index) in evidence" :key="index" class="scout-plan mt-3">
        <div>
          <dt>{{ t('scout.url') }}</dt>
          <dd>
            {{ item.source_url || selected.record.source_url || t('scout.workspace.notSpecified') }}
          </dd>
        </div>
        <div>
          <dt>{{ t('scout.fieldSelector') }}</dt>
          <dd>
            <code>{{ item.locator || t('scout.workspace.notSpecified') }}</code>
          </dd>
        </div>
        <div>
          <dt>{{ t('scout.workspace.rawValue') }}</dt>
          <dd>{{ item.raw_value ?? t('scout.flow.notFound') }}</dd>
        </div>
      </dl>
      <p v-if="!evidence.length" class="scout-muted small mt-2 mb-0">
        {{ t('scout.workspace.noEvidence') }}
      </p>
    </section>
  </div>
</template>
