<template>
  <section class="page" data-module="outsource">
    <header class="page-head">
      <div>
        <h2>委外合同管理</h2>
        <p class="page-desc">登记委外单位、服务范围与结算单价；作业完成后把天窗与处置单的工作量按合同条款汇总成应结金额，超上限、缺条款、对不上账的一律拦住。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showCreate = !showCreate">登记委外合同</button>
        <button class="btn" type="button" @click="exportRows">导出委外合同清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="filter-bar" @submit.prevent="createContract">
      <label v-for="field in createFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <input v-model="createForm[field.key]" :placeholder="field.placeholder" />
      </label>
      <button class="btn primary" type="submit">保存合同</button>
      <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
    </form>

    <form class="filter-bar" @submit.prevent="reloadContracts">
      <label class="filter-item">
        <span>合同编号 / 委外单位</span>
        <input v-model="contractKeyword" placeholder="按合同编号或委外单位检索" />
      </label>
      <label class="filter-item">
        <span>合同状态</span>
        <select v-model="contractStatus">
          <option value="">全部</option>
          <option v-for="item in contractStatuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetContractFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in contractColumns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in contracts" :key="String(row.id)">
          <td v-for="column in contractColumns" :key="column">{{ displayCell(column, cellValue(column, row)) }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="loadAggregate(row)">汇总结算</button>
            <button
              v-if="row.status === '合作中'"
              class="link"
              type="button"
              @click="runContractAction('暂停合作', row)"
            >暂停合作</button>
            <button
              v-if="row.status === '已暂停'"
              class="link"
              type="button"
              @click="runContractAction('恢复合作', row)"
            >恢复合作</button>
          </td>
        </tr>
        <tr v-if="!contracts.length">
          <td :colspan="contractColumns.length + 1" class="empty-state">暂无委外合同，可先登记委外合同</td>
        </tr>
      </tbody>
    </table>

    <section v-if="aggregate" class="settle-panel">
      <header class="panel-head">
        <strong>合同 {{ aggregate.合同编号 }}（{{ aggregate.委外单位 }}）· {{ aggregate.结算月份 }} 工作量汇总</strong>
        <span class="panel-tools">
          <input v-model="settleMonth" class="month-input" placeholder="2026-09" />
          <button class="btn" type="button" @click="loadAggregate()">重新汇总</button>
          <button class="btn ghost" type="button" @click="aggregate = null">收起</button>
        </span>
      </header>

      <table class="data-table">
        <thead>
          <tr><th>来源</th><th>单号</th><th>工作量</th><th>单价(元)</th><th>金额(元)</th><th>结算状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in aggregate.明细" :key="`${item.来源}-${item.单据id}`">
            <td>{{ item.来源 }}</td>
            <td>{{ item.单号 }}</td>
            <td>{{ item.工作量 }}</td>
            <td>{{ fmtMoney(item.单价) }}</td>
            <td>{{ fmtMoney(item.金额) }}</td>
            <td>{{ item.结算状态 }}</td>
          </tr>
          <tr v-if="!aggregate.明细.length">
            <td colspan="6" class="empty-state">该月没有已完成且未结算的天窗或处置单</td>
          </tr>
        </tbody>
      </table>

      <div class="amount-row">
        <span>汇总金额：<strong>{{ fmtMoney(aggregate.汇总金额) }}</strong> 元</span>
        <span>扣款比例：<strong>{{ fmtRatio(aggregate.扣款比例) }}</strong></span>
        <span>扣款金额：<strong>{{ fmtMoney(aggregate.扣款金额) }}</strong> 元</span>
        <span>应结金额：<strong>{{ fmtMoney(aggregate.应结金额) }}</strong> 元</span>
        <span>月度上限：<strong>{{ fmtMoney(aggregate.月度上限) }}</strong> 元</span>
      </div>

      <ul v-if="aggregate.拦截原因.length" class="block-list">
        <li v-for="reason in aggregate.拦截原因" :key="reason" class="error-text">{{ reason }}</li>
      </ul>

      <div class="panel-foot">
        <label class="filter-item">
          <span>对方申报金额（可选，用于对数）</span>
          <input v-model="declaredAmount" placeholder="群里对数的金额" />
        </label>
        <button class="btn primary" type="button" :disabled="!aggregate.可否保存" @click="createSettlement">
          生成结算单
        </button>
      </div>
    </section>

    <header class="page-head settle-head">
      <div>
        <h2>委外结算单</h2>
        <p class="page-desc">同一个月多家委外单位各自计算；核定后结果固化，刷新不会变；单位暂停合作时未结算单据挂起保留。</p>
      </div>
      <div class="page-actions">
        <input v-model="settleFilterMonth" class="month-input" placeholder="按月份过滤，如 2026-09" @change="reloadSettlements" />
      </div>
    </header>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in settleColumns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in settlements" :key="String(row.id)">
          <td v-for="column in settleColumns" :key="column">{{ displayCell(column, cellValue(column, row)) }}</td>
          <td class="row-actions">
            <button
              v-if="row.status === '待核定'"
              class="link"
              type="button"
              @click="runSettleAction('核定', row)"
            >核定</button>
            <button
              v-if="row.status === '待核定' || row.status === '已挂起'"
              class="link"
              type="button"
              @click="runSettleAction('作废', row)"
            >作废</button>
            <span v-if="row.status === '已核定'">已固化</span>
            <span v-if="row.status === '已挂起'">挂起中</span>
          </td>
        </tr>
        <tr v-if="!settlements.length">
          <td :colspan="settleColumns.length + 1" class="empty-state">暂无结算单，可先在合同列表里点「汇总结算」</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ contractsTotal }} 条委外合同 · {{ settlementsTotal }} 张结算单</span>
      <span v-if="message" :class="messageOk ? '' : 'error-text'">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type AggregateItem = { 来源: string; 单据id: number; 单号: string; 工作量: number; 单价: number; 金额: number; 结算状态: string }
