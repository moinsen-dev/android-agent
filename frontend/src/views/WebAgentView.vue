<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { api } from '@/composables/useApi'
import WebBrowserWidget from '@/components/WebBrowserWidget.vue'

interface ChatMessage {
  role: string
  content: string
  tool_name?: string
  tool_args?: any
  image?: string
}

const url = ref('https://example.com')
const sessionId = ref('')
const chatMessages = ref<ChatMessage[]>([])
const chatInput = ref('')
const chatSending = ref(false)
const chatActivity = ref('')
const chatTokens = ref(0)
const chatVerbose = ref(false)
const chatSessionId = ref('')
let chatAbortController: AbortController | null = null

const chatProvider = ref(localStorage.getItem('agent_provider') || 'deepseek')
const chatModel = ref(localStorage.getItem('agent_model') || 'deepseek-chat')
const CHAT_PROVIDERS = ref<{ id: string; label: string; models: string[] }[]>([
  { id: 'anthropic', label: 'Anthropic', models: ['claude-sonnet-4-20250514', 'claude-opus-4-20250514'] },
  { id: 'openrouter', label: 'OpenRouter', models: ['anthropic/claude-sonnet-4', 'google/gemini-2.5-pro'] },
  { id: 'deepseek', label: 'DeepSeek', models: ['deepseek-chat', 'deepseek-reasoner'] },
  { id: 'ollama', label: 'Ollama', models: ['llama3.2:3b', 'gemma3:4b', 'qwen3:4b'] },
])

const deviceHandle = computed(() => sessionId.value ? `web:${sessionId.value}` : '')
const canChat = computed(() => !!deviceHandle.value)

async function fetchProviders() {
  try {
    const resp = await fetch('/api/agent-chat/providers')
    if (resp.ok) CHAT_PROVIDERS.value = await resp.json()
  } catch {}
}

function onProviderChange() {
  localStorage.setItem('agent_provider', chatProvider.value)
  const p = CHAT_PROVIDERS.value.find(p => p.id === chatProvider.value)
  if (p) {
    chatModel.value = p.models[0] || chatModel.value
    localStorage.setItem('agent_model', chatModel.value)
  }
  chatSessionId.value = ''
}

function onModelChange() {
  localStorage.setItem('agent_model', chatModel.value)
  chatSessionId.value = ''
}

async function createSession() {
  if (!url.value.trim()) return
  try {
    const resp = await api('/api/web/session', {
      method: 'POST',
      body: JSON.stringify({ viewport: { width: 1280, height: 720 } }),
    })
    sessionId.value = resp.sid
    await api('/api/web/navigate', {
      method: 'POST',
      body: JSON.stringify({ sid: sessionId.value, url: url.value }),
    })
    chatMessages.value.push({ role: 'system', content: `Opened ${url.value} in session ${sessionId.value}` })
  } catch (e: any) {
    chatMessages.value.push({ role: 'error', content: e.message })
  }
}

