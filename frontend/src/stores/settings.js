import { defineStore } from 'pinia'
import { get, put, post } from '../api/client'

export const DEFAULT_SETTINGS = {
  alignModel: 'base',
  llm: { provider: 'openai', apiKey: '', model: '', enabled: false, thinking: false },
  defaultSpeed: 1.0,
  showTranslationDefault: true,
}

export const LLM_PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'kimi', label: '月之暗面 Kimi' },
]

export const SPEED_OPTIONS = [0.5, 0.75, 1.0, 1.25, 1.5]

export function cloneSettings(data) {
  return JSON.parse(JSON.stringify(data))
}

function normalizeModelEntry(entry) {
  if (!entry) return { status: 'unknown', error: null }
  if (typeof entry === 'string') return { status: entry, error: null }
  return { status: entry.status || 'unknown', error: entry.error || null }
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    settings: cloneSettings(DEFAULT_SETTINGS),
    loaded: false,
    loadError: '',
    saving: false,
    saveError: '',
    testingLlm: false,
    llmTest: null, // {ok, message}
    modelStatus: {}, // { base: {status, error}, large: {...} }；status ∈ downloaded/not_downloaded/downloading/error
    modelStatusError: '',
  }),
  getters: {
    llmConfigured: (s) => !!(s.settings.llm && s.settings.llm.enabled),
  },
  actions: {
    async load(force = false) {
      if (this.loaded && !force) return
      try {
        const data = await get('/api/settings')
        this.settings = {
          ...cloneSettings(DEFAULT_SETTINGS),
          ...data,
          llm: { ...cloneSettings(DEFAULT_SETTINGS.llm), ...(data.llm || {}) },
        }
        this.loaded = true
        this.loadError = ''
      } catch (e) {
        this.loadError = e.message || '设置加载失败'
      }
    },
    async save(next) {
      this.saving = true
      this.saveError = ''
      try {
        const data = await put('/api/settings', next)
        this.settings = {
          ...cloneSettings(DEFAULT_SETTINGS),
          ...data,
          llm: { ...cloneSettings(DEFAULT_SETTINGS.llm), ...(data.llm || {}) },
        }
        this.loaded = true
        // 保存后清空旧测试结果（配置已变更）
        this.llmTest = null
        return true
      } catch (e) {
        this.saveError = e.message || '设置保存失败'
        return false
      } finally {
        this.saving = false
      }
    },
    async testLlm(config) {
      this.testingLlm = true
      this.llmTest = null
      try {
        this.llmTest = await post('/api/settings/test-llm', config || {})
      } catch (e) {
        this.llmTest = { ok: false, message: e.message || '连通性测试失败' }
      } finally {
        this.testingLlm = false
      }
    },
    async refreshModelStatus() {
      try {
        const data = await get('/api/models/align-status')
        const raw = data.models || data
        this.modelStatus = {
          base: normalizeModelEntry(raw.base),
          large: normalizeModelEntry(raw.large),
        }
        this.modelStatusError = ''
      } catch (e) {
        this.modelStatusError = e.message || '模型下载状态获取失败'
      }
    },
    async downloadModel(model) {
      try {
        await post(`/api/models/align/${model}/download`, {})
      } catch (e) {
        // 失败详情由状态接口轮询显示（status=error）
      }
    },
  },
})
