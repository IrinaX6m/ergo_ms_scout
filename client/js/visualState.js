export function visualPlanStamp(form) {
  return JSON.stringify({
    url: form.url.trim(),
    recordMode: form.recordMode,
    recordKind: form.recordKind,
    recordSelector: form.recordSelector,
    fields: form.fields,
  })
}

export function matchSummary(result) {
  const rows = result?.rows || []
  return {
    matches: rows.reduce((sum, row) => sum + (Number(row.match_count) || 0), 0),
    missing: rows.filter((row) => row.match_count === 0).length,
    multiple: rows.some((row) => row.match_count > 1),
    nodeIds: [
      ...new Set(
        rows.flatMap((row) =>
          result.field ? row.match_node_ids || [] : row.node_id ? [row.node_id] : [],
        ),
      ),
    ],
  }
}
