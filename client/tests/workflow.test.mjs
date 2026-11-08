import assert from 'node:assert/strict'
import test from 'node:test'
import { fieldProblems, planMatchesRun, validSource, workflowStage } from '../js/workflowState.js'
import { displayValue, flattenValues } from '../js/recordTable.js'
import workspaceLocales from '../js/workspaceLocales.js'
import visualLocales from '../js/visualLocales.js'
import inspectorLocales from '../prototypes/inspectorLocales.js'
import { matchSummary, visualPlanStamp } from '../js/visualState.js'

test('a preview and confirmation remain separate from running collection', () => {
  const run = { status: 'awaiting_confirmation', approved: false }
  assert.equal(workflowStage(run, 'source', false, ''), 'preview')
  assert.equal(workflowStage(run, 'source', true, ''), 'confirm')
  assert.equal(workflowStage({ ...run, approved: true }, 'source', null, ''), 'confirm')
  assert.equal(workflowStage({ ...run, approved: true }, 'source', false, ''), 'preview')
  assert.equal(workflowStage({ status: 'running' }, 'mode', true, ''), 'collect')
})

test('pending cancellation does not show a returned editor or completed run', () => {
  assert.equal(workflowStage({ status: 'cancelling' }, 'source', false, 'editor'), 'preview')
  assert.equal(workflowStage({ status: 'pausing' }, 'source', false, ''), 'collect')
  assert.equal(workflowStage({ status: 'paused' }, 'source', false, ''), 'collect')
  assert.equal(workflowStage({ status: 'cancelled' }, 'source', false, ''), 'result')
})

test('a loaded job, exact revision and unchanged draft are required to start', () => {
  const run = { status: 'awaiting_confirmation', job_public_id: 'job-a', plan_hash: 'revision-a' }
  assert.equal(planMatchesRun(run, 'job-a', 'revision-a', 'draft-a', 'draft-a'), true)
  for (const [job, hash, draft, saved] of [
    ['', 'revision-a', 'draft-a', 'draft-a'],
    ['job-b', 'revision-a', 'draft-a', 'draft-a'],
    ['job-a', 'revision-b', 'draft-a', 'draft-a'],
    ['job-a', '', 'draft-a', 'draft-a'],
    ['job-a', 'revision-a', 'draft-b', 'draft-a'],
    ['job-a', 'revision-a', '', ''],
  ])
    assert.equal(planMatchesRun(run, job, hash, draft, saved), false)
  assert.equal(
    planMatchesRun({ ...run, status: 'running' }, 'job-a', 'revision-a', 'draft-a', 'draft-a'),
    false,
  )
})

test('only complete HTTP(S) URLs pass client validation', () => {
  assert.equal(validSource(' https://example.com/events '), true)
  assert.equal(validSource('http://example.com'), true)
  for (const url of [
    '',
    'http-not-a-url',
    'https://',
    'javascript:alert(1)',
    'file:///tmp/a',
    'ftp://example.com',
  ])
    assert.equal(validSource(url), false)
})

test('duplicate fields cannot silently replace each other in result values', () => {
  assert.deepEqual(
    fieldProblems([
      { name: 'title', selector: 'h1' },
      { name: ' title ', selector: 'h2' },
    ]),
    ['duplicate', 'duplicate'],
  )
  assert.deepEqual(
    fieldProblems([
      { name: '', selector: 'h1' },
      { name: 'date', selector: '' },
    ]),
    ['required', 'required'],
  )
})

test('zero and false are values, while an empty string is missing', () => {
  assert.equal(displayValue({ normalized: 0, raw: 7 }, 'missing'), '0')
  assert.equal(displayValue({ normalized: false }, 'missing'), 'false')
  assert.equal(displayValue({ normalized: '' }, 'missing'), 'missing')
  assert.deepEqual(flattenValues({ count: { raw: 0 } }, 'row-a', 'missing'), {
    id: 'row-a',
    count: '0',
  })
})

test('new interface keys exist in all supported languages', () => {
  const keys = (object, prefix = '') =>
    Object.entries(object)
      .flatMap(([key, value]) =>
        typeof value === 'object' ? keys(value, `${prefix}${key}.`) : `${prefix}${key}`,
      )
      .sort()
  assert.deepEqual(keys(workspaceLocales.en), keys(workspaceLocales.ru))
  assert.deepEqual(keys(workspaceLocales.fr), keys(workspaceLocales.ru))
  assert.deepEqual(keys(visualLocales.en), keys(visualLocales.ru))
  assert.deepEqual(keys(visualLocales.fr), keys(visualLocales.ru))
  assert.deepEqual(keys(inspectorLocales.en), keys(inspectorLocales.ru))
  assert.deepEqual(keys(inspectorLocales.fr), keys(inspectorLocales.ru))
})

test('visual validation preserves missing rows and detects ambiguous single fields', () => {
  const result = {
    field: { name: 'price' },
    rows: [
      { match_count: 0, match_node_ids: [] },
      { match_count: 2, match_node_ids: ['n1', 'n2'] },
      { match_count: 1, match_node_ids: ['n2'] },
    ],
  }
  assert.deepEqual(matchSummary(result), {
    matches: 3,
    missing: 1,
    multiple: true,
    nodeIds: ['n1', 'n2'],
  })
  assert.deepEqual(matchSummary({ rows: [{ node_id: 'n3' }] }).nodeIds, ['n3'])
})

test('visual acceptance is invalidated by source, card and field changes', () => {
  const form = {
    url: 'https://example.com/',
    recordMode: 'cards',
    recordKind: 'css',
    recordSelector: 'article',
    fields: [{ name: 'price', selector: '.price', scope: 'record' }],
  }
  const stamp = visualPlanStamp(form)
  for (const changes of [
    { url: 'https://other.example/' },
    { recordSelector: 'li' },
    { fields: [{ name: 'price', selector: '.other', scope: 'record' }] },
  ])
    assert.notEqual(visualPlanStamp({ ...form, ...changes }), stamp)
})
