<template>
  <section class="page" data-module="outsource">
    <header class="page-head">
      <div>
        <h2>委外合同管理</h2>
        <p class="page-desc">登记委外单位、服务范围与结算单价；天窗与处置单工作量按合同条款汇总成应结金额，扣款比例与月度上限按条款判定，超额拦截、核定固化、暂停挂起。</p>
      </div>
    </header>

    <nav class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-item"
        :class="{ active: activeTab === tab.key }"
        type="button"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </nav>

    <span v-if="message" :class="messageOk ? 'success-text' : 'error-text'">{{ message }}</span>

    <!-- ============================================================ 合同台账 -->
    <template v-if="activeTab === 'contract'">
      <div class="stat-row">
        <article class="stat-card"><span class="stat-label">合同总数</span><strong class="stat-value">{{ contracts.length }}</strong></article>
        <article class="stat-card"><span class="stat-label">合作中</span><strong class="stat-value">{{ contractStats.active }}</strong></article>
        <article class="stat-card"><span class="stat-label">暂停合作</span><strong class="stat-value">{{ contractStats.paused }}</strong></article>
      </div>

      <form class="form-panel" @submit.prevent="submitContract">
        <h3>登记委外合同（单位 / 服务范围 / 结算单价 / 扣款比例 / 月度上限）</h3>
        <div class="form-grid">
          <div class="form-field">
            <label>合同编号 *</label>
            <input v-model="contractForm.合同编号" placeholder="如 WW-HT-2026-003" />
          </div>
          <div class="form-field">
            <label>委外单位 *</label>
            <input v-model="contractForm.单位名称" placeholder="委外检修队名称" />
          </div>
          <div class="form-field">
            <label>扣款比例% *</label>
            <input v-model="contractForm.扣款比例" type="number" min="0" max="100" step="0.01" placeholder="如 5 表示 5%" />
          </div>
          <div class="form-field">
            <label>月度应结上限(元) *</label>
            <input v-model="contractForm.月度上限" type="number" min="0" step="0.01" placeholder="按合同条款填写" />
          </div>
        </div>
        <div class="form-field" style="margin-top: 8px;">
          <label>服务范围 *</label>
          <input v-model="contractForm.服务范围" style="min-width: 420px;" placeholder="如 道岔检修、故障抢修及车辆段信号设备维护" />
        </div>
        <div class="price-editor">
          <label class="form-field" style="font-size: 12px; color: var(--muted);">结算单价明细 *（作业项目与单价必须与合同条款一致）</label>
          <div v-for="(_, index) in contractForm.单价明细" :key="index" class="price-row">
            <input v-model="contractForm.单价明细[index].作业项目" placeholder="作业项目，如 道岔检修" style="min-width: 220px;" />
            <input v-model.number="contractForm.单价明细[index].单价" type="number" min="0" step="0.01" placeholder="单价(元)" />
            <button class="btn ghost" type="button" @click="contractForm.单价明细.splice(index, 1)">删除</button>
          </div>
          <button class="btn" type="button" @click="contractForm.单价明细.push({ 作业项目: '', 单价: undefined })">＋ 增加单价项</button>
        </div>
        <button class="btn primary" type="submit">保存合同</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th>合同编号</th><th>委外单位</th><th>服务范围</th><th>结算单价（合同条款）</th>
            <th>扣款比例</th><th>月度上限</th><th>合作状态</th><th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in contracts" :key="String(row.id)">
            <td>{{ row.合同编号 }}</td>
            <td>{{ row.单位名称 }}</td>
            <td>{{ row.服务范围 }}</td>
            <td>
              <span v-for="item in row.单价明细" :key="item.作业项目" style="display: inline-block; margin-right: 8px;">
                {{ item.作业项目 }}：{{ item.单价 }} 元
              </span>
            </td>
            <td>{{ row.扣款比例 }}%</td>
            <td>{{ row.月度上限 }} 元</td>
            <td>
              <span class="badge" :class="row.status === '合作中' ? 'ok' : 'hold'">{{ row.status }}</span>
            </td>
            <td class="row-actions">
              <button v-if="row.status === '合作中'" class="link" type="button" @click="contractAction('暂停合作', row)">暂停合作</button>
              <button v-else class="link" type="button" @click="contractAction('恢复合作', row)">恢复合作</button>
            </td>
          </tr>
          <tr v-if="!contracts.length">
            <td colspan="8" class="empty-state">暂无委外合同，请先登记单位与合同条款</td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- ============================================================ 工作量台账 -->
    <template v-if="activeTab === 'workload'">
      <div class="stat-row">
        <article class="stat-card"><span class="stat-label">待结算</span><strong class="stat-value">{{ workloadStats.pending }}</strong></article>
        <article class="stat-card"><span class="stat-label">已挂起</span><strong class="stat-value">{{ workloadStats.hold }}</strong></article>
        <article class="stat-card"><span class="stat-label">已结算</span><strong class="stat-value">{{ workloadStats.done }}</strong></article>
      </div>

      <form class="form-panel" @submit.prevent="submitWorkload">
        <h3>登记工作量（依据：已销记天窗 / 已验收处置单，单价取合同条款）</h3>
        <div class="form-grid">
          <div class="form-field">
            <label>委外合同 *</label>
            <select v-model.number="workloadForm.合同id">
              <option :value="undefined" disabled>请选择合同</option>
              <option v-for="c in contracts" :key="c.id" :value="c.id">
                {{ c.合同编号 }}｜{{ c.单位名称 }}（{{ c.status }}）
              </option>
            </select>
          </div>
          <div class="form-field">
            <label>来源类型 *</label>
            <select v-model="workloadForm.来源类型" @change="onSourceTypeChange">
              <option value="" disabled>请选择</option>
              <option value="天窗">天窗（已销记）</option>
              <option value="处置">处置单（已验收）</option>
            </select>
          </div>
          <div class="form-field">
            <label>来源单号 *</label>
            <select v-model="workloadForm.来源单号">
              <option value="" disabled>请先选类型</option>
              <option v-for="s in filteredSources" :key="`${s.来源类型}-${s.来源单号}`" :value="s.来源单号">
                {{ s.来源单号 }}｜{{ s.作业项目口径 }}｜完成 {{ s.作业月份 }}
              </option>
            </select>
          </div>
          <div class="form-field">
            <label>作业项目 *（限合同服务范围）</label>
            <select v-model="workloadForm.作业项目">
              <option value="" disabled>请选择项目</option>
              <option v-for="item in selectedContractItems" :key="item.作业项目" :value="item.作业项目">
                {{ item.作业项目 }}（{{ item.单价 }} 元）
              </option>
            </select>
          </div>
          <div class="form-field">
            <label>完成数量 *</label>
            <input v-model.number="workloadForm.数量" type="number" min="0" step="0.01" placeholder="按单据实际完成量" />
          </div>
          <button class="btn primary" type="submit">登记工作量</button>
        </div>
        <p class="page-desc" style="margin-top: 8px;">金额 = 数量 × 合同单价，由系统计算；同一张单据同一项目重复登记、未完成单据、合同外项目都会被拦下。</p>
      </form>

      <form class="filter-bar" @submit.prevent="loadWorkloads">
        <label class="filter-item">
          <span>合同</span>
          <select v-model.number="workloadFilters.contract_id">
            <option :value="undefined">全部</option>
            <option v-for="c in contracts" :key="c.id" :value="c.id">{{ c.单位名称 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>作业月份</span>
          <input v-model="workloadFilters.month" placeholder="YYYY-MM，如 2026-09" />
        </label>
        <label class="filter-item">
          <span>状态</span>
          <input v-model="workloadFilters.status" placeholder="待结算/已挂起/已计入/已结算" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetWorkloadFilters">重置</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th>工作量编号</th><th>委外单位</th><th>来源</th><th>作业项目</th>
            <th>数量</th><th>结算单价</th><th>金额</th><th>作业月份</th><th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in workloads" :key="String(row.id)">
            <td>{{ row.工作量编号 }}</td>
            <td>{{ row.委外单位 }}</td>
            <td>{{ row.来源类型 }} {{ row.来源单号 }}</td>
            <td>{{ row.作业项目 }}</td>
            <td>{{ row.数量 }}</td>
            <td>{{ row.结算单价 }} 元</td>
            <td class="money-strong">{{ row.金额 }} 元</td>
            <td>{{ row.作业月份 }}</td>
            <td>
              <span class="badge" :class="statusBadge(row.status)">{{ row.status }}</span>
            </td>
          </tr>
          <tr v-if="!workloads.length">
            <td colspan="9" class="empty-state">暂无工作量，可从已销记天窗、已验收处置单登记</td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- ============================================================ 月度结算 -->
    <template v-if="activeTab === 'settlement'">
      <div class="stat-row">
        <article class="stat-card"><span class="stat-label">待核定</span><strong class="stat-value">{{ settlementStats.pending }}</strong></article>
        <article class="stat-card"><span class="stat-label">已挂起</span><strong class="stat-value">{{ settlementStats.hold }}</strong></article>
        <article class="stat-card"><span class="stat-label">已核定（固化）</span><strong class="stat-value">{{ settlementStats.approved }}</strong></article>
      </div>

      <form class="form-panel" @submit.prevent="previewSettlement">
        <h3>月度结算测算（同一月多家单位按各自合同分别计算，保存前先测算）</h3>
        <div class="form-grid">
          <div class="form-field">
            <label>委外合同 *</label>
            <select v-model.number="settlementForm.合同id">
              <option :value="undefined" disabled>请选择合同</option>
              <option v-for="c in contracts" :key="c.id" :value="c.id">
                {{ c.合同编号 }}｜{{ c.单位名称 }}（{{ c.status }}）
              </option>
            </select>
          </div>
          <div class="form-field">
            <label>结算月份 *</label>
            <input v-model="settlementForm.结算月份" placeholder="YYYY-MM，如 2026-09" />
          </div>
          <button class="btn" type="submit">按条款测算</button>
          <button class="btn primary" type="button" @click="saveSettlement">确认无误，保存结算单</button>
        </div>
        <div v-if="preview" class="detail-box">
          <div v-if="preview.超上限" class="money-over">
            测算不通过：{{ preview.委外单位 }} {{ preview.结算月份 }} 累计应结 {{ preview.累计应结 }} 元，
            超过合同月度上限 {{ preview.月度上限 }} 元（已核定 {{ preview.已核定金额 }} 元，本次 {{ preview.应结金额 }} 元），
            超出上限的金额不允许保存。
          </div>
          <template v-else>
            <div>工作量金额合计 <strong>{{ preview.工作量金额 }}</strong> 元；
              扣款比例 {{ preview.扣款比例 }}%，扣款 {{ preview.扣款金额 }} 元；
              应结金额 <span class="money-strong">{{ preview.应结金额 }} 元</span>；
              本月已核定 {{ preview.已核定金额 }} 元，核定后累计 {{ preview.累计应结 }} / 上限 {{ preview.月度上限 }} 元。
            </div>
            <table class="data-table">
              <thead><tr><th>工作量编号</th><th>来源</th><th>作业项目</th><th>数量</th><th>单价</th><th>金额</th></tr></thead>
              <tbody>
                <tr v-for="line in preview.明细" :key="line.工作量编号">
                  <td>{{ line.工作量编号 }}</td>
                  <td>{{ line.来源类型 }} {{ line.来源单号 }}</td>
                  <td>{{ line.作业项目 }}</td>
                  <td>{{ line.数量 }}</td>
                  <td>{{ line.结算单价 }}</td>
                  <td>{{ line.金额 }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </div>
      </form>

      <form class="filter-bar" @submit.prevent="loadSettlements">
        <label class="filter-item">
          <span>合同</span>
          <select v-model.number="settlementFilters.contract_id">
            <option :value="undefined">全部</option>
            <option v-for="c in contracts" :key="c.id" :value="c.id">{{ c.单位名称 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>结算月份</span>
          <input v-model="settlementFilters.month" placeholder="YYYY-MM" />
        </label>
        <label class="filter-item">
          <span>状态</span>
          <input v-model="settlementFilters.status" placeholder="待核定/已挂起/已核定/已作废" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetSettlementFilters">重置</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th>结算编号</th><th>委外单位</th><th>月份</th><th>工作量金额</th>
            <th>扣款(比例)</th><th>应结金额</th><th>上限/累计</th><th>状态</th><th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in settlements" :key="String(row.id)">
            <tr>
              <td>{{ row.结算编号 }}</td>
              <td>{{ row.委外单位 }}</td>
              <td>{{ row.结算月份 }}</td>
              <td>{{ row.工作量金额 }} 元</td>
              <td>{{ row.扣款金额 }} 元（{{ row.扣款比例 }}%）</td>
              <td class="money-strong">{{ row.应结金额 }} 元</td>
              <td>{{ row.月度上限 }} / {{ row.累计应结 }} 元</td>
              <td><span class="badge" :class="statusBadge(row.status)">{{ row.status }}</span></td>
              <td class="row-actions">
                <button v-if="row.status === '待核定'" class="link" type="button" @click="settlementAction('重新测算', row)">重新测算</button>
                <button v-if="row.status === '待核定'" class="link" type="button" @click="settlementAction('提交核定', row)">提交核定</button>
                <button v-if="row.status === '待核定' || row.status === '已挂起'" class="link" type="button" @click="settlementAction('作废', row)">作废</button>
              </td>
            </tr>
            <tr v-if="expandedId === row.id">
              <td colspan="9">
                <div class="detail-box">
                  <div>核定条款快照：扣款比例 {{ row.条款快照?.扣款比例 }}%，月度上限 {{ row.条款快照?.月度上限 }} 元；
                    单价 {{ row.条款快照?.单价明细?.map((p: PriceItem) => `${p.作业项目} ${p.单价}元`).join('、') }}
                  </div>
                  <table class="data-table">
                    <thead><tr><th>工作量编号</th><th>来源</th><th>作业项目</th><th>数量</th><th>结算单价</th><th>金额</th></tr></thead>
                    <tbody>
                      <tr v-for="line in row.工作量清单" :key="line.工作量编号">
                        <td>{{ line.工作量编号 }}</td>
                        <td>{{ line.来源类型 }} {{ line.来源单号 }}</td>
                        <td>{{ line.作业项目 }}</td>
                        <td>{{ line.数量 }}</td>
                        <td>{{ line.结算单价 }}</td>
                        <td>{{ line.金额 }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </td>
            </tr>
            <tr>
              <td colspan="9" style="padding: 0 10px;">
                <button class="link" type="button" @click="toggleDetail(row.id)">
                  {{ expandedId === row.id ? '收起工作量清单' : '查看工作量清单与条款快照' }}
                </button>
              </td>
            </tr>
          </template>
          <tr v-if="!settlements.length">
            <td colspan="9" class="empty-state">暂无月度结算，先选择合同与月份进行测算</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>已核定结果按核定当时的合同条款固化，刷新不变；作废只释放工作量，单据保留可查。</span>
      </footer>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Scalar = string | number | boolean | null | undefined
type Row = Record<string, any>
interface PriceItem { 作业项目: string; 单价: number | undefined }
interface SourceItem { 来源类型: string; 来源单号: string; 作业项目口径: string; 作业月份: string }
interface ActionResponse { ok: boolean; message: string; entry?: Row }
interface LineItem { 工作量编号: string; 来源类型: string; 来源单号: string; 作业项目: string; 数量: number; 结算单价: number; 金额: number }

const API = '/api/outsource'
const tabs = [
  { key: 'contract', label: '委外合同' },
  { key: 'workload', label: '工作量台账' },
  { key: 'settlement', label: '月度结算' },
] as const
type TabKey = (typeof tabs)[number]['key']

const activeTab = ref<TabKey>('contract')
const message = ref('')
const messageOk = ref(false)
const expandedId = ref<number | null>(null)

function notify(text: string, ok = false) {
  message.value = text
  messageOk.value = ok
}

async function postJson(path: string, body: Record<string, unknown>): Promise<ActionResponse> {
  const response = await request(`${API}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return (await response.json()) as ActionResponse
}

// ------------------------------------------------------------------ 合同
const contracts = ref<Row[]>([])
const contractForm = reactive<{ 合同编号: string; 单位名称: string; 服务范围: string; 扣款比例: number | undefined; 月度上限: number | undefined; 单价明细: PriceItem[] }>({
  合同编号: '', 单位名称: '', 服务范围: '', 扣款比例: undefined, 月度上限: undefined,
  单价明细: [{ 作业项目: '', 单价: undefined }],
})

const contractStats = computed(() => ({
  active: contracts.value.filter((c) => c.status === '合作中').length,
  paused: contracts.value.filter((c) => c.status === '暂停合作').length,
}))

async function loadContracts() {
  const response = await request(`${API}/contracts?size=200`)
  if (!response.ok) {
    notify('委外合同列表读取失败')
    return
  }
  const payload = (await response.json()) as { items: Row[] }
  contracts.value = payload.items ?? []
}

function resetContractForm() {
  contractForm.合同编号 = ''
  contractForm.单位名称 = ''
  contractForm.服务范围 = ''
  contractForm.扣款比例 = undefined
  contractForm.月度上限 = undefined
  contractForm.单价明细 = [{ 作业项目: '', 单价: undefined }]
}

async function submitContract() {
  const result = await postJson('/contracts', { values: { ...contractForm } })
  notify(result.message, result.ok)
  if (result.ok) {
    resetContractForm()
    await loadContracts()
  }
}

async function contractAction(action: string, row: Row) {
  const result = await postJson(`/contracts/${row.id}/actions`, { values: { action } })
  notify(result.message, result.ok)
  await loadContracts()
  if (activeTab.value !== 'contract') {
    await Promise.all([loadWorkloads(), loadSettlements()])
  }
}

// ------------------------------------------------------------------ 工作量
const workloads = ref<Row[]>([])
const sources = ref<SourceItem[]>([])
const workloadForm = reactive<{ 合同id: number | undefined; 来源类型: string; 来源单号: string; 作业项目: string; 数量: number | undefined }>({
  合同id: undefined, 来源类型: '', 来源单号: '', 作业项目: '', 数量: undefined,
})
const workloadFilters = reactive<{ contract_id: number | undefined; month: string; status: string }>({
  contract_id: undefined, month: '', status: '',
})

const workloadStats = computed(() => ({
  pending: workloads.value.filter((w) => w.status === '待结算').length,
  hold: workloads.value.filter((w) => w.status === '已挂起').length,
  done: workloads.value.filter((w) => w.status === '已结算' || w.status === '已计入').length,
}))

const selectedContract = computed(() => contracts.value.find((c) => c.id === workloadForm.合同id))
const selectedContractItems = computed<PriceItem[]>(() => (selectedContract.value?.单价明细 as PriceItem[] | undefined) ?? [])
const filteredSources = computed(() => sources.value.filter((s) => s.来源类型 === workloadForm.来源类型))

async function loadSources() {
  const response = await request(`${API}/sources`)
  if (!response.ok) {
    notify('已完成单据读取失败')
    return
  }
  const payload = (await response.json()) as { items: SourceItem[] }
  sources.value = payload.items ?? []
}

function onSourceTypeChange() {
  workloadForm.来源单号 = ''
}

function buildQuery(filters: Record<string, string | number | undefined>) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== '') params.set(key, String(value))
  })
  return params.toString()
}

async function loadWorkloads() {
  const query = buildQuery({ ...workloadFilters, size: 200 })
  const response = await request(`${API}/workloads?${query}`)
  if (!response.ok) {
    notify('工作量列表读取失败')
    return
  }
  const payload = (await response.json()) as { items: Row[] }
  workloads.value = payload.items ?? []
}

function resetWorkloadFilters() {
  workloadFilters.contract_id = undefined
  workloadFilters.month = ''
  workloadFilters.status = ''
  void loadWorkloads()
}

async function submitWorkload() {
  const result = await postJson('/workloads', { values: { ...workloadForm } })
  notify(result.message, result.ok)
  if (result.ok) {
    workloadForm.来源单号 = ''
    workloadForm.作业项目 = ''
    workloadForm.数量 = undefined
    await loadWorkloads()
  }
}

// ------------------------------------------------------------------ 结算
const settlements = ref<Row[]>([])
const settlementForm = reactive<{ 合同id: number | undefined; 结算月份: string }>({
  合同id: undefined, 结算月份: '2026-09',
})
const settlementFilters = reactive<{ contract_id: number | undefined; month: string; status: string }>({
  contract_id: undefined, month: '', status: '',
})
const preview = ref<Row | null>(null)

const settlementStats = computed(() => ({
  pending: settlements.value.filter((s) => s.status === '待核定').length,
  hold: settlements.value.filter((s) => s.status === '已挂起').length,
  approved: settlements.value.filter((s) => s.status === '已核定').length,
}))

async function loadSettlements() {
  const query = buildQuery({ ...settlementFilters, size: 200 })
  const response = await request(`${API}/settlements?${query}`)
  if (!response.ok) {
    notify('结算单列表读取失败')
    return
  }
  const payload = (await response.json()) as { items: Row[] }
  settlements.value = payload.items ?? []
}

function resetSettlementFilters() {
  settlementFilters.contract_id = undefined
  settlementFilters.month = ''
  settlementFilters.status = ''
  void loadSettlements()
}

async function previewSettlement() {
  preview.value = null
  const result = await postJson('/settlements/preview', { values: { ...settlementForm } })
  notify(result.message, result.ok)
  if (result.ok && result.entry) {
    preview.value = result.entry
  }
}

async function saveSettlement() {
  const result = await postJson('/settlements', { values: { ...settlementForm } })
  notify(result.message, result.ok)
  if (result.ok) {
    preview.value = null
    await Promise.all([loadSettlements(), loadWorkloads()])
  }
}

async function settlementAction(action: string, row: Row) {
  const result = await postJson(`/settlements/${row.id}/actions`, { values: { action } })
  notify(result.message, result.ok)
  await Promise.all([loadSettlements(), loadWorkloads()])
}

function toggleDetail(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

function statusBadge(status: Scalar) {
  if (status === '合作中' || status === '已结算' || status === '已核定') return 'ok'
  if (status === '暂停合作' || status === '已挂起' || status === '待核定') return 'hold'
  return 'dead'
}

async function switchTab(key: TabKey) {
  activeTab.value = key
  message.value = ''
  await Promise.all([loadContracts(), loadWorkloads(), loadSettlements()])
  if (key === 'workload') await loadSources()
}

onMounted(async () => {
  await Promise.all([loadContracts(), loadWorkloads(), loadSettlements(), loadSources()])
})
</script>