async function sendChat() {
  if (!chatInput.value.trim() || chatSending.value || !canChat.value) return
  const msg = chatInput.value.trim()
  chatInput.value = ''
  chatMessages.value.push({ role: 'user', content: msg })
  chatSending.value = true
  chatActivity.value = 'Reading page...'
  chatTokens.value += msg.length / 4

  try {
    chatAbortController = new AbortController()
    const body: any = {
      content: msg,
      device: deviceHandle.value,
      provider: chatProvider.value,
      model: chatModel.value,
    }
    if (chatSessionId.value) body.session_id = chatSessionId.value
    const resp = await fetch('/api/agent-chat/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: chatAbortController.signal,
    })
    const reader = resp.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const event = JSON.parse(line.slice(6))
          if (event.type === 'session' && event.session_id) {
            chatSessionId.value = event.session_id
          } else if (event.type === 'text') {
            chatActivity.value = ''
            const last = chatMessages.value[chatMessages.value.length - 1]
            if (last?.role === 'assistant') {
              last.content += event.content
            } else {
              chatMessages.value.push({ role: 'assistant', content: event.content })
            }
          } else if (event.type === 'tool_call') {
            const TOOL_EMOJI: Record<string, string> = {
              screenshot: '📸', get_screen_tree: '🌳', get_elements: '🔍', tap: '👆', tap_element: '👆',
              swipe: '👋', type_text: '⌨️', press_key: '🔘', launch_app: '🚀', navigate: '🌐',
              set_viewport: '📐', wait: '⏳',
            }
            const SHORT_NAME: Record<string, string> = {
              get_screen_tree: 'tree', get_elements: 'elements', type_text: 'type', press_key: 'key',
              tap_element: 'tap #', screenshot: 'screenshot', navigate: 'navigate', set_viewport: 'viewport',
            }
            const emoji = TOOL_EMOJI[event.name] || '🔧'
            const short = SHORT_NAME[event.name] || event.name
            chatActivity.value = `${emoji} ${short}...`
            if (chatVerbose.value) {
              chatMessages.value.push({ role: 'tool_call', content: `${emoji} ${event.name}(${JSON.stringify(event.args).slice(0, 120)})`, tool_name: event.name, tool_args: event.args })
            } else {
              let brief = `${emoji} ${short}`
              const a = event.args || {}
              if (event.name === 'tap' && a.x != null) brief = `${emoji} (${a.x},${a.y})`
              else if (event.name === 'type_text' && a.text) brief = `${emoji} "${a.text.slice(0, 20)}"`
              else if (event.name === 'navigate' && a.url) brief = `${emoji} ${a.url.slice(0, 30)}`
              else if (event.name === 'set_viewport') brief = `${emoji} ${a.width}×${a.height}`
              chatMessages.value.push({ role: 'tool_call', content: brief, tool_name: event.name })
            }
          } else if (event.type === 'tool_result') {
            chatActivity.value = '🤔 Thinking...'
            if (chatVerbose.value) {
              chatMessages.value.push({ role: 'tool_result', content: event.result?.slice(0, 300) || '', tool_name: event.name })
            }
          } else if (event.type === 'activity') {
            chatActivity.value = event.content || 'Working...'
          } else if (event.type === 'screenshot') {
            chatMessages.value.push({ role: 'screenshot', content: '', image: event.image })
          } else if (event.type === 'error') {
            chatMessages.value.push({ role: 'error', content: event.content })
            chatActivity.value = ''
          } else if (event.type === 'done') {
            chatActivity.value = ''
          }
          await nextTick()
          const el = document.getElementById('web-chat-scroll')
          if (el) el.scrollTop = el.scrollHeight
        } catch {}
      }
    }
  } catch (e: any) {
    chatMessages.value.push({ role: 'error', content: e.message })
  }
  chatSending.value = false
}

function chatStop() {
  if (chatAbortController) { chatAbortController.abort(); chatAbortController = null }
  if (chatSessionId.value) {
    fetch(`/api/agent-chat/stop/${chatSessionId.value}`, { method: 'POST' }).catch(() => {})
  }
  chatSending.value = false
  chatActivity.value = ''
  chatMessages.value.push({ role: 'error', content: 'Stopped by user' })
}

function chatClear() {
  chatMessages.value = []
  chatSessionId.value = ''
  chatTokens.value = 0
  chatActivity.value = ''
}

onMounted(() => {
  fetchProviders()
})
</script>

