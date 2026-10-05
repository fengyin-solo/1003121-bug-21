<template>
  <section class="page" data-module="roadway">
    <header class="page-head">
      <div>
        <h2>巷道维修管理</h2>
        <p class="page-desc">
          维修任务按施工队伍归属：只有本队验收人员能在「待验收」填写验收结论，跨队打开仅可查看；
          同一条任务重复验收只认第一次落库的结论，结论同步至巷道维修台账复核清单。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记维修任务</button>
        <button class="btn" type="button" @click="exportRows">导出巷道维修清单</button>
      </div>
    </header>

    <div class="identity-bar">
      <span class="identity-label">当前操作者</span>
      <select v-model="session.operatorId" @change="applyOperator">
        <option v-for="op in operators" :key="op.id" :value="op.id">
          {{ op.name }}（{{ op.role }}{{ op.team ? ' · ' + op.team : '' }}）
        </option>
      </select>
      <span v-if="currentOperator" class="identity-meta">
        角色：{{ currentOperator.role }}<template v-if="currentOperator.team"> ｜ 归属队伍：{{ currentOperator.team }}</template>
      </span>
      <span class="identity-hint">写操作均带此身份提交，越权会被后端当场拒绝并记入操作日志</span>
    </div>

    <div class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        type="button"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 任务列表 -->
    <div v-if="activeTab === 'tasks'">
      <div class="stat-row">
        <article v-for="item in stats" :key="item.label" class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong class="stat-value">{{ item.value }}</strong>
        </article>
      </div>

      <form class="filter-bar" @submit.prevent="reload">
        <label class="filter-item">
          <span>任务编号</span>
          <input v-model="filters.keyword" placeholder="按任务编号检索" />
        </label>
        <label class="filter-item">
          <span>任务状态</span>
          <select v-model="filters.status">
            <option value="">全部</option>
            <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>施工队伍</span>
          <select v-model="filters.team">
            <option value="">全部</option>
            <option v-for="t in teams" :key="t" :value="t">{{ t }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">
              <template v-if="column === '任务状态'">
                <span :class="{ 'status-done': row[column] === '已竣工' }">{{ row[column] ?? '—' }}</span>
              </template>
              <template v-else-if="column === '施工队伍'">
                {{ row[column] }}
                <em v-if="!isOwnTeam(row)" class="readonly-tag">跨队·只读</em>
              </template>
              <template v-else>{{ row[column] || '—' }}</template>
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="openDetail(row)">查看详情</button>
              <template v-for="action in availableActions(row)" :key="action.name">
                <button
                  v-if="action.name !== '验收竣工'"
                  class="link"
                  type="button"
                  @click="runAction(action.name, row)"
                >
                  {{ action.name }}
                </button>
                <button
                  v-else
                  class="link"
                  type="button"
                  @click="openAccept(row)"
                >
                  填写验收结论
                </button>
              </template>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">暂无巷道维修数据，可先登记维修任务</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条巷道维修记录（列表、详情、台账同一份数据口径）</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </div>

    <!-- 台账复核清单 -->
    <div v-else-if="activeTab === 'review'">
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in reviewColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in reviewRows" :key="String(row.id)">
            <td v-for="column in reviewColumns" :key="column">
              <template v-if="column === '复核结论'">
                {{ row[column] }}
                <em v-if="row['历史签字保留']" class="legacy-tag">历史跨队签字保留</em>
              </template>
              <template v-else>{{ row[column] || '—' }}</template>
            </td>
          </tr>
          <tr v-if="!reviewRows.length">
            <td :colspan="reviewColumns.length" class="empty-state">暂无已复核记录，验收竣工后自动同步至此</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ reviewRows.length }} 条复核记录，来源为任务首次落库的验收结论</span>
        <span v-if="reviewError" class="error-text">{{ reviewError }}</span>
      </footer>
    </div>

    <!-- 操作日志 -->
    <div v-else>
      <div class="filter-bar">
        <label class="filter-item">
          <span>
            <input v-model="logDeniedOnly" type="checkbox" @change="loadLogs" />
            只看越权拒绝
          </span>
        </label>
        <button class="btn ghost" type="button" @click="loadLogs">刷新日志</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in logColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in logRows" :key="String(row.id)">
            <td v-for="column in logColumns" :key="column">
              <template v-if="column === '结果'">
                <span :class="{ 'log-denied': row.result === '越权拒绝' }">{{ row.result }}</span>
              </template>
              <template v-else-if="column === '操作者'">
                {{ row.operator_name }}（{{ row.role || '-' }}{{ row.team ? ' · ' + row.team : '' }}）
              </template>
              <template v-else-if="column === '缺失授权'">{{ missingText(row) }}</template>
              <template v-else>{{ (column === '时间' ? row.time : column === '动作' ? row.action : column === '任务ID' ? row.entry_id : column === '原因' ? row.reason : '') || '—' }}</template>
            </td>
          </tr>
          <tr v-if="!logRows.length">
            <td :colspan="logColumns.length" class="empty-state">暂无操作日志</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 验收弹窗 -->
    <div v-if="acceptTarget" class="modal-mask" @click.self="acceptTarget = null">
      <div class="modal">
        <h3>填写验收结论 · {{ acceptTarget['任务编号'] }}</h3>
        <p class="modal-sub">
          {{ acceptTarget['维修巷道'] }} ｜ 施工队伍：{{ acceptTarget['施工队伍'] }}
          <em v-if="!canAccept(acceptTarget)" class="legacy-tag">你不是该队验收人员，提交会被当场拒绝</em>
        </p>
        <label class="form-row">
          <span>验收结论 <b>*</b></span>
          <select v-model="acceptForm.conclusion">
            <option value="">请选择</option>
            <option v-for="r in acceptResults" :key="r" :value="r">{{ r }}</option>
          </select>
        </label>
        <label class="form-row">
          <span>验收意见</span>
          <textarea v-model="acceptForm.opinion" rows="3" placeholder="质量、尺寸、整改情况等说明"></textarea>
        </label>
        <p v-if="acceptError" class="error-text">{{ acceptError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="acceptTarget = null">取消</button>
          <button class="btn primary" type="button" @click="submitAccept">提交验收</button>
        </div>
      </div>
    </div>

    <!-- 详情弹窗：列表与详情读同一份 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <h3>任务详情 · {{ detail['任务编号'] }}</h3>
        <p v-if="!isOwnTeam(detail)" class="modal-sub"><em class="readonly-tag">跨队任务，仅可查看，不能执行任何动作</em></p>
        <dl class="detail-grid">
          <template v-for="item in detailItems" :key="item.key">
            <dt>{{ item.label }}</dt>
            <dd>{{ detail[item.key] || '—' }}</dd>
          </template>
        </dl>
        <p v-if="detail['历史签字保留']" class="modal-sub">
          <em class="legacy-tag">该记录竣工时验收人非本队验收人员，按当时签字保留原结论，不追溯改判</em>
        </p>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 登记弹窗 -->
    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <h3>登记维修任务</h3>
        <label class="form-row">
          <span>任务编号 <b>*</b></span>
          <input v-model="createForm['任务编号']" placeholder="如 ROAD-0006" />
        </label>
        <label class="form-row">
          <span>维修巷道 <b>*</b></span>
          <input v-model="createForm['维修巷道']" />
        </label>
        <label class="form-row">
          <span>维修内容 <b>*</b></span>
          <textarea v-model="createForm['维修内容']" rows="2"></textarea>
        </label>
        <label class="form-row">
          <span>施工队伍 <b>*</b></span>
          <select v-model="createForm['施工队伍']">
            <option value="">请选择归属队伍</option>
            <option v-for="t in teams" :key="t" :value="t">{{ t }}</option>
          </select>
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="creating = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">提交登记</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null | string[]>
interface OperatorInfo {
  id: string
  name: string
  role: string
  team: string | null
}

const ENDPOINT = '/api/roadway'
const columns = ['任务编号', '维修巷道', '维修内容', '施工队伍', '派发日期', '开工日期', '竣工日期', '验收人员', '验收结论', '任务状态']
const reviewColumns = ['任务编号', '维修巷道', '施工队伍', '竣工日期', '复核状态', '复核结论', '复核意见', '复核人', '复核时间']
const logColumns = ['时间', '操作者', '动作', '任务ID', '结果', '缺失授权', '原因']
const statuses = ['待派发', '施工中', '待验收', '已竣工']
const acceptResults = ['验收合格', '验收不合格']

const session = useSessionStore()
const operators = ref<OperatorInfo[]>([])
const teams = ref<string[]>([])
const currentOperator = computed<OperatorInfo | null>(
  () => operators.value.find((op) => op.id === session.operatorId) ?? null,
)

const tabs = [
  { key: 'tasks', label: '维修任务' },
  { key: 'review', label: '台账复核清单' },
  { key: 'logs', label: '操作日志' },
] as const
const activeTab = ref<(typeof tabs)[number]['key']>('tasks')

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = reactive<Record<string, string>>({ keyword: '', status: '', team: '' })

const reviewRows = ref<Row[]>([])
const reviewError = ref('')
const logRows = ref<Row[]>([])
const logDeniedOnly = ref(false)

const stats = computed(() => [
  { label: '待派发任务', value: rows.value.filter((r) => r['任务状态'] === '待派发').length },
  { label: '施工中任务', value: rows.value.filter((r) => r['任务状态'] === '施工中').length },
  { label: '待验收任务', value: rows.value.filter((r) => r['任务状态'] === '待验收').length },
  { label: '已竣工任务', value: rows.value.filter((r) => r['任务状态'] === '已竣工').length },
])

const detailItems = [
  { key: '维修巷道', label: '维修巷道' },
  { key: '维修内容', label: '维修内容' },
  { key: '施工队伍', label: '施工队伍' },
  { key: '派发日期', label: '派发日期' },
  { key: '开工日期', label: '开工日期' },
  { key: '竣工日期', label: '竣工日期' },
  { key: '任务状态', label: '任务状态' },
  { key: '验收人员', label: '验收人员' },
  { key: '验收结论', label: '验收结论' },
  { key: '验收意见', label: '验收意见' },
  { key: '验收时间', label: '验收时间' },
]

const detail = ref<Row | null>(null)
const creating = ref(false)
const createForm = reactive<Record<string, string>>({ 任务编号: '', 维修巷道: '', 维修内容: '', 施工队伍: '' })
const createError = ref('')
const acceptTarget = ref<Row | null>(null)
const acceptForm = reactive({ conclusion: '', opinion: '' })
const acceptError = ref('')

function isOwnTeam(row: Row): boolean {
  const op = currentOperator.value
  return !!op && !!op.team && op.team === row['施工队伍']
}

function missingText(row: Row): string {
  const missing = row.missing
  return Array.isArray(missing) && missing.length ? missing.join('、') : '—'
}

function canAccept(row: Row): boolean {
  const op = currentOperator.value
  return !!op && op.role === '验收' && isOwnTeam(row)
}

function availableActions(row: Row): { name: string }[] {
  // 只露出当前状态允许的动作；是否有权点得动以后端校验为准（越权点击用于验证拦截）。
  switch (row['任务状态']) {
    case '待派发':
      return [{ name: '派发任务' }]
    case '施工中':
      return isOwnTeam(row) ? [{ name: '开始施工' }] : []
    case '待验收':
      return [{ name: '验收竣工' }]
    default:
      return []
  }
}

async function loadDirectory() {
  try {
    const response = await request(`${ENDPOINT}/operators`)
    if (response.ok) {
      const payload = await response.json()
      operators.value = payload.operators ?? []
      teams.value = payload.teams ?? []
      applyOperator()
    }
  } catch {
    // 目录加载失败不阻断列表读取
  }
}

function applyOperator() {
  const op = operators.value.find((item) => item.id === session.operatorId)
  if (op) {
    session.setOperator(op)
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.team = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createError.value = ''
  creating.value = true
}

async function submitCreate() {
  createError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.detail || payload.message || '登记失败')
    }
    creating.value = false
    Object.assign(createForm, { 任务编号: '', 维修巷道: '', 维修内容: '', 施工队伍: '' })
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '登记失败'
  }
}

