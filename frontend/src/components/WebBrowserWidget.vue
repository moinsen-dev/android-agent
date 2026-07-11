<script setup lang="ts">
/**
 * WebBrowserWidget — resizable headless browser preview.
 *
 * Props:
 *   sid         — web session id (required)
 *   label       — display name (optional)
 *   autoStream  — start streaming on mount (default: true)
 *   fps         — screenshot poll interval in ms (default: 800)
 *
 * Emits:
 *   tap(x, y, pageW, pageH) — user clicked on the page
 */
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { api } from '@/composables/useApi'

const props = withDefaults(defineProps<{
  sid: string
  label?: string
  autoStream?: boolean
  fps?: number
}>(), {
  label: '',
  autoStream: true,
  fps: 800,
})

const emit = defineEmits<{
  tap: [x: number, y: number, pageW: number, pageH: number]
}>()

const streaming = ref(false)
const streamImg = ref('')
const pageWidth = ref(1280)
const pageHeight = ref(720)
const viewportWidth = ref(1280)
const viewportHeight = ref(720)
const urlInput = ref('')
const currentUrl = ref('')
const currentTitle = ref('')
const domTree = ref('')
const showTree = ref(false)
const customWidth = ref(1280)
const customHeight = ref(720)
let timer: number | null = null

const VIEWPORT_PRESETS = [
  { id: 'mobile-s', label: 'Mobile S', width: 375, height: 667 },
  { id: 'mobile-l', label: 'Mobile L', width: 390, height: 844 },
  { id: 'tablet', label: 'Tablet', width: 768, height: 1024 },
  { id: 'desktop', label: 'Desktop', width: 1280, height: 720 },
  { id: 'desktop-l', label: 'Desktop L', width: 1440, height: 900 },
  { id: 'custom', label: 'Custom', width: 0, height: 0 },
]
const selectedPreset = ref('desktop')

const isCustom = computed(() => selectedPreset.value === 'custom')

function startStream() {
  if (streaming.value) return
  streaming.value = true
  pollFrame()
  timer = window.setInterval(pollFrame, props.fps)
}

function stopStream() {
  streaming.value = false
  if (timer) { clearInterval(timer); timer = null }
  streamImg.value = ''
}

function toggleStream() {
  if (streaming.value) stopStream()
  else startStream()
}

async function pollFrame() {
  if (!props.sid) return
  try {
    const resp = await api(`/api/web/screenshot/${encodeURIComponent(props.sid)}`)
    if (resp.ok && resp.image) {
      streamImg.value = `data:image/jpeg;base64,${resp.image}`
      pageWidth.value = resp.width || pageWidth.value
      pageHeight.value = resp.height || pageHeight.value
    }
  } catch {}
}

async function fetchMetadata() {
  if (!props.sid) return
  try {
    const [u, t] = await Promise.all([
      api(`/api/web/url/${encodeURIComponent(props.sid)}`),
      api(`/api/web/title/${encodeURIComponent(props.sid)}`),
    ])
    if (u.ok) currentUrl.value = u.url
    if (t.ok) currentTitle.value = t.title
    urlInput.value = currentUrl.value
  } catch {}
}

async function navigate() {
  if (!props.sid || !urlInput.value) return
  await api('/api/web/navigate', {
    method: 'POST',
    body: JSON.stringify({ sid: props.sid, url: urlInput.value }),
  })
  await fetchMetadata()
  await pollFrame()
}

async function applyViewport() {
  if (!props.sid) return
  let w = viewportWidth.value
  let h = viewportHeight.value
  if (isCustom.value) {
    w = customWidth.value
    h = customHeight.value
  }
  await api('/api/web/viewport', {
    method: 'POST',
    body: JSON.stringify({ sid: props.sid, width: w, height: h }),
  })
  viewportWidth.value = w
  viewportHeight.value = h
  await pollFrame()
}

function onPresetChange() {
  const preset = VIEWPORT_PRESETS.find(p => p.id === selectedPreset.value)
  if (!preset || preset.id === 'custom') return
  viewportWidth.value = preset.width
  viewportHeight.value = preset.height
  customWidth.value = preset.width
  customHeight.value = preset.height
  applyViewport()
}

async function fetchDomTree() {
  if (!props.sid) return
  try {
    const resp = await api(`/api/web/screen-tree/${encodeURIComponent(props.sid)}`)
    if (resp.ok) domTree.value = resp.tree
  } catch {}
}

function handleClick(e: MouseEvent) {
  const el = e.target as HTMLImageElement
  const rect = el.getBoundingClientRect()
  const pw = pageWidth.value || el.naturalWidth || viewportWidth.value
  const ph = pageHeight.value || el.naturalHeight || viewportHeight.value
  const x = Math.round((e.clientX - rect.left) / rect.width * pw)
  const y = Math.round((e.clientY - rect.top) / rect.height * ph)
  emit('tap', x, y, pw, ph)
  api('/api/web/tap', {
    method: 'POST',
    body: JSON.stringify({ sid: props.sid, x, y }),
  })
}

async function pressKey(key: string) {
  if (!props.sid) return
  await api('/api/web/key', {
    method: 'POST',
    body: JSON.stringify({ sid: props.sid, key }),
  })
  await pollFrame()
}

onMounted(() => {
  fetchMetadata()
  if (props.autoStream && props.sid) startStream()
})
onUnmounted(() => stopStream())

watch(() => props.sid, (newVal, oldVal) => {
  if (newVal !== oldVal) {
    stopStream()
    fetchMetadata()
    if (newVal) startStream()
  }
})

defineExpose({ startStream, stopStream, streaming, refresh: pollFrame })
</script>

