import { defineStore } from 'pinia'
import { get, post, del } from '../api/client'

export const REVIEW_TYPE_LABELS = {
  word: '单词',
  phrase: '短语',
  sentence: '没听懂句',
}

export const useReviewStore = defineStore('review', {
  state: () => ({
    dueCount: 0,
    dueItems: [],
    dueLoaded: false,
    dueLoading: false,
    dueError: '',
    items: [],
    itemsLoaded: false,
    itemsLoading: false,
    itemsError: '',
  }),
  actions: {
    // GET /api/review/due → {count, items}（items ≤ 20 张，count 为今日到期总数）
    async fetchDue() {
      this.dueLoading = true
      this.dueError = ''
      try {
        const data = await get('/api/review/due')
        this.dueCount = data.count ?? (data.items || []).length
        this.dueItems = data.items || []
        this.dueLoaded = true
      } catch (e) {
        this.dueError = e.message || '到期条目加载失败'
      } finally {
        this.dueLoading = false
      }
    },
    // POST /api/review/items/{rid}/rate {passed}
    async rate(id, passed) {
      await post(`/api/review/items/${id}/rate`, { passed })
    },
    // GET /api/review/items?materialId=&type=&sort=familiarity
    async fetchItems({ materialId = '', type = '', sortFamiliarity = false } = {}) {
      this.itemsLoading = true
      this.itemsError = ''
      try {
        const params = new URLSearchParams()
        if (materialId) params.set('materialId', materialId)
        if (type) params.set('type', type)
        if (sortFamiliarity) params.set('sort', 'familiarity')
        const qs = params.toString()
        this.items = await get(`/api/review/items${qs ? '?' + qs : ''}`)
        this.itemsLoaded = true
      } catch (e) {
        this.itemsError = e.message || '生词本加载失败'
      } finally {
        this.itemsLoading = false
      }
    },
    // DELETE /api/review/items/{rid}（唯一移除方式）
    async removeItem(id) {
      await del(`/api/review/items/${id}`)
      this.items = this.items.filter((it) => it.id !== id)
    },
  },
})
