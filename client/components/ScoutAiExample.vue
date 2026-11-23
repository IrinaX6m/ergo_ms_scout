<script setup>
import { useId, computed, ref, watch } from 'vue'
import { useAppI18n } from '@/i18n/useAppI18n.js'
import { useVisualSnapshot } from '../js/useVisualSnapshot.js'
const page = defineModel({ type: Object, required: true })
const props = defineProps({ proxyRevision: String, disabled: Boolean, multiple: Boolean })
const emit = defineEmits(['remove'])
const uid = useId()
const { t } = useAppI18n()
const enabled = ref(true)
const { snapshot, status, error, load } = useVisualSnapshot(
  computed(() => page.value.url),
  enabled,
  computed(() => ({ proxy_profile_revision_public_id: props.proxyRevision || null })),
)
watch([snapshot, status], () => {
  page.value.snapshotId = status.value === 'ready' ? snapshot.value?.public_id : ''
})
</script>
<template>
  <fieldset :disabled="disabled" class="scout-field-rule">
    <label class="scout-input-label" :for="`${uid}-1`"
      >{{ t('scout.product.pageUrl')
      }}<input
        :id="`${uid}-1`"
        :aria-label="t('scout.product.pageUrl')"
        v-model="page.url"
        type="url"
        class="form-control" /></label
    ><template v-if="multiple"
      ><label class="scout-input-label" :for="`${uid}-2`"
        >{{ t('scout.product.typeId')
        }}<input
          :id="`${uid}-2`"
          :aria-label="t('scout.product.typeId')"
          v-model="page.id"
          class="form-control" /></label
      ><label class="scout-input-label" :for="`${uid}-3`"
        >{{ t('scout.product.pattern')
        }}<input
          :id="`${uid}-3`"
          :aria-label="t('scout.product.pattern')"
          v-model="page.pattern"
          class="form-control" /></label
      ><label class="scout-input-label" :for="`${uid}-4`"
        >{{ t('scout.product.pageAction')
        }}<select
          :id="`${uid}-4`"
          :aria-label="t('scout.product.pageAction')"
          v-model="page.action"
          class="form-select"
        >
          <option value="extract">{{ t('scout.product.extract') }}</option>
          <option value="discover">{{ t('scout.product.discover') }}</option>
        </select></label
      ></template
    >
    <div class="scout-actions mt-2">
      <button
        type="button"
        class="btn btn-outline-secondary"
        :disabled="status === 'loading'"
        @click="load"
      >
        {{ t('scout.visual.load') }}</button
      ><button
        v-if="multiple"
        type="button"
        class="btn btn-outline-secondary"
        @click="emit('remove')"
      >
        {{ t('scout.product.remove') }}
      </button>
    </div>
    <p v-if="status === 'loading'" role="status">{{ t('scout.visual.loading') }}</p>
    <p v-if="status === 'ready'" role="status">{{ t('scout.visual.snapshotTitle') }} ✓</p>
    <p v-if="error" class="scout-warning" role="alert">
      {{ t(`scout.visual.${error.key}`) }} {{ error.detail }}
    </p>
  </fieldset>
</template>
