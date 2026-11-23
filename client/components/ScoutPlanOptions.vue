<script setup>
import { useId, onUnmounted, ref, reactive, watch } from 'vue'
import { apiClient } from '@/js/api/manager'
import { useAppI18n } from '@/i18n/useAppI18n.js'
const form = defineModel({ type: Object, required: true })
defineProps({ disabled: Boolean })
const uid = useId()
const { t } = useAppI18n()
const profiles = ref([]),
  busy = ref(false),
  message = ref(''),
  outcome = ref('')
const proxy = reactive({ ip: '', port: 8443, auth_type: 'none', username: '', password: '' })
const quiet = { quietStatuses: [400, 403, 404, 409, 429, 500, 502, 503] }
let generation = 0
onUnmounted(() => {
  generation++
})
watch(
  () => form.value.proxyRevision,
  () => {
    generation++
    outcome.value = ''
    message.value = ''
  },
)
watch(
  () => proxy.auth_type,
  () => {
    proxy.username = ''
    proxy.password = ''
  },
)
async function request(action) {
  if (busy.value) return
  busy.value = true
  message.value = ''
  outcome.value = ''
  const owner = generation
  try {
    let response
    if (action === 'list') response = await apiClient.get('scout/proxy-profiles/', {}, true, quiet)
    else if (action === 'create')
      response = await apiClient.post(
        'scout/proxy-profiles/',
        {
          ip: proxy.ip.trim(),
          port: Number(proxy.port),
          auth_type: proxy.auth_type,
          ...(proxy.auth_type === 'basic'
            ? { username: proxy.username, password: proxy.password }
            : {}),
        },
        true,
        quiet,
      )
    else {
      const profile = profiles.value.find(
        (item) => item.revision_public_id === form.value.proxyRevision,
      )
      if (!profile) return
      response = await apiClient.post(
        `scout/proxy-profiles/${profile.public_id}/check/`,
        {},
        true,
        quiet,
      )
    }
    if (owner !== generation) return
    if (!response.success) {
      message.value = response.data?.detail || response.message || t('scout.product.failed')
      return
    }
    if (action === 'list') profiles.value = response.data.profiles || []
    if (action === 'create') {
      profiles.value.push(response.data)
      form.value.proxyRevision = response.data.revision_public_id
    }
    if (action === 'check') {
      outcome.value = response.data.status
      message.value = response.data.code || ''
    }
  } catch {
    if (owner === generation) message.value = t('scout.product.failed')
  } finally {
    proxy.password = ''
    busy.value = false
  }
}
function loadOptions(event) {
  if (event.target === event.currentTarget && event.target.open && !profiles.value.length)
    request('list')
}
function overrides(type) {
  try {
    const value = JSON.parse(type.selectorsText || '{}')
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  } catch {
    return {}
  }
}
function setOverride(type, name, key, value) {
  const rules = overrides(type)
  rules[name] = {
    ...(rules[name] || {
      kind: form.value.fields.find((field) => field.name === name)?.kind || 'css',
      selector: '',
    }),
    [key]: value,
  }
  type.selectorsText = JSON.stringify(rules)
}
function addType() {
  form.value.pageTypes.push({
    id: `type_${form.value.pageTypes.length + 1}`,
    action: 'extract',
    match: [{ kind: 'prefix', pattern: '/' }],
    selectorsText: '{}',
  })
}
</script>
<template>
  <details class="scout-section scout-plan-options" @toggle="loadOptions">
    <summary class="h6">{{ t('scout.product.advanced') }}</summary>
    <fieldset :disabled="disabled || busy">
      <h3 class="h6 mt-3">{{ t('scout.product.proxy') }}</h3>
      <label class="scout-input-label" :for="`${uid}-1`"
        >{{ t('scout.product.proxy') }}
        <select
          :id="`${uid}-1`"
          :aria-label="t('scout.product.proxy')"
          v-model="form.proxyRevision"
          class="form-select"
        >
          <option value="">{{ t('scout.product.direct') }}</option>
          <option
            v-if="
              form.proxyRevision &&
              !profiles.some((p) => p.revision_public_id === form.proxyRevision)
            "
            :value="form.proxyRevision"
          >
            {{ form.proxyRevision }}
          </option>
          <option
            v-for="profile in profiles"
            :key="profile.revision_public_id"
            :value="profile.revision_public_id"
          >
            {{ profile.ip }}:{{ profile.port }} · {{ profile.auth_type }}
          </option>
        </select>
      </label>
      <div class="scout-actions mt-2">
        <button type="button" class="btn btn-outline-secondary" @click="request('list')">
          {{ t('scout.product.refresh') }}</button
        ><button
          type="button"
          class="btn btn-outline-secondary"
          :disabled="
            !form.proxyRevision ||
            !profiles.some((p) => p.revision_public_id === form.proxyRevision)
          "
          @click="request('check')"
        >
          {{ t('scout.product.checkProxy') }}
        </button>
      </div>
      <p class="small scout-muted">{{ t('scout.product.proxyUnchecked') }}</p>
      <p v-if="outcome" role="status">
        {{ t(outcome === 'ready' ? 'scout.product.ready' : 'scout.product.failed') }}
      </p>
      <p v-if="message" class="scout-warning" role="alert">{{ message }}</p>
      <details>
        <summary>{{ t('scout.product.createProxy') }}</summary>
        <label class="scout-input-label" :for="`${uid}-2`"
          >{{ t('scout.product.ip')
          }}<input
            :id="`${uid}-2`"
            :aria-label="t('scout.product.ip')"
            v-model="proxy.ip"
            class="form-control"
            autocomplete="off"
        /></label>
        <label class="scout-input-label" :for="`${uid}-3`"
          >{{ t('scout.product.port')
          }}<input
            :id="`${uid}-3`"
            :aria-label="t('scout.product.port')"
            v-model="proxy.port"
            class="form-control"
            type="number"
            min="1"
            max="65535"
        /></label>
        <label class="scout-input-label" :for="`${uid}-4`"
          >{{ t('scout.product.auth')
          }}<select
            :id="`${uid}-4`"
            :aria-label="t('scout.product.auth')"
            v-model="proxy.auth_type"
            class="form-select"
          >
            <option value="none">{{ t('scout.product.none') }}</option>
            <option value="basic">{{ t('scout.product.basic') }}</option>
          </select></label
        >
        <template v-if="proxy.auth_type === 'basic'"
          ><label class="scout-input-label" :for="`${uid}-5`"
            >{{ t('scout.product.username')
            }}<input
              :id="`${uid}-5`"
              :aria-label="t('scout.product.username')"
              v-model="proxy.username"
              class="form-control"
              autocomplete="off" /></label
          ><label class="scout-input-label" :for="`${uid}-6`"
            >{{ t('scout.product.password')
            }}<input
              :id="`${uid}-6`"
              :aria-label="t('scout.product.password')"
              v-model="proxy.password"
              class="form-control"
              type="password"
              autocomplete="new-password" /></label
        ></template>
        <button
          type="button"
          class="btn btn-outline-secondary mt-2"
          :disabled="
            !proxy.ip ||
            !proxy.port ||
            (proxy.auth_type === 'basic' && (!proxy.username || !proxy.password))
          "
          @click="request('create')"
        >
          {{ t('scout.product.create') }}
        </button>
      </details>
      <h3 class="h6 mt-4">{{ t('scout.product.identity') }}</h3>
      <label class="scout-input-label" :for="`${uid}-7`"
        >{{ t('scout.product.identity')
        }}<select
          :id="`${uid}-7`"
          :aria-label="t('scout.product.identity')"
          v-model="form.identityKind"
          class="form-select"
        >
          <option value="">{{ t('scout.product.noIdentity') }}</option>
          <option value="sku">SKU</option>
          <option value="field">{{ t('scout.product.identityField') }}</option>
          <option value="url" :disabled="form.recordMode === 'cards'">URL</option>
        </select></label
      >
      <template v-if="form.identityKind"
        ><label class="scout-input-label" :for="`${uid}-8`"
          >{{ t('scout.product.namespace')
          }}<input
            :id="`${uid}-8`"
            :aria-label="t('scout.product.namespace')"
            v-model="form.identityNamespace"
            class="form-control" /></label
        ><label v-if="form.identityKind !== 'url'" class="scout-input-label" :for="`${uid}-9`"
          >{{ t('scout.product.identityField')
          }}<select
            :id="`${uid}-9`"
            :aria-label="t('scout.product.identityField')"
            v-model="form.identityField"
            class="form-select"
          >
            <option
              v-for="field in form.fields.filter((f) => f.name && !f.many && !f.conversion)"
              :key="field.name"
              :value="field.name"
            >
              {{ field.name }}
            </option>
          </select></label
        ></template
      >
      <template v-if="form.crawlMode === 'site'">
        <label class="scout-input-label" :for="`${uid}-previews`"
          >{{ t('scout.product.additionalPreviews')
          }}<textarea
            :id="`${uid}-previews`"
            v-model="form.additionalPreviewUrls"
            class="form-control"
            rows="3"
          />
        </label>
        <h3 class="h6 mt-4">Sitemap / robots.txt</h3>
        <label class="scout-input-label" :for="`${uid}-10`"
          >{{ t('scout.product.sitemap')
          }}<input
            :id="`${uid}-10`"
            :aria-label="t('scout.product.sitemap')"
            v-model="form.sitemapUrl"
            type="url"
            class="form-control"
        /></label>
        <label :for="`${uid}-11`"
          ><input
            :id="`${uid}-11`"
            :aria-label="t('scout.product.robots')"
            v-model="form.sitemapFromRobots"
            type="checkbox"
          />
          {{ t('scout.product.robots') }}</label
        >
        <h3 class="h6 mt-4">{{ t('scout.product.pageTypes') }}</h3>
        <div v-for="(type, index) in form.pageTypes" :key="index" class="scout-field-rule">
          <label class="scout-input-label" :for="`${uid}-12-${index}`"
            >{{ t('scout.product.typeId')
            }}<input
              :id="`${uid}-12-${index}`"
              :aria-label="t('scout.product.typeId')"
              v-model="type.id"
              class="form-control"
          /></label>
          <label class="scout-input-label" :for="`${uid}-13-${index}`"
            >{{ t('scout.product.pageAction')
            }}<select
              :id="`${uid}-13-${index}`"
              :aria-label="t('scout.product.pageAction')"
              v-model="type.action"
              class="form-select"
            >
              <option value="extract">{{ t('scout.product.extract') }}</option>
              <option value="discover">{{ t('scout.product.discover') }}</option>
            </select></label
          >
          <label
            v-for="(rule, ruleIndex) in type.match"
            :key="ruleIndex"
            class="scout-input-label"
            :for="`${uid}-14-${index}-${ruleIndex}`"
            >{{ t('scout.product.pattern') }} · {{ rule.kind
            }}<input
              :id="`${uid}-14-${index}-${ruleIndex}`"
              :aria-label="t('scout.product.pattern')"
              v-model="rule.pattern"
              class="form-control"
          /></label>
          <details v-if="type.action === 'extract'">
            <summary>{{ t('scout.product.overrides') }}</summary>
            <div
              v-for="field in form.fields.filter((item) => item.name)"
              :key="field.name"
              class="scout-input-label mt-2"
            >
              <strong>{{ field.name }}</strong>
              <label :for="`${uid}-override-kind-${index}-${field.name}`"
                >{{ t('scout.fieldKind') }}
                <select
                  :id="`${uid}-override-kind-${index}-${field.name}`"
                  class="form-select"
                  :value="overrides(type)[field.name]?.kind || field.kind"
                  @change="setOverride(type, field.name, 'kind', $event.target.value)"
                >
                  <option value="css">CSS</option>
                  <option value="xpath">XPath</option>
                </select></label
              >
              <label :for="`${uid}-override-rule-${index}-${field.name}`"
                >{{ t('scout.fieldSelector') }}
                <input
                  :id="`${uid}-override-rule-${index}-${field.name}`"
                  class="form-control"
                  :value="overrides(type)[field.name]?.selector || ''"
                  :placeholder="field.selector"
                  @input="setOverride(type, field.name, 'selector', $event.target.value)"
              /></label>
            </div>
          </details>
          <button
            type="button"
            class="btn btn-outline-secondary btn-sm mt-2"
            @click="form.pageTypes.splice(index, 1)"
          >
            {{ t('scout.product.remove') }}
          </button>
        </div>
        <button
          type="button"
          class="btn btn-outline-secondary"
          :disabled="form.pageTypes.length >= 5"
          @click="addType"
        >
          {{ t('scout.product.addType') }}
        </button>
      </template>
    </fieldset>
  </details>
</template>
