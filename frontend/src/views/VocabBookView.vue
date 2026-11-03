<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '../api/client'
import { useReviewStore, REVIEW_TYPE_LABELS } from '../stores/review'

const router = useRouter()
const store = useReviewStore()

const materials = ref([]) // [{id, title}]
const filterMaterialId = ref('')
const filterType = ref('')
const sortFamiliarity = ref(false)
const deletingId = ref('')

const typeBadgeClass = {
  word: 't-word',
  phrase: 't-phrase',
  sentence: 't-sentence',
}

const materialTitle = computed(() => {
  const map = {}
  for (const m of materials.value) map[m.id] = m.title
  return map
})

async function reload() {
  await store.fetchItems({
    materialId: filterMaterialId.value,
    type: filterType.value,
    sortFamiliarity: sortFamiliarity.value,
  })
}

async function removeItem(item) {
  if (!window.confirm(`删除条目「${item.text}」？\n删除后不再出现在复习队列中。`)) return
  deletingId.value = item.id
  try {
    await store.removeItem(item.id)
  } catch (e) {
    window.alert(e.message || '删除失败')
  } finally {
    deletingId.value = ''
  }
}

function fmtDue(dueAt) {
  if (!dueAt) return '—'
  const d = new Date(dueAt)
  if (Number.isNaN(d.getTime())) return dueAt
  return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

watch([filterMaterialId, filterType, sortFamiliarity], reload)

onMounted(async () => {
  try {
    materials.value = await get('/api/materials')
  } catch {
    materials.value = []
  }
  reload()
})
</script>

<template>
  <div class="page">
    <header class="topbar">
      <button class="btn ghost" @click="router.push('/library')">← 材料库</button>
      <h1>生词本</h1>
      <span class="count-badge" v-if="store.itemsLoaded">{{ store.items.length }} 条</span>
    </header>

    <section class="panel">
      <div class="filters">
        <label>
          材料
          <select v-model="filterMaterialId">
            <option value="">全部材料</option>
            <option v-for="m in materials" :key="m.id" :value="m.id">{{ m.title }}</option>
          </select>
        </label>
        <label>
          类型
          <select v-model="filterType">
            <option value="">全部类型</option>
            <option value="word">单词</option>
            <option value="phrase">短语</option>
            <option value="sentence">没听懂句</option>
          </select>
        </label>
        <label class="switch-label">
          <input type="checkbox" v-model="sortFamiliarity" />
          按熟悉度排序
        </label>
      </div>

      <p v-if="store.itemsLoading" class="muted">加载中…</p>
      <p v-else-if="store.itemsError" class="error-text">
        {{ store.itemsError }} <button class="btn small" @click="reload">重试</button>
      </p>

      <!-- 空态 -->
      <div v-else-if="!store.items.length" class="empty">
        <p class="empty-icon">📭</p>
        <p>暂无复习条目。</p>
        <p class="muted">在学习界面开启「标记模式」划词添加生词/短语，或点击句尾「没听懂」图标，条目会自动汇入这里。</p>
        <button class="btn primary" @click="router.push('/library')">去学习</button>
      </div>

      <!-- 条目列表 -->
      <div v-else class="item-list">
        <div v-for="item in store.items" :key="item.id" class="item">
          <div class="item-main">
            <div class="item-head">
              <span class="type-badge" :class="typeBadgeClass[item.type]">
                {{ REVIEW_TYPE_LABELS[item.type] || item.type }}
              </span>
              <span class="item-text">{{ item.text }}</span>
            </div>
            <p v-if="item.meaning" class="item-meaning">释义：{{ item.meaning }}</p>
            <p v-else-if="item.type !== 'sentence'" class="item-meaning empty">未填写释义</p>
            <p class="item-meta">
              来自《{{ materialTitle[item.materialId] || item.materialId }}》 ·
              熟悉度：认识 {{ item.knownCount }} / 复习 {{ item.reviewCount }} ·
              下次到期 {{ fmtDue(item.dueAt) }}
            </p>
          </div>
          <button
            class="btn small danger"
            :disabled="deletingId === item.id"
            @click="removeItem(item)"
          >
            删除
          </button>
        </div>
      </div>

      <p class="note">条目不自动移除——是否删除完全由你决定（FR-039）。</p>
    </section>
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
}
.count-badge {
  font-size: 12px;
  color: #6b7280;
  background: #f3f4f6;
  border-radius: 10px;
  padding: 2px 10px;
  white-space: nowrap;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 20px;
}
.filters {
  display: flex;
  gap: 14px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 14px;
  font-size: 13px;
  color: #4b5563;
}
.filters label {
  display: flex;
  align-items: center;
  gap: 6px;
}
.filters select {
  padding: 6px 8px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 13px;
  background: #fff;
  max-width: 180px;
}
.switch-label {
  cursor: pointer;
  user-select: none;
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
.btn.small {
  padding: 4px 10px;
  font-size: 12px;
}
.btn.danger {
  color: #dc2626;
  border-color: #fecaca;
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
  margin-top: 12px;
}
.error-text {
  color: #dc2626;
  font-size: 14px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 10px;
  padding: 10px 14px;
}
.empty {
  text-align: center;
  padding: 30px 10px;
}
.empty-icon {
  font-size: 36px;
  margin: 0 0 6px;
}
.empty p {
  margin: 6px 0;
}
.item-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: #f9fafb;
  border-radius: 10px;
  padding: 12px 14px;
}
.item-main {
  flex: 1;
  min-width: 0;
}
.item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.type-badge {
  font-size: 11px;
  border-radius: 8px;
  padding: 1px 8px;
  white-space: nowrap;
}
.t-word {
  color: #1d4ed8;
  background: #eff6ff;
}
.t-phrase {
  color: #047857;
  background: #ecfdf5;
}
.t-sentence {
  color: #c2410c;
  background: #fff7ed;
}
.item-text {
  font-size: 15px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.item-meaning {
  margin: 4px 0 0;
  font-size: 13px;
  color: #047857;
}
.item-meaning.empty {
  color: #b45309;
}
.item-meta {
  margin: 4px 0 0;
  font-size: 12px;
  color: #9ca3af;
}
</style>