function openDetail(row: Row) {
  detail.value = row
}

function openAccept(row: Row) {
  acceptTarget.value = row
  acceptForm.conclusion = ''
  acceptForm.opinion = ''
  acceptError.value = ''
}

async function submitAccept() {
  if (!acceptTarget.value) return
  acceptError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${acceptTarget.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: { action: '验收竣工', 验收结论: acceptForm.conclusion, 验收意见: acceptForm.opinion },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.detail || payload.message || '验收未生效')
    }
    acceptTarget.value = null
    await reload()
    await loadReview()
    await loadLogs()
  } catch (error) {
    acceptError.value = error instanceof Error ? error.message : '验收提交失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.detail || payload.message || '巷道维修动作未生效')
    }
    await reload()
    if (activeTab.value === 'logs') {
      await loadLogs()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巷道维修操作失败'
    await loadLogs()
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.team) query.set('team', filters.team)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('维修任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巷道维修列表读取失败'
  }
}

async function loadReview() {
  reviewError.value = ''
  try {
    const response = await request(`${ENDPOINT}/review`)
    if (!response.ok) {
      throw new Error('台账复核清单读取失败')
    }
    const payload = await response.json()
    reviewRows.value = payload.items ?? []
  } catch (error) {
    reviewError.value = error instanceof Error ? error.message : '台账复核清单读取失败'
  }
}

