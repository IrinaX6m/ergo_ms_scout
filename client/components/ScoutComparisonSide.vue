<script setup>
import { useAppI18n } from '@/i18n/useAppI18n.js'
import { displayValue } from '../js/recordTable.js'
import { safeEvidenceLink } from '../js/comparisonState.js'
import messages from '../js/comparisonLocales.js'
defineProps({ side: { type: Object, default: null }, title: { type: String, required: true } })
const { t } = useAppI18n()
function label(group, key) {
  return t(
    Object.hasOwn(messages.ru[group], key)
      ? `scout.comparison.${group}.${key}`
      : 'scout.comparison.unknown',
  )
}
</script>
<template>
  <section class="scout-comparison-side" :aria-label="title">
    <h4 class="h6">{{ title }}</h4>
    <p v-if="!side">{{ t('scout.comparison.noRecord') }}</p>
    <template v-else
      ><p class="scout-comparison-value">
        {{ displayValue(side.value, t('scout.comparison.missing')) }}
      </p>
      <p class="small">{{ t('scout.comparison.state') }}: {{ label('states', side.state) }}</p>
      <details>
        <summary>{{ t('scout.comparison.technical') }}</summary>
        <dl>
          <div>
            <dt>{{ t('scout.comparison.record') }}</dt>
            <dd>
              <code>{{ side.record_public_id }}</code>
            </dd>
          </div>
          <div>
            <dt>{{ t('scout.comparison.raw') }}</dt>
            <dd>{{ side.value?.raw ?? t('scout.comparison.missing') }}</dd>
          </div>
          <div>
            <dt>{{ t('scout.comparison.normalized') }}</dt>
            <dd>{{ side.value?.normalized ?? t('scout.comparison.missing') }}</dd>
          </div>
        </dl>
      </details>
      <details class="scout-comparison-evidence">
        <summary>{{ t('scout.comparison.evidence') }} · {{ side.evidence?.length || 0 }}</summary>
        <p class="small scout-muted">{{ t('scout.comparison.evidenceHint') }}</p>
        <p v-if="!side.evidence?.length">{{ t('scout.comparison.noEvidence') }}</p>
        <ol>
          <li v-for="(item, index) in side.evidence" :key="`${item.snapshot_public_id}-${index}`">
            <p v-if="typeof item.selected === 'boolean'" class="small">
              {{ t(item.selected ? 'scout.comparison.selected' : 'scout.comparison.additional') }}
            </p>
            <dl>
              <div>
                <dt>{{ t('scout.comparison.source') }}</dt>
                <dd>
                  <a
                    v-if="safeEvidenceLink(item.source_url)"
                    :href="safeEvidenceLink(item.source_url)"
                    target="_blank"
                    rel="noopener noreferrer"
                    >{{ item.source_url }}</a
                  ><span v-else>{{ item.source_url }}</span>
                </dd>
              </div>
              <div>
                <dt>{{ t('scout.comparison.locator') }}</dt>
                <dd>
                  <code>{{ item.locator }}</code>
                </dd>
              </div>
              <div>
                <dt>{{ t('scout.comparison.raw') }}</dt>
                <dd>{{ item.raw_value ?? t('scout.comparison.missing') }}</dd>
              </div>
              <div v-if="item.snapshot_public_id">
                <dt>{{ t('scout.comparison.snapshot') }}</dt>
                <dd>
                  <code>{{ item.snapshot_public_id }}</code>
                </dd>
              </div>
              <div v-if="item.rules_revision_public_id">
                <dt>{{ t('scout.comparison.revision') }}</dt>
                <dd>
                  <code>{{ item.rules_revision_public_id }}</code>
                </dd>
              </div>
              <div v-if="item.html_availability">
                <dt>{{ t('scout.comparison.html') }}</dt>
                <dd>{{ label('htmlStates', item.html_availability) }}</dd>
              </div>
            </dl>
          </li>
        </ol>
      </details></template
    >
  </section>
</template>
