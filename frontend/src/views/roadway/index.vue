<template>
  <section class="page" data-module="roadway">
    <header class="page-head">
      <div>
        <h2>巷道维修管理</h2>
        <p class="page-desc">
          维修任务按施工队伍归属：跨队只能查看；仅本队验收员可在待验收步骤填验收结论，
          两人同时验收以第一次落库为准。验收结论同步进巷道维修台账复核清单。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记维修任务</button>
        <button class="btn" type="button" @click="exportRows">导出巷道维修清单</button>
      </div>
    </header>

    <div class="identity-banner">
      当前身份：<strong>{{ store.operator }}</strong>
      <template v-if="store.team">（{{ store.team }} · {{ store.roles.join('、') || '无角色' }}）</template>
      <template v-else>（无归属队伍，所有任务仅可查看）</template>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>任务编号</span>
        <input v-model="keyword" placeholder="按任务编号检索" />
      </label>
      <label class="filter-item">
        <span>任务状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>施工队伍</span>
        <select v-model="teamFilter">
          <option value="">全部队伍</option>
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
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button v-if="column === '任务编号'" class="link" type="button" @click="openDetail(row)">
              {{ row[column] ?? '—' }}
            </button>
            <template v-else>
              <span v-if="column === '验收人员' && row['历史签字']" :title="'存量记录：验收人非本队在册验收员，按当时签字保留'">
                {{ row[column] || '—' }}<em class="legacy-tag">历史签字</em>
              </span>
              <span v-else>{{ row[column] || '—' }}</span>
            </template>
          </td>
          <td class="row-actions">
            <!-- 状态允许且本队有角色才显示按钮；即使前端漏判，后端也会 403 并留日志 -->
            <template v-if="row.status === '待派发' && store.canConstruct(row['施工队伍'])">
              <button class="link" type="button" @click="runAction('派发任务', row)">派发任务</button>
            </template>
            <template v-if="row.status === '施工中' && store.canConstruct(row['施工队伍'])">
              <button class="link" type="button" @click="runAction('开始施工', row)">送验（完成施工）</button>
            </template>
            <button
              v-if="row.status === '待验收' && store.canAccept(row['施工队伍'])"
              class="link"
              type="button"
              @click="openAccept(row)"
            >
              填验收结论
            </button>
            <button class="link" type="button" @click="openDetail(row)">查看</button>
            <span v-if="row.status === '待验收' && !store.canAccept(row['施工队伍'])" class="action-hint">
              验收需{{ row['施工队伍'] }}验收员
            </span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的巷道维修数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条巷道维修记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 验收结论弹窗 -->
    <div v-if="acceptTarget" class="modal-mask" @click.self="closeAccept">
      <div class="modal">
        <h3>填写验收结论</h3>
        <dl class="detail-list compact">
          <div><dt>任务编号</dt><dd>{{ acceptTarget['任务编号'] }}</dd></div>
          <div><dt>维修巷道</dt><dd>{{ acceptTarget['维修巷道'] }}</dd></div>
          <div><dt>施工队伍</dt><dd>{{ acceptTarget['施工队伍'] }}</dd></div>
          <div><dt>验收人</dt><dd>{{ store.operator }}（{{ store.team }}）</dd></div>
        </dl>
        <form class="accept-form" @submit.prevent="submitAccept">
          <label class="filter-item">
            <span>验收结论（一经落库不可更改）</span>
            <select v-model="acceptForm.conclusion">
              <option value="合格">合格 — 竣工</option>
              <option value="不合格，返工">不合格，返工 — 退回施工中</option>
            </select>
          </label>
          <label class="filter-item">
            <span>验收说明</span>
            <textarea v-model="acceptForm.remark" rows="3" placeholder="断面、支护、文明施工等复核情况"></textarea>
          </label>
          <div class="modal-actions">
            <button class="btn primary" type="submit" :disabled="accepting">{{ accepting ? '提交中…' : '提交验收' }}</button>
            <button class="btn ghost" type="button" @click="closeAccept">取消</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 详情抽屉：列表/详情/台账读同一份后端数据 -->
    <div v-if="detail" class="drawer-mask" @click.self="detail = null">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>维修任务明细</h3>
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </header>
        <dl class="detail-list">
          <div v-for="item in detailItems" :key="item.key">
            <dt>{{ item.label }}</dt>
            <dd>
              {{ detail[item.key] || '—' }}
              <em v-if="item.key === '验收人员' && detail['历史签字']" class="legacy-tag">
                存量记录：非本队验收员，按当时签字保留
              </em>
            </dd>
          </div>
        </dl>
        <div class="drawer-actions">
          <button
            v-if="detail.status === '待验收' && store.canAccept(detail['施工队伍'])"
            class="btn primary"
            type="button"
            @click="openAccept(detail)"
          >
            填验收结论
          </button>
          <p v-else-if="detail.status === '待验收'" class="action-hint">
            跨队或角色不符：仅 {{ detail['施工队伍'] }} 的验收员可验收，当前账号只能查看。
          </p>
        </div>
      </aside>
    </div>

    <!-- 台账复核清单与操作日志 -->
    <section class="sub-panel">
      <div class="sub-panel-head">
        <h3>巷道维修台账 · 复核清单</h3>
        <button class="btn" type="button" @click="loadReview">刷新</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="col in reviewColumns" :key="col">{{ col }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="v in reviews" :key="String(v.id)">
            <td v-for="col in reviewColumns" :key="col">
              <em v-if="col === '验收人员' && v['历史签字']" class="legacy-tag">历史签字</em>
              {{ v[col] || '—' }}
            </td>
          </tr>
          <tr v-if="!reviews.length">
            <td :colspan="reviewColumns.length" class="empty-state">暂无复核记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="sub-panel">
      <div class="sub-panel-head">
        <h3>操作日志（含全部越权尝试）</h3>
        <button class="btn" type="button" @click="loadLogs">刷新</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="col in logColumns" :key="col">{{ col }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in logs" :key="String(log.id)" :class="{ 'log-denied': log['结果'] === '拒绝' }">
            <td v-for="col in logColumns" :key="col">{{ log[col] || '—' }}</td>
          </tr>
          <tr v-if="!logs.length">
            <td :colspan="logColumns.length" class="empty-state">暂无操作日志</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { readError, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/roadway'
const store = useSessionStore()

const columns = [
  '任务编号', '维修巷道', '维修内容', '施工队伍', '派发日期', '开工日期',
  '竣工日期', '验收人员', '验收结论', '验收时间', '任务状态',
]
const statuses = ['待派发', '施工中', '待验收', '已竣工']
const teams = ['掘进一队', '掘进二队']
const reviewColumns = [
  '任务编号', '维修巷道', '施工队伍', '派发日期', '验收人员',
  '验收结论', '验收时间', '复核状态', '任务状态', '来源',
]
const logColumns = ['时间', '结果', '动作', '操作人', '所属队伍', '记录ID', '缺失授权', '说明']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const teamFilter = ref('')

const reviews = ref<Row[]>([])
const logs = ref<Row[]>([])

const stats = computed(() => [
  { label: '待派发任务', value: rows.value.filter((r) => r.status === '待派发').length },
  { label: '施工中任务', value: rows.value.filter((r) => r.status === '施工中').length },
  { label: '待验收任务', value: rows.value.filter((r) => r.status === '待验收').length },
  { label: '已竣工任务', value: rows.value.filter((r) => r.status === '已竣工').length },
])

// ---------- 详情 ----------
const detail = ref<Row | null>(null)
const detailItems = columns
  .filter((key) => key !== '任务状态')
  .map((key) => ({ key, label: key }))
  .concat([{ key: 'status', label: '权威状态（status）' }])

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error(await readError(response))
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '明细读取失败'
  }
}

// ---------- 施工动作 ----------
async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(await readError(response))
    if (payload.ok === false) throw new Error(payload.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巷道维修操作失败'
  }
}

