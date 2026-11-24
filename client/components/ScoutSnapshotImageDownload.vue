<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { useAppI18n } from '@/i18n/useAppI18n.js'
import { apiClient } from '@/js/api/manager'
import { downloadBlob, extractFilenameFromHeaders } from '@/js/utils/file-helpers.js'
import { scoutEndpoints } from '../js/endpoints.js'

const props = defineProps({
  snapshotId: { type: String, required: true },
  treeVersion: { type: String, required: true },
  nodeId: { type: String, required: true },
})
const { t } = useAppI18n()
const pending = ref(false)
const message = ref('')
let active = true
onBeforeUnmount(() => {
  active = false
})

const extensions = new Map([
  ['image/jpeg', 'jpg'],
  ['image/png', 'png'],
  ['image/gif', 'gif'],
  ['image/webp', 'webp'],
])
const errorByStatus = {
  401: 'denied',
  403: 'denied',
  404: 'reload',
  409: 'reload',
  413: 'tooLarge',
  415: 'unsupported',
  422: 'unavailable',
  429: 'rateLimit',
}
async function download() {
  if (pending.value) return
  pending.value = true
  message.value = ''
  try {
    const response = await apiClient.downloadFile(
      scoutEndpoints.visualSnapshotImage(props.snapshotId),
      {
        node_id: props.nodeId,
        tree_version: props.treeVersion,
      },
    )
    if (!active) return
    if (!response.success) {
      message.value = errorByStatus[response.status] || 'failed'
      return
    }
    const image = response.data
    const extension = image instanceof Blob && extensions.get(image.type)
    if (!extension || !image.size) {
      message.value = 'unsupported'
      return
    }
    const filename = extractFilenameFromHeaders(
      response.headers,
      `scout-${props.nodeId}.${extension}`,
    )
    downloadBlob(image, filename)
    message.value = 'started'
  } catch {
    if (active) message.value = 'failed'
  } finally {
    if (active) pending.value = false
  }
}
</script>

<template>
  <div class="mb-2">
    <button
      type="button"
      class="btn btn-outline-secondary"
      :aria-disabled="pending"
      :aria-busy="pending"
      @click="download"
    >
      {{ t(pending ? 'scout.visual.image.loading' : 'scout.visual.image.download') }}
    </button>
    <p v-if="message" class="small mt-1 mb-0" role="status">
      {{ t(`scout.visual.image.${message}`) }}
    </p>
  </div>
</template>
