export const WORKFLOW_STEPS = ['mode', 'source', 'preview', 'confirm', 'collect', 'result']
export const ACTIVE_STATUSES = ['exploring', 'running', 'pausing', 'cancelling']
export const TERMINAL_STATUSES = ['cancelled', 'completed', 'completed_with_errors', 'failed']
export const EXPORTABLE_STATUSES = ['completed', 'completed_with_errors']

export function workflowStage(run, editorStep, confirmationOpen, returning) {
  if (!run?.status) return editorStep
  if (returning || run.status === 'exploring') return 'preview'
  if (run.status === 'awaiting_confirmation') {
    return (confirmationOpen ?? run.approved) ? 'confirm' : 'preview'
  }
  if (['running', 'pausing', 'paused', 'cancelling'].includes(run.status)) return 'collect'
  return 'result'
}

export function planMatchesRun(run, jobId, revisionHash, draft, saved) {
  return Boolean(
    run?.status === 'awaiting_confirmation' &&
    jobId &&
    jobId === run.job_public_id &&
    revisionHash &&
    revisionHash === run.plan_hash &&
    saved &&
    draft === saved,
  )
}

export function validSource(value) {
  try {
    const url = new URL(value.trim())
    return ['http:', 'https:'].includes(url.protocol) && Boolean(url.hostname)
  } catch {
    return false
  }
}

export function fieldProblems(fields) {
  const counts = new Map()
  fields.forEach((field) => {
    const name = field.name.trim()
    counts.set(name, (counts.get(name) || 0) + 1)
  })
  return fields.map((field) => {
    if (!field.name.trim() || !field.selector.trim()) return 'required'
    if (counts.get(field.name.trim()) > 1) return 'duplicate'
    return ''
  })
}
