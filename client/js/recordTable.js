export function displayValue(cell, missing) {
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
