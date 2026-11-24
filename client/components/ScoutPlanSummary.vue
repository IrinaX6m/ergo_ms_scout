<script setup>
import { useAppI18n } from '@/i18n/useAppI18n.js'
import ScoutCrawlSummary from './ScoutCrawlSummary.vue'
defineProps({
  plan: { type: Object, required: true },
  mode: { type: String, default: 'manual' },
  expanded: { type: Boolean, default: false },
  approved: { type: Boolean, default: false },
})
const { t } = useAppI18n()
</script>

<template>
  <dl class="scout-plan" :class="{ 'scout-plan--expanded': expanded }">
    <div>
      <dt>{{ t('scout.workspace.modeLabel') }}</dt>
      <dd>{{ t(`scout.workspace.modes.${mode}.title`) }}</dd>
    </div>
    <div>
      <dt>{{ t('scout.url') }}</dt>
      <dd>
        <ul v-if="plan.seed_urls?.some(Boolean)" class="list-unstyled mb-0">
          <li v-for="(url, index) in plan.seed_urls" :key="index">{{ url }}</li>
        </ul>
        <template v-else>{{ t('scout.workspace.notSpecified') }}</template>
      </dd>
    </div>
    <div>
      <dt>{{ t('scout.workspace.resultFields') }}</dt>
      <dd>
        <template v-if="expanded"
          ><div v-for="(field, index) in plan.fields" :key="index" class="scout-plan-field">
            <strong>{{ field.name || t('scout.workspace.notSpecified') }}</strong
            ><code>{{ field.kind }}: {{ field.selector || t('scout.workspace.notSpecified') }}</code
            ><span class="scout-muted small">
              {{ field.scope === 'record' ? t('scout.scopeRecord') : t('scout.scopePage') }}
              <template v-if="field.value_source === 'image'"> · {{ t('scout.visual.image.field') }}</template>
              <template v-if="field.conversion">
                · {{ t(`scout.product.${field.conversion.type}`) }}
                <code>{{ JSON.stringify(field.conversion) }}</code></template
              >
              <template v-if="field.many"> · {{ t('scout.fieldMany') }}</template>
            </span>
          </div></template
        >
        <template v-else>{{
          plan.fields
            .map((field) => field.name)
            .filter(Boolean)
            .join(', ') || t('scout.workspace.notSpecified')
        }}</template>
      </dd>
    </div>
    <div v-if="expanded">
      <dt>{{ t('scout.workspace.recordUnit') }}</dt>
      <dd>
        <code v-if="plan.record">{{ plan.record.kind }}: {{ plan.record.selector }}</code
        ><template v-else>{{ t('scout.flow.oneRecord') }}</template>
      </dd>
    </div>
    <div>
      <dt>{{ t('scout.workspace.collectionBounds') }}</dt>
      <dd>
        {{
          plan.crawl?.mode === 'site'
            ? t('scout.workspace.siteBounds', {
                depth: plan.crawl.max_depth,
                pages: plan.crawl.max_pages,
              })
            : t('scout.flow.pagesOnly')
        }}
      </dd>
    </div>
    <div>
      <dt>{{ t('scout.workspace.planState') }}</dt>
      <dd>{{ approved ? t('scout.workspace.planApproved') : t('scout.workspace.planWaiting') }}</dd>
    </div>
    <div v-if="expanded && plan.crawl?.mode === 'site'">
      <dt>{{ t('scout.workspace.collectionBounds') }}</dt>
      <dd><ScoutCrawlSummary :run="{ crawl: plan.crawl }" plan-details /></dd>
    </div>
    <template v-if="expanded">
      <div>
        <dt>{{ t('scout.product.proxy') }}</dt>
        <dd>{{ plan.proxy_profile_revision_public_id || t('scout.product.direct') }}</dd>
      </div>
      <div v-if="plan.identity">
        <dt>{{ t('scout.product.identity') }}</dt>
        <dd>
          {{ plan.identity.kind }} · {{ plan.identity.namespace }}
          <code>{{ plan.identity.field }}</code>
        </dd>
      </div>
      <div v-if="plan.crawl?.sitemap_url || plan.crawl?.sitemap_from_robots">
        <dt>Sitemap / robots.txt</dt>
        <dd>
          {{ plan.crawl.sitemap_url }}
          <span v-if="plan.crawl.sitemap_from_robots">{{ t('scout.product.robots') }}</span>
        </dd>
      </div>
      <div v-if="plan.crawl?.page_types?.length">
        <dt>{{ t('scout.product.pageTypes') }}</dt>
        <dd>
          <div v-for="type in plan.crawl.page_types" :key="type.id">
            <strong>{{ type.id }}</strong> · {{ t(`scout.product.${type.action}`)
            }}<code>{{ JSON.stringify(type.match) }}</code
            ><code v-if="type.selectors">{{ JSON.stringify(type.selectors) }}</code>
          </div>
        </dd>
      </div>
    </template>
    <div v-if="expanded && plan.limits">
      <dt>{{ t('scout.workspace.requestLimits') }}</dt>
      <dd>
        {{
          t('scout.workspace.requestBudget', {
            bytes: plan.limits.max_bytes,
            seconds: plan.limits.timeout_seconds,
          })
        }}
      </dd>
    </div>
  </dl>
</template>
