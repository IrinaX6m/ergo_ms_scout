// Explicit test data. The fixture never deletes real files or records.
export function installRetentionFixture(api, fixture) {
  const clone = (value) => JSON.parse(JSON.stringify(value)),
    ok = (data) => ({ success: true, data: clone(data) }),
    fail = (status, code) => ({
      success: false,
      status,
      data: { code, detail: 'Fixture response' },
    })
  const state = (fixture.retention = {
    calls: [],
    policy: {
      version: 1,
      automatic_enabled: false,
      html_days: 30,
      result_days: 365,
      export_days: 7,
      visual_snapshot_hours: 1,
      keep_latest_results: 2,
    },
    hold: { version: 1, scope: null },
    previewNumber: 0,
    lastScopes: [],
    previews: {},
    cleanup: null,
    accepted: new Map(),
    error: 0,
    policyConflict: false,
    holdConflict: false,
    unknownHold: false,
    holdReplies: new Map(),
    notExecutable: false,
    unknown: false,
    expire: false,
    previewConflict: false,
    itemError: false,
    defer: false,
    release: null,
    cleanupDone: false,
    cleanupRows: 1,
  })
  const previous = api._request.bind(api)
  api._request = async (method, url, body = {}, token = true, config = {}, options = {}) => {
    if (!url.includes('retention/')) return previous(method, url, body, token, config, options)
    const actualBody = method === 'DELETE' ? config.data : body
    state.calls.push([method, url, clone(actualBody), clone(config)])
    if (state.error)
      return fail(state.error, state.error === 403 ? 'forbidden' : 'storage_unavailable')
    if (url === 'scout/retention/policy/') {
      if (method === 'GET') return ok(state.policy)
      if (state.policyConflict) {
        state.policyConflict = false
        state.policy.version++
        state.policy.html_days = 25
        return fail(409, 'retention_policy_changed')
      }
      if (body.expected_version !== state.policy.version)
        return fail(409, 'retention_policy_changed')
      state.policy = { ...state.policy, ...body, version: state.policy.version + 1 }
      delete state.policy.expected_version
      return ok(state.policy)
    }
    if (url.endsWith('/retention/'))
      return ok({
        policy: state.policy,
        hold: state.hold,
        results_availability: 'available',
        html_availability: 'available',
        eligible_at: {
          html:
            state.policy.html_days === null
              ? null
              : new Date(Date.UTC(2026, 10, 23 + state.policy.html_days, 20)).toISOString(),
          results: '2027-11-23T20:00:00Z',
        },
        protected: {
          html: state.hold.scope === 'all' ? 'hold' : null,
          results: state.hold.scope ? 'hold' : 'latest_results',
          exports: null,
        },
        retained_counts: {},
      })
    if (url.endsWith('/retention/hold/')) {
      if (!config.headers?.['Idempotency-Key'] || (method === 'DELETE' && !config.data))
        return fail(400, 'invalid')
      const key = config.headers['Idempotency-Key']
      if (state.holdReplies.has(key)) return ok(state.holdReplies.get(key))
      if (state.holdConflict) {
        state.holdConflict = false
        state.hold.version++
        state.hold.scope = 'all'
        return fail(409, 'retention_hold_changed')
      }
      if (actualBody.expected_version !== state.hold.version)
        return fail(409, 'retention_hold_changed')
      state.hold = {
        version: state.hold.version + 1,
        scope: method === 'DELETE' ? null : body.scope,
      }
      const reply = { ...state.hold, unavailable: state.hold.scope === 'all' ? ['exports'] : [] }
      state.holdReplies.set(key, clone(reply))
      if (state.unknownHold) {
        state.unknownHold = false
        throw new Error('Fixture hold response lost after commit')
      }
      return ok(reply)
    }
    if (url === 'scout/retention/previews/') {
      state.lastScopes = body.scopes
      const id = 'preview-' + ++state.previewNumber,
        preview = {
          preview_public_id: id,
          policy_version: state.policy.version,
          evaluated_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + (state.expire ? 1500 : 900000)).toISOString(),
          manifest_hash: 'hash-' + id,
          executable: !state.notExecutable,
          totals: {
            runs_with_result_deletion: body.scopes.includes('results') ? 1 : 0,
            records: body.scopes.includes('results') ? 20 : 0,
            images: body.scopes.includes('results') ? 2 : 0,
            image_bytes: body.scopes.includes('results') ? 500 : 0,
            evidence: body.scopes.includes('results') ? 40 : 0,
            html_files: body.scopes.includes('results') ? 0 : 1,
            export_files: body.scopes.includes('results') ? 1 : 0,
            visual_snapshots: 0,
            file_bytes_reclaimable: state.notExecutable ? null : 1024,
            visual_body_bytes: 0,
            database_bytes_estimate: null,
          },
          protected: { latest_results: 2, shared_blob: 1 },
          warnings: state.notExecutable ? ['storage_not_verified'] : [],
        }
      state.previews[id] = preview
      if (state.defer) {
        state.defer = false
        await new Promise((resolve) => {
          state.release = () => {
            state.release = null
            resolve()
          }
        })
      }
      return ok(preview)
    }
    if (url.includes('/previews/') && url.endsWith('/items/')) {
      if (state.itemError) return fail(503, 'storage_unavailable')
      return ok({
        items: body.cursor
          ? [{ kind: 'html', public_id: 'shared-html', reason: 'shared_blob' }]
          : !state.lastScopes.includes('results')
            ? [
                { kind: 'html', public_id: 'old-html', bytes: 1024, executable: true },
                { kind: 'html', public_id: 'shared-html', reason: 'shared_blob' },
              ]
            : [
                {
                  kind: 'results',
                  public_id: 'old-run',
                  run_public_id: 'old-run',
                  records: 20,
                  evidence: 40,
                  export_files: 1,
                  comparison_will_expire: true,
                  executable: !state.notExecutable,
                  eligible_at: '2025-01-01T00:00:00Z',
                },
                {
                  kind: 'results',
                  public_id: 'new-run',
                  reason: 'latest_results',
                  run_public_id: 'new-run',
                },
              ],
        next_cursor: body.cursor ? null : 'next-items',
      })
    }
    if (url === 'scout/retention/cleanups/') {
      if (state.accepted.has(body.idempotency_key))
        return ok(state.accepted.get(body.idempotency_key))
      if (state.previewConflict) {
        state.previewConflict = false
        return fail(409, 'cleanup_preview_changed')
      }
      const preview = state.previews[body.preview_public_id]
      if (!preview || body.manifest_hash !== preview.manifest_hash)
        return fail(400, 'invalid_manifest')
      if (Date.parse(preview.expires_at) <= Date.now()) return fail(409, 'cleanup_preview_expired')
      if (!preview.executable) return fail(409, 'cleanup_preview_not_executable')
      state.cleanup = {
        cleanup_public_id: 'cleanup-one',
        status: 'queued',
        trigger: 'manual',
        deleted: {},
        skipped: {},
        failed: {},
        pending: { results: 1 },
        deleted_bytes: 0,
        deleted_rows: 0,
        errors: [],
      }
      state.accepted.set(body.idempotency_key, clone(state.cleanup))
      if (state.unknown) {
        state.unknown = false
        throw new Error('Fixture response lost after commit')
      }
      return ok(state.cleanup)
    }
    if (url.includes('/cleanups/') && url.endsWith('/items/')) {
      const offset = Number(body.cursor || 0),
        count = Math.min(body.limit, state.cleanupRows - offset)
      if (body.limit > 200) return fail(400, 'invalid_limit')
      return ok({
        items: Array.from({ length: count }, (_, index) => ({
          kind: 'results',
          public_id: 'item-' + (offset + index + 1),
          status: state.cleanupDone ? 'deleted' : 'pending',
          reason: '',
          deleted_bytes: state.cleanupDone ? 1024 : 0,
          deleted_rows: state.cleanupDone ? 60 : 0,
        })),
        next_cursor: offset + count < state.cleanupRows ? String(offset + count) : null,
      })
    }
    if (url.includes('/cleanups/')) {
      if (!state.cleanup || !url.endsWith('/' + state.cleanup.cleanup_public_id + '/'))
        return fail(404, 'notFound')
      if (state.cleanupDone)
        state.cleanup = {
          ...state.cleanup,
          status: 'completed',
          deleted: { results: 1 },
          pending: {},
          deleted_bytes: 1024,
          deleted_rows: 60,
        }
      return ok(state.cleanup)
    }
    return fail(404, 'notFound')
  }
}
