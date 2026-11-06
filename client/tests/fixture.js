// Isolated browser fixture: real Scout UI, core controls and router, simulated API only.
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory, RouterView } from 'vue-router'
import '@/scss/styles.scss'
import '@/js/utils/logger.js'
import NotificationProvider from '@/components/NotificationProvider.vue'
import { ensureBootLocales, i18n } from '@/i18n/index.js'
import { initTheme } from '@/js/theme-manager.js'
import { apiClient } from '@/js/api/manager'
import ScoutPage from '../components/ScoutPage.vue'
import locales from '../js/locales.js'
import '../styles/scout-workflow.scss'
import { installVisualFixture } from './visual-fixture.js'

const jobId = '11111111-1111-4111-8111-111111111111'
const runId = '22222222-2222-4222-8222-222222222222'
const fixture = {
  calls: [],
  systemOpened: 0,
  failAction: '',
  networkDown: false,
  deferNextRecords: false,
  releaseRecords: null,
  pauseStatus: 'pausing',
  run: null,
  job: null,
  setStatus(status) {
    this.run.status = status
  },
}
const clone = (value) => JSON.parse(JSON.stringify(value))
const result = (data) => ({ success: true, data: clone(data) })
const rows = () =>
  Array.from({ length: 25 }, (_, index) => ({
    public_id: `record-${index + 1}`,
    values: {
      title: { raw: `Событие ${index + 1}`, normalized: `Событие ${index + 1}` },
      count: { raw: 0, normalized: 0 },
    },
    evidence: [
      {
        field_path: 'title',
        source_url: 'https://events.example/list',
        locator: '.title',
        raw_value: `Событие ${index + 1}`,
      },
    ],
  }))

apiClient.get = async (url) => {
  fixture.calls.push(['get', url])
  if (fixture.networkDown) throw new Error('Fixture network interruption')
  if (url.endsWith('/records/')) {
    if (fixture.deferNextRecords) {
      fixture.deferNextRecords = false
      await new Promise((resolve) => {
        fixture.releaseRecords = resolve
      })
    }
    return result({ records: rows() })
  }
  if (url.startsWith('scout/jobs/')) return result(fixture.job)
  if (url.startsWith('scout/runs/')) return result(fixture.run)
  return result({})
}
apiClient.patch = async (url, body) => {
  fixture.calls.push(['patch', url])
  fixture.job = {
    public_id: jobId,
    title: body.title,
    revision: { ...clone(body), plan_hash: 'fixture-plan', approved: false },
  }
  return result(fixture.job)
}
apiClient.post = async (url, body) => {
  fixture.calls.push(['post', url])
  if (url === 'scout/jobs/') return apiClient.patch(`scout/jobs/${jobId}/`, body)
  if (url.endsWith('/explore/')) {
    fixture.run = {
      public_id: runId,
      job_public_id: jobId,
      plan_hash: 'fixture-plan',
      approved: false,
      status: 'awaiting_confirmation',
      record_count: 0,
      snapshot_count: 1,
      preview: rows().slice(0, 3),
      tasks: [],
      events: [],
      journal: [],
      crawl: { mode: 'pages' },
    }
    return result(fixture.run)
  }
  const action = url.split('/').filter(Boolean).at(-1)
  if (fixture.failAction === action) {
    fixture.failAction = ''
    return { success: false, message: 'Fixture rejection' }
  }
  if (action === 'approve') fixture.run.approved = true
  if (action === 'start') {
    fixture.run.status = 'running'
    fixture.run.record_count = 25
  }
  if (action === 'pause') fixture.run.status = fixture.pauseStatus
  if (action === 'resume') fixture.run.status = 'running'
  if (action === 'cancel') fixture.run.status = 'cancelled'
  return result(fixture.run || {})
}
installVisualFixture(apiClient, fixture, result)
window.__scoutTest = fixture
window.addEventListener('ergo:open-user-settings', () => {
  fixture.systemOpened += 1
})
await ensureBootLocales()
i18n.global.locale.value = 'ru'
Object.entries(locales).forEach(([locale, messages]) =>
  i18n.global.mergeLocaleMessage(locale, messages),
)
initTheme()
const router = createRouter({
  history: createWebHashHistory(),
  routes: [{ path: '/:pathMatch(.*)*', component: ScoutPage }],
})
const app = createApp({ render: () => h('div', [h(RouterView), h(NotificationProvider)]) })
app.use(createPinia()).use(i18n).use(router)
await router.isReady()
app.mount('#app')
