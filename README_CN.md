# OneAI Construction Twin v0.7.1
## Enterprise Pilot Edition｜企业试点版

**面向建筑与基础设施的 AI 原生数字孪生**

> 看见项目，理解项目，预测下一步，在问题发生前采取行动。

这是 OneAI Construction Twin 企业试点版的累计完整代码库。它完整包含 v0.6 的数字孪生与分布式资产管线，并加入企业试点所需的数据库迁移、多租户权限、OIDC/JWT 接入、审计、就绪检查、备份恢复、安全默认值、运行监控和端到端试点流程。

## 已包含的完整能力

### 数字孪生与项目智能
- Project World Model 与 Twin Entity
- IFC 语义导入；支持 IfcOpenShell，并提供明确标识的 STEP 降级解析
- IFC 几何、Three.js 可视化和构件选择
- IFC 到 GLB、3D Tiles 1.1 的资产生成
- LOD0 / LOD1 / LOD2 与 Cesium 空间流式加载
- 分布式资产 Job、Partition、Worker Lease、取消/恢复和内容寻址缓存
- 进度计划 CSV 导入和 BIM ↔ Schedule 映射
- Baseline / Actual / Forecast 4D 时间轴
- Evidence-first Ask Twin：对项目记录做 BM25 检索，声明由检索结果推导，检索不到证据时强制降级为 provisional
- 风险评估与 P10/P50/P90 预测：均由实测活动偏差计算，并随响应返回所用模型、样本量与"未标定"状态
- What-if Simulation：完整返回本次使用的假设集
- Agent 建议基于当前进度状态生成，须人工审批；审计记录采用哈希链，可验证是否被篡改

### 企业试点底座
- Alembic 数据库迁移基线
- Tenant、Organization、Project 数据范围隔离
- 面向人类与 AI Agent 身份的 RBAC
- 本地 JWT、API Key 与 OIDC-ready 认证模式
- 上传文件类型、大小、文件名与 SHA256 校验
- Request ID、安全响应头与 Rate Limit
- `/health`、`/health/ready`、`/ready`、`/metrics` 与 Worker Heartbeat
- Local / S3 / MinIO 对象存储
- PostgreSQL/SQLite 与对象存储的备份、校验和恢复工具
- 结构化日志、Prometheus 指标与可选 OpenTelemetry 导出
- Docker Compose、Kubernetes、HPA、PDB 与 Network Policy 参考
- Pilot 状态、验收清单和 E2E 验证脚本

### v0.7.1 加固内容
- 生成资产一律经鉴权、按租户隔离下发，已移除公开静态挂载
- 审计记录哈希链化，并提供校验端点
- Rate Limit 改用稳定的凭证指纹，按调用方而非按路径计额
- 每个 AI 响应显式声明来源（`reasoning.model_backed`）
- 自动化测试从 8 个增加到 31 个，且运行在隔离数据库上

完整清单见 `RELEASE_NOTES_V071.md`。

## 累计版本关系

| 版本 | 累计能力 |
|---|---|
| v0.1 | M12 后端与领域底座 |
| v0.2 | 产品前端、Twin Viewer 与完整 Read API |
| v0.3 | IFC 语义与 BIM ↔ Schedule Mapping |
| v0.4 | IFC Geometry 与 4D Construction Timeline |
| v0.5 | GLB、3D Tiles、LOD 与 Cesium Streaming |
| v0.6 | Durable 分布式资产管线与对象存储 |
| **v0.7** | **企业试点强化：安全、迁移、恢复、监控和运维** |

## 本地快速启动

建议环境：
- Python 3.12
- Node.js 20.9+（推荐 22）
- npm 10+

### 1. 启动 API

```bash
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# 推荐：开启完整 IFC 语义/几何支持
python -m pip install -r requirements-ifc.txt
python -m uvicorn app.main:app --reload
```

Swagger：`http://127.0.0.1:8000/docs`

### 2. 启动 Asset Worker

```bash
cd apps/api
source .venv/bin/activate
python -m app.workers.asset_worker
```

### 3. 启动 Web

```bash
cd apps/web
cp .env.local.example .env.local
npm install --registry=https://registry.npmjs.org
npm run dev
```

访问：`http://localhost:3000`

### 4. 测试与 Demo

```bash
cd ../..
PYTHONPATH=apps/api python -m pytest -q
python scripts/e2e_pilot.py
```

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

启动 3 个并行 Worker：

```bash
docker compose up --build --scale asset-worker=3
```

开启 Prometheus / Grafana：

```bash
docker compose --profile monitoring up --build
```

正式部署前必须先阅读 `RUN_ENTERPRISE_V07.md`、`docs/DEPLOYMENT.md` 和 `docs/SECURITY.md`。Production 模式会主动拒绝不安全的默认配置。

## 首个 Pilot 推荐范围

**Steel Structure Schedule Intelligence｜钢结构进度智能**

```text
IFC + Baseline Schedule + Daily Reports + Photos + RFI/NCR + Inspections
  -> 实际与计划对比
  -> 带证据的延期原因
  -> 下游影响
  -> P10/P50/P90 预测
  -> 纠偏方案
  -> 人工审批行动
  -> 审计轨迹
```

## Evidence 原则

> **No AI conclusion without evidence｜没有证据，不形成正式 AI 结论。**

Ask Twin 返回 Answer、Confidence、Claims、Evidence 与 Recommended Actions。没有关联证据时，系统会明确降低置信度并标记为 provisional。

## 文档

- `RUN_ENTERPRISE_V07.md`：完整启动与验收步骤
- `docs/architecture/ENTERPRISE_PILOT_V07.md`：系统架构
- `docs/DEPLOYMENT.md`：本地、Docker、Kubernetes 部署
- `docs/SECURITY.md`：认证、授权和生产安全
- `docs/BACKUP_RESTORE.md`：备份恢复
- `docs/PILOT_RUNBOOK.md`：企业试点运行手册
- `docs/DATA_MODEL.md`：Project World Model 数据模型
- `docs/API_REFERENCE.md`：主要 API
- `docs/E2E_TEST_PLAN.md`：端到端发布门禁
- `docs/KNOWN_LIMITATIONS.md`：明确能力边界

## 发布边界

v0.7.0 是**企业试点基线**，不是对通用生产成熟度的宣称。真实客户部署前，必须配置正式身份提供商、生产 Secret、HTTPS、备份、监控、Worker、数据驻留规则、客户专属权限以及经过验证的恢复流程。
