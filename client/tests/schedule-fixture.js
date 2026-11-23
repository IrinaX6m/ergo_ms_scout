// Deliberately simulated schedule API; no automatic jobs are started by these tests.
export function installScheduleFixture(api, fixture, context) {
  const clone = (value) => JSON.parse(JSON.stringify(value))
  const ok = (data) => ({ success: true, data: clone(data) })
  const fail = (status, code, detail = '') => ({ success: false, status, data: { code, detail } })
  const state = (fixture.schedule = {
    context,
    current: null,
    calls: [],
    error: 0,
    conflict: false,
    unknown: false,
    defer: false,
    release: null,
    historyFail: false,
  })
  for (const method of ['get', 'post', 'patch']) {
    const previous = api[method]
    api[method] = async (url, body = {}, ...args) => {
      if (!url.includes('/schedule/')) return previous(url, body, ...args)
      state.calls.push([method, url, clone(body)])
      if (method === 'get') {
        if (url.endsWith('/occurrences/')) {
          if (state.historyFail) return fail(503, 'unavailable')
          return ok({
            occurrences: [
              {
                public_id: body.cursor ? 'day-older' : 'day-newest',
                schedule_version: 1,
                local_date: body.cursor ? '2026-10-25' : '2026-10-26',
                scheduled_at: body.cursor ? null : '2026-10-26T06:00:00Z',
                processed_at: '2026-10-26T06:15:01Z',
                status: 'skipped',
                reason: body.cursor ? 'local_time_missing' : 'slot_busy',
                run_public_id: body.cursor ? 'run-history' : null,
              },
            ],
            next_cursor: body.cursor ? null : 'older-days',
          })
        }
        const captured = state.current ? ok(state.current) : fail(404, 'not_found')
        if (state.defer) {
          state.defer = false
          await new Promise((resolve) => {
            state.release = () => {
              state.release = null
              resolve()
            }
          })
        }
        if (state.error) return fail(state.error, 'denied')
        return captured
      }
      if (state.error) return fail(state.error, 'denied')
      if (state.conflict && state.current) {
        state.conflict = false
        state.current.version++
        state.current.local_time = '12:00'
        return fail(409, 'schedule_changed')
      }
      if (method === 'post' && state.current) return fail(409, 'schedule_exists')
      if (method === 'patch' && body.expected_version !== state.current?.version)
        return fail(409, 'schedule_changed')
      state.current = {
        public_id: 'schedule-one',
        job_public_id: context.jobId,
        start_window_seconds: 900,
        ...state.current,
        ...clone(body),
        version: (state.current?.version || 0) + 1,
      }
      delete state.current.expected_version
      state.current.next_scheduled_at = state.current.enabled ? '2026-11-24T06:00:00Z' : null
      if (state.unknown) {
        state.unknown = false
        throw new Error('Response lost after server committed')
      }
      return ok(state.current)
    }
  }
}
