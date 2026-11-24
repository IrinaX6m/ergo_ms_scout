export const RETENTION_SCOPES = ['html', 'results', 'exports', 'visual_snapshots']
export const POLICY_DAYS = ['html_days', 'result_days', 'export_days']
export const TOTAL_COUNTS = [
  'runs_with_result_deletion',
  'records',
  'evidence',
  'html_files',
  'export_files',
  'visual_snapshots',
]
export const BYTE_COUNTS = [
  'file_bytes_reclaimable',
  'visual_body_bytes',
  'database_bytes_estimate',
]
export const PROTECTION_REASONS = [
  'active_run',
  'open_tasks',
  'latest_results',
  'hold',
  'operation_in_progress',
  'shared_blob',
]
export function policyValues(policy) {
  return Object.fromEntries(
    [...POLICY_DAYS, 'keep_latest_results', 'automatic_enabled'].map((key) => [key, policy[key]]),
  )
}
export function validPolicy(draft) {
  return (
    typeof draft.automatic_enabled === 'boolean' &&
    POLICY_DAYS.every(
      (key) =>
        draft[key] === null ||
        (Number.isInteger(draft[key]) && draft[key] >= 1 && draft[key] <= 3650),
    ) &&
    Number.isInteger(draft.keep_latest_results) &&
    draft.keep_latest_results >= 2 &&
    draft.keep_latest_results <= 100 &&
    (draft.result_days === null ||
      ['html_days', 'export_days'].every(
        (key) => draft[key] === null || draft[key] <= draft.result_days,
      ))
  )
}
export function previewSelection(policyVersion, job, scopes) {
  return {
    policy_version: policyVersion,
    ...(job ? { job_public_id: job } : {}),
    scopes: RETENTION_SCOPES.filter(
      (key) => scopes.includes(key) && (!job || key !== 'visual_snapshots'),
    ),
  }
}
export function currentPreview(preview, policy, dirty, now = Date.now()) {
  return (
    !!preview &&
    typeof preview.preview_public_id === 'string' &&
    !!preview.preview_public_id &&
    typeof preview.manifest_hash === 'string' &&
    !!preview.manifest_hash &&
    preview.executable === true &&
    !dirty &&
    preview.policy_version === policy?.version &&
    Number.isFinite(Date.parse(preview.expires_at)) &&
    now < Date.parse(preview.expires_at)
  )
}
export function cleanupRequest(preview, key) {
  return {
    preview_public_id: preview.preview_public_id,
    manifest_hash: preview.manifest_hash,
    idempotency_key: key,
  }
}
export function retentionCount(value, locale = 'ru') {
  return typeof value === 'number' && Number.isFinite(value)
    ? new Intl.NumberFormat(locale).format(value)
    : '—'
}
export function retentionBytes(value, locale = 'ru') {
  return typeof value === 'number' && Number.isFinite(value)
    ? new Intl.NumberFormat(locale, { style: 'unit', unit: 'byte', unitDisplay: 'short' }).format(
        value,
      )
    : '—'
}
