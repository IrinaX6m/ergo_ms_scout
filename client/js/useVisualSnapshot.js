import { onUnmounted, ref, watch } from 'vue'
import { apiClient } from '@/js/api/manager'
import { scoutEndpoints } from './endpoints.js'
import { validSource } from './workflowState.js'

// A URL/mode change invalidates every pending response, including check requests.
export function useVisualSnapshot(url, enabled) {
  const snapshot = ref(null)
  const status = ref('idle')
  const error = ref(null)
  const checking = ref(false)
  let generation = 0
  let checkRequest = 0
  let timer = 0
  let disposed = false
  const quiet = { quietStatuses: [400, 403, 404, 409, 429, 500, 502, 503] }

  function invalidate() {
    generation += 1
    checkRequest += 1
    window.clearTimeout(timer)
    snapshot.value = null
    status.value = 'idle'
    error.value = null
    checking.value = false
  }
  function fail(response) {
    const code = response.status || response.response?.status
    const data = response.data || response.response?.data
    error.value = {
      key:
        code === 404
          ? 'expired'
          : code === 409 && data?.code === 'tree_version_changed'
            ? 'versionChanged'
            : code === 429
              ? 'rateLimit'
              : 'requestFailed',
      detail: data?.detail || response.message || '',
    }
    if (code === 404 || (code === 409 && data?.code === 'tree_version_changed')) {
      status.value = 'expired'
      snapshot.value = null
      window.clearTimeout(timer)
    }
  }
  async function poll(id, owner) {
    try {
      const response = await apiClient.get(scoutEndpoints.visualSnapshot(id), {}, true, quiet)
      if (disposed || owner !== generation || !enabled.value) return
      if (!response.success) {
        fail(response)
        if (status.value !== 'expired') status.value = 'failed'
        return
      }
      snapshot.value = response.data
      status.value = response.data.status
      if (status.value === 'loading') timer = window.setTimeout(() => poll(id, owner), 1500)
      if (status.value === 'failed')
        error.value = { key: 'loadFailed', detail: response.data.error?.detail || '' }
    } catch (failure) {
      if (disposed || owner !== generation) return
      fail(failure)
      status.value = 'failed'
    }
  }
  async function load() {
    if (!enabled.value) return
    invalidate()
    if (!validSource(url.value)) {
      error.value = { key: 'invalidUrl' }
      return
    }
    const owner = generation
    status.value = 'loading'
    try {
      const response = await apiClient.post(
        scoutEndpoints.visualSnapshots,
        { url: url.value.trim() },
        true,
        quiet,
      )
      if (disposed || owner !== generation || !enabled.value) return
      if (!response.success) {
        fail(response)
        status.value = 'failed'
        return
      }
      snapshot.value = response.data
      await poll(response.data.public_id, owner)
    } catch (failure) {
      if (disposed || owner !== generation) return
      fail(failure)
      status.value = 'failed'
    }
  }
  function invalidateCheck() {
    checkRequest += 1
    checking.value = false
  }
  async function check(body) {
    if (status.value !== 'ready' || !snapshot.value || !enabled.value) return null
    const owner = generation
    const request = ++checkRequest
    const id = snapshot.value.public_id
    checking.value = true
    error.value = null
    try {
      const response = await apiClient.post(
        scoutEndpoints.checkVisualSnapshot(id),
        body,
        true,
        quiet,
      )
      if (disposed || owner !== generation || request !== checkRequest || !enabled.value)
        return null
      if (!response.success) {
        fail(response)
        return null
      }
      return response.data
    } catch (failure) {
      if (!disposed && owner === generation && request === checkRequest) fail(failure)
      return null
    } finally {
      if (request === checkRequest) checking.value = false
    }
  }
  watch([url, enabled], invalidate, { flush: 'sync' })
  onUnmounted(() => {
    disposed = true
    invalidate()
  })
  return { snapshot, status, error, checking, load, check, invalidateCheck }
}
