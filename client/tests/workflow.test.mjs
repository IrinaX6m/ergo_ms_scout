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


test('advanced plan options preserve proxy, page types and explicit identity', async () => {
  const { optionForm, optionPayload, crawlOptions } = await import('../js/planOptions.js')
  const plan = {
    proxy_profile_revision_public_id: 'proxy-v1',
    identity: { kind: 'field', namespace: 'catalog', field: 'title' },
    fields: [{ name: 'title', kind: 'css', selector: 'h1' }],
    crawl: {
      page_types: [{
        id: 'product', action: 'extract', match: [{ kind: 'contains', pattern: 'item' }],
        selectors: { title: { kind: 'css', selector: 'h2' } },
      }],
      sitemap_url: 'https://example.org/sitemap.xml',
    },
  }
  const form = { ...optionForm(plan), crawlMode: 'site' }
  assert.deepEqual(optionPayload(form), {
    proxy_profile_revision_public_id: 'proxy-v1', identity: plan.identity,
  })
  assert.deepEqual(crawlOptions(form).page_types, plan.crawl.page_types)
  assert.equal(crawlOptions(form).sitemap_url, plan.crawl.sitemap_url)
  form.sitemapFromRobots = true
  assert.equal(crawlOptions(form).sitemap_from_robots, true)
  assert.equal('sitemap_url' in crawlOptions(form), false)
  form.sitemapFromRobots = false
  assert.equal(crawlOptions(form).sitemap_url, plan.crawl.sitemap_url)
  assert.deepEqual(crawlOptions({ ...form, crawlMode: 'pages' }), {})
  assert.deepEqual(optionPayload({ ...form, proxyRevision: '', identityKind: '' }), {
    proxy_profile_revision_public_id: null,
  })
})

test('switching extraction modes preserves all saved URL rules and page type edits', async () => {
  const { addPageType, crawlOptions, optionForm, updateRule } = await import('../js/planOptions.js')
  const rules = [{ kind: 'prefix', pattern: '/sale' }, { kind: 'contains', pattern: 'outlet' }]
  const form = { ...optionForm({ crawl: { extract_on: rules } }), crawlMode: 'site' }
  assert.equal(form.extractionMode, 'filter')
  addPageType(form)
  form.extractionMode = 'types'
  assert.deepEqual(crawlOptions(form).page_types[0].match, rules)
  assert.deepEqual(crawlOptions(form).extract_on, [])
  form.pageTypes[0].match[1].pattern = 'discount'
  form.extractionMode = 'filter'
  assert.equal('page_types' in crawlOptions(form), false)
  assert.deepEqual(updateRule(form.extractRules, form.extractPrefix), rules)
  form.extractionMode = 'types'
  assert.equal(crawlOptions(form).page_types[0].match[1].pattern, 'discount')
})

test('type selectors follow each field through renaming, removal and reuse of its name', async () => {
  const { addPageType, crawlOptions, optionForm, setTypeSelector } = await import('../js/planOptions.js')
  const form = { ...optionForm(), crawlMode: 'site', extractionMode: 'types' }
  const [field] = form.fields
  field.name = 'price'
  addPageType(form)
  const [type] = form.pageTypes
  setTypeSelector(field, type, { selector: '.sale-price' })
  field.name = ''
  form.fields.push({ name: 'price', kind: 'css' })
  field.name = 'cost'
  type.id = 'discount'
  assert.deepEqual(crawlOptions(form).page_types[0].selectors, {
    cost: { kind: 'css', selector: '.sale-price' },
  })
  form.fields.shift()
  assert.deepEqual(crawlOptions(form).page_types[0].selectors, {})
})
test('typed values preserve exact amounts, zero, dates and invalid raw text', () => {
  assert.equal(displayValue({typed:{type:'integer',status:'ok',value:0}},'missing'),'0')
  assert.equal(displayValue({typed:{type:'money',status:'ok',value:{amount:'1234.50',currency:'RUB'}}},'missing'),'1234.50 RUB')
  assert.equal(displayValue({normalized:'31.02.2026',typed:{type:'date',status:'invalid',value:null,error:{code:'invalid_date'}}},'missing'),'31.02.2026')
  assert.equal(displayValue({typed:{type:'date',status:'ok',value:'2026-11-06'}},'missing'),'2026-11-06')
})
test('product copy has matching translation keys', async () => {
  const {default: locales} = await import('../js/productLocales.js')
  const keys = object => Object.entries(object).flatMap(([key,value])=> typeof value === 'object' ? keys(value).map(child=>key+'.'+child) : [key]).sort()
  assert.deepEqual(keys(locales.ru),keys(locales.en))
  assert.deepEqual(keys(locales.ru),keys(locales.fr))
})


