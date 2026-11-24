<script setup>
import { useAppI18n } from '@/i18n/useAppI18n.js'
import { retentionCount, retentionBytes } from '../js/retentionState.js'
import { scheduleMoment } from '../js/scheduleState.js'
import messages from '../js/retentionLocales.js'
defineProps({ items: { type: Array, default: () => [] } })
const { t, locale } = useAppI18n()
function label(group, key) {
  return t(
    Object.hasOwn(messages.ru[group], key)
      ? `scout.retention.${group}.${key}`
      : 'scout.retention.readOnlyUnknown',
  )
}
</script>
<template>
  <ol class="scout-retention-items">
    <li v-for="(item, index) in items" :key="`${item.kind}-${item.public_id}-${index}`">
      <div class="scout-retention-item-heading">
        <strong>{{ label('scopes', item.kind) }}</strong
        ><span>{{
          item.status
            ? label('statuses', item.status)
            : t(item.reason ? 'scout.retention.excluded' : 'scout.retention.candidate')
        }}</span>
      </div>
      <dl class="scout-retention-details">
        <div>
          <dt>{{ t('scout.retention.object') }}</dt>
          <dd>
            <code>{{ item.public_id }}</code>
          </dd>
        </div>
        <div v-if="item.run_public_id">
          <dt>{{ t('scout.retention.run') }}</dt>
          <dd>
            <code>{{ item.run_public_id }}</code>
          </dd>
        </div>
        <div v-if="item.reason">
          <dt>
            {{ t(item.status ? 'scout.retention.operationItemReason' : 'scout.retention.reason') }}
          </dt>
          <dd>{{ label('reasons', item.reason) }}</dd>
        </div>
        <div v-if="item.eligible_at">
          <dt>{{ t('scout.retention.eligible') }}</dt>
          <dd>{{ scheduleMoment(item.eligible_at, 'UTC', locale) }} UTC</dd>
        </div>
        <div
          v-for="key in ['records', 'evidence', 'export_files'].filter((key) =>
            Object.hasOwn(item, key),
          )"
          :key="key"
        >
          <dt>{{ t(`scout.retention.${key === 'export_files' ? 'exportFiles' : key}`) }}</dt>
          <dd>{{ retentionCount(item[key], locale) }}</dd>
        </div>
        <div v-if="Object.hasOwn(item, 'bytes')">
          <dt>{{ t('scout.retention.bytes') }}</dt>
          <dd>
            {{
              item.bytes === null
                ? t('scout.retention.unknown')
                : retentionBytes(item.bytes, locale)
            }}
          </dd>
        </div>
        <div v-if="Object.hasOwn(item, 'deleted_bytes')">
          <dt>{{ t('scout.retention.deletedBytes') }}</dt>
          <dd>{{ retentionCount(item.deleted_bytes, locale) }}</dd>
        </div>
        <div v-if="Object.hasOwn(item, 'deleted_rows')">
          <dt>{{ t('scout.retention.deletedRows') }}</dt>
          <dd>{{ retentionCount(item.deleted_rows, locale) }}</dd>
        </div>
      </dl>
      <p v-if="item.comparison_will_expire" class="scout-warning">
        {{ t('scout.retention.itemComparison') }}
      </p>
      <p v-if="item.executable === false" class="scout-warning">
        {{ t('scout.retention.itemUnavailable') }}
      </p>
    </li>
  </ol>
</template>