<template>
  <div class="wbw">
    <!-- Toolbar -->
    <div class="wbw-toolbar">
      <span class="wbw-status-dot" :style="{ background: streaming ? '#22c55e' : '#475569' }"></span>
      <span class="wbw-label">{{ label || sid || 'No session' }}</span>

      <form class="wbw-url" @submit.prevent="navigate">
        <input v-model="urlInput" placeholder="https://example.com" />
        <button type="submit">Go</button>
      </form>

      <select v-model="selectedPreset" @change="onPresetChange" class="wbw-select">
        <option v-for="p in VIEWPORT_PRESETS" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>

      <template v-if="isCustom">
        <input v-model.number="customWidth" type="number" class="wbw-dim" />
        <span class="wbw-x">×</span>
        <input v-model.number="customHeight" type="number" class="wbw-dim" />
        <button @click="applyViewport">Apply</button>
      </template>
      <template v-else>
        <span class="wbw-dim-label">{{ viewportWidth }}×{{ viewportHeight }}</span>
      </template>

      <button class="wbw-tree-btn" @click="showTree = !showTree; if (showTree) fetchDomTree()">
        {{ showTree ? 'Hide DOM' : 'Show DOM' }}
      </button>
      <button class="wbw-stream-btn" @click="toggleStream">
        {{ streaming ? 'Stop' : 'Stream' }}
      </button>
    </div>

    <!-- Meta -->
    <div v-if="currentTitle" class="wbw-meta">{{ currentTitle }}</div>

    <!-- Content -->
    <div class="wbw-content">
      <div class="wbw-viewport" :style="{ width: viewportWidth + 'px', height: viewportHeight + 'px' }">
        <div v-if="streaming && streamImg" class="wbw-frame">
          <img :src="streamImg" @click="handleClick" draggable="false" />
        </div>
        <div v-else class="wbw-placeholder">
          Enter a URL and click Stream to start
        </div>
      </div>
      <pre v-if="showTree" class="wbw-tree">{{ domTree }}</pre>
    </div>

    <!-- Footer keys -->
    <div class="wbw-footer">
      <button class="wbw-key" @click="pressKey('Enter')">Enter</button>
      <button class="wbw-key" @click="pressKey('Tab')">Tab</button>
      <button class="wbw-key" @click="pressKey('Escape')">Esc</button>
      <button class="wbw-key" @click="pressKey('ArrowDown')">↓</button>
      <button class="wbw-key" @click="pressKey('ArrowUp')">↑</button>
    </div>
  </div>
</template>

<style scoped>
.wbw {
  display: flex;
  flex-direction: column;
  background: var(--bg-card, #111827);
  border: 1px solid var(--border, #1e293b);
  border-radius: 10px;
  overflow: hidden;
  height: 100%;
}
.wbw-toolbar {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border, #1e293b);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.wbw-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.wbw-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-3, #94a3b8);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wbw-url {
  display: flex;
  gap: 4px;
  flex: 1;
  min-width: 180px;
}
.wbw-url input {
  flex: 1;
  background: #0b0f14;
  border: 1px solid #2a3044;
  border-radius: 4px;
  color: #e2e8f0;
  padding: 4px 8px;
  font-size: 11px;
}
.wbw-url button, .wbw-toolbar button {
  background: #1a1f2e;
  border: 1px solid #2a3044;
  border-radius: 4px;
  color: #94a3b8;
  padding: 4px 8px;
  font-size: 11px;
  cursor: pointer;
}
.wbw-toolbar button:hover { background: #252b3d; color: #e2e8f0; }
.wbw-select {
  background: #0b0f14;
  border: 1px solid #2a3044;
  border-radius: 4px;
  color: #e2e8f0;
  padding: 4px 6px;
  font-size: 11px;
}
.wbw-dim {
  width: 56px;
  background: #0b0f14;
  border: 1px solid #2a3044;
  border-radius: 4px;
  color: #e2e8f0;
  padding: 4px;
  font-size: 11px;
}
.wbw-x { color: #64748b; font-size: 11px; }
.wbw-dim-label { color: #94a3b8; font-size: 11px; min-width: 70px; }
.wbw-stream-btn { margin-left: auto; }
.wbw-tree-btn { }
.wbw-meta {
  padding: 4px 10px;
  font-size: 10px;
  color: #64748b;
  border-bottom: 1px solid var(--border, #1e293b);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.wbw-content {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: auto;
  background: #070b10;
  padding: 12px;
  gap: 12px;
}
.wbw-viewport {
  flex-shrink: 0;
  background: #000;
  border: 1px solid #2a3044;
  border-radius: 6px;
  overflow: auto;
  resize: both;
  position: relative;
}
.wbw-frame {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
}
.wbw-frame img {
  width: 100%;
  height: auto;
  display: block;
  cursor: crosshair;
}
.wbw-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #334155;
  font-size: 11px;
}
.wbw-tree {
  flex: 1;
  min-width: 260px;
  background: #0b0f14;
  border: 1px solid #2a3044;
  border-radius: 6px;
  color: #94a3b8;
  font-size: 10px;
  padding: 10px;
  overflow: auto;
  white-space: pre-wrap;
}
.wbw-footer {
  padding: 6px 10px;
  border-top: 1px solid var(--border, #1e293b);
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.wbw-key {
  padding: 2px 8px;
  background: #1a1f2e;
  border: 1px solid #2a3044;
  border-radius: 4px;
  color: #94a3b8;
  font-size: 10px;
  cursor: pointer;
}
.wbw-key:hover { background: #252b3d; color: #e2e8f0; }
</style>