async function loadLogs() {
  const query = new URLSearchParams()
  if (logDeniedOnly.value) query.set('denied_only', 'true')
  const response = await request(`${ENDPOINT}/audit-logs?${query.toString()}`)
  if (response.ok) {
    const payload = await response.json()
    logRows.value = payload.items ?? []
  }
}

function switchTab(key: (typeof tabs)[number]['key']) {
  activeTab.value = key
  if (key === 'review') void loadReview()
  if (key === 'logs') void loadLogs()
}

onMounted(async () => {
  await loadDirectory()
  await reload()
})
</script>

<style scoped>
.identity-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.identity-label { color: var(--muted); }
.identity-meta { color: #1f2937; }
.identity-hint { color: var(--muted); font-size: 12px; margin-left: auto; }
.tab-bar { display: flex; gap: 8px; margin-bottom: 12px; }
.tab-btn {
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 6px 6px 0 0;
  padding: 6px 16px;
  cursor: pointer;
  font-size: 13px;
}
.tab-btn.active { background: var(--brand); border-color: var(--brand); color: #fff; }
.readonly-tag,
.legacy-tag {
  font-style: normal;
  font-size: 11px;
  border-radius: 4px;
  padding: 1px 6px;
  margin-left: 6px;
}
.readonly-tag { background: #f1f5f9; color: var(--muted); border: 1px solid var(--border); }
.legacy-tag { background: #fff7ed; color: #c2410c; border: 1px solid #fed7aa; }
.status-done { color: #047857; font-weight: 600; }
.log-denied { color: #b42318; font-weight: 600; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  background: #fff;
  border-radius: 10px;
  width: 560px;
  max-width: 92vw;
  padding: 18px 20px;
}
.modal h3 { margin: 0 0 6px; font-size: 16px; }
.modal-sub { color: var(--muted); font-size: 12px; margin: 0 0 12px; }
.form-row { display: block; margin-bottom: 10px; font-size: 13px; }
.form-row span { display: block; margin-bottom: 4px; color: var(--muted); }
.form-row b { color: #b42318; }
.form-row input,
.form-row select,
.form-row textarea {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: inherit;
  font-size: 13px;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.detail-grid {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 6px 12px;
  font-size: 13px;
  margin: 0;
}
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
</style>
