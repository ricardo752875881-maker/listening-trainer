import { defineStore } from 'pinia'

import { del, get, request } from '../api/client'

export const useMaterialStore = defineStore('material', {
  state: () => ({
    materials: [],
    loading: false,
    error: null,
  }),
  getters: {
    stageOrder: () => ({ learning: 0, reviewing: 1, mastered: 2 }),
  },
  actions: {
    async loadMaterials() {
      this.loading = true
      this.error = null
      try {
        const list = await get('/api/materials')
        this.materials = Array.isArray(list) ? list : []
        return this.materials
      } catch (e) {
        this.error = e.message || '加载材料列表失败'
        throw e
      } finally {
        this.loading = false
      }
    },
    async rename(id, title) {
      const trimmed = (title || '').trim()
      if (!trimmed) throw new Error('标题不能为空')
      const updated = await request(`/api/materials/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title: trimmed }),
      })
      const idx = this.materials.findIndex((m) => m.id === id)
      if (idx >= 0) {
        this.materials[idx] = { ...this.materials[idx], title: trimmed, ...(updated && updated.id ? updated : {}) }
      }
      return updated
    },
    async remove(id) {
      await del(`/api/materials/${id}`)
      this.materials = this.materials.filter((m) => m.id !== id)
    },
  },
})
