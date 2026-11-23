<script setup>
import { computed, ref, useId, watch } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import FormCard from '@/components/FormCard.vue'
import FormField from '@/components/FormField.vue'
import { confirmAction } from '@/js/utils/confirm.js'
import { useAppI18n } from '@/i18n/useAppI18n.js'
import ScoutRetentionItems from './ScoutRetentionItems.vue'
import ScoutRetentionError from './ScoutRetentionError.vue'
import { useScoutRetention } from '../js/useScoutRetention.js'
import {
  POLICY_DAYS,
  RETENTION_SCOPES,
  TOTAL_COUNTS,
  BYTE_COUNTS,
  validPolicy,
  retentionCount,
  retentionBytes,
} from '../js/retentionState.js'
import { scheduleMoment } from '../js/scheduleState.js'
import messages from '../js/retentionLocales.js'
const route = useRoute(),
  router = useRouter(),
  { t, locale } = useAppI18n(),
  uid = useId()
const jobId = computed(() => (typeof route.query.job === 'string' ? route.query.job : ''))
const runId = computed(() => (typeof route.query.run === 'string' ? route.query.run : ''))
const cleanupId = computed(() =>
  typeof route.query.cleanup === 'string' ? route.query.cleanup : '',
)
const model = useScoutRetention(jobId, runId, cleanupId, (id) =>
  router.replace({ query: { ...route.query, cleanup: id } }),
)
const {
  policy,
  draft,
  policyState,
  policyError,
  policyReview,
  dirty,
  saved,
  runState,
  runError,
  holdError,
  holdUnavailable,
  holdIntent,
  ownerScope,
  scopes,
  preview,
  previewError,
  previewLoading,
  previewItems,
  previewCursor,
  itemsError,
  itemsLoading,
  cleanup,
  cleanupError,
  cleanupItems,
  cleanupCursor,
  cleanupItemsError,
  cleanupItemsLoading,
  pending,
  busy,
  now,
  canPreview,
  canExecute,
  loadPolicy,
  choosePolicy,
  savePolicy,
  loadRun,
  changeHold,
  createPreview,
  loadPreviewItems,
  execute,
  loadCleanup,
  loadCleanupItems,
} = model
const confirming = ref(false),
  notice = ref(''),
  accepted = ref(false)
const blocked = computed(() => busy.value || confirming.value)
const expired = computed(() => !!preview.value && now.value >= Date.parse(preview.value.expires_at))
const availableScopes = computed(() =>
  RETENTION_SCOPES.filter((key) => ownerScope.value || key !== 'visual_snapshots'),
)
const back = computed(() => ({
  path: '/scout',
  query: {
    ...(jobId.value ? { job: jobId.value } : {}),
    ...(runId.value ? { run: runId.value } : {}),
  },
}))
const moment = (value) =>
  value ? scheduleMoment(value, 'UTC', locale.value) + ' UTC' : t('scout.retention.notDated')
const count = (value) => retentionCount(value, locale.value)
const bytes = (value) =>
  value === null || value === undefined
    ? t('scout.retention.unknown')
    : retentionBytes(value, locale.value)
