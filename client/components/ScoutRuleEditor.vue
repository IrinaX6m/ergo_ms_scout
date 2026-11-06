<script setup>
import { computed } from 'vue'
import { Plus, Trash2 } from '@lucide/vue'
import FormCard from '@/components/FormCard.vue'
import FormField from '@/components/FormField.vue'
import SelectBox from '@/components/SelectBox.vue'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import { useAppI18n } from '@/i18n/useAppI18n.js'
import ScoutCrawlSettings from './ScoutCrawlSettings.vue'

const form = defineModel({ type: Object, required: true })
defineProps({
  errors: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
defineEmits(['add-field', 'remove-field'])
const { t } = useAppI18n()
const kinds = computed(() => ['css', 'xpath'].map((id) => ({ id, name: t(`scout.fields.${id}`) })))
const scopes = computed(() => [
  { id: 'page', name: t('scout.scopePage') },
  { id: 'record', name: t('scout.scopeRecord') },
])
</script>

<template>
  <fieldset class="scout-editor" :disabled="disabled">
    <legend class="visually-hidden">{{ t('scout.flow.rules') }}</legend>
    <FormCard>
      <FormField
        :label="t('scout.url')"
        label-for="scout-url"
        :error="errors.url"
        required
        :hint="t('scout.workspace.sourceHint')"
      >
        <input
          id="scout-url"
          v-model="form.url"
          class="form-control"
          type="url"
          autocomplete="url"
          :aria-invalid="!!errors.url"
          :aria-describedby="errors.url ? 'scout-url-error' : undefined"
        />
        <span v-if="errors.url" id="scout-url-error" class="visually-hidden">{{ errors.url }}</span>
      </FormField>
      <FormField :label="t('scout.flow.optionalTitle')" label-for="scout-title" last>
        <input
          id="scout-title"
          v-model="form.title"
          class="form-control"
          type="text"
          maxlength="200"
        />
      </FormField>
    </FormCard>

    <section class="scout-section" :aria-label="t('scout.flow.rules')">
      <div class="scout-section-heading">
        <h2 class="h5 mb-0">{{ t('scout.flow.rules') }}</h2>
      </div>
      <p class="scout-muted small">{{ t('scout.workspace.rulesHint') }}</p>
      <div v-for="(field, index) in form.fields" :key="index" class="scout-field-rule">
        <div class="scout-field-rule__main">
          <label class="scout-input-label" :for="`scout-name-${index}`">
            <span>{{ t('scout.fieldName') }}</span>
            <input
              :id="`scout-name-${index}`"
              v-model="field.name"
              class="form-control"
              type="text"
              :aria-invalid="!!errors.fields[index]"
              :aria-describedby="errors.fields[index] ? `scout-field-error-${index}` : undefined"
            />
          </label>
          <div class="scout-input-label">
            <span>{{ t('scout.fieldKind') }}</span>
            <SelectBox
              :id="`scout-kind-${index}`"
              v-model="field.kind"
              :options="kinds"
              value-key="id"
              label-key="name"
              :include-all-option="false"
              :disabled="disabled"
              :aria-label="t('scout.fieldKind')"
            />
          </div>
          <label class="scout-input-label" :for="`scout-selector-${index}`">
            <span>{{ t('scout.fieldSelector') }}</span>
            <input
              :id="`scout-selector-${index}`"
              v-model="field.selector"
              class="form-control scout-code"
              type="text"
              spellcheck="false"
              :aria-invalid="!!errors.fields[index]"
              :aria-describedby="errors.fields[index] ? `scout-field-error-${index}` : undefined"
            />
          </label>
          <button
            type="button"
            class="btn btn-outline-secondary scout-remove-field"
            :aria-label="t('scout.workspace.removeField', { number: index + 1 })"
            :disabled="disabled || form.fields.length === 1"
            @click="$emit('remove-field', index)"
          >
            <Trash2 :size="17" aria-hidden="true" />
          </button>
        </div>
        <div
          v-if="errors.fields[index]"
          :id="`scout-field-error-${index}`"
          class="text-danger small mt-2"
          role="alert"
        >
          {{ errors.fields[index] }}
        </div>
        <details class="scout-field-rule__options">
          <summary>{{ t('scout.workspace.fieldOptions') }}</summary>
          <div class="scout-field-options">
            <div v-if="form.recordMode === 'cards'" class="scout-input-label">
              <span>{{ t('scout.fieldScope') }}</span>
              <SelectBox
                :id="`scout-scope-${index}`"
                v-model="field.scope"
                :options="scopes"
                value-key="id"
                label-key="name"
                :include-all-option="false"
                :disabled="disabled"
                :aria-label="t('scout.fieldScope')"
              />
            </div>
            <div>
              <ToggleSwitch
                v-model="field.many"
                :label="t('scout.fieldMany')"
                :disabled="disabled"
              />
              <p class="scout-muted small mt-2 mb-0">{{ t('scout.flow.manyHint') }}</p>
            </div>
          </div>
        </details>
      </div>
      <button
        type="button"
        class="btn btn-outline-secondary btn-sm"
        :disabled="disabled"
        @click="$emit('add-field')"
      >
        <Plus :size="16" aria-hidden="true" />{{ t('scout.addField') }}
      </button>
    </section>

    <section class="scout-section" :aria-label="t('scout.workspace.recordUnit')">
      <h2 class="h5">{{ t('scout.workspace.recordUnit') }}</h2>
      <div class="scout-radio-group">
        <label for="scout-record-page"
          ><input
            id="scout-record-page"
            v-model="form.recordMode"
            type="radio"
            value="page"
            name="scout-record-mode"
          />
          {{ t('scout.flow.oneRecord') }}</label
        >
        <label for="scout-record-cards"
          ><input
            id="scout-record-cards"
            v-model="form.recordMode"
            type="radio"
            value="cards"
            name="scout-record-mode"
          />
          {{ t('scout.flow.manyCards') }}</label
        >
      </div>
      <FormCard v-if="form.recordMode === 'cards'" class="mt-3">
        <FormField
          :label="t('scout.recordSelector')"
          label-for="scout-record"
          :error="errors.card"
          :hint="t('scout.flow.cardRowHint')"
          last
        >
          <div class="scout-record-rule">
            <SelectBox
              id="scout-record-kind"
              v-model="form.recordKind"
              :options="kinds"
              value-key="id"
              label-key="name"
              :include-all-option="false"
              :disabled="disabled"
              :aria-label="t('scout.fieldKind')"
            />
            <input
              id="scout-record"
              v-model="form.recordSelector"
              class="form-control scout-code"
              type="text"
              :aria-invalid="!!errors.card"
            />
          </div>
        </FormField>
      </FormCard>
    </section>

    <details class="scout-section scout-crawl-editor">
      <summary>{{ t('scout.workspace.collectionBounds') }}</summary>
      <p class="scout-muted small mt-2">{{ t('scout.workspace.boundsHint') }}</p>
      <ScoutCrawlSettings
        v-model:mode="form.crawlMode"
        v-model:hosts="form.allowedHosts"
        v-model:visit="form.visitPrefix"
        v-model:extract="form.extractPrefix"
        v-model:depth="form.crawlDepth"
        v-model:pages="form.crawlPages"
        v-model:limits="form.crawlLimits"
        v-model:preview-url="form.previewUrl"
      />
    </details>
  </fieldset>
</template>