// ---------- 验收 ----------
const acceptTarget = ref<Row | null>(null)
const acceptForm = ref({ conclusion: '合格', remark: '' })
const accepting = ref(false)

function openAccept(row: Row) {
  acceptTarget.value = row
  acceptForm.value = { conclusion: '合格', remark: '' }
  errorMessage.value = ''
}

function closeAccept() {
  acceptTarget.value = null
}

async function submitAccept() {
  if (!acceptTarget.value) return
  accepting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${acceptTarget.value.id}/accept`, {
      method: 'POST',
      body: JSON.stringify({
        values: { 验收结论: acceptForm.value.conclusion, 验收说明: acceptForm.value.remark },
      }),
    })
    if (!response.ok) throw new Error(await readError(response))
    acceptTarget.value = null
    await Promise.all([reload(), loadReview(), loadLogs()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '验收提交失败'
  } finally {
    accepting.value = false
  }
}

// ---------- 列表与附属数据 ----------
function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  teamFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '维修任务登记入口尚未接入审批流'
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  if (teamFilter.value) query.set('team', teamFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error(await readError(response))
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巷道维修列表读取失败'
  }
}

async function loadReview() {
  try {
    const response = await request(`${ENDPOINT}/review-ledger`)
    if (!response.ok) return
    const payload = await response.json()
    reviews.value = payload.items ?? []
  } catch {
    // 附属数据读取失败不阻断主列表
  }
}

async function loadLogs() {
  try {
    const response = await request(`${ENDPOINT}/logs`)
    if (!response.ok) return
    const payload = await response.json()
    logs.value = payload.items ?? []
  } catch {
    // 同上
  }
}

onMounted(() => {
  void reload()
  void loadReview()
  void loadLogs()
})
</script>

<style scoped>
.identity-banner {
  background: #eef4ff;
  border: 1px solid #c6d9ff;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 12px;
}
.identity-switch select {
  margin: 0 4px;
  padding: 2px 4px;
}
.action-hint {
  color: var(--muted);
  font-size: 12px;
}
.legacy-tag {
  color: #b54708;
  font-style: normal;
  font-size: 12px;
  margin-left: 6px;
  background: #fef3c7;
  border-radius: 4px;
  padding: 0 4px;
}
.modal-mask,
.drawer-mask {
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
  border-radius: 8px;
  padding: 18px 20px;
  width: 460px;
}
.modal h3 {
  margin: 0 0 12px;
}
.accept-form .filter-item {
  display: block;
  margin-bottom: 10px;
}
.accept-form select,
.accept-form textarea {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: inherit;
}
.modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.drawer {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 440px;
  background: #fff;
  padding: 18px 20px;
  overflow-y: auto;
  box-shadow: -4px 0 16px rgba(15, 23, 42, 0.15);
}
.drawer-mask {
  justify-content: flex-end;
}
.drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.detail-list {
  margin: 0;
}
.detail-list > div {
  display: flex;
  border-bottom: 1px dashed var(--border);
  padding: 8px 0;
  font-size: 13px;
}
.detail-list dt {
  width: 130px;
  color: var(--muted);
  margin: 0;
}
.detail-list dd {
  margin: 0;
  flex: 1;
}
.detail-list.compact > div {
  padding: 4px 0;
}
.drawer-actions {
  margin-top: 16px;
}
.sub-panel {
  margin-top: 20px;
}
.sub-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.log-denied {
  background: #fef2f2;
}
</style>
