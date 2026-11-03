<template>
  <div class="library">
    <header class="topbar">
      <h1>精听工坊</h1>
      <nav class="entries">
        <button class="btn" @click="go('/vocab-book')">生词本</button>
        <button class="btn" @click="go('/settings')">设置</button>
      </nav>
    </header>

    <div v-if="dueCount > 0" class="review-banner" role="button" @click="go('/review-session')">
      <span>今日待复习 {{ dueCount }} 条</span>
      <span class="banner-action">开始复习 →</span>
    </div>

    <p v-if="pageError" class="error-text">{{ pageError }}</p>
    <p v-else-if="store.loading" class="hint">加载中…</p>

    <div v-if="!store.loading && sorted.length" class="grid">
      <article v-for="m in sorted" :key="m.id" class="card">
        <div class="card-head">
          <template v-if="editingId === m.id">
            <input
              v-model="editTitle"
              class="title-input"
              type="text"
              maxlength="200"
              autofocus
              @keyup.enter="confirmRename"
              @keyup.esc="cancelRename"
            />
          </template>
          <h3 v-else class="card-title">{{ m.title }}</h3>
          <span class="stage-tag" :class="stageClass(m.stage)">{{ stageLabel(m.stage) }}</span>
        </div>

        <p class="meta">{{ formatDuration(m.durationSec) }}</p>
        <p class="meta">
          最好成绩：{{ m.bestScore == null ? '—' : Math.round(m.bestScore) + ' 分' }}
          · 生词 {{ m.stats?.vocab ?? 0 }} · 没听懂 {{ m.stats?.notUnderstood ?? 0 }}
        </p>

        <div v-if="editingId === m.id" class="actions">
          <button class="btn primary" :disabled="savingRename" @click="confirmRename">保存</button>
          <button class="btn" @click="cancelRename">取消</button>
        </div>
        <div v-else class="actions">
          <button v-if="m.stage === 'learning'" class="btn primary" @click="go(`/learn/${m.id}`)">
            继续学习
          </button>
          <template v-else-if="m.stage === 'reviewing'">
            <button class="btn primary" @click="go(`/review/${m.id}`)">去泛听</button>
            <button class="btn" @click="go(`/quiz/${m.id}`)">开始检测</button>
          </template>
          <template v-else>
            <button class="btn primary" @click="go(`/learn/${m.id}`)">查看文稿</button>
            <button class="btn" @click="go(`/quiz/${m.id}`)">重测</button>
          </template>
        </div>

        <div v-if="editingId !== m.id" class="ops">
          <button class="op" @click="startRename(m)">重命名</button>
          <button class="op danger" @click="askDelete(m)">删除</button>
        </div>
        <p v-if="editingId === m.id && renameError" class="error-text">{{ renameError }}</p>
      </article>

      <button class="card new-card" @click="go('/import')">
        <span class="plus">＋</span>
        <span>新建导入</span>
      </button>
    </div>

    <div v-else-if="!store.loading && !pageError" class="empty">
      <p>还没有任何材料</p>
      <p class="hint">导入一段音频和官方文稿，开始你的第一段精听训练。</p>
      <button class="btn primary big" @click="go('/import')">＋ 新建导入</button>
    </div>

    <div v-if="pendingDelete" class="modal-mask" @click.self="pendingDelete = null">
      <div class="modal" role="dialog" aria-modal="true">
        <h2>删除材料</h2>
        <p>确定删除「{{ pendingDelete.title }}」吗？</p>
        <p class="warn">将连带音频与学习数据一并删除，且不可恢复。</p>
        <p v-if="deleteError" class="error-text">{{ deleteError }}</p>
        <div class="modal-actions">
          <button class="btn danger-solid" :disabled="deleting" @click="confirmDelete">
            {{ deleting ? '删除中…' : '确认删除' }}
          </button>
          <button class="btn" @click="pendingDelete = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { get } from '../api/client'
import { useMaterialStore } from '../stores/material'

const router = useRouter()
const store = useMaterialStore()

const STAGES = {
  learning: { label: '学习中', cls: 'tag-learning' },
  reviewing: { label: '复习中', cls: 'tag-reviewing' },
  mastered: { label: '已掌握', cls: 'tag-mastered' },
}
const STAGE_ORDER = { learning: 0, reviewing: 1, mastered: 2 }

const dueCount = ref(0)
const pageError = ref('')
const editingId = ref(null)
const editTitle = ref('')
const renameError = ref('')
const savingRename = ref(false)
const pendingDelete = ref(null)
const deleting = ref(false)
const deleteError = ref('')

const sorted = computed(() =>
  [...store.materials].sort(
    (a, b) =>
      (STAGE_ORDER[a.stage] ?? 9) - (STAGE_ORDER[b.stage] ?? 9) ||
      String(b.createdAt || '').localeCompare(String(a.createdAt || '')),
  ),
)

function stageLabel(stage) {
  return STAGES[stage]?.label || stage
}

