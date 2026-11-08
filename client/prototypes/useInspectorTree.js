import { computed, onUnmounted, ref, watch } from 'vue'
import { apiClient } from '@/js/api/manager'

export const nodeLabel = (node) =>
  node
    ? `${node.tag || node.rendered_tag}${node.element_id ? '#' + node.element_id : ''}${(node.classes || []).map((value) => '.' + value).join('')}`
    : ''

// UX-004 interaction prototype; metadata and selection always use API-004 IDs/version.
export function useInspectorTree(snapshot, enabled) {
  const nodes = ref({})
  const branches = ref({})
  const expanded = ref(new Set())
  const detail = ref(null)
  const searchResult = ref(null)
  const query = ref('')
  const searching = ref(false)
  const loading = ref(false)
  const error = ref('')
  const invalid = ref(false)
  const nodeCount = ref(0)
  let generation = 0,
    selection = 0,
    searchRequest = 0,
    disposed = false
  const branchRequests = new Map()
  const quiet = { quietStatuses: [400, 403, 404, 409, 422, 429, 500, 503] }
  const version = computed(() => snapshot.value?.tree_version)
  const base = () => `scout/visual-snapshots/${snapshot.value.public_id}/tree/`
  function reset() {
    generation++
    selection++
    searchRequest++
    nodes.value = {}
    branches.value = {}
    expanded.value = new Set()
    detail.value = null
    searchResult.value = null
    query.value = ''
    error.value = ''
    invalid.value = false
    loading.value = false
    searching.value = false
    nodeCount.value = 0
    branchRequests.clear()
  }
  async function request(method, endpoint, body, owner) {
    try {
      const response = await apiClient[method](endpoint, body, true, quiet)
      if (disposed || owner !== generation || !enabled.value) return null
      if (!response.success) {
        error.value =
          response.status === 409
            ? 'versionChanged'
            : response.status === 404
              ? 'unavailable'
              : 'treeFailed'
        if ([404, 409].includes(response.status)) {
          invalid.value = true
          detail.value = null
          nodes.value = {}
          branches.value = {}
          expanded.value = new Set()
          searchResult.value = null
        }
        return null
      }
      if (
        response.data.tree_version !== version.value ||
        response.data.snapshot_public_id !== snapshot.value?.public_id
      ) {
        error.value = 'versionChanged'
        invalid.value = true
        detail.value = null
        nodes.value = {}
        branches.value = {}
        expanded.value = new Set()
        searchResult.value = null
        return null
      }
      return response.data
    } catch {
      if (!disposed && owner === generation) error.value = 'treeFailed'
      return null
    }
  }
  function remember(items) {
    const copy = { ...nodes.value }
    items.forEach((item) => {
      copy[item.node_id] = item
    })
    nodes.value = copy
  }
  async function branch(parent = null, cursor = null, around = null, owner = generation) {
    if (!version.value || invalid.value) return
    const key = parent || 'root',
      requestId = (branchRequests.get(key) || 0) + 1
    branchRequests.set(key, requestId)
    const params = {
      tree_version: version.value,
      limit: 30,
      ...(parent ? { parent_id: parent } : {}),
      ...(cursor ? { cursor } : around ? { around_node_id: around } : {}),
    }
    const data = await request('get', base(), params, owner)
    if (!data || branchRequests.get(key) !== requestId) return
    remember(data.items)
    branches.value = { ...branches.value, [parent || 'root']: data }
    if (data.node_count !== undefined) nodeCount.value = data.node_count
    return data
  }
  async function toggle(id) {
    const owner = generation
    const next = new Set(expanded.value)
    if (next.has(id)) next.delete(id)
    else {
      next.add(id)
      if (!branches.value[id]) await branch(id)
    }
    if (owner === generation) expanded.value = next
  }
  async function select(id) {
    if (!version.value || invalid.value) return
    const owner = generation,
      current = ++selection
    loading.value = true
    const data = await request(
      'get',
      `${base()}nodes/${encodeURIComponent(id)}/`,
      { tree_version: version.value },
      owner,
    )
    if (!data || current !== selection || owner !== generation) {
      if (current === selection) loading.value = false
      return
    }
    detail.value = data
    remember([...data.ancestors, data.node])
    for (const node of [...data.ancestors, data.node]) {
      if (owner !== generation || current !== selection) return
      if (node.parent_id) expanded.value = new Set([...expanded.value, node.parent_id])
      const existing = branches.value[node.parent_id || 'root']
      if (!existing?.items.some((item) => item.node_id === node.node_id))
        await branch(node.parent_id, null, node.node_id, owner)
    }
    if (current === selection) loading.value = false
  }
  async function search(cursor = null) {
    if (!query.value.trim()) {
      searchResult.value = null
      searchRequest++
      return
    }
    const owner = generation,
      current = ++searchRequest
    searching.value = true
    const data = await request(
      'post',
      `${base()}search/`,
      {
        q: query.value.trim(),
        tree_version: version.value,
        limit: 20,
        ...(cursor ? { cursor } : {}),
      },
      owner,
    )
    if (current === searchRequest && owner === generation) {
      searchResult.value = data
      if (data) remember(data.items)
      searching.value = false
    }
  }
  watch(query, () => {
    searchRequest++
    searching.value = false
    searchResult.value = null
  })
  const visible = computed(() => {
    const result = []
    function visit(parent) {
      const page = branches.value[parent || 'root']
      for (const item of page?.items || []) {
        result.push(item)
        if (expanded.value.has(item.node_id)) visit(item.node_id)
      }
    }
    visit(null)
    return result
  })
  async function move(direction) {
    const node = detail.value?.node
    if (!node) return
    if (direction === 'parent') {
      if (node.parent_id) await select(node.parent_id)
      return
    }
    if (direction === 'child') {
      const data = branches.value[node.node_id] || (await branch(node.node_id))
      if (data?.items.length) await select(data.items[0].node_id)
      return
    }
    let page = branches.value[node.parent_id || 'root']
    let index = page?.items.findIndex((item) => item.node_id === node.node_id)
    const delta = direction === 'previous' ? -1 : 1
    if (index !== undefined && page?.items[index + delta])
      return select(page.items[index + delta].node_id)
    const cursor = delta < 0 ? page?.previous_cursor : page?.next_cursor
    if (cursor) {
      page = await branch(node.parent_id, cursor)
      if (page?.items.length)
        await select(page.items[delta < 0 ? page.items.length - 1 : 0].node_id)
    }
  }
  watch(
    [() => snapshot.value?.public_id, version, enabled],
    async () => {
      reset()
      if (enabled.value && snapshot.value?.status === 'ready') {
        if (!version.value) {
          error.value = 'treeFailed'
          return
        }
        loading.value = true
        const owner = generation
        await branch()
        if (owner === generation) loading.value = false
      }
    },
    { immediate: true, flush: 'sync' },
  )
  onUnmounted(() => {
    disposed = true
    reset()
  })
  function clearSelection() {
    selection++
    detail.value = null
    loading.value = false
  }
  return {
    setQuery: (value) => {
      query.value = value
    },
    nodes,
    branches,
    expanded,
    detail,
    searchResult,
    query,
    searching,
    loading,
    error,
    invalid,
    nodeCount,
    visible,
    branch,
    toggle,
    select,
    search,
    move,
    clearSelection,
  }
}
