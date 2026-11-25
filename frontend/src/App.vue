<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">数契工坊 · 数据契约与服务化查询开放平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向数据契约登记、契约版本演进、字段承诺校验、消费方订阅、服务化查询端点、结果集快照、口径对账与双跑差异归因、新鲜度追踪、服务等级目标违约处置与用量计量的数据应用开放平台。</span>
        <span class="head-user">当前值班：数据工程组</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "订阅取数", path: "/fetch_console" }, { label: "数据契约", path: "/data_contract" }, { label: "契约版本", path: "/contract_version" }, { label: "字段承诺", path: "/field_promise" }, { label: "消费方应用", path: "/consumer_app" }, { label: "订阅计划", path: "/subscription_plan" }, { label: "查询端点", path: "/service_endpoint" }, { label: "查询计划", path: "/query_plan" }, { label: "结果集快照", path: "/result_set" }, { label: "缓存策略", path: "/cache_policy" }, { label: "限流配额", path: "/rate_quota" }, { label: "服务等级目标", path: "/sla_target" }, { label: "违约事件", path: "/sla_breach" }, { label: "口径对账", path: "/reconcile_task" }, { label: "双跑比对", path: "/dual_run" }, { label: "差异归因", path: "/diff_attrib" }, { label: "数据集发布", path: "/dataset_release" }, { label: "新鲜度追踪", path: "/freshness_track" }, { label: "抽样探查", path: "/sample_probe" }, { label: "访问授权", path: "/access_grant" }, { label: "用量计量", path: "/usage_meter" }, { label: "服务事件", path: "/incident_log" }, { label: "来源批次", path: "/source_batch" }, { label: "取数回执", path: "/fetch_receipt" }, { label: "交付分段", path: "/delivery_segment" }, { label: "契约审计", path: "/contract_audit" }]
</script>
