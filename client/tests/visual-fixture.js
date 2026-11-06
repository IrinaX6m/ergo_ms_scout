// Deterministic API-002 boundary fixture; live acceptance uses the real server separately.
export function installVisualFixture(apiClient, fixture, result) {
  const originalGet = apiClient.get
  const originalPost = apiClient.post
  fixture.visual = { count: 0, error: 0, failed: false, defer: '', release: null }
  const visual = fixture.visual
  const html =
    '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; base-uri &#39;none&#39;; form-action &#39;none&#39;"></head><body>' +
    Array.from(
      { length: 20 },
      (_, index) =>
        `<article data-scout-node="n${index * 3 + 1}"><h3 data-scout-node="n${index * 3 + 2}">Book ${index + 1}</h3><p data-scout-node="n${index * 3 + 3}">£51.77</p></article>`,
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
  apiClient.get = async (url, ...args) => {
    if (!url.startsWith('scout/visual-snapshots/')) return originalGet(url, ...args)
    fixture.calls.push(['get', url])
    const data = visual.failed
      ? { status: 'failed', error: { code: 'not_html', detail: 'Fixture not HTML' } }
      : { status: 'ready', html, final_url: 'https://books.toscrape.com/' }
    return defer(
      'get',
      visual.error ? error() : result({ public_id: `visual-${visual.count}`, ...data }),
    )
  }
  apiClient.post = async (url, body, ...args) => {
    if (!url.startsWith('scout/visual-snapshots/')) return originalPost(url, body, ...args)
    fixture.calls.push(['post', url, JSON.parse(JSON.stringify(body))])
    if (url === 'scout/visual-snapshots/') {
      visual.count += 1
      return defer('create', result({ public_id: `visual-${visual.count}`, status: 'loading' }))
    }
    if (visual.error) return error()
    const record = body.record
      ? { kind: 'css', selector: body.record.selector || 'article.product_pod' }
      : null
    const field = body.field
      ? { ...body.field, kind: 'css', selector: body.field.selector || '.price_color' }
      : null
    if (field) delete field.node_id
    const count = field?.selector === '.absent' ? 0 : field?.selector === 'p' ? 2 : 1
    const rows = Array.from({ length: record ? 20 : 1 }, (_, index) => ({
      node_id: record ? `n${index * 3 + 1}` : null,
      ...(field
        ? {
            match_count: count,
            match_node_ids: count ? [`n${index * 3 + 3}`] : [],
            value: count ? { raw: '£51.77', normalized: '£51.77' } : null,
          }
        : {}),
    }))
    return defer('check', result({ record, field, row_count: record ? 20 : 1, rows }))
  }
}
