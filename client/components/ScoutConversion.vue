<script setup>
import { useId, watch, computed } from 'vue'
import { useAppI18n } from '@/i18n/useAppI18n.js'
const field = defineModel({ type: Object, required: true })
defineProps({ disabled: Boolean })
const uid = useId()
const { t } = useAppI18n()
watch(
  () => field.value.many,
  (many) => {
    if (many) delete field.value.conversion
  },
  { immediate: true },
)
const kind = computed({
  get: () => field.value.conversion?.type || '',
  set: (type) => {
    if (!type) delete field.value.conversion
    else
      field.value.conversion =
        type === 'money'
          ? { type, currency: 'RUB', decimal_separator: ',' }
          : type === 'date'
            ? { type, format: 'DD.MM.YYYY' }
            : { type }
  },
})
</script>
<template>
  <div>
    <label class="scout-input-label" :for="`${uid}-1`"
      >{{ t('scout.product.conversion')
      }}<select
        :id="`${uid}-1`"
        :aria-label="t('scout.product.conversion')"
        v-model="kind"
        class="form-select"
        :disabled="disabled || field.many"
      >
        <option value="">{{ t('scout.product.text') }}</option>
        <option v-for="type in ['money', 'integer', 'date']" :key="type" :value="type">
          {{ t(`scout.product.${type}`) }}
        </option>
      </select></label
    ><template v-if="kind === 'money'"
      ><label class="scout-input-label" :for="`${uid}-2`"
        >{{ t('scout.product.currency')
        }}<input
          :id="`${uid}-2`"
          :aria-label="t('scout.product.currency')"
          :value="field.conversion.currency"
          readonly
          class="form-control"
          :disabled="disabled" /></label
      ><label class="scout-input-label" :for="`${uid}-3`"
        >{{ t('scout.product.decimal')
        }}<select
          :id="`${uid}-3`"
          :aria-label="t('scout.product.decimal')"
          v-model="field.conversion.decimal_separator"
          class="form-select"
          :disabled="disabled"
        >
          <option value=",">,</option>
          <option value=".">.</option>
        </select></label
      ></template
    ><label v-if="kind === 'date'" class="scout-input-label" :for="`${uid}-4`"
      >{{ t('scout.product.format')
      }}<input
        :id="`${uid}-4`"
        :aria-label="t('scout.product.format')"
        :value="field.conversion.format"
        readonly
        class="form-control"
        :disabled="disabled"
    /></label>
  </div>
</template>
