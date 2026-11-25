<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
    moduleRows.value = [{"name": "数据契约", "created": 0, "pending": 0, "abnormal": 0}, {"name": "契约版本", "created": 0, "pending": 0, "abnormal": 0}, {"name": "字段承诺", "created": 0, "pending": 0, "abnormal": 0}, {"name": "消费方应用", "created": 0, "pending": 0, "abnormal": 0}, {"name": "订阅计划", "created": 0, "pending": 0, "abnormal": 0}, {"name": "查询端点", "created": 0, "pending": 0, "abnormal": 0}, {"name": "查询计划", "created": 0, "pending": 0, "abnormal": 0}, {"name": "结果集快照", "created": 0, "pending": 0, "abnormal": 0}, {"name": "缓存策略", "created": 0, "pending": 0, "abnormal": 0}, {"name": "限流配额", "created": 0, "pending": 0, "abnormal": 0}, {"name": "服务等级目标", "created": 0, "pending": 0, "abnormal": 0}, {"name": "违约事件", "created": 0, "pending": 0, "abnormal": 0}, {"name": "口径对账", "created": 0, "pending": 0, "abnormal": 0}, {"name": "双跑比对", "created": 0, "pending": 0, "abnormal": 0}, {"name": "差异归因", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据集发布", "created": 0, "pending": 0, "abnormal": 0}, {"name": "新鲜度追踪", "created": 0, "pending": 0, "abnormal": 0}, {"name": "抽样探查", "created": 0, "pending": 0, "abnormal": 0}, {"name": "访问授权", "created": 0, "pending": 0, "abnormal": 0}, {"name": "用量计量", "created": 0, "pending": 0, "abnormal": 0}, {"name": "服务事件", "created": 0, "pending": 0, "abnormal": 0}, {"name": "来源批次", "created": 0, "pending": 0, "abnormal": 0}, {"name": "取数回执", "created": 0, "pending": 0, "abnormal": 0}, {"name": "交付分段", "created": 0, "pending": 0, "abnormal": 0}, {"name": "契约审计", "created": 0, "pending": 0, "abnormal": 0}]
  }
})
</script>
