<script setup>
import { computed, ref, useId } from 'vue'
import FormCard from '@/components/FormCard.vue'
import FormField from '@/components/FormField.vue'
import { confirmAction } from '@/js/utils/confirm.js'
import { useAppI18n } from '@/i18n/useAppI18n.js'
import { useScoutSchedule } from '../js/useScoutSchedule.js'
import {
  OCCURRENCE_STATUSES,
  OCCURRENCE_REASONS,
  sameSchedulePlan,
  validScheduleDraft,
  scheduleDate,
  scheduleMoment,
} from '../js/scheduleState.js'
const props = defineProps({
  jobId: { type: String, required: true },
  plan: { type: Object, default: null },
  planDirty: Boolean,
  disabled: Boolean,
})
const { t, locale } = useAppI18n()
const uid = useId(),
  confirming = ref(false),
  notice = ref('')
const {
  current,
  state,
  error,
  forbidden,
  writing,
  needsReview,
  saved,
  draft,
  dirty,
  candidateReady,
  canWrite,
  history,
  historyCursor,
  historyError,
  historyLoading,
  reload,
  readHistory,
  resolveConflict,
  write,
} = useScoutSchedule(
  computed(() => props.jobId),
  computed(() => props.plan),
  computed(() => props.planDirty),
)
const blocked = computed(
  () =>
    props.disabled ||
    confirming.value ||
    writing.value ||
    state.value === 'loading' ||
    needsReview.value ||
    forbidden.value,
)
const canSave = computed(
  () =>
    !blocked.value &&
    canWrite.value &&
    validScheduleDraft(draft) &&
    (current.value || candidateReady.value),
)
const differentPlan = computed(
  () => !!current.value && !!props.plan && !sameSchedulePlan(current.value, props.plan),
)
const planName = computed(() =>
  !current.value || sameSchedulePlan(current.value, props.plan)
    ? props.plan?.revision_number
      ? t('scout.schedule.revision', { number: props.plan.revision_number })
      : t('scout.schedule.currentPlan')
    : t('scout.schedule.olderPlan'),
)
const moment = (value) => scheduleMoment(value, current.value?.timezone || 'UTC', locale.value)
function actionStamp() {
  return JSON.stringify({
    job: props.jobId,
    version: current.value?.version,
    plan: props.plan,
    dirtyPlan: props.planDirty,
    draft,
  })
}
async function save(bindPlan = false) {
  if (!canSave.value || (bindPlan && !candidateReady.value)) return
  notice.value = ''
  const before = actionStamp()
  if (draft.enabled) {
    confirming.value = true
    let confirmed
    try {
      confirmed = await confirmAction({
        title: t('scout.schedule.confirmTitle'),
        message: t('scout.schedule.confirmMessage', {
          time: draft.local_time,
          zone: draft.timezone,
          plan: bindPlan
            ? t('scout.schedule.revision', { number: props.plan.revision_number || '—' })
            : planName.value,
        }),
        confirmText: t('scout.schedule.confirmEnable'),
        cancelText: t('scout.schedule.cancel'),
        variant: 'primary',
      })
    } finally {
      confirming.value = false
    }
    if (!confirmed) return
    if (before !== actionStamp()) {
      notice.value = t('scout.schedule.stale')
      return
    }
  }
  await write({ bindPlan })
}
</script>
<template>
  <FormCard class="scout-schedule">
    <details>
      <summary class="scout-schedule-summary">
        <strong>{{ t('scout.schedule.title') }}</strong
        ><span v-if="current">{{
          t(current.enabled ? 'scout.schedule.on' : 'scout.schedule.off')
        }}</span>
      </summary>
      <div class="scout-schedule-content">
        <p>{{ t('scout.schedule.lead') }}</p>
        <p v-if="state === 'loading'" role="status">{{ t('scout.schedule.loading') }}</p>
        <p v-if="state === 'absent'" class="scout-muted">{{ t('scout.schedule.absent') }}</p>
        <div v-if="error" class="alert alert-warning" role="alert">
          <p class="mb-0">{{ t(`scout.schedule.errors.${error.key}`) }}</p>
          <p v-if="error.detail" class="small mb-0">{{ error.detail }}</p>
        </div>
        <p v-if="notice" class="alert alert-warning" role="status">{{ notice }}</p>
        <p v-if="saved && !dirty" role="status">{{ t('scout.schedule.saved') }}</p>
        <div v-if="needsReview && current" class="scout-schedule-conflict" role="status">
          <p>{{ t('scout.schedule.conflict') }}</p>
          <strong
            >{{ t('scout.schedule.serverValues') }}: {{ current.local_time }} ·
            {{ current.timezone }} ·
            {{ t(current.enabled ? 'scout.schedule.on' : 'scout.schedule.off') }}</strong
          >
          <div class="scout-schedule-buttons">
            <button
              type="button"
              class="btn btn-outline-secondary"
              :disabled="writing"
              @click="resolveConflict(true)"
            >
              {{ t('scout.schedule.takeServer') }}</button
            ><button
              type="button"
              class="btn btn-outline-secondary"
              :disabled="writing"
              @click="resolveConflict(false)"
            >
              {{ t('scout.schedule.keepMine') }}
            </button>
          </div>
        </div>
        <template v-if="current">
          <dl class="scout-plan">
            <div>
              <dt>{{ t('scout.schedule.bound') }}</dt>
              <dd>
                {{ planName }}
                <details>
                  <summary>{{ t('scout.schedule.details') }}</summary>
                  <code>{{ current.plan_revision_public_id }}</code
                  ><code>{{ current.plan_hash }}</code>
                </details>
              </dd>
            </div>
            <div>
              <dt>{{ t('scout.schedule.next') }}</dt>
              <dd>
                {{
                  current.enabled
                    ? current.next_scheduled_at
                      ? moment(current.next_scheduled_at) + ' · ' + current.timezone
                      : t('scout.schedule.unknownNext')
                    : t('scout.schedule.noNext')
                }}
              </dd>
            </div>
          </dl>
          <p class="small scout-muted">
            {{ t('scout.schedule.version', { number: current.version }) }}
          </p>
          <p v-if="differentPlan" class="alert alert-info">
            {{ t('scout.schedule.differentPlan') }}
          </p>
        </template>
        <p v-if="planDirty" class="alert alert-info">{{ t('scout.schedule.unsavedPlan') }}</p>
        <p v-else-if="!candidateReady" class="scout-muted">
          {{ t('scout.schedule.planRequired') }}
        </p>
        <form @submit.prevent="save(false)">
          <fieldset :disabled="blocked || !['ready', 'absent'].includes(state)">
            <legend class="visually-hidden">{{ t('scout.schedule.title') }}</legend>
            <div class="scout-schedule-fields">
              <FormField :label="t('scout.schedule.time')" :label-for="`${uid}-time`"
                ><input
                  :id="`${uid}-time`"
                  v-model="draft.local_time"
                  type="time"
                  step="60"
                  class="form-control"
                  required
                  :aria-invalid="error?.path === '/local_time'"
              /></FormField>
              <FormField
                :label="t('scout.schedule.zone')"
                :label-for="`${uid}-zone`"
                :hint="t('scout.schedule.zoneHint')"
                ><input
                  :id="`${uid}-zone`"
                  v-model="draft.timezone"
                  :list="`${uid}-zones`"
                  class="form-control"
                  maxlength="128"
                  required
                  :aria-invalid="error?.path === '/timezone'" /><datalist :id="`${uid}-zones`">
                  <option
                    v-for="zone in [
                      'UTC',
                      'Europe/Moscow',
                      'Europe/Berlin',
                      'Asia/Almaty',
                      'Asia/Vladivostok',
                      'America/New_York',
                    ]"
                    :key="zone"
                    :value="zone"
                  /></datalist
              ></FormField>
            </div>
            <label class="scout-schedule-consent" :for="`${uid}-enabled`"
              ><input :id="`${uid}-enabled`" v-model="draft.enabled" type="checkbox" />{{
                t('scout.schedule.enabled')
              }}</label
            >
            <p class="small scout-muted">{{ t('scout.schedule.rules') }}</p>
            <p class="small scout-muted">
              {{ t('scout.schedule.offline') }} {{ t('scout.schedule.window') }}
            </p>
            <p v-if="current && dirty" class="small scout-warning">
              {{ t('scout.schedule.dirty') }}
            </p>
            <div class="scout-schedule-buttons">
              <button type="submit" class="btn btn-primary" :disabled="!canSave">
                {{
                  t(
                    writing
                      ? 'scout.schedule.saving'
                      : current
                        ? 'scout.schedule.save'
                        : 'scout.schedule.create',
                  )
                }}</button
              ><button
                v-if="differentPlan && candidateReady"
                type="button"
                class="btn btn-outline-secondary"
                :disabled="!canSave"
                @click="save(true)"
              >
                {{ t('scout.schedule.rebind') }}
              </button>
            </div>
          </fieldset>
        </form>
        <div class="scout-schedule-buttons mt-3">
          <button
            type="button"
            class="btn btn-outline-secondary"
            :disabled="props.disabled || writing || confirming || state === 'loading'"
            @click="reload"
          >
            {{ t('scout.schedule.reload') }}</button
          ><button
            v-if="current?.enabled"
            type="button"
            class="btn btn-outline-secondary"
            :disabled="props.disabled || confirming || !canWrite"
            @click="write({ disableOnly: true })"
          >
            {{ t('scout.schedule.disable') }}
          </button>
        </div>
        <p v-if="current" class="small scout-muted">{{ t('scout.schedule.disableHint') }}</p>
        <section
          v-if="current"
          class="scout-schedule-history"
          :aria-label="t('scout.schedule.history')"
        >
          <h3 class="h6">{{ t('scout.schedule.history') }}</h3>
          <p class="small scout-muted">{{ t('scout.schedule.historyHint') }}</p>
          <button
            type="button"
            class="btn btn-outline-secondary btn-sm"
            :disabled="historyLoading || writing"
            @click="readHistory()"
          >
            {{ t('scout.schedule.reloadHistory') }}
          </button>
          <p v-if="historyError" class="alert alert-warning mt-2" role="alert">
            {{ t('scout.schedule.errors.historyFailed') }}
          </p>
          <p v-if="historyLoading" role="status">{{ t('scout.schedule.historyLoading') }}</p>
          <p v-else-if="!history.length && !historyError" class="scout-muted">
            {{ t('scout.schedule.emptyHistory') }}
          </p>
          <ol class="scout-schedule-days">
            <li v-for="day in history" :key="day.public_id">
              <div class="scout-schedule-day-heading">
                <strong>{{ scheduleDate(day.local_date, locale) }}</strong
                ><span>{{
                  t(
                    OCCURRENCE_STATUSES.includes(day.status)
                      ? `scout.schedule.statuses.${day.status}`
                      : 'scout.schedule.unknownStatus',
                  )
                }}</span>
              </div>
              <p v-if="day.reason" class="mb-1">
                {{ t('scout.schedule.reason') }}:
                {{
                  t(
                    OCCURRENCE_REASONS.includes(day.reason)
                      ? `scout.schedule.reasons.${day.reason}`
                      : 'scout.schedule.unknownReason',
                  )
                }}
              </p>
              <dl class="scout-schedule-day-details">
                <div>
                  <dt>{{ t('scout.schedule.scheduledAt') }}</dt>
                  <dd>{{ moment(day.scheduled_at) }}</dd>
                </div>
                <div>
                  <dt>{{ t('scout.schedule.processedAt') }}</dt>
                  <dd>{{ moment(day.processed_at) }}</dd>
                </div>
                <div>
                  <dt>{{ t('scout.schedule.historyVersion') }}</dt>
                  <dd>{{ t('scout.schedule.version', { number: day.schedule_version }) }}</dd>
                </div>
              </dl>
              <RouterLink
                v-if="day.run_public_id"
                :to="{
                  path: '/scout',
                  query: { job: jobId, run: day.run_public_id, mode: 'manual' },
                }"
                class="btn btn-outline-secondary btn-sm"
                >{{ t('scout.schedule.openRun') }}</RouterLink
              >
            </li>
          </ol>
          <button
            v-if="historyCursor"
            type="button"
            class="btn btn-outline-secondary"
            :disabled="historyLoading || writing"
            @click="readHistory(true)"
          >
            {{ t('scout.schedule.historyMore') }}
          </button>
        </section>
      </div>
    </details>
  </FormCard>
</template>
