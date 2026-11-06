<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useAppI18n } from '@/i18n/useAppI18n.js'

const props = defineProps({ html: String, nodeIds: { type: Array, default: () => [] } })
const emit = defineEmits(['select'])
const { t } = useAppI18n()
const frame = ref(null)
const rectangles = ref([])
let cleanup = () => {}
let observer
let themeObserver
let animation = 0
function update() {
  cancelAnimationFrame(animation)
  animation = requestAnimationFrame(() => {
    const document = frame.value?.contentDocument
    rectangles.value = props.nodeIds.flatMap((id) => {
      if (!/^n\d+$/.test(id)) return []
      const element = document?.querySelector(`[data-scout-node="${id}"]`)
      if (!element) return []
      const box = element.getBoundingClientRect()
      return [{ id, x: box.x, y: box.y, width: box.width, height: box.height }]
    })
  })
}
function attach() {
  cleanup()
  const document = frame.value?.contentDocument
  if (!document?.body) return
  // Scripts remain disabled by sandbox. Parent listeners only read server-issued node IDs.
  const scheme = document.createElement('meta')
  scheme.name = 'color-scheme'
  document.head.append(scheme)
  const syncTheme = () => {
    scheme.content = window.document.documentElement.dataset.bsTheme === 'dark' ? 'dark' : 'light'
    update()
  }
  syncTheme()
  themeObserver?.disconnect()
  themeObserver = new MutationObserver(syncTheme)
  themeObserver.observe(window.document.documentElement, {
    attributes: true,
    attributeFilter: ['data-bs-theme'],
  })
  let focused = document.querySelector('[data-scout-node]')
  if (focused) focused.tabIndex = 0
  function select(element) {
    const ancestors = []
    for (let node = element; node?.hasAttribute('data-scout-node'); node = node.parentElement) {
      ancestors.push({
        id: node.getAttribute('data-scout-node'),
        tag: node.tagName.toLowerCase(),
        text: (node.textContent || '').trim().slice(0, 70),
      })
    }
    if (ancestors.length) emit('select', ancestors)
  }
  function focus(element) {
    if (!element?.hasAttribute('data-scout-node')) return
    if (focused) focused.tabIndex = -1
    focused = element
    focused.tabIndex = 0
    focused.focus()
  }
  const click = (event) => {
    event.preventDefault()
    event.stopPropagation()
    const element = event.target.closest('[data-scout-node]')
    if (element) {
      focus(element)
      select(element)
    }
  }
  const key = (event) => {
    const element = event.target.closest('[data-scout-node]')
    if (!element) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      select(element)
    }
    const next = {
      ArrowUp: element.parentElement,
      ArrowDown: element.firstElementChild,
      ArrowLeft: element.previousElementSibling,
      ArrowRight: element.nextElementSibling,
    }[event.key]
    if (next?.hasAttribute('data-scout-node')) {
      event.preventDefault()
      focus(next)
    }
  }
  document.addEventListener('click', click, true)
  document.addEventListener('keydown', key)
  document.addEventListener('scroll', update, true)
  frame.value.contentWindow.addEventListener('resize', update)
  cleanup = () => {
    document.removeEventListener('click', click, true)
    document.removeEventListener('keydown', key)
    document.removeEventListener('scroll', update, true)
    document.defaultView?.removeEventListener('resize', update)
  }
  update()
}
watch(
  () => props.nodeIds,
  () => nextTick(update),
  { deep: true },
)
onMounted(() => {
  observer = new ResizeObserver(update)
  if (frame.value) observer.observe(frame.value)
})
onUnmounted(() => {
  cleanup()
  observer?.disconnect()
  themeObserver?.disconnect()
  cancelAnimationFrame(animation)
})
</script>

<template>
  <div class="scout-snapshot-frame">
    <iframe
      ref="frame"
      :srcdoc="html"
      sandbox="allow-same-origin"
      referrerpolicy="no-referrer"
      :title="t('scout.visual.snapshotTitle')"
      @load="attach"
    />
    <svg class="scout-snapshot-highlights" aria-hidden="true">
      <rect
        v-for="box in rectangles"
        :key="box.id"
        :x="box.x"
        :y="box.y"
        :width="box.width"
        :height="box.height"
      />
    </svg>
  </div>
</template>
