import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { apiClient } from '@/js/api/manager'
import { scoutEndpoints } from './endpoints.js'
import {
  approvedSchedulePlan,
  scheduleValues,
  scheduleWrite,
  validScheduleDraft,
  writeMatchesSchedule,
} from './scheduleState.js'

export function useScoutSchedule(jobId, plan, planDirty) {
  const current = ref(null),
    state = ref('idle'),
    error = ref(null),
    forbidden = ref(false)
  const writing = ref(false),
    needsReview = ref(false),
    saved = ref(false)
  const draft = reactive({ local_time: '09:00', timezone: 'UTC', enabled: false })
  const history = ref([]),
    historyCursor = ref(null),
    historyError = ref(false),
    historyLoading = ref(false)
  let generation = 0,
    readId = 0,
    historyId = 0,
    disposed = false
  const quiet = { quietStatuses: [400, 401, 403, 404, 409, 429, 500, 502, 503, 504] }
  const initialValues = ref(scheduleValues())
  const stamp = computed(() => JSON.stringify({ ...draft, timezone: draft.timezone.trim() }))
  const dirty = computed(
    () =>
      stamp.value !== JSON.stringify(current.value ? scheduleValues(current.value) : initialValues.value),
  )
  const candidateReady = computed(() => approvedSchedulePlan(plan.value, planDirty.value))
  const canWrite = computed(
    () =>
      !forbidden.value &&
      !needsReview.value &&
      !writing.value &&
      ['ready', 'absent'].includes(state.value),
  )

  function failure(response, fallback) {
    const status = response.status || response.response?.status
    const data = response.data || response.response?.data || {}
    return {
      key:
        status === 403 || status === 401
          ? 'forbidden'
          : data.code === 'approval_required'
            ? 'approval'
            : status === 404
              ? 'notFound'
              : fallback,
      detail: data.detail || response.message || '',
      path: data.path || '',
      status,
      code: data.code,
    }
  }
  function apply(data, preserve = false) {
    current.value = data
    state.value = 'ready'
    if (!preserve) Object.assign(draft, scheduleValues(data))
  }
  async function read({ preserveDraft = false, keepError = false } = {}) {
    const id = jobId.value,
      owner = generation,
      request = ++readId,
      initialStamp = stamp.value
    if (!id || disposed) return null
    const previousVersion = current.value?.version
    state.value = 'loading'
    if (!keepError) {
      error.value = null
      saved.value = false
    }
    try {
      const response = await apiClient.get(scoutEndpoints.schedule(id), {}, true, quiet)
      if (disposed || owner !== generation || request !== readId) return null
      if (!response.success) {
        if (response.status === 404) {
          current.value = null
          state.value = 'absent'
          needsReview.value = false
          if (!keepError) forbidden.value = false
          return null
        }
        state.value = 'error'
        error.value = failure(response, 'loadFailed')
        return null
      }
      const keep = preserveDraft || initialStamp !== stamp.value
      apply(response.data, keep)
      if (!keepError) forbidden.value = false
      if (keep && previousVersion !== response.data.version && !keepError) {
        needsReview.value = true
        error.value = { key: 'conflict', detail: '', path: '' }
      }
      return response.data
    } catch (failureResponse) {
      if (disposed || owner !== generation || request !== readId) return null
      state.value = 'error'
      error.value = failure(failureResponse, 'loadFailed')
      return null
    }
  }
  async function readHistory(append = false) {
    if (!current.value || historyLoading.value || disposed) return
    const owner = generation,
      request = ++historyId,
      scheduleId = current.value.public_id
    const cursor = append ? historyCursor.value : null
    historyLoading.value = true
    historyError.value = false
    try {
      const response = await apiClient.get(
        scoutEndpoints.scheduleOccurrences(jobId.value),
        { limit: 50, ...(cursor ? { cursor } : {}) },
        true,
        quiet,
      )
      if (
        disposed ||
        owner !== generation ||
        request !== historyId ||
        current.value?.public_id !== scheduleId
      )
        return
      if (!response.success) {
        historyError.value = true
        return
      }
      const rows = response.data.occurrences || []
      history.value = append
        ? [...new Map([...history.value, ...rows].map((row) => [row.public_id, row])).values()]
        : rows
      historyCursor.value = response.data.next_cursor || null
    } catch {
      if (!disposed && owner === generation && request === historyId) historyError.value = true
    } finally {
      if (request === historyId) historyLoading.value = false
    }
  }
  async function reload() {
    const data = await read({ preserveDraft: dirty.value })
    if (data) {
      historyId++
      historyLoading.value = false
      await readHistory()
    }
  }
  function resolveConflict(serverValues) {
    if (!current.value) return
    if (serverValues) Object.assign(draft, scheduleValues(current.value))
    needsReview.value = false
    error.value = null
  }
  async function write({ bindPlan = false, disableOnly = false } = {}) {
    if (
      disposed ||
      !jobId.value ||
      !canWrite.value ||
      (disableOnly && !current.value) ||
      (!current.value && !candidateReady.value)
    )
      return
    if (!disableOnly && (!validScheduleDraft(draft) || (bindPlan && !candidateReady.value))) return
    const owner = generation,
      id = jobId.value,
      existing = current.value
    const body = disableOnly
      ? { expected_version: existing.version, enabled: false }
      : scheduleWrite(draft, existing, plan.value, bindPlan)
    if (writeMatchesSchedule(existing, body)) return
    writing.value = true
    saved.value = false
    error.value = null
    const preserve = disableOnly && dirty.value
    try {
      const response = await (existing
        ? apiClient.patch(scoutEndpoints.schedule(id), body, true, quiet)
        : apiClient.post(scoutEndpoints.schedule(id), body, true, quiet)
      ).catch((cause) => ({
        success: false,
        status: cause?.response?.status,
        data: cause?.response?.data,
        message: cause?.message,
      }))
      if (disposed || owner !== generation) return
      if (response.success) {
        apply(response.data, preserve)
        if (disableOnly) draft.enabled = false
        saved.value = true
        historyId++
        historyLoading.value = false
        await readHistory()
        return
      }
      const problem = failure(response, 'saveFailed')
      if (problem.status === 403 || problem.status === 401) forbidden.value = true
      if (problem.code === 'schedule_changed' || problem.code === 'schedule_exists') {
        await read({ preserveDraft: true, keepError: true })
        if (disposed || owner !== generation) return
        needsReview.value = !!current.value
        error.value = { ...problem, key: 'conflict' }
      } else if (!problem.status || problem.status >= 500) await reconcile(body, owner)
      else error.value = problem
    } finally {
      if (owner === generation) writing.value = false
    }
  }
  async function reconcile(body, owner) {
    const data = await read({ preserveDraft: true, keepError: true })
    if (disposed || owner !== generation) return
    if (writeMatchesSchedule(data, body)) {
      for (const key of ['enabled', 'local_time', 'timezone'])
        if (key in body) draft[key] = body[key]
      saved.value = true
      error.value = null
      return
    }
    if (data) needsReview.value = true
    error.value = { key: 'uncertain', detail: '', path: '' }
  }
  watch(
    jobId,
    () => {
      generation++
      readId++
      historyId++
      current.value = null
      state.value = 'idle'
      writing.value = false
      needsReview.value = false
      error.value = null
      forbidden.value = false
      saved.value = false
      history.value = []
      historyCursor.value = null
      historyError.value = false
      historyLoading.value = false
      let timezone = 'UTC'
      try {
        timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
      } catch {
        /* Use an explicit UTC default. */
      }
      initialValues.value = { local_time: '09:00', timezone, enabled: false }
      Object.assign(draft, initialValues.value)
      if (jobId.value) reload()
    },
    { immediate: true, flush: 'sync' },
  )
  onUnmounted(() => {
    disposed = true
    generation++
    readId++
    historyId++
  })
  return {
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
  }
}