type AggregateResult = {
  合同编号: string
  委外单位: string
  合同状态: string
  结算月份: string
  明细: AggregateItem[]
  天窗工作量: number
  处置工作量: number
  汇总金额: number
  扣款比例: number | null
  扣款金额: number | null
  应结金额: number | null
  月度上限: number | null
  可否保存: boolean
  拦截原因: string[]
}

const ENDPOINT = '/api/outsource'
const contractColumns = ['合同编号', '委外单位', '服务范围', '天窗单价', '处置单价', '扣款比例', '月度上限', '合同状态']
const settleColumns = ['结算单号', '合同编号', '委外单位', '结算月份', '汇总金额', '扣款金额', '应结金额', '结算状态']
const contractStatuses = ['合作中', '已暂停']
const createFields = [
  { key: '委外单位', label: '委外单位', placeholder: '如：华信信号工程队' },
  { key: '服务范围', label: '服务范围', placeholder: '如：信号机日常检修' },
  { key: '天窗单价', label: '天窗单价(元/次)', placeholder: '如：800' },
  { key: '处置单价', label: '处置单价(元/张)', placeholder: '如：500' },
  { key: '扣款比例', label: '扣款比例', placeholder: '如：0.05 或 5%' },
  { key: '月度上限', label: '月度上限(元)', placeholder: '如：20000' },
  { key: '联系人', label: '联系人', placeholder: '选填' },
]
const moneyColumns = new Set(['天窗单价', '处置单价', '月度上限', '汇总金额', '扣款金额', '应结金额'])

const contracts = ref<Row[]>([])
const contractsTotal = ref(0)
const settlements = ref<Row[]>([])
const settlementsTotal = ref(0)
const contractKeyword = ref('')
const contractStatus = ref('')
const settleFilterMonth = ref('')
const settleMonth = ref(new Date().toISOString().slice(0, 7))
const declaredAmount = ref('')
const aggregate = ref<AggregateResult | null>(null)
const activeContract = ref<Row | null>(null)
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})
const message = ref('')
const messageOk = ref(true)

const stats = computed(() => [
  { label: '合作中合同', value: contracts.value.filter((row) => row.status === '合作中').length },
  { label: '已暂停合同', value: contracts.value.filter((row) => row.status === '已暂停').length },
  { label: '待核定结算单', value: settlements.value.filter((row) => row.status === '待核定').length },
  { label: '挂起中结算单', value: settlements.value.filter((row) => row.status === '已挂起').length },
])

function fmtMoney(value: unknown): string {
  const num = Number(value)
  return Number.isFinite(num) ? num.toFixed(2) : '—'
}