test('daily schedules require an approved unchanged plan and keep the pinned revision until explicit rebind', async () => {
  const {approvedSchedulePlan,scheduleWrite,writeMatchesSchedule,validScheduleDraft} = await import('../js/scheduleState.js')
  const plan={public_id:'new-revision',plan_hash:'new-hash',approved:true}
  assert.equal(approvedSchedulePlan(plan),true)
  for(const [value,dirty] of [[plan,true],[{...plan,approved:false},false],[{...plan,public_id:''},false],[{...plan,plan_hash:''},false]]) assert.equal(approvedSchedulePlan(value,dirty),false)
  const draft={local_time:'09:00',timezone:' Europe/Moscow ',enabled:true}
  const current={version:7,plan_revision_public_id:'old-revision',plan_hash:'old-hash'}
  const edited=scheduleWrite(draft,current,plan)
  assert.deepEqual(edited,{local_time:'09:00',timezone:'Europe/Moscow',enabled:true,expected_version:7})
  assert.deepEqual(scheduleWrite(draft,current,plan,true),{...edited,plan_revision_public_id:'new-revision',plan_hash:'new-hash'})
  assert.deepEqual(scheduleWrite(draft,null,plan),{local_time:'09:00',timezone:'Europe/Moscow',enabled:true,plan_revision_public_id:'new-revision',plan_hash:'new-hash'})
  assert.equal(writeMatchesSchedule({...edited,version:8},edited),true)
  assert.equal(writeMatchesSchedule({...edited,enabled:false},edited),false)
  assert.equal(writeMatchesSchedule(null,edited),false)
  for(const local_time of ['24:00','12:60','9:00','']) assert.equal(validScheduleDraft({...draft,local_time}),false)
  assert.equal(validScheduleDraft(draft),true)
})

test('schedule dates stay on the local calendar day and all server states have translated labels', async () => {
  const {scheduleDate,scheduleMoment,OCCURRENCE_STATUSES,OCCURRENCE_REASONS}=await import('../js/scheduleState.js')
  const {default:locales}=await import('../js/scheduleLocales.js')
  assert.equal(scheduleDate('2026-10-25','en'),'Oct 25, 2026')
  assert(scheduleMoment('2026-10-26T06:00:00Z','Europe/Moscow','en').includes('9:00'))
  assert.equal(scheduleMoment(null,'Europe/Moscow'),'—')
  for(const locale of ['ru','en','fr']) {
    assert.deepEqual(Object.keys(locales[locale]).sort(),Object.keys(locales.ru).sort())
    for(const status of OCCURRENCE_STATUSES) assert(locales[locale].statuses[status])
    for(const reason of OCCURRENCE_REASONS) assert(locales[locale].reasons[reason])
  }
})


test('retention policy validates finite/null periods and result bundle consistency',async()=>{
 const {validPolicy,policyValues}=await import('../js/retentionState.js')
 const policy={version:4,html_days:30,result_days:365,export_days:7,keep_latest_results:2,automatic_enabled:false,visual_snapshot_hours:1}
 assert(validPolicy(policy));assert(validPolicy({...policy,result_days:null}));assert(validPolicy({...policy,html_days:null,export_days:null}))
 for(const change of [{html_days:0},{html_days:''},{export_days:1.5},{result_days:20},{keep_latest_results:1},{keep_latest_results:101},{automatic_enabled:'false'}])assert.equal(validPolicy({...policy,...change}),false)
 assert.equal('version' in policyValues(policy),false);assert.equal('visual_snapshot_hours' in policyValues(policy),false)
})

test('retention cleanup uses a current server manifest and the same explicit request key',async()=>{
 const {previewSelection,currentPreview,cleanupRequest,retentionBytes,retentionCount}=await import('../js/retentionState.js')
 assert.deepEqual(previewSelection(3,'job',['results','visual_snapshots','html']),{policy_version:3,job_public_id:'job',scopes:['html','results']})
 const preview={preview_public_id:'preview',manifest_hash:'server-hash',policy_version:3,executable:true,expires_at:'2026-11-23T20:15:00Z'}
 const now=Date.parse('2026-11-23T20:00:00Z')
 assert(currentPreview(preview,{version:3},false,now));assert.equal(currentPreview(preview,{version:4},false,now),false);assert.equal(currentPreview(preview,{version:3},true,now),false);assert.equal(currentPreview({...preview,executable:false},{version:3},false,now),false);assert.equal(currentPreview(preview,{version:3},false,Date.parse(preview.expires_at)),false)
 assert.deepEqual(cleanupRequest(preview,'stable-key'),{preview_public_id:'preview',manifest_hash:'server-hash',idempotency_key:'stable-key'})
 assert.equal(retentionBytes(null),'—');assert.equal(retentionCount(0),'0')
})

test('all retention UI labels and server protection reasons have translations',async()=>{
 const {default:locales}=await import('../js/retentionLocales.js')
 function keys(value,prefix=''){return Object.entries(value).flatMap(([key,child])=>typeof child==='object'?keys(child,prefix+key+'.'):[prefix+key]).sort()}
 assert.deepEqual(keys(locales.ru),keys(locales.en));assert.deepEqual(keys(locales.ru),keys(locales.fr))
 const {RETENTION_SCOPES,PROTECTION_REASONS}=await import('../js/retentionState.js')
 for(const lang of Object.values(locales)){for(const scope of RETENTION_SCOPES)assert(lang.scopes[scope]);for(const reason of PROTECTION_REASONS)assert(lang.reasons[reason])}
})