function stageClass(stage) {
  return STAGES[stage]?.cls || 'tag-learning'
}

function formatDuration(sec) {
  const total = Math.max(0, Math.round(Number(sec) || 0))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

function go(path) {
  router.push(path)
}

async function loadDue() {
  try {
    const res = await get('/api/review/due')
    dueCount.value = res?.count ?? 0
  } catch {
    dueCount.value = 0
  }
}

function startRename(m) {
  editingId.value = m.id
  editTitle.value = m.title
  renameError.value = ''
}

function cancelRename() {
  editingId.value = null
  renameError.value = ''
}

async function confirmRename() {
  if (!editingId.value) return
  savingRename.value = true
  renameError.value = ''
  try {
    await store.rename(editingId.value, editTitle.value)
    editingId.value = null
  } catch (e) {
    renameError.value = e.message || '重命名失败'
  } finally {
    savingRename.value = false
  }
}

function askDelete(m) {
  pendingDelete.value = m
  deleteError.value = ''
}

async function confirmDelete() {
  if (!pendingDelete.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await store.remove(pendingDelete.value.id)
    pendingDelete.value = null
    await loadDue()
  } catch (e) {
    deleteError.value = e.message || '删除失败'
  } finally {
    deleting.value = false
  }
}

onMounted(async () => {
  loadDue()
  try {
    await store.loadMaterials()
  } catch (e) {
    pageError.value = e.message || '加载材料列表失败'
  }
})
</script>

<style scoped>
.library {
  max-width: 1080px;
  margin: 0 auto;
  padding: 16px 20px 64px;
  font-family: 'Segoe UI', 'Microsoft YaHei', system-ui, sans-serif;
  color: #1f2933;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.topbar h1 {
  font-size: 22px;
  margin: 0;
}
.entries {
  display: flex;
  gap: 8px;
}
.btn {
  padding: 7px 16px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #fff;
  font-size: 14px;
  cursor: pointer;
}
.btn:hover {
  background: #f3f4f6;
}
.btn.primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}
.btn.primary:hover {
  background: #1d4ed8;
}
.btn.primary:disabled {
  background: #93c5fd;
  border-color: #93c5fd;
  cursor: not-allowed;
}
.btn.big {
  padding: 10px 24px;
  font-size: 15px;
}
.btn.danger-solid {
  background: #dc2626;
  border-color: #dc2626;
  color: #fff;
}
.btn.danger-solid:hover {
  background: #b91c1c;
}
.btn.danger-solid:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.review-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff7ed;
  border: 1px solid #fdba74;
  border-radius: 10px;
  padding: 12px 18px;
  margin-bottom: 16px;
  cursor: pointer;
  font-size: 14px;
  color: #9a3412;
}
.review-banner:hover {
  background: #ffedd5;
}
.banner-action {
  font-weight: 600;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.card-title {
  font-size: 16px;
  margin: 0;
  word-break: break-all;
}
.title-input {
  flex: 1;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid #2563eb;
  border-radius: 6px;
  font-size: 14px;
}
.stage-tag {
  flex-shrink: 0;
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 999px;
  white-space: nowrap;
}
.tag-learning {
  background: #eff6ff;
  color: #1d4ed8;
}
.tag-reviewing {
  background: #fff7ed;
  color: #c2410c;
}
.tag-mastered {
  background: #ecfdf5;
  color: #047857;
}
.meta {
  margin: 0;
  font-size: 13px;
  color: #6b7280;
}
.actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.ops {
  display: flex;
  gap: 14px;
  margin-top: 8px;
}
.op {
  background: none;
  border: none;
  padding: 0;
  font-size: 13px;
  color: #6b7280;
  cursor: pointer;
}
.op:hover {
  color: #2563eb;
}
.op.danger:hover {
  color: #dc2626;
}
.new-card {
  align-items: center;
  justify-content: center;
  min-height: 148px;
  border-style: dashed;
  border-width: 2px;
  color: #6b7280;
  font-size: 15px;
  cursor: pointer;
  background: #fafafa;
}
.new-card:hover {
  border-color: #2563eb;
  color: #2563eb;
  background: #eff6ff;
}
.new-card .plus {
  font-size: 28px;
  line-height: 1;
}
.empty {
  text-align: center;
  padding: 72px 20px;
  color: #4b5563;
}
.empty .hint {
  margin-top: 4px;
}
.hint {
  color: #9ca3af;
  font-size: 13px;
}
.error-text {
  color: #dc2626;
  font-size: 13px;
  margin: 8px 0 0;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(17, 24, 39, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  background: #fff;
  border-radius: 12px;
  padding: 20px 24px;
  max-width: 380px;
  width: calc(100% - 48px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.18);
}
.modal h2 {
  font-size: 16px;
  margin: 0 0 10px;
}
.modal p {
  font-size: 14px;
  margin: 6px 0;
}
.modal .warn {
  color: #b45309;
}
.modal-actions {
  display: flex;
  gap: 10px;
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
