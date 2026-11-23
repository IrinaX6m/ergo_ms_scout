export function optionForm(plan = {}) {
  const crawl = plan.crawl || {}
  return {
    proxyRevision: plan.proxy_profile_revision_public_id || '',
    identityKind: plan.identity?.kind || '',
    identityNamespace: plan.identity?.namespace || '',
    identityField: plan.identity?.field || '',
    sitemapUrl: crawl.sitemap_url || '',
    additionalPreviewUrls: (crawl.preview_urls || []).slice(1).join('\n'),
    sitemapFromRobots: !!crawl.sitemap_from_robots,
    pageTypes: (crawl.page_types || []).map((type) => ({
      ...type,
      match: type.match.map((rule) => ({ ...rule })),
      selectorsText: JSON.stringify(type.selectors || {}, null, 2),
    })),
  }
}
export function optionPayload(form) {
  return {
    proxy_profile_revision_public_id: form.proxyRevision || null,
    ...(form.identityKind
      ? {
          identity: {
            kind: form.identityKind,
            namespace: form.identityNamespace.trim(),
            ...(form.identityKind !== 'url' ? { field: form.identityField } : {}),
          },
        }
      : {}),
  }
}
export function crawlOptions(form) {
  if (form.crawlMode !== 'site') return {}
  const pageTypes = (form.pageTypes || []).map(
    ({ selectorsText, selectors: _selectors, ...type }) => {
      let selectors
      try {
        selectors = JSON.parse(selectorsText || '{}')
        if (selectors && typeof selectors === 'object' && !Array.isArray(selectors))
          selectors = Object.fromEntries(
            Object.entries(selectors).filter(([, rule]) => rule?.selector?.trim()),
          )
      } catch {
        selectors = selectorsText
      }
      return { ...type, ...(type.action === 'extract' ? { selectors } : {}) }
    },
  )
  return {
    ...(pageTypes.length ? { page_types: pageTypes, extract_on: [] } : {}),
    ...(form.sitemapUrl.trim() ? { sitemap_url: form.sitemapUrl.trim() } : {}),
    sitemap_from_robots: form.sitemapFromRobots,
    preview_urls: [form.previewUrl, ...(form.additionalPreviewUrls || '').split(/\r?\n/)]
      .map((value) => (value || '').trim())
      .filter(Boolean),
  }
}
