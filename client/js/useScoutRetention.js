import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { apiClient } from '@/js/api/manager'
import { scoutEndpoints as endpoints } from './endpoints.js'
import {
  cleanupRequest,
  currentPreview,
  policyValues,
  previewSelection,
  validPolicy,
} from './retentionState.js'

const quiet = { quietStatuses: [400, 401, 403, 404, 409, 410, 429, 500, 502, 503, 504] }
const pendingKey = 'scout.retention.pending-cleanup'
export function useScoutRetention(jobId, runId, cleanupId, onCleanup) {
  const policy = ref(null),
    draft = reactive({}),
    policyState = ref('loading'),
    policyError = ref(null),
    policyReview = ref(false)
  const runState = ref(null),
    runError = ref(null),
    holdIntent = ref(null),
    holdError = ref(null),
    holdUnavailable = ref([])
  const ownerScope = ref(!jobId.value),
    scopes = ref(['html', 'exports']),
    preview = ref(null),
    previewError = ref(null),
    previewLoading = ref(false)
  const previewItems = ref([]),
    previewCursor = ref(null),
    itemsError = ref(null),
    itemsLoading = ref(false)
  const cleanup = ref(null),
    cleanupError = ref(null),
    cleanupItems = ref([]),
    cleanupCursor = ref(null),
    cleanupItemsError = ref(null),
    cleanupItemsLoading = ref(false),
    pending = ref(null)
  const busy = ref(false),
    now = ref(Date.now()),
    saved = ref(false)
  let context = 0,
    disposed = false,
    policyRead = 0,
    runRead = 0,
    previewRead = 0,
    itemsRead = 0,
    cleanupRead = 0,
    cleanupItemsRead = 0,
    timer = null,
    clock = null
  const contextStamp = computed(() => JSON.stringify([jobId.value, runId.value]))
  const policyStamp = computed(() => JSON.stringify(draft))
  const dirty = computed(
    () => !!policy.value && policyStamp.value !== JSON.stringify(policyValues(policy.value)),
  )
  const selection = computed(() =>
    previewSelection(policy.value?.version, ownerScope.value ? '' : jobId.value, scopes.value),
  )
  const selectionStamp = computed(() => JSON.stringify(selection.value))
  const canPreview = computed(
    () =>
      policyState.value === 'ready' &&
      !policyReview.value &&
      !dirty.value &&
      !busy.value &&
      !pending.value &&
      selection.value.scopes.length > 0,
  )
  const canExecute = computed(
    () =>
      policyState.value === 'ready' &&
      !policyReview.value &&
      !busy.value &&
      !pending.value &&
      !itemsLoading.value &&
      !itemsError.value &&
      currentPreview(preview.value, policy.value, dirty.value, now.value),
  )
  function active(version) {
    return !disposed && version === context
  }
  async function request(method, url, body = {}, config = {}) {
    try {
      // Keep token refresh/error handling in the shared client. DELETE needs a JSON body, not query params.
      return await apiClient._request(
        method,
        url,
        method === 'DELETE' ? {} : body,
        true,
        method === 'DELETE' ? { ...config, data: body } : config,
        quiet,
      )
    } catch (error) {
      return {
        success: false,
        status: error.response?.status,
        data: error.response?.data,
        message: error.message,
      }
    }
  }
  function problem(response, fallback = 'requestFailed') {
    const data = response.data || {}
    return {
      key:
        response.status === 401 || response.status === 403
          ? 'forbidden'
          : response.status === 404
            ? 'notFound'
            : response.status === 410
              ? 'expired'
              : data.code || fallback,
      detail: data.detail || response.message || '',
      status: response.status,
    }
  }
  function invalidatePreview() {
    previewRead++
    itemsRead++
    preview.value = null
    previewItems.value = []
    previewCursor.value = null
    previewLoading.value = false
    itemsLoading.value = false
    previewError.value = null
    itemsError.value = null
  }
  async function loadPolicy(preserve = false) {
    const version = context,
      read = ++policyRead,
      stamp = policyStamp.value,
      previous = policy.value?.version
    policyState.value = 'loading'
    policyError.value = null
    saved.value = false
    const response = await request('GET', endpoints.retentionPolicy)
    if (!active(version) || read !== policyRead) return
    if (!response.success) {
      policyState.value = 'error'
      policyError.value = problem(response)
      return
    }
    const keep = preserve || stamp !== policyStamp.value
    if (previous !== response.data.version) invalidatePreview()
    policy.value = response.data
    policyState.value = 'ready'
    if (!keep) Object.assign(draft, policyValues(response.data))
    if (keep && previous && previous !== response.data.version) policyReview.value = true
  }
  function choosePolicy(server) {
    if (server && policy.value) Object.assign(draft, policyValues(policy.value))
    policyReview.value = false
    policyError.value = null
  }
  async function savePolicy() {
    if (
      disposed ||
      busy.value ||
      policyState.value !== 'ready' ||
      policyReview.value ||
      !validPolicy(draft)
    )
      return
    const version = context,
      body = { ...policyValues(draft), expected_version: policy.value.version }
    busy.value = true
    policyError.value = null
    saved.value = false
    invalidatePreview()
    const response = await request('PATCH', endpoints.retentionPolicy, body)
    if (!active(version)) return
    if (response.success) {
      policy.value = response.data
      Object.assign(draft, policyValues(response.data))
      saved.value = true
    } else {
      policyError.value = problem(response)
      if (response.status === 409 || !response.status || response.status >= 500) {
        await loadPolicy(true)
        if (active(version)) {
          policyReview.value = true
          policyError.value = problem(response, !response.status ? 'uncertain' : 'requestFailed')
        }
      }
    }
    if (active(version)) busy.value = false
  }
  async function loadRun() {
    if (!runId.value) {
      runState.value = null
      return
    }
    const version = context,
      read = ++runRead
    runError.value = null
    const response = await request('GET', endpoints.runRetention(runId.value))
    if (!active(version) || read !== runRead) return
    if (response.success) runState.value = response.data
    else runError.value = problem(response)
  }
  async function changeHold(scope, retry = false) {
    if (disposed || !runState.value || busy.value) return
    const version = context
    if (!retry)
      holdIntent.value = {
        run: runId.value,
        method: scope ? 'PUT' : 'DELETE',
        body: { expected_version: runState.value.hold.version, ...(scope ? { scope } : {}) },
        key: crypto.randomUUID(),
      }
    const intent = holdIntent.value
    if (!intent || intent.run !== runId.value) return
    busy.value = true
    holdError.value = null
    invalidatePreview()
    const response = await request(
      intent.method,
      endpoints.retentionHold(intent.run),
      intent.body,
      { headers: { 'Idempotency-Key': intent.key } },
    )
    if (!active(version)) return
    if (response.success) {
      holdIntent.value = null
      holdUnavailable.value = response.data?.unavailable || []
      await loadRun()
    } else {
      holdError.value = problem(response)
      if (response.status && response.status < 500) holdIntent.value = null
      holdUnavailable.value = response.data?.unavailable || []
      await loadRun()
    }
    if (active(version)) busy.value = false
  }
  async function createPreview() {
    if (disposed || !canPreview.value) return
    invalidatePreview()
    const version = context,
      read = ++previewRead,
      stamp = selectionStamp.value
    previewLoading.value = true
    const response = await request('POST', endpoints.retentionPreviews, selection.value)
    if (!active(version) || read !== previewRead || stamp !== selectionStamp.value) return
    previewLoading.value = false
    if (response.success) {
      preview.value = response.data
      await loadPreviewItems()
    } else {
      previewError.value = problem(response)
      if (response.data?.code === 'retention_policy_changed') await loadPolicy(true)
    }
  }
  async function loadPreviewItems(append = false) {
    if (!preview.value || itemsLoading.value) return
    const version = context,
      read = ++itemsRead,
      id = preview.value.preview_public_id
    itemsLoading.value = true
    itemsError.value = null
    const response = await request('GET', endpoints.retentionPreviewItems(id), {
      limit: 50,
      ...(append && previewCursor.value ? { cursor: previewCursor.value } : {}),
    })
    if (!active(version) || read !== itemsRead || preview.value?.preview_public_id !== id) return
    itemsLoading.value = false
    if (response.success) {
      previewItems.value = append
        ? [...previewItems.value, ...response.data.items]
        : response.data.items
      previewCursor.value = response.data.next_cursor || null
    } else itemsError.value = problem(response)
  }
  function persistPending() {
    try {
      if (pending.value)
        sessionStorage.setItem(
          pendingKey + ':' + contextStamp.value,
          JSON.stringify({ context: contextStamp.value, body: pending.value }),
        )
      else sessionStorage.removeItem(pendingKey + ':' + contextStamp.value)
    } catch {
      /* In-memory retry still keeps the same idempotency key. */
    }
  }
  async function execute(retry = false) {
    if (disposed || busy.value || (!retry && !canExecute.value)) return
    if (!retry) {
      pending.value = cleanupRequest(preview.value, crypto.randomUUID())
      persistPending()
    }
    const body = pending.value
    if (!body) return
    const version = context
    busy.value = true
    cleanupError.value = null
    const response = await request('POST', endpoints.retentionCleanups, body)
    if (!active(version)) return
    if (response.success) {
      cleanupItemsRead++
      cleanupItemsLoading.value = false
      cleanupItems.value = []
      cleanupCursor.value = null
      cleanup.value = response.data
      pending.value = null
      persistPending()
      invalidatePreview()
      onCleanup(response.data.cleanup_public_id)
      await loadCleanupItems()
      schedulePoll()
    } else {
      cleanupError.value = problem(response, !response.status ? 'uncertain' : 'requestFailed')
      if (response.status && response.status < 500) {
        pending.value = null
        persistPending()
        if (response.status === 400 || response.status === 409) invalidatePreview()
      }
    }
    if (active(version)) busy.value = false
  }
  function schedulePoll() {
    clearTimeout(timer)
    if (cleanup.value && ['queued', 'running'].includes(cleanup.value.status))
      timer = setTimeout(() => loadCleanup(cleanup.value.cleanup_public_id), 5000)
  }
  async function loadCleanup(id = cleanupId.value) {
    if (!id) return
    clearTimeout(timer)
    const version = context,
      read = ++cleanupRead
    const response = await request('GET', endpoints.retentionCleanup(id))
    if (!active(version) || read !== cleanupRead) return
    if (response.success) {
      cleanupError.value = null
      cleanup.value = response.data
      await loadCleanupItems()
      schedulePoll()
    } else cleanupError.value = problem(response)
  }
  async function loadCleanupItems(append = false) {
    if (!cleanup.value || cleanupItemsLoading.value) return
    const version = context,
      read = ++cleanupItemsRead,
      id = cleanup.value.cleanup_public_id
    cleanupItemsLoading.value = true
    cleanupItemsError.value = null
    const response = await request('GET', endpoints.retentionCleanupItems(id), {
      limit: 50,
      ...(append && cleanupCursor.value ? { cursor: cleanupCursor.value } : {}),
    })
    if (!active(version) || read !== cleanupItemsRead || cleanup.value?.cleanup_public_id !== id)
      return
    cleanupItemsLoading.value = false
    if (response.success) {
      cleanupItems.value = append
        ? [...cleanupItems.value, ...response.data.items]
        : response.data.items
      cleanupCursor.value = response.data.next_cursor || null
    } else cleanupItemsError.value = problem(response)
  }
  watch(
    [policyStamp, selectionStamp],
    () => {
      saved.value = false
      invalidatePreview()
    },
    { flush: 'sync' },
  )
  watch(
    contextStamp,
    () => {
      context++
      policyRead++
      runRead++
      cleanupRead++
      cleanupItemsRead++
      clearTimeout(timer)
      policy.value = null
      policyState.value = 'loading'
      Object.keys(draft).forEach((key) => delete draft[key])
      policyReview.value = false
      policyError.value = null
      saved.value = false
      busy.value = false
      runState.value = null
      runError.value = null
      holdError.value = null
      holdUnavailable.value = []
      holdIntent.value = null
      ownerScope.value = !jobId.value
      scopes.value = ['html', 'exports']
      invalidatePreview()
      cleanup.value = null
      cleanupError.value = null
      cleanupItems.value = []
      cleanupCursor.value = null
      cleanupItemsError.value = null
      cleanupItemsLoading.value = false
      pending.value = null
      try {
        const stored = JSON.parse(
          sessionStorage.getItem(pendingKey + ':' + contextStamp.value) || 'null',
        )
        if (stored?.context === contextStamp.value && stored.body?.idempotency_key)
          pending.value = stored.body
      } catch {
        /* Ignore an unavailable or invalid local retry record. */
      }
      loadPolicy()
      loadRun()
      if (cleanupId.value) loadCleanup(cleanupId.value)
    },
    { immediate: true, flush: 'sync' },
  )
  watch(cleanupId, (id) => {
    if (id && id !== cleanup.value?.cleanup_public_id) {
      cleanupRead++
      cleanupItemsRead++
      cleanupItemsLoading.value = false
      cleanupItems.value = []
      cleanupCursor.value = null
      loadCleanup(id)
    }
  })
  clock = setInterval(() => {
    now.value = Date.now()
  }, 1000)
  onUnmounted(() => {
    disposed = true
    context++
    clearTimeout(timer)
    clearInterval(clock)
  })
  return {
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
  }
}