function fmtRatio(value: unknown): string {
  const num = Number(value)
  return Number.isFinite(num) ? `${(num * 100).toFixed(0)}%` : '缺失'
}

function cellValue(column: string, row: Row): unknown {
  // 状态列在后端统一放在 status 字段，表头用的是中文名，这里做一次映射。
  if (column === '合同状态' || column === '结算状态') return row.status
  return row[column]
}

function displayCell(column: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (column === '扣款比例') return fmtRatio(value)
  if (moneyColumns.has(column)) return fmtMoney(value)
  return String(value)
}

function showMessage(text: string, ok: boolean) {
  message.value = text
  messageOk.value = ok
}

async function readResult(response: Response): Promise<{ ok: boolean; message: string }> {
  const payload = await response.json()
  if (!response.ok) {
    return { ok: false, message: payload?.detail ?? `接口返回 ${response.status}` }
  }
  return { ok: Boolean(payload.ok), message: payload.message ?? '' }
}

function resetContractFilters() {
  contractKeyword.value = ''
  contractStatus.value = ''
  void reloadContracts()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function createContract() {
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const result = await readResult(response)
    showMessage(result.message, result.ok)
    if (result.ok) {
      createForm.value = {}
      showCreate.value = false
      await reloadContracts()
    }
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '委外合同登记失败', false)
  }
}

async function runContractAction(action: string, row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const result = await readResult(response)
    showMessage(result.message, result.ok)
    await Promise.all([reloadContracts(), reloadSettlements()])
    if (aggregate.value && activeContract.value?.id === row.id) {
      await loadAggregate(row)
    }
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '委外合同操作失败', false)
  }
}

async function loadAggregate(row?: Row) {
  if (row) activeContract.value = row
  const target = activeContract.value
  if (!target) return
  try {
    const response = await request(`${ENDPOINT}/${target.id}/aggregate?month=${encodeURIComponent(settleMonth.value)}`)
    const payload = await response.json()
    if (!response.ok) {
      showMessage(payload?.detail ?? '汇总失败', false)
      return
    }
    aggregate.value = payload as AggregateResult
    declaredAmount.value = ''
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '工作量汇总失败', false)
  }
}

async function createSettlement() {
  if (!aggregate.value) return
  try {
    const response = await request(`${ENDPOINT}/settlements`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          合同编号: aggregate.value.合同编号,
          结算月份: aggregate.value.结算月份,
          申报金额: declaredAmount.value,
        },
      }),
    })
    const result = await readResult(response)
    showMessage(result.message, result.ok)
    if (result.ok) {
      await Promise.all([reloadSettlements(), loadAggregate()])
    }
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '结算单保存失败', false)
  }
}

async function runSettleAction(action: string, row: Row) {
  try {
    const response = await request(`${ENDPOINT}/settlements/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const result = await readResult(response)
    showMessage(result.message, result.ok)
    await Promise.all([reloadSettlements(), reloadContracts()])
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '结算单操作失败', false)
  }
}

async function reloadContracts() {
  const query = new URLSearchParams()
  if (contractKeyword.value) query.set('keyword', contractKeyword.value)
  if (contractStatus.value) query.set('status', contractStatus.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    const payload = await response.json()
    contracts.value = payload.items ?? []
    contractsTotal.value = payload.total ?? contracts.value.length
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '委外合同列表读取失败', false)
  }
}

async function reloadSettlements() {
  const query = new URLSearchParams()
  if (settleFilterMonth.value) query.set('month', settleFilterMonth.value)
  try {
    const response = await request(`${ENDPOINT}/settlements?${query.toString()}`)
    const payload = await response.json()
    settlements.value = payload.items ?? []
    settlementsTotal.value = payload.total ?? settlements.value.length
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '结算单列表读取失败', false)
  }
}

onMounted(() => {
  void reloadContracts()
  void reloadSettlements()
})
</script>

<style scoped>
.settle-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin: 12px 0;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.panel-tools {
  display: flex;
  gap: 8px;
  align-items: center;
}
.month-input {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  width: 130px;
}
.amount-row {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin: 10px 0;
  font-size: 13px;
}
.block-list {
  margin: 0 0 10px;
  padding-left: 18px;
  font-size: 13px;
}
.panel-foot {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}
.settle-head {
  margin-top: 20px;
}
select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  background: #fff;
}
</style>