function label(group, key) {
  return t(
    Object.hasOwn(messages.ru[group], key)
      ? `scout.retention.${group}.${key}`
      : 'scout.retention.readOnlyUnknown',
  )
}
function stamp() {
  return JSON.stringify({
    job: jobId.value,
    run: runId.value,
    policy: policy.value?.version,
    draft,
    preview: preview.value?.manifest_hash,
    previewId: preview.value?.preview_public_id,
    owner: ownerScope.value,
    scopes: scopes.value,
    hold: runState.value?.hold,
  })
}
async function confirmThen(action, options) {
  if (blocked.value) return
  const before = stamp()
  confirming.value = true
  notice.value = ''
  let yes
  try {
    yes = await confirmAction({ ...options, cancelText: t('scout.retention.cancel') })
  } finally {
    confirming.value = false
  }
  if (!yes) return
  if (before !== stamp()) {
    notice.value = t('scout.retention.changedDuringConfirm')
    return
  }
  await action()
}
async function save() {
  if (blocked.value || !validPolicy(draft) || policyReview.value) return
  if (draft.automatic_enabled)
    await confirmThen(savePolicy, {
      title: t('scout.retention.automaticTitle'),
      message: t('scout.retention.automaticMessage'),
      confirmText: t('scout.retention.automaticConfirm'),
      variant: 'warning',
    })
  else await savePolicy()
}
function unpin() {
  return confirmThen(() => changeHold(null), {
    title: t('scout.retention.unpinTitle'),
    message: t('scout.retention.unpinMessage'),
    confirmText: t('scout.retention.unpin'),
    variant: 'warning',
  })
}
function remove() {
  if (!accepted.value || !canExecute.value || blocked.value) return
  const totals = preview.value.totals
  return confirmThen(
    () => {
      if (!canExecute.value) {
        notice.value = t('scout.retention.expiredPreview')
        return
      }
      return execute()
    },
    {
      title: t('scout.retention.deleteTitle'),
      message: t('scout.retention.deleteMessage', {
        at: moment(preview.value.evaluated_at),
        runs: count(totals.runs_with_result_deletion),
        records: count(totals.records),
        evidence: count(totals.evidence),
        html: count(totals.html_files),
        exports: count(totals.export_files),
        visual: count(totals.visual_snapshots),
        bytes: bytes(totals.file_bytes_reclaimable),
      }),
      confirmText: t('scout.retention.deleteConfirm'),
      variant: 'danger',
    },
  )
}
function toggleAge(key, event) {
  draft[key] = event.target.checked
    ? null
    : { html_days: 30, result_days: 365, export_days: 7 }[key]
}
onBeforeRouteLeave(async () => {
  if (busy.value) {
    notice.value = t('scout.retention.waitOperation')
    return false
  }
  if (!dirty.value) return true
  return await confirmAction({
    title: t('scout.retention.leaveTitle'),
    message: t('scout.retention.leaveMessage'),
    confirmText: t('scout.retention.leaveConfirm'),
    cancelText: t('scout.retention.cancel'),
    variant: 'warning',
  })
})
watch(
  () => preview.value?.preview_public_id,
  () => {
    accepted.value = false
  },
)
</script>
<template>
  <main class="scout-workflow scout-retention">
    <header class="scout-header">
      <div>
        <p class="scout-eyebrow">SCOUT</p>
        <h1>{{ t('scout.retention.title') }}</h1>
        <p class="scout-muted">{{ t('scout.retention.lead') }}</p>
      </div>
      <RouterLink :to="back" class="btn btn-outline-secondary">{{
        t('scout.retention.back')
      }}</RouterLink>
    </header>
    <p v-if="notice" class="alert alert-warning" role="status">{{ notice }}</p>
    <FormCard class="scout-retention-card">
      <section :aria-labelledby="`${uid}-policy`">
        <h2 :id="`${uid}-policy`" class="h4">{{ t('scout.retention.policy') }}</h2>
        <p>{{ t('scout.retention.policyScope') }}</p>
        <p v-if="policyState === 'loading'" role="status">{{ t('scout.retention.loading') }}</p>
        <ScoutRetentionError :problem="policyError" />
        <template v-if="policy"
          ><p class="small scout-muted">
            {{ t('scout.retention.version', { number: policy.version }) }}
          </p>
          <div v-if="policyReview" class="alert alert-warning" role="status">
            <p>{{ t('scout.retention.conflict') }}</p>
            <details>
              <summary>{{ t('scout.retention.serverValues') }}</summary>
              <dl class="scout-retention-details">
                <div v-for="key in POLICY_DAYS" :key="key">
                  <dt>{{ t(`scout.retention.${key}`) }}</dt>
                  <dd>
                    {{
                      policy[key] === null
                        ? t('scout.retention.forever')
                        : count(policy[key]) + ' ' + t('scout.retention.days')
                    }}
                  </dd>
                </div>
                <div>
                  <dt>{{ t('scout.retention.keep_latest_results') }}</dt>
                  <dd>{{ count(policy.keep_latest_results) }}</dd>
                </div>
                <div>
                  <dt>{{ t('scout.retention.automatic') }}</dt>
                  <dd>{{ policy.automatic_enabled ? t('common.yes') : t('common.no') }}</dd>
                </div>
              </dl>
            </details>
            <div class="scout-retention-buttons">
              <button
                type="button"
                class="btn btn-outline-secondary"
                :disabled="blocked"
                @click="choosePolicy(true)"
              >
                {{ t('scout.retention.takeServer') }}</button
              ><button
                type="button"
                class="btn btn-outline-secondary"
                :disabled="blocked"
                @click="choosePolicy(false)"
              >
                {{ t('scout.retention.keepDraft') }}
              </button>
            </div>
          </div>
          <form @submit.prevent="save">
            <fieldset :disabled="blocked || policyState !== 'ready' || policyReview">
              <legend class="visually-hidden">{{ t('scout.retention.policy') }}</legend>
              <div class="scout-retention-policy-fields">
                <FormField
                  v-for="key in POLICY_DAYS"
                  :key="key"
                  :label="t(`scout.retention.${key}`)"
                  :label-for="`${uid}-${key}`"
                  ><input
                    :id="`${uid}-${key}`"
                    v-model.number="draft[key]"
                    type="number"
                    class="form-control"
                    min="1"
                    max="3650"
                    step="1"
                    :disabled="draft[key] === null"
                    :required="draft[key] !== null"
                  /><label class="scout-retention-checkbox" :for="`${uid}-${key}-forever`"
                    ><input
                      :id="`${uid}-${key}-forever`"
                      type="checkbox"
                      :checked="draft[key] === null"
                      @change="toggleAge(key, $event)"
                    />{{ t('scout.retention.forever')
                    }}<span class="visually-hidden"
                      >: {{ t(`scout.retention.${key}`) }}</span
                    ></label
                  ></FormField
                >
                <FormField
                  :label="t('scout.retention.keep_latest_results')"
                  :label-for="`${uid}-latest`"
                  ><input
                    :id="`${uid}-latest`"
                    v-model.number="draft.keep_latest_results"
                    type="number"
                    class="form-control"
                    min="2"
                    max="100"
                    step="1"
                    required
                /></FormField>
              </div>
              <p class="small scout-muted">{{ t('scout.retention.policyHint') }}</p>
              <p class="small scout-muted">{{ t('scout.retention.visualHours') }}</p>
              <label class="scout-retention-checkbox" :for="`${uid}-auto`"
                ><input :id="`${uid}-auto`" v-model="draft.automatic_enabled" type="checkbox" />{{
                  t('scout.retention.automatic')
                }}</label
              >
              <p class="small scout-muted">{{ t('scout.retention.automaticHint') }}</p>
              <p v-if="!validPolicy(draft)" class="scout-warning" role="status">
                {{ t('scout.retention.invalidPolicy') }}
              </p>
              <button
                type="submit"
                class="btn btn-primary"
                :disabled="!dirty || !validPolicy(draft)"
              >
                {{ t('scout.retention.savePolicy') }}
              </button>
            </fieldset>
          </form>
          <p v-if="saved && !dirty" role="status">
            {{ t('scout.retention.policySaved') }}
          </p> </template
        ><button
          type="button"
          class="btn btn-outline-secondary mt-3"
          :disabled="blocked || policyState === 'loading'"
          @click="loadPolicy(dirty)"
        >
          {{ t('scout.retention.reloadPolicy') }}
        </button>
      </section>
    </FormCard>
    <FormCard v-if="runId" class="scout-retention-card"
      ><section :aria-labelledby="`${uid}-run`">
        <h2 :id="`${uid}-run`" class="h4">{{ t('scout.retention.runTitle') }}</h2>
        <p>{{ t('scout.retention.runHint') }}</p>
        <code>{{ runId }}</code
        ><ScoutRetentionError :problem="runError" /><ScoutRetentionError :problem="holdError" />
        <template v-if="runState"
          ><dl class="scout-retention-details">
            <div>
              <dt>{{ t('scout.retention.availability') }}</dt>
              <dd>{{ label('availabilityValues', runState.results_availability) }}</dd>
            </div>
            <div>
              <dt>{{ t('scout.retention.htmlAvailability') }}</dt>
              <dd>{{ label('availabilityValues', runState.html_availability) }}</dd>
            </div>
            <div>
              <dt>{{ t('scout.retention.eligibleHtml') }}</dt>
              <dd>{{ moment(runState.eligible_at.html) }}</dd>
            </div>
            <div>
              <dt>{{ t('scout.retention.eligibleResults') }}</dt>
              <dd>{{ moment(runState.eligible_at.results) }}</dd>
            </div>
            <div>
              <dt>{{ t('scout.retention.hold') }}</dt>
              <dd>
                {{
                  t(
                    runState.hold.scope === 'all'
                      ? 'scout.retention.holdAll'
                      : runState.hold.scope === 'results'
                        ? 'scout.retention.holdResults'
                        : 'scout.retention.holdNone',
                  )
                }}
                · {{ t('scout.retention.version', { number: runState.hold.version }) }}
              </dd>
            </div>
          </dl>
          <h3 class="h6">{{ t('scout.retention.protection') }}</h3>
          <dl class="scout-retention-details">
            <div v-for="(reason, key) in runState.protected" :key="key">
              <dt>{{ label('scopes', key) }}</dt>
              <dd>{{ reason ? label('reasons', reason) : '—' }}</dd>
            </div>
          </dl>
          <p class="small scout-muted">{{ t('scout.retention.holdHint') }}</p>
          <div class="scout-retention-buttons">
            <button
              type="button"
              class="btn btn-outline-secondary"
              :disabled="
                blocked ||
                !!runError ||
                !!holdIntent ||
                runState.results_availability !== 'available'
              "
              @click="changeHold('results')"
            >
              {{ t('scout.retention.pinResults') }}</button
            ><button
              type="button"
              class="btn btn-outline-secondary"
              :disabled="
                blocked ||
                !!runError ||
                !!holdIntent ||
                runState.results_availability !== 'available'
              "
              @click="changeHold('all')"
            >
              {{ t('scout.retention.pinAll') }}</button
            ><button
              v-if="runState.hold.scope"
              type="button"
              class="btn btn-outline-secondary"
              :disabled="blocked || !!runError || !!holdIntent"
              @click="unpin"
            >
              {{ t('scout.retention.unpin') }}
            </button>
          </div>
          <p
            v-if="
              runState.hold.scope === 'all' &&
              (runState.html_availability !== 'available' || holdUnavailable.length)
            "
            class="scout-warning"
          >
            {{ t('scout.retention.unavailableParts') }}
            <span v-for="part in holdUnavailable" :key="part">{{ label('scopes', part) }}. </span>
          </p></template
        >
        <div class="scout-retention-buttons">
          <button
            type="button"
            class="btn btn-outline-secondary"
            :disabled="blocked"
            @click="loadRun"
          >
            {{ t('scout.retention.refresh') }}</button
          ><button
            v-if="holdIntent"
            type="button"
            class="btn btn-outline-secondary"
            :disabled="blocked"
            @click="changeHold(null, true)"
          >
            {{ t('scout.retention.retryHold') }}
          </button>
        </div>
      </section></FormCard
    >
    <FormCard class="scout-retention-card"
      ><section :aria-labelledby="`${uid}-selection`">
        <h2 :id="`${uid}-selection`" class="h4">{{ t('scout.retention.selection') }}</h2>
        <p>{{ t('scout.retention.previewHint') }}</p>
        <fieldset :disabled="blocked || previewLoading || !!pending">
          <legend class="visually-hidden">{{ t('scout.retention.selection') }}</legend>
          <label v-if="jobId" class="scout-retention-checkbox" :for="`${uid}-job`"
            ><input
              :id="`${uid}-job`"
              v-model="ownerScope"
              type="radio"
              :value="false"
              :name="`${uid}-owner`"
            />{{ t('scout.retention.thisJob') }}</label
          ><label class="scout-retention-checkbox" :for="`${uid}-owner`"
            ><input
              :id="`${uid}-owner`"
              v-model="ownerScope"
              type="radio"
              :value="true"
              :name="`${uid}-owner`"
            />{{ t('scout.retention.allJobs') }}</label
          >
          <p class="small scout-muted">{{ t('scout.retention.ownerHint') }}</p>
          <fieldset>
            <legend class="h6">{{ t('scout.retention.scopesLabel') }}</legend>
            <label
              v-for="key in availableScopes"
              :key="key"
              :for="`${uid}-scope-${key}`"
              class="scout-retention-checkbox"
              ><input :id="`${uid}-scope-${key}`" v-model="scopes" type="checkbox" :value="key" />{{
                label('scopes', key)
              }}</label
            >
          </fieldset>
          <p v-if="dirty" class="scout-warning">{{ t('scout.retention.pendingChanges') }}</p>
          <button
            type="button"
            class="btn btn-primary"
            :disabled="!canPreview"
            @click="createPreview"
          >
            {{ t('scout.retention.createPreview') }}
          </button>
        </fieldset>
        <p v-if="previewLoading" role="status">{{ t('scout.retention.loading') }}</p>
        <ScoutRetentionError :problem="previewError" /></section
    ></FormCard>
    <FormCard v-if="preview" class="scout-retention-card"
      ><section :aria-labelledby="`${uid}-preview`">
        <h2 :id="`${uid}-preview`" class="h4">{{ t('scout.retention.previewTitle') }}</h2>
        <dl class="scout-retention-details">
          <div>
            <dt>{{ t('scout.retention.evaluated') }}</dt>
            <dd>{{ moment(preview.evaluated_at) }}</dd>
          </div>
          <div>
            <dt>{{ t('scout.retention.expires') }}</dt>
            <dd>{{ moment(preview.expires_at) }}</dd>
          </div>
        </dl>
        <p v-if="expired" class="alert alert-warning" role="status">
          {{ t('scout.retention.expiredPreview') }}
        </p>
        <p v-if="!preview.executable" class="alert alert-warning" role="status">
          {{ t('scout.retention.notExecutable') }}
        </p>
        <dl class="scout-retention-totals">
          <div v-for="key in TOTAL_COUNTS" :key="key">
            <dt>{{ t(`scout.retention.totals.${key}`) }}</dt>
            <dd>{{ count(preview.totals[key]) }}</dd>
          </div>
          <div v-for="key in BYTE_COUNTS" :key="key">
            <dt>{{ t(`scout.retention.totals.${key}`) }}</dt>
            <dd>{{ bytes(preview.totals[key]) }}</dd>
          </div>
        </dl>
        <p v-for="(warning, index) in preview.warnings" :key="index" class="scout-warning">
          {{
            t(
              warning === 'storage_not_verified'
                ? 'scout.retention.storageWarning'
                : 'scout.retention.otherWarning',
            )
          }}
        </p>
        <p v-if="preview.totals.runs_with_result_deletion > 0" class="alert alert-warning">
          {{ t('scout.retention.comparisonLoss') }}
        </p>
        <h3 class="h6">{{ t('scout.retention.protectedTitle') }}</h3>
        <p class="small scout-muted">{{ t('scout.retention.protectedHint') }}</p>
        <dl class="scout-retention-details">
          <div v-for="(value, key) in preview.protected" :key="key">
            <dt>{{ label('reasons', key) }}</dt>
            <dd>{{ count(value) }}</dd>
          </div>
        </dl>
        <p v-if="!Object.keys(preview.protected).length" class="scout-muted">
          {{ t('scout.retention.noProtected') }}
        </p>
        <h3 class="h6">{{ t('scout.retention.itemsTitle') }}</h3>
        <ScoutRetentionError :problem="itemsError" />
        <p v-if="itemsLoading" role="status">{{ t('scout.retention.loading') }}</p>
        <p v-else-if="!previewItems.length && !itemsError">{{ t('scout.retention.emptyItems') }}</p>
        <ScoutRetentionItems :items="previewItems" />
        <div class="scout-retention-buttons">
          <button
            v-if="itemsError"
            type="button"
            class="btn btn-outline-secondary"
            :disabled="blocked || itemsLoading"
            @click="loadPreviewItems()"
          >
            {{ t('scout.retention.retryItems') }}</button
          ><button
            v-if="previewCursor"
            type="button"
            class="btn btn-outline-secondary"
            :disabled="blocked || itemsLoading"
            @click="loadPreviewItems(true)"
          >
            {{ t('scout.retention.moreItems') }}
          </button>
        </div>
        <label class="scout-retention-checkbox" :for="`${uid}-accept`"
          ><input
            :id="`${uid}-accept`"
            v-model="accepted"
            type="checkbox"
            :disabled="blocked || !canExecute"
          />{{ t('scout.retention.acceptList') }}</label
        ><button
          type="button"
          class="btn btn-danger"
          :disabled="blocked || !canExecute || !accepted"
          @click="remove"
        >
          {{ t('scout.retention.deleteButton') }}
        </button>
      </section></FormCard
    >
    <ScoutRetentionError :problem="cleanupError" />
    <div v-if="pending" class="alert alert-warning" role="status">
      <p>{{ t('scout.retention.pendingRequest') }}</p>
      <button
        type="button"
        class="btn btn-outline-secondary"
        :disabled="blocked"
        @click="execute(true)"
      >
        {{ t('scout.retention.retryCleanup') }}
      </button>
    </div>
    <FormCard v-if="cleanup" class="scout-retention-card"
      ><section :aria-labelledby="`${uid}-cleanup`">
        <h2 :id="`${uid}-cleanup`" class="h4">
          {{ t('scout.retention.cleanupTitle') }} · {{ label('statuses', cleanup.status) }}
        </h2>
        <p>{{ t('scout.retention.cleanupHint') }}</p>
        <p>
          {{ t('scout.retention.cleanupId') }}: <code>{{ cleanup.cleanup_public_id }}</code>
        </p>
        <dl class="scout-retention-totals">
          <div v-for="state in ['deleted', 'skipped', 'failed', 'pending']" :key="state">
            <dt>{{ t(`scout.retention.${state}`) }}</dt>
            <dd>
              <span v-for="(value, key) in cleanup[state]" :key="key"
                >{{ label('scopes', key) }}: {{ count(value) }}<br /></span
              ><span v-if="!Object.keys(cleanup[state] || {}).length">0</span>
            </dd>
          </div>
          <div>
            <dt>{{ t('scout.retention.deletedBytes') }}</dt>
            <dd>{{ bytes(cleanup.deleted_bytes) }}</dd>
          </div>
          <div>
            <dt>{{ t('scout.retention.deletedRows') }}</dt>
            <dd>{{ count(cleanup.deleted_rows) }}</dd>
          </div>
        </dl>
        <div v-if="cleanup.errors?.length" class="alert alert-warning">
          <strong>{{ t('scout.retention.cleanupErrors') }}</strong>
          <ul>
            <li v-for="(reason, index) in cleanup.errors" :key="index">
              {{ label('reasons', reason) }}
            </li>
          </ul>
        </div>
        <button
          type="button"
          class="btn btn-outline-secondary"
          :disabled="blocked"
          @click="loadCleanup()"
        >
          {{ t('scout.retention.retryStatus') }}
        </button>
        <h3 class="h6 mt-3">{{ t('scout.retention.cleanupItems') }}</h3>
        <ScoutRetentionError :problem="cleanupItemsError" />
        <p v-if="cleanupItemsLoading" role="status">{{ t('scout.retention.loading') }}</p>
        <ScoutRetentionItems :items="cleanupItems" /><button
          v-if="cleanupCursor"
          type="button"
          class="btn btn-outline-secondary"
          :disabled="blocked || cleanupItemsLoading"
          @click="loadCleanupItems(true)"
        >
          {{ t('scout.retention.moreItems') }}</button
        ><button
          v-if="cleanupItemsError"
          type="button"
          class="btn btn-outline-secondary"
          :disabled="blocked || cleanupItemsLoading"
          @click="loadCleanupItems()"
        >
          {{ t('scout.retention.retryItems') }}
        </button>
      </section></FormCard
    >
  </main>
</template>
