export function blankField(scope = 'page') {
  return { name: '', kind: 'css', selector: '', scope, many: false }
}

export function optionForm(plan = {}) {
  const crawl = plan.crawl || {}
  const fields = plan.fields?.length
    ? plan.fields.map((field) => ({ ...blankField(), ...field }))
    : [blankField()]
  const pageTypes = (crawl.page_types || []).map(({ id, action, match, selectors }) => {
    const type = { id, action, match: match.map((rule) => ({ ...rule })) }
    for (const field of fields) {
      if (selectors && Object.hasOwn(selectors, field.name))
        setTypeSelector(field, type, selectors[field.name])
    }
    return type
  })
  return {
    fields,
    pageTypes,
    extractionMode: pageTypes.length ? 'types' : 'filter',
    extractRules: crawl.extract_on || [],
    extractPrefix: crawl.extract_on?.[0]?.pattern || '',
    proxyRevision: plan.proxy_profile_revision_public_id || '',
    identityKind: plan.identity?.kind || '',
    identityNamespace: plan.identity?.namespace || '',
    identityField: plan.identity?.field || '',
    sitemapUrl: crawl.sitemap_url || '',
    additionalPreviewUrls: (crawl.preview_urls || []).slice(1).join('\n'),
    sitemapFromRobots: !!crawl.sitemap_from_robots,
  }
}

// The field and page type can both be renamed while editing.
export function setTypeSelector(field, type, updates) {
  field.typeSelectors ??= new WeakMap()
  const existing = field.typeSelectors.get(type) || { kind: field.kind, selector: '' }
  field.typeSelectors.set(type, { ...existing, ...updates })
}

export function updateRule(rules = [], firstPattern) {
  const [first, ...otherRules] = rules
  const pattern = firstPattern.trim()
  return pattern ? [{ kind: first?.kind || 'prefix', pattern }, ...otherRules] : otherRules
}

export function addPageType(form) {
  let number = 1
  while (form.pageTypes.some((type) => type.id === `type_${number}`)) number++
  const rules = form.pageTypes.length ? [] : updateRule(form.extractRules, form.extractPrefix)
  form.pageTypes.push({
    id: `type_${number}`,
    action: 'extract',
    match: rules.length ? rules.map((rule) => ({ ...rule })) : [{ kind: 'prefix', pattern: '/' }],
  })
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
  const typeOptions = {}
  if (form.extractionMode === 'types') {
    typeOptions.extract_on = []
    typeOptions.page_types = form.pageTypes.map((type) => {
      if (type.action !== 'extract') return type
      const selectors = Object.fromEntries(
        form.fields
          .map((field) => [field.name.trim(), field.typeSelectors?.get(type)])
          .filter(([name, rule]) => name && rule?.selector.trim()),
      )
      return { ...type, selectors }
    })
  }
  return {
    ...typeOptions,
    ...(!form.sitemapFromRobots && form.sitemapUrl.trim()
      ? { sitemap_url: form.sitemapUrl.trim() }
      : {}),
    sitemap_from_robots: form.sitemapFromRobots,
    preview_urls: [form.previewUrl, ...(form.additionalPreviewUrls || '').split(/\r?\n/)]
      .map((value) => (value || '').trim())
      .filter(Boolean),
  }
}
