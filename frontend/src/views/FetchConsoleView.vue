<template>
  <section class="page" data-module="fetch_console">
    <header class="page-head">
      <div>
        <h2>订阅取数</h2>
        <p class="page-desc">
          按订阅的列权限与契约版本读取源批：同一来源批交给不同订阅时，每张回执只含各自可见列，
          分批续取沿用同一份仍有效的列承诺，快照复取只读回执归属内的授权列。
        </p>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="onSubscribe">
      <label class="filter-item">
        <span>订阅编号</span>
        <input v-model="form.subscriptionId" data-testid="fetch-subscription" placeholder="如 SUB-001" />
      </label>
      <label class="filter-item">
        <span>端点编号</span>
        <input v-model="form.endpointId" data-testid="fetch-endpoint" placeholder="如 EP-001" />
      </label>
      <label class="filter-item">
        <span>分段大小</span>
        <input v-model.number="form.pageSize" data-testid="fetch-page-size" type="number" min="1" />
      </label>
      <label class="filter-item">
        <span>核验日期</span>
        <input v-model="form.today" data-testid="fetch-today" placeholder="如 2026-11-21" />
      </label>
      <button class="btn primary" data-testid="fetch-submit" type="submit">按订阅取数</button>
    </form>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <div v-if="result" class="stat-row">
      <article class="stat-card">
        <span class="stat-label">取数状态</span>
        <strong class="stat-value">{{ result.status }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">可读列</span>
        <strong class="stat-value">{{ (result.columns || []).join(' / ') || '—' }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">列承诺版本</span>
        <strong class="stat-value">{{ result.promise_version || '—' }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">分段进度</span>
        <strong class="stat-value">
          {{ result.receipt ? `${result.receipt.已交付页数}/${result.receipt.总页数}` : '—' }}
        </strong>
      </article>
    </div>

    <p v-if="result && result.message" class="error-text" data-testid="fetch-message">{{ result.message }}</p>

    <table v-if="result && result.rows && result.rows.length" class="data-table" data-testid="fetch-rows">
      <thead>
        <tr>
          <th v-for="column in result.columns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in result.rows" :key="index">
          <td v-for="column in result.columns" :key="column">{{ row[column] ?? '—' }}</td>
        </tr>
      </tbody>
    </table>

    <div v-if="result && result.receipt" class="page-actions">
      <button class="btn" data-testid="fetch-continue" type="button" :disabled="!canContinue" @click="onContinue">
        续取下一段
      </button>
      <button class="btn" data-testid="fetch-refetch" type="button" @click="onRefetch">
        复取首段快照
      </button>
      <button class="btn" data-testid="fetch-inspect" type="button" @click="onInspect">
        复核回执
      </button>
    </div>

    <section v-if="report" class="analysis-card" data-testid="fetch-report">
      <h3>回执复核：{{ report.receipt?.回执编号 }}</h3>
      <dl class="dag-detail">
        <div><dt>归属标识</dt><dd>{{ report.receipt?.归属标识 }}</dd></div>
        <div><dt>列承诺版本</dt><dd>{{ report.承诺版本 }}</dd></div>
        <div><dt>可读列</dt><dd>{{ (report.可读列 || []).join(', ') }}</dd></div>
        <div><dt>快照列</dt><dd>{{ (report.快照列 || []).join(', ') || '—' }}</dd></div>
        <div><dt>快照状态</dt><dd>{{ report.快照状态 }}</dd></div>
        <div><dt>已交付 / 总段数</dt><dd>{{ report.已交付页数 }} / {{ report.总页数 }}</dd></div>
        <div><dt>后续领取资格</dt><dd>{{ report.可继续领取 ? '可继续' : '不可继续' }}</dd></div>
        <div><dt>说明</dt><dd>{{ report.后续领取说明 }}</dd></div>
      </dl>
      <table class="data-table">
        <thead>
          <tr><th>页码</th><th>承诺版本</th><th>可读列</th><th>实际列</th><th>行数</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="segment in report.segments || []" :key="segment.分段编号" :data-testid="`segment-${segment.页码}`">
            <td>{{ segment.页码 }}</td>
            <td>{{ segment.承诺版本 }}</td>
            <td>{{ segment.可读列.join(', ') }}</td>
            <td>{{ segment.实际列.join(', ') }}</td>
            <td>{{ segment.行数 }}</td>
            <td>{{ outOfScope(segment) ? '越界' : segment.status }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import {
  continueSegment,
  fetchBySubscription,
  inspectReceipt,
  refetchSnapshot,
} from '@/api/fetch-service'
import {
  canKeepFetching,
  type FetchResult,
  type InspectionReport,
  type InspectionSegment,
} from '@/domain/fetch_receipt'

const form = reactive({
  subscriptionId: 'SUB-001',
  endpointId: 'EP-001',
  pageSize: 2,
  today: '2026-11-21',
})
const result = ref<FetchResult | null>(null)
const report = ref<InspectionReport | null>(null)
const errorMessage = ref('')

const canContinue = computed(() =>
  result.value?.receipt ? canKeepFetching(result.value.receipt) : false,
)

function outOfScope(segment: InspectionSegment): boolean {
  if (!report.value?.receipt) return false
  return (report.value.越界分段 || []).some((item) => item.分段编号 === segment.分段编号)
}

async function run(task: () => Promise<FetchResult>) {
  errorMessage.value = ''
  try {
    result.value = await task()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '取数失败'
  }
}

async function onSubscribe() {
  report.value = null
  await run(() => fetchBySubscription(form.subscriptionId, form.endpointId, form.pageSize, form.today))
}

async function onContinue() {
  if (!result.value?.receipt) return
  await run(() => continueSegment(result.value!.receipt!.回执编号, form.today))
}

async function onRefetch() {
  if (!result.value?.receipt) return
  await run(() => refetchSnapshot(result.value!.receipt!.回执编号, 1, form.today))
}

async function onInspect() {
  if (!result.value?.receipt) return
  errorMessage.value = ''
  try {
    report.value = await inspectReceipt(result.value.receipt.回执编号, form.today)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核失败'
  }
}
</script>
