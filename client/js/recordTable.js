export function displayValue(cell, missing) {
  if (Array.isArray(cell?.images))
    return cell.images.map((image) => image.source_url).filter(Boolean).join(', ') || missing
  const typed = cell?.typed
  if (typed?.status === 'ok') {
    if (typed.type === 'money') return `${typed.value.amount} ${typed.value.currency}`
    return String(typed.value)
  }
  const value = cell?.normalized ?? cell?.raw ?? ''
  return String(value).trim() || missing
}

export function flattenValues(values, id, missing) {
  const row = { id }
  Object.entries(values || {}).forEach(([key, cell]) => {
    row[key] = displayValue(cell, missing)
  })
  return row
}
