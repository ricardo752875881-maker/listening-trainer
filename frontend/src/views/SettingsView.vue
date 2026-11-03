<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  useSettingsStore,
  LLM_PROVIDERS,
  SPEED_OPTIONS,
  cloneSettings,
} from '../stores/settings'

const router = useRouter()
const store = useSettingsStore()

const draft = ref(null)
const savedMsg = ref(false)
const ALIGN_MODELS = [
  { value: 'base', label: 'base（推荐）', desc: 'facebook/wav2vec2-base-960h，速度快，边界精度够用' },
  { value: 'large', label: 'large', desc: 'facebook/wav2vec2-large-960h-lv60-self，边界更准，CPU 上慢约 3 倍' },
]

function masked(v) {
  return typeof v === 'string' && v.startsWith('****')
}

const llmKeyChanged = computed(() => draft.value && !masked(draft.value.llm.apiKey))

// ---------- 对齐模型下载状态 ----------

let pollTimer = null

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function ensurePoll() {
  const anyDownloading = ALIGN_MODELS.some(
    (m) => store.modelStatus[m.value]?.status === 'downloading'
  )
  if (anyDownloading && !pollTimer) {
    pollTimer = setInterval(async () => {
      await store.refreshModelStatus()
      const still = ALIGN_MODELS.some(
        (m) => store.modelStatus[m.value]?.status === 'downloading'
      )
      if (!still) stopPoll()
    }, 1500)
  }
}

async function refreshModels() {
  await store.refreshModelStatus()
  ensurePoll()
}

async function downloadModel(model) {
  await store.downloadModel(model)
  await refreshModels()
}

// ---------- 保存 ----------

async function save() {
  savedMsg.value = false
  const d = draft.value
  const payload = {
    alignModel: d.alignModel,
    llm: {
      provider: d.llm.provider,
      apiKey: d.llm.apiKey,
      model: d.llm.model,
      enabled: !!d.llm.enabled,
      thinking: !!d.llm.thinking,
    },
    defaultSpeed: Number(d.defaultSpeed),
    showTranslationDefault: !!d.showTranslationDefault,
  }
  const ok = await store.save(payload)
  if (ok) {
    draft.value = cloneSettings(store.settings)
    savedMsg.value = true
    setTimeout(() => (savedMsg.value = false), 3000)
  }
}

function testLlm() {
  const d = draft.value.llm
  store.testLlm({
    provider: d.provider,
    apiKey: llmKeyChanged.value ? d.apiKey : undefined,
    model: d.model,
    thinking: !!d.thinking,
  })
}

onMounted(async () => {
  await store.load()
  if (!draft.value) draft.value = cloneSettings(store.settings)
  refreshModels()
})
onBeforeUnmount(stopPoll)
</script>

