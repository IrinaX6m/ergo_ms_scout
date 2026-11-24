// Deterministic API-002 boundary fixture; live acceptance uses the real server separately.
export function installVisualFixture(apiClient, fixture, result) {
  const originalGet = apiClient.get
  const originalPost = apiClient.post
  const originalDownload = apiClient.downloadFile.bind(apiClient)
  fixture.visual = { count: 0, error: 0, failed: false, defer: '', release: null, redirects: {} }
  const visual = fixture.visual
  const snapshotUrls = new Map()
  const version = 'dom-v1:' + 'a'.repeat(64)
  const nodes = Array.from({ length: 60 }, (_, index) => ({
    node_id: `n${index + 1}`,
    parent_id: index % 3 ? `n${index - (index % 3) + 1}` : null,
    child_index: index % 3 ? (index % 3) - 1 : index / 3,
    depth: index % 3 ? 1 : 0,
    children_count: index % 3 ? 0 : 2,
    tag: ['article', 'h3', 'p'][index % 3],
    rendered_tag: ['article', 'h3', 'p'][index % 3],
    element_id: null,
    classes: index % 3 === 0 ? ['product_pod'] : index % 3 === 2 ? ['price_color'] : [],
    text_preview: index % 3 === 2 ? '£51.77' : `Book ${Math.floor(index / 3) + 1}`,
    metadata_limited: false,
  }))
  nodes[0].children_count++
  nodes.push({
    ...nodes[1],
    node_id: 'n61',
    child_index: 2,
    tag: 'img',
    rendered_tag: 'span',
    text_preview: '',
  })
  const envelope = (data) =>
    result({ snapshot_public_id: `visual-${visual.count}`, tree_version: version, ...data })
  const html =
    '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; base-uri &#39;none&#39;; form-action &#39;none&#39;"></head><body>' +
    Array.from(
      { length: 20 },
      (_, index) =>
        `<article data-scout-node="n${index * 3 + 1}"><h3 data-scout-node="n${index * 3 + 2}">Book ${index + 1}</h3><p data-scout-node="n${index * 3 + 3}">£51.77</p>${index === 0 ? '<span data-scout-node="n61" data-scout-image>Изображение</span>' : ''}</article>`,
    ).join('') +
    '<script>parent.__snapshotScriptRan=true</script></body></html>'
  function defer(kind, response) {
    if (visual.defer !== kind) return response
    visual.defer = ''
    return new Promise((resolve) => {
      visual.release = () => {
        visual.release = null
        resolve(response)
      }
    })
  }
  function error() {
    return { success: false, status: visual.error, data: { detail: 'Fixture visual error' } }
  }
  apiClient.downloadFile = async (url, params, ...args) => {
    if (!/^scout\/(visual-snapshots\/[^/]+\/image|runs\/[^/]+\/images\/[^/]+)\/$/.test(url))
      return originalDownload(url, params, ...args)
    fixture.calls.push(['download', url, { ...params }])
    if (visual.imageError) return { success: false, status: visual.imageError }
    const bytes = Uint8Array.from(
      atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC'),
      (c) => c.charCodeAt(0),
    )
    return defer('image', {
      success: true,
      data: new Blob([bytes], { type: visual.imageMime || 'image/png' }),
      headers: visual.imageHeaders || {},
    })
  }
  apiClient.get = async (url, ...args) => {
    if (!url.startsWith('scout/visual-snapshots/')) return originalGet(url, ...args)
    fixture.calls.push(['get', url])
    if (url.includes('/tree/')) {
      const params = args[0] || {}
      if (visual.treeError)
        return { success: false, status: visual.treeError, data: { code: 'tree_version_changed' } }
      const id = url.match(/\/nodes\/(n\d+)\//)?.[1]
      if (id) {
        const node = nodes.find((item) => item.node_id === id)
        return defer(
          'node',
          envelope({
            node,
            ancestors: node.parent_id
              ? [nodes.find((item) => item.node_id === node.parent_id)]
              : [],
          }),
        )
      }
      const items = nodes.filter((node) => node.parent_id === (params.parent_id || null))
      return defer(
        'tree',
        envelope({
          items,
          parent_id: params.parent_id || null,
          total_count: items.length,
          node_count: nodes.length,
          previous_cursor: null,
          next_cursor: null,
        }),
      )
    }
    const publicId = url.split('/').at(-2)
    const data = visual.failed
      ? { status: 'failed', error: { code: 'not_html', detail: 'Fixture not HTML' } }
      : { status: 'ready', html, tree_version: version, final_url: snapshotUrls.get(publicId) }
    return defer(
      'get',
      visual.error ? error() : result({ public_id: publicId, ...data }),
    )
  }
  apiClient.post = async (url, body, ...args) => {
    if (!url.startsWith('scout/visual-snapshots/')) return originalPost(url, body, ...args)
    fixture.calls.push(['post', url, JSON.parse(JSON.stringify(body))])
    if (url.endsWith('/tree/search/')) {
      const items = nodes.filter((node) =>
        [node.tag, ...node.classes, node.text_preview].some((value) =>
          value.toLowerCase().includes(body.q.toLowerCase()),
        ),
      )
      const start = Number(body.cursor || 0),
        limit = body.limit || 20
      return envelope({
        items: items.slice(start, start + limit),
        total_count: items.length,
        previous_cursor: start ? String(Math.max(0, start - limit)) : null,
        next_cursor: start + limit < items.length ? String(start + limit) : null,
      })
    }
    if (url === 'scout/visual-snapshots/') {
      visual.count += 1
      const publicId = `visual-${visual.count}`
      snapshotUrls.set(publicId, visual.redirects[body.url] || body.url)
      return defer('create', result({ public_id: publicId, status: 'loading' }))
    }
    if (visual.error) return error()
    const record = body.record
      ? { kind: 'css', selector: body.record.selector || 'article.product_pod' }
      : null
    const field = body.field
      ? { ...body.field, kind: 'css', selector: body.field.selector || '.price_color' }
      : null
    if (field) {
      if (field.node_id === 'n61') {
        field.value_source = 'image'
        field.selector = 'img'
      }
      delete field.node_id
    }
    const count = field?.selector === '.absent' ? 0 : field?.selector === 'p' ? 2 : 1
    const rows = Array.from({ length: record ? 20 : 1 }, (_, index) => ({
      node_id: record ? `n${index * 3 + 1}` : null,
      ...(field
        ? {
            match_count: count,
            match_node_ids: count ? [field.value_source === 'image' ? 'n61' : `n${index * 3 + 3}`] : [],
            value: field.value_source === 'image'
              ? { images: [{ source_url: 'https://books.toscrape.com/cover.png', status: 'candidate' }] }
              : count ? { raw: '£51.77', normalized: '£51.77' } : null,
          }
        : {}),
    }))
    return defer('check', result({ record, field, row_count: record ? 20 : 1, rows }))
  }
}
