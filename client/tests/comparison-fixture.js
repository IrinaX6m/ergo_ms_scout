export function installComparisonFixture(api, fixture) {
  const baseId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    targetId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    job = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
  const clone = (value) => JSON.parse(JSON.stringify(value)),
    ok = (data) => ({ success: true, data: clone(data) }),
    fail = (status, code) => ({
      success: false,
      status,
      data: { code, detail: 'Fixture response' },
    })
  const state = (fixture.comparison = {
    baseId,
    targetId,
    calls: [],
    error: 0,
    incompatible: false,
    partial: false,
    stopReason: 'max_pages',
    empty: false,
    uncertain: false,
    defer: false,
    release: null,
  })
  const previous = api.get.bind(api)
  const value = (amount) => ({
    raw: amount + ' ₽',
    normalized: amount + ' ₽',
    typed: { status: 'ok', type: 'money', value: { amount, currency: 'RUB' } },
  })
  const side = (amount, tag) => ({
    record_public_id: 'record-' + tag,
    state: 'ok',
    value: value(amount),
    evidence: [
      {
        field_path: 'price',
        source_url: 'https://catalog.example/' + tag,
        locator: '.price',
        raw_value: amount + ' ₽',
        normalized_value: amount + ' ₽',
        snapshot_public_id: 'snapshot-' + tag,
        rules_revision_public_id: 'revision-one',
        selected: true,
        html_availability: 'expired',
      },
    ],
  })
  api.get = async (url, params = {}, ...args) => {
    if (!url.includes(baseId) && !url.includes(targetId) && !url.includes(job))
      return previous(url, params, ...args)
    state.calls.push([url, clone(params)])
    if (state.error)
      return fail(
        state.error,
        state.error === 410
          ? 'comparison_data_expired'
          : state.error === 409
            ? 'comparison_incompatible'
            : state.error === 400
              ? 'invalid_comparison'
              : 'unavailable',
      )
    if (url.endsWith('/compare/')) {
      const response = {
        job_public_id: job,
        field: params.field,
        base: {
          run_public_id: baseId,
          status: 'completed',
          completeness: 'complete',
          stop_reason: '',
          failed_tasks: 0,
          record_count: 3,
          unkeyed_records: 1,
        },
        target: {
          run_public_id: targetId,
          status: state.partial ? 'completed_with_errors' : 'completed',
          completeness: state.partial ? 'partial' : 'complete',
          stop_reason: state.partial ? state.stopReason : '',
          failed_tasks: state.partial ? 1 : 0,
          record_count: 4,
          unkeyed_records: 1,
        },
        counts: {
          changed: state.empty ? 0 : 1,
          unchanged: state.empty ? 3 : 1,
          uncertain: 0,
          added: state.empty ? 0 : 1,
          not_seen_before: 0,
          not_seen: 0,
          not_checked: state.partial ? 1 : 0,
        },
        changes: state.empty
          ? []
          : params.cursor
            ? [
                {
                  entity_key: 'new-item',
                  key: { kind: 'field', value: 'EXTERNAL-03' },
                  status: state.partial ? 'not_checked' : 'added',
                  before: state.partial ? side('990.00', 'base-missing') : null,
                  after: state.partial ? null : side('1490.00', 'new'),
                },
              ]
            : [
                {
                  entity_key: 'changed-item',
                  sku: 'K-01',
                  status: 'changed',
                  before: side('1250.00', 'before'),
                  after: side('1350.00', 'after'),
                },
              ],
        next_cursor: state.empty || params.cursor ? null : 'next-change',
      }
      if (response.changes.length && !params.cursor) {
        if (params.field === 'zero') {
          response.changes[0].before.value = {
            raw: '0',
            normalized: '0',
            typed: { type: 'integer', status: 'ok', value: 0 },
          }
          response.changes[0].after.value = {
            raw: '1',
            normalized: '1',
            typed: { type: 'integer', status: 'ok', value: 1 },
          }
        }
        if (state.uncertain) {
          response.counts.changed = 0
          response.counts.uncertain = 1
          response.changes[0].status = 'uncertain'
          response.changes[0].before.state = 'conflict'
          response.changes[0].after.state = 'invalid'
          response.changes[0].after.value = {
            raw: 'не число',
            normalized: 'не число',
            typed: { type: 'money', status: 'invalid', value: null, error: 'invalid_money' },
          }
        }
      }
      if (state.defer) {
        state.defer = false
        await new Promise((resolve) => {
          state.release = () => {
            state.release = null
            resolve()
          }
        })
      }
      return ok(response)
    }
    if (url.startsWith('scout/jobs/'))
      return ok({
        public_id: job,
        title: 'Сравнение: обозначенный каталог',
        revision: {
          plan_hash: 'same-plan',
          fields: [
            { name: 'price', many: false },
            { name: 'zero', many: false },
            { name: 'many', many: true },
          ],
        },
      })
    return ok({
      public_id: url.includes(baseId) ? baseId : targetId,
      job_public_id:
        state.incompatible && url.includes(baseId) ? 'cccccccc-cccc-4ccc-8ccc-cccccccccccc' : job,
      plan_hash: state.incompatible && url.includes(baseId) ? 'other-plan' : 'same-plan',
      status: 'completed',
      record_count: 3,
    })
  }
}