<template>
  <div class="page">
    <header class="topbar">
      <button class="btn ghost" @click="router.push('/library')">← 材料库</button>
      <h1>设置</h1>
      <span></span>
    </header>

    <p v-if="store.loadError" class="error-text">{{ store.loadError }}</p>
    <p v-if="!draft" class="muted">加载中…</p>

    <template v-else>
      <!-- 对齐模型 -->
      <section class="panel">
        <h2>对齐模型（wav2vec2 强制对齐）</h2>
        <p class="note">
          导入时用所选模型把官方文稿逐词钉到音频上，全程本机离线运行，首次使用自动下载。
        </p>
        <div class="sub-section">
          <div v-for="m in ALIGN_MODELS" :key="m.value" class="model-row">
            <label class="radio-row compact">
              <input type="radio" :value="m.value" v-model="draft.alignModel" />
              <span>
                <b>{{ m.label }}</b>
                <small>{{ m.desc }}</small>
              </span>
            </label>
            <span class="model-status">
              <template v-if="store.modelStatus[m.value]?.status === 'downloaded'">
                <span class="chip ok">已下载</span>
              </template>
              <template v-else-if="store.modelStatus[m.value]?.status === 'downloading'">
                <span class="chip busy">下载中…</span>
              </template>
              <template v-else-if="store.modelStatus[m.value]?.status === 'error'">
                <span class="chip bad" :title="store.modelStatus[m.value]?.error">
                  下载失败：{{ store.modelStatus[m.value]?.error || '未知错误' }}
                </span>
                <button class="btn small" @click="downloadModel(m.value)">
                  重试
                </button>
              </template>
              <template v-else-if="store.modelStatus[m.value]?.status === 'not_downloaded'">
                <span class="chip">未下载</span>
                <button class="btn small" @click="downloadModel(m.value)">预下载</button>
              </template>
              <template v-else>
                <span class="chip">状态未知</span>
                <button class="btn small" @click="refreshModels">刷新</button>
              </template>
            </span>
          </div>
          <p v-if="store.modelStatusError" class="note">{{ store.modelStatusError }}</p>
        </div>
      </section>

      <!-- 大模型 -->
      <section class="panel">
        <h2>大模型（可选，用于跟读推荐）</h2>
        <div class="provider-row">
          <label v-for="p in LLM_PROVIDERS" :key="p.value" class="radio-row compact">
            <input type="radio" :value="p.value" v-model="draft.llm.provider" />
            <span><b>{{ p.label }}</b></span>
          </label>
        </div>
        <div class="key-row">
          <input
            v-model="draft.llm.apiKey"
            type="text"
            placeholder="API Key"
            autocomplete="off"
          />
          <input v-model="draft.llm.model" type="text" placeholder="模型名，如 deepseek-chat" />
        </div>
        <div class="key-row">
          <label class="switch-label">
            <input type="checkbox" v-model="draft.llm.enabled" />
            启用跟读片段推荐
          </label>
          <label v-if="draft.llm.provider === 'kimi'" class="switch-label">
            <input type="checkbox" v-model="draft.llm.thinking" />
            思考模式（更深但更慢，默认关闭）
          </label>
          <button class="btn" :disabled="store.testingLlm" @click="testLlm">
            {{ store.testingLlm ? '测试中…' : '连通性测试' }}
          </button>
        </div>
        <p v-if="!llmKeyChanged && draft.llm.apiKey" class="note">已保存 Key（已掩码显示）；输入新值可替换。</p>
        <p v-if="!draft.llm.enabled" class="note">关闭或未配置时不做跟读推荐，不影响其他功能。</p>
        <p v-if="store.llmTest" class="test-result" :class="store.llmTest.ok ? 'ok' : 'bad'">
          {{ store.llmTest.ok ? '✓' : '✗' }} {{ store.llmTest.message }}
        </p>
      </section>

      <!-- 偏好 -->
      <section class="panel">
        <h2>播放与显示</h2>
        <div class="pref-row">
          <label>
            默认播放速度
            <select v-model.number="draft.defaultSpeed">
              <option v-for="s in SPEED_OPTIONS" :key="s" :value="s">{{ s }}×</option>
            </select>
          </label>
          <label class="switch-label">
            <input type="checkbox" v-model="draft.showTranslationDefault" />
            默认显示译文
          </label>
        </div>
        <p class="note">新导入的材料与学习界面将按此偏好展示。</p>
      </section>

      <div class="save-bar">
        <span v-if="savedMsg" class="saved-msg">✓ 已保存</span>
        <span v-if="store.saveError" class="error-text small">{{ store.saveError }}</span>
        <button class="btn primary big" :disabled="store.saving" @click="save">
          {{ store.saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page {
  max-width: 680px;
  margin: 24px auto;
  padding: 0 16px;
  font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
  color: #1f2937;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.topbar h1 {
  font-size: 18px;
  flex: 1;
  margin: 0;
  text-align: center;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 20px;
  margin-bottom: 16px;
}
.panel h2 {
  font-size: 15px;
  margin: 0 0 12px;
}
.panel h3 {
  font-size: 13px;
  color: #4b5563;
  margin: 16px 0 8px;
}
.btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid #d1d5db;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
}
.btn.primary {
  background: #1d4ed8;
  color: #fff;
  border-color: #1d4ed8;
}
.btn.big {
  padding: 10px 32px;
  font-size: 15px;
}
.btn.small {
  padding: 4px 10px;
  font-size: 12px;
}
.btn.ghost {
  border-color: transparent;
  color: #374151;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.muted {
  color: #6b7280;
  font-size: 14px;
}
.note {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 8px;
}
.error-text {
  color: #dc2626;
  font-size: 14px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 10px;
  padding: 10px 14px;
}
.error-text.small {
  padding: 6px 10px;
  font-size: 12px;
}
.radio-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  margin-bottom: 8px;
  cursor: pointer;
}
.radio-row.compact {
  padding: 6px 10px;
  margin-bottom: 0;
  border: none;
  align-items: center;
}
.radio-row input[type='radio'] {
  margin-top: 3px;
}
.radio-row.compact input[type='radio'] {
  margin-top: 0;
}
.radio-row span {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.radio-row small {
  color: #9ca3af;
  font-size: 12px;
}
.privacy-box {
  margin-top: 10px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #c2410c;
  font-size: 13px;
  border-radius: 10px;
  padding: 10px 14px;
}
.sub-section {
  margin-top: 14px;
  border-top: 1px dashed #e5e7eb;
  padding-top: 4px;
}
.model-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 0;
  flex-wrap: wrap;
}
.model-status {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chip {
  font-size: 12px;
  color: #6b7280;
  background: #f3f4f6;
  border-radius: 10px;
  padding: 2px 10px;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chip.ok {
  color: #047857;
  background: #ecfdf5;
}
.chip.busy {
  color: #1d4ed8;
  background: #eff6ff;
}
.chip.bad {
  color: #dc2626;
  background: #fef2f2;
}
.key-row {
  display: flex;
  gap: 10px;
  margin-top: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.key-row input[type='text'] {
  flex: 1;
  min-width: 200px;
  padding: 9px 10px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
}
.provider-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.test-result {
  margin: 10px 0 0;
  font-size: 13px;
  border-radius: 10px;
  padding: 8px 12px;
}
.test-result.ok {
  color: #047857;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
}
.test-result.bad {
  color: #dc2626;
  background: #fef2f2;
  border: 1px solid #fecaca;
}
.pref-row {
  display: flex;
  gap: 24px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 14px;
}
.pref-row select {
  margin-left: 8px;
  padding: 7px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  background: #fff;
}
.switch-label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
}
.save-bar {
  display: flex;
  gap: 14px;
  align-items: center;
  justify-content: flex-end;
  margin: 8px 0 24px;
}
.saved-msg {
  color: #047857;
  font-size: 14px;
}
</style>
