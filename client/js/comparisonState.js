export const COMPARISON_STATUSES = [
  'changed',
  'unchanged',
  'uncertain',
  'added',
  'not_seen_before',
  'not_seen',
  'not_checked',
]
export function validRunId(value) {
  return (
    typeof value === 'string' &&
    /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value)
  )
}
export function resultLink(id, origin) {
  return validRunId(id) ? new URL('/scout?run=' + id, origin).href : ''
}
export function runFromResultLink(value, origin) {
  if (typeof value !== 'string' || value.length > 4096 || !value.trim()) return null
  try {
    const url = new URL(value.trim(), origin)
    if (
      url.origin !== new URL(origin).origin ||
      !['/scout', '/scout/', '/scout/ux-004'].includes(url.pathname) ||
      url.searchParams.getAll('run').length !== 1
    )
      return null
    const id = url.searchParams.get('run')
    return validRunId(id) ? id.toLowerCase() : null
  } catch {
    return null
  }
}
export function compatibleRunMetadata(base, target) {
  return (
    !!base &&
    !!target &&
    base.public_id !== target.public_id &&
    base.job_public_id === target.job_public_id &&
    base.plan_hash === target.plan_hash &&
    [base, target].every((run) => ['completed', 'completed_with_errors'].includes(run.status))
  )
}
export function comparisonParams(base, field, cursor) {
  return { base_run_public_id: base, field, limit: 50, ...(cursor ? { cursor } : {}) }
}
export function safeEvidenceLink(value) {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password
      ? url.href
      : null
  } catch {
    return null
  }
}
