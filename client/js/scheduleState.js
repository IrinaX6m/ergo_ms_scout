export const OCCURRENCE_STATUSES = [
  'preparing',
  'running',
  'completed',
  'completed_with_errors',
  'failed',
  'cancelled',
  'skipped',
]
export const OCCURRENCE_REASONS = [
  'local_time_missing',
  'missed',
  'slot_busy',
  'superseded',
  'permission_revoked',
  'plan_unapproved',
  'proxy_revoked',
]
export function scheduleValues(value = {}) {
  return {
    local_time: value.local_time || '09:00',
    timezone: value.timezone || 'UTC',
    enabled: value.enabled === true,
  }
}
export function approvedSchedulePlan(plan, dirty = false) {
  return !!(!dirty && plan?.approved === true && plan.public_id && plan.plan_hash)
}
export function sameSchedulePlan(schedule, plan) {
  return (
    !!schedule &&
    !!plan &&
    schedule.plan_revision_public_id === plan.public_id &&
    schedule.plan_hash === plan.plan_hash
  )
}
export function validScheduleDraft(draft) {
  return (
    /^([01]\d|2[0-3]):[0-5]\d$/.test(draft.local_time) &&
    !!draft.timezone.trim() &&
    draft.timezone.trim().length <= 80
  )
}
export function scheduleWrite(draft, current, plan, bindPlan = false) {
  const body = { ...scheduleValues(draft), timezone: draft.timezone.trim() }
  if (current) body.expected_version = current.version
  if (!current || bindPlan) {
    body.plan_revision_public_id = plan.public_id
    body.plan_hash = plan.plan_hash
  }
  return body
}
export function writeMatchesSchedule(schedule, body) {
  return (
    !!schedule &&
    Object.entries(body).every(
      ([key, value]) => key === 'expected_version' || schedule[key] === value,
    )
  )
}
export function scheduleMoment(value, timezone, locale = 'ru') {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  try {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: timezone,
    }).format(date)
  } catch {
    return value
  }
}
export function scheduleDate(value, locale = 'ru') {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return value || '—'
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(
    new Date(value + 'T12:00:00Z'),
  )
}
