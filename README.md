# 数契工坊 · 数据契约与服务化查询开放平台

面向数据契约登记、契约版本演进、字段承诺校验、消费方订阅、服务化查询端点、结果集快照、口径对账与双跑差异归因、新鲜度追踪、服务等级目标违约处置与用量计量的数据应用开放平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8002/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5175/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8002`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据契约 | `data_contract` | 数据契约 | 契约编号、契约名称、数据主题 |
| 契约版本 | `contract_version` | 契约版本 | 版本编号、所属契约、版本号 |
| 字段承诺 | `field_promise` | 字段承诺 | 承诺编号、所属版本、字段名称 |
| 消费方应用 | `consumer_app` | 消费方应用 | 应用编号、应用名称、所属团队 |
| 订阅计划 | `subscription_plan` | 订阅计划 | 订阅编号、消费方应用、所属契约 |
| 查询端点 | `service_endpoint` | 查询端点 | 端点编号、所属契约、端点路径 |
| 查询计划 | `query_plan` | 查询计划 | 计划编号、所属端点、筛选条件 |
| 结果集快照 | `result_set` | 结果集快照 | 快照编号、所属计划、绑定版本 |
| 缓存策略 | `cache_policy` | 缓存策略 | 策略编号、所属端点、缓存键构成 |
| 限流配额 | `rate_quota` | 限流配额 | 配额编号、消费方应用、所属端点 |
| 服务等级目标 | `sla_target` | 等级目标 | 目标编号、所属契约、目标类型 |
| 违约事件 | `sla_breach` | 违约事件 | 事件编号、所属目标、违约窗口 |
| 口径对账 | `reconcile_task` | 对账任务 | 对账编号、对账口径、左侧来源 |
| 双跑比对 | `dual_run` | 双跑记录 | 双跑编号、关联对账、旧口径版本 |
| 差异归因 | `diff_attrib` | 归因条目 | 归因编号、关联比对、差异字段 |
| 数据集发布 | `dataset_release` | 发布批次 | 发布编号、数据集名称、绑定版本 |
| 新鲜度追踪 | `freshness_track` | 新鲜度读数 | 读数编号、所属契约、承诺延迟 |
| 抽样探查 | `sample_probe` | 探查样本 | 样本编号、所属数据集、抽样比例 |
| 访问授权 | `access_grant` | 授权记录 | 授权编号、消费方应用、所属端点 |
| 用量计量 | `usage_meter` | 用量读数 | 计量编号、消费方应用、所属端点 |
| 服务事件 | `incident_log` | 服务事件 | 事件编号、所属端点、事件类别 |
| 契约审计 | `contract_audit` | 审计条目 | 条目编号、所属契约、操作类型 |
| 来源批次 | `source_batch` | 来源批次 | 批次编号、契约编号、绑定版本 |
| 取数回执 | `fetch_receipt` | 取数回执 | 回执编号、订阅编号、可读列 |
| 交付分段 | `delivery_segment` | 交付分段 | 分段编号、所属回执、页码 |

## 订阅取数

同一批源数据可以交给多个订阅，但每个订阅只能拿到属于自己的那份列投影：

```text
可读列 = 端点返回列集合 ∩ 授权可见列范围 ∩ 订阅绑定版本的字段承诺 ∩ 源批实际列
```

- `POST /api/fetch/subscribe`：按订阅取数，冻结快照、签发回执并交付首段。
  回执钉住可读列、列承诺版本（含摘要）与快照归属；同一来源批交给两个订阅时
  各自回执只含各自可见列。
- `POST /api/fetch/continue`：持回执续取下一段。必须沿用回执钉住的同一份仍有效
  列承诺：版本已废止、承诺内容变更、授权收窄、快照不可读都会拒绝续取，
  并把回执与快照整体失效。
- `POST /api/fetch/refetch`：持回执复取已交付快照分段，只能读到该回执归属内的
  授权列，快照里多出的列会被再次投影剔除。
- `GET /api/fetch/inspect/{回执编号}`：逐段复核页码、承诺版本、可读列与实际列，
  给出后续领取资格与说明。
- `POST /api/fetch/switch-version`：切换契约适用的列承诺版本；`retire_previous`
  为真时旧版本立即废止，为假时旧版本留在过渡中，未完成回执可继续用旧承诺分页。

来源批业务行、快照投影行与分段实际交付行分别存放在内部支撑表
`_source_batch_row`、`_snapshot_rows`、`_delivery_row`，不参与概览统计。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据分析与数据应用