<template>
  <div class="web-agent">
    <!-- Header -->
    <div class="wa-header">
      <div class="wa-row">
        <span class="wa-title">🌐 Web Agent</span>
        <form class="wa-url" @submit.prevent="createSession">
          <input v-model="url" placeholder="https://example.com" />
          <button type="submit" :disabled="!url.trim()">Open</button>
        </form>
        <select v-model="chatProvider" @change="onProviderChange">
          <option v-for="p in CHAT_PROVIDERS" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <select v-model="chatModel" @change="onModelChange">
          <option v-for="m in (CHAT_PROVIDERS.find(p => p.id === chatProvider)?.models || [])" :key="m" :value="m">{{ m }}</option>
        </select>
        <button @click="chatVerbose = !chatVerbose"
          :style="{ background: chatVerbose ? '#6366f133' : '#1a1f2e', color: chatVerbose ? '#a5b4fc' : '#64748b' }">
          {{ chatVerbose ? 'Verbose' : 'Brief' }}
        </button>
        <button @click="chatClear">Clear</button>
      </div>
      <div v-if="sessionId" class="wa-session">Session: {{ sessionId }}</div>
    </div>

    <!-- Main layout -->
    <div class="wa-layout">
      <!-- Chat -->
      <div class="wa-chat">
        <div id="web-chat-scroll" class="wa-messages">
          <div v-for="(m, i) in chatMessages" :key="i" :class="['wa-msg', `wa-msg--${m.role}`]">
            <div v-if="m.role === 'screenshot'" class="wa-screenshot">
              <img :src="`data:image/jpeg;base64,${m.image}`" />
            </div>
            <pre v-else>{{ m.content }}</pre>
          </div>
          <div v-if="chatActivity" class="wa-activity">{{ chatActivity }}</div>
        </div>
        <div class="wa-input-bar">
          <input
            v-model="chatInput"
            :disabled="chatSending || !canChat"
            :placeholder="canChat ? 'Tell the agent what to do...' : 'Open a URL first...'"
            @keyup.enter="sendChat"
          />
          <button @click="sendChat" :disabled="chatSending || !chatInput.trim() || !canChat">Send</button>
          <button v-if="chatSending" @click="chatStop" style="background:#ef444433;color:#f87171">Stop</button>
        </div>
      </div>

      <!-- Browser preview -->
      <div class="wa-preview">
        <WebBrowserWidget v-if="sessionId" :sid="sessionId" :auto-stream="true" />
        <div v-else class="wa-no-preview">Open a URL to start the web agent.</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.web-agent {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 12px;
  min-height: 0;
}
.wa-header {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}
.wa-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.wa-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-1);
}
.wa-url {
  display: flex;
  gap: 4px;
  flex: 1;
  min-width: 220px;
}
.wa-url input {
  flex: 1;
  background: var(--bg-deep, #0b0f14);
  border: 1px solid var(--border, #2a3044);
  border-radius: 6px;
  color: var(--text-1);
  padding: 6px 10px;
  font-size: 12px;
}
.wa-row select, .wa-row button {
  background: var(--bg-deep, #0b0f14);
  border: 1px solid var(--border, #2a3044);
  border-radius: 6px;
  color: var(--text-2);
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
}
.wa-row button:hover { background: var(--bg-card); }
.wa-row button:disabled { opacity: 0.5; cursor: not-allowed; }
.wa-session {
  font-size: 10px;
  color: var(--text-3);
  font-family: monospace;
}
.wa-layout {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(360px, 1fr) minmax(420px, 1.4fr);
  gap: 12px;
  min-height: 0;
}
.wa-chat {
  display: flex;
  flex-direction: column;
  background: var(--bg-card, #111827);
  border: 1px solid var(--border, #1e293b);
  border-radius: 10px;
  overflow: hidden;
  min-height: 0;
}
.wa-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.wa-msg pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.45;
}
.wa-msg--user {
  align-self: flex-end;
  background: #4f46e5;
  color: #fff;
  padding: 8px 12px;
  border-radius: 12px 12px 2px 12px;
  max-width: 90%;
}
.wa-msg--assistant {
  align-self: flex-start;
  background: var(--bg-deep, #0b0f14);
  color: var(--text-1);
  padding: 8px 12px;
  border-radius: 12px 12px 12px 2px;
  max-width: 95%;
}
.wa-msg--system, .wa-msg--tool_call, .wa-msg--tool_result {
  align-self: flex-start;
  background: transparent;
  color: var(--text-3);
  font-size: 11px;
  padding: 2px 0;
  max-width: 95%;
}
.wa-msg--error {
  align-self: flex-start;
  color: #f87171;
  font-size: 11px;
}
.wa-screenshot img {
  max-width: 180px;
  border-radius: 6px;
  border: 1px solid var(--border);
  cursor: pointer;
}
.wa-activity {
  align-self: flex-start;
  color: #94a3b8;
  font-size: 11px;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.wa-input-bar {
  display: flex;
  gap: 8px;
  padding: 10px;
  border-top: 1px solid var(--border);
}
.wa-input-bar input {
  flex: 1;
  background: var(--bg-deep, #0b0f14);
  border: 1px solid var(--border, #2a3044);
  border-radius: 8px;
  color: var(--text-1);
  padding: 8px 12px;
  font-size: 13px;
}
.wa-input-bar button {
  background: #4f46e5;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13px;
  cursor: pointer;
}
.wa-input-bar button:hover { background: #4338ca; }
.wa-input-bar button:disabled { opacity: 0.5; cursor: not-allowed; }
.wa-preview {
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.wa-no-preview {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-3);
  font-size: 13px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
}
@media (max-width: 1024px) {
  .wa-layout {
    grid-template-columns: 1fr;
    grid-template-rows: 1fr 1fr;
  }
}
</style>
