# Intelligence Survey Platform — Agent Handoff Prompt

> 将以下内容完整粘贴给接手法 AI Agent，它将获得继续开发所需的全部上下文。

---

## Prompt

```
你正在接手一个正在进行中的全栈产品开发项目：Intelligence Survey Platform（智能学术调查平台）。这是一个面向学术研究者的 AI 驱动在线调查平台，已完成 Phase 1 和 Phase 2 的全部 11 项任务 + Phase 3 的 3 项任务（共 14 项），当前处于 Phase 3 后半段。

## 项目仓库

- 本地路径: /Users/wells/Documents/2512-PHD_PROJECT-v2/SSLens/projects/proj-1778694582034-hx08yv/
- GitHub: https://github.com/Wells-XW/intelligence-survey-platform
- Git 状态: 最新 commit dfaaac8（本地已保存，SSH 暂不可用，需要 git push）

## 项目愿景

成为中文学术调查的基础设施——就像 Overleaf 之于 LaTeX 论文写作，Qualtrics 之于英文学术调查。

核心差异化四支柱：
1. 学术规范性内置（AAPOR/APA 标准，信效度检验，伦理合规）
2. AI 驱动全流程（研究设计→问卷生成→数据分析→报告撰写）
3. 风险自动检测（测量偏差、样本偏倚、伦理问题、统计误用）
4. 中文优先 + 国际兼容（PIPL 合规，CNKI 集成）

## 技术栈

前端：
- React 19.2.6 + TypeScript 6.0.3 + Vite 8.0.13
- Tailwind CSS 4.3 + shadcn/ui（组件在 apps/web/src/components/ui/）
- SurveyJS Creator 2.5.24（问卷拖拽编辑器）
- Zustand 5.0.13（客户端状态）+ TanStack Query 5.100.10（服务端缓存）
- ECharts（可视化图表）

后端：
- Python FastAPI 0.128 + SQLAlchemy async + asyncpg
- PostgreSQL 16（Docker，端口 5433→5432）
- Redis 7（Docker，端口 6379）
- JWT 认证（access 15min + refresh 7d 一次性轮转）
- RBAC 权限（owner>editor>viewer，Survey 级别）
- Celery + Redis（AI 异步任务队列）
- openai SDK → DeepSeek-R1 API（中文问卷生成主力）

Monorepo 结构（pnpm workspace）：
- apps/web/ — React 前端
- apps/api/core/ — FastAPI 后端
- docker-compose.yml — PostgreSQL + Redis + API + Web + Celery

## 已完成的 14 项任务（12 个 Git commits）

Phase 1 — 基础建设（6/6 ✅）
- T1: 需求验证与用户访谈 → outputs/requirements-validation-report-v1.md（~5,500 字）
- T2: 竞品功能拆解与差距分析 → outputs/competitor-feature-gap-analysis-v1.md（~8,000 字，9 平台 47 项功能对比）
- T3: 技术架构设计与技术选型 → outputs/technical-architecture-and-stack-decision-v1.md（~8,000 字）
- T4: MVP 问卷设计器 → ~10,300 行代码（SurveyJS Creator + FastAPI CRUD + Docker）
- T5: 数据安全与权限机制 → ~2,829 行（JWT + RBAC + 速率限制 + 审计日志 + PIPL 合规）
- T6: 基础分析与可视化模块 → ~3,107 行（Cronbach's α + ECharts 图表 + 回复质量检测）

Phase 2 — AI 集成（5/5 ✅）
- T7: AI 问卷生成引擎 → ~3,390 行（多模型路由 + SQP 质量评估 + SSE 流式输出）
- T8: 知识库与文献检索集成 → ~4,540 行（PubMed/Semantic Scholar/CNKI + 量表库 + 10 种子量表）
- T9: 数据质量控制模块 → 缺失模式检测 + 不一致检测 + 注意力检测 + 响应时间分布
- T10: 伦理合规与风险提示引擎 → PIPL 6 项 + GDPR 5 项检查规则 + AI 辅助审查 + 合规页面
- T11: MVP 内部测试与迭代 → outputs/mvp-test-plan.md + outputs/beta-user-feedback-guide.md + outputs/mvp-iteration-log.md

Phase 3 — 完善发布（3/6 ✅）
- T12: 样本与发放管理模块 → ~4,134 行（SampleGroup/Recipient/Distribution/Quota 四模型 + CSV 导入 + 配额引擎）
- T13: 协作与版本管理 → ~2,689 行（SurveyVersion 快照 + CollaborationInvitation + 乐观锁冲突检测）
- T14: 测量工具箱 → ~2,949 行（Split-half/Item-total/KMO/Bartlett 纯数学引擎 + APA 报告 + 常模对标）

## 待完成的 3 项任务

T15: API 开放平台与导出完善（P3，计划 2027-07-01）
- 依赖：T12（样本发放）✅ + T13（协作管理）✅ — 无阻塞
- 核心交付：RESTful API 文档、API Key 管理、Webhook 通知、多格式导出（CSV/Excel/SPSS/SAS/JSON）、API 限流

T16: Beta 公测与学术合作试点（P1，计划 2027-08-01）
- 依赖：T15 + T14
- 核心交付：部署生产环境、招募 10-15 位学术用户、收集反馈、迭代修复

T17: 商业模式验证与定价策略确定（P2，计划 2027-09-01）
- 依赖：T16
- 核心交付：定价模型、支付集成、用户分层、收入预测

## 代码库架构（关键文件）

后端核心文件：
- apps/api/core/app/main.py — FastAPI 入口（84 条路由，12 个模块）
- apps/api/core/app/models/ — ORM 模型（survey.py, user.py, response.py, ai_generation.py, knowledge_base.py, sample_distribution.py, collaboration.py, compliance.py, audit.py）
- apps/api/core/app/schemas/ — Pydantic v2 schemas
- apps/api/core/app/services/ — 业务逻辑（knowledge_base.py, compliance.py, psychometrics.py, sample_service.py 等）
- apps/api/core/app/api/v1/ — API 路由（surveys.py, auth.py, responses.py, analytics.py, ai_generation.py, knowledge_base.py, compliance.py, sample_distribution.py, psychometrics.py, collaboration.py）
- apps/api/core/app/core/ — 配置（config.py）、数据库（database.py）、安全（security.py）、依赖注入（deps.py）
- apps/api/core/app/core/psychometrics.py — 纯 Python 心理计量学引擎（410 行，numpy/scipy）
- apps/api/core/app/core/seed_data.py — 10 个学术量表 + 6 个方法学指南种子数据
- apps/api/core/app/core/llm_client.py — 多模型 LLM 客户端（DeepSeek/Claude/GPT 路由）
- apps/api/core/app/core/sqp_evaluator.py — SQP 问卷质量评估器
- apps/api/core/alembic/ — 数据库迁移（0001-0007）

前端核心文件：
- apps/web/src/main.tsx — React 入口
- apps/web/src/app/App.tsx — 路由根组件（BrowserRouter + AuthGuard）
- apps/web/src/app/pages/ — 页面组件（LoginPage, RegisterPage, SurveyListPage, SurveyDesignerPage, AiGenerationPage, MeasurementToolkitPage, CompliancePage, SampleDistributionPage, KnowledgeBasePage, LiteratureSearchPage, ScaleLibraryPage）
- apps/web/src/features/ — 功能模块（survey-designer/, ai-generation/, knowledge-base/, sample-distribution/, collaboration/, compliance/, measurement-toolkit/）
- apps/web/src/lib/api.ts — API 客户端 + 全部 TypeScript 类型定义
- apps/web/src/stores/ — Zustand 状态（auth.ts, survey.ts, knowledge.ts, ethics.ts, measurement.ts, sample.ts）
- apps/web/src/components/ui/ — 15 个 shadcn/ui 组件

配置文件：
- docker-compose.yml — 5 服务（postgres, redis, api, celery-worker, web）
- .env.example — 环境变量模板
- pnpm-workspace.yaml — Monorepo 配置
- turbo.json — Turborepo 配置
- .github/workflows/ci.yml — GitHub Actions CI

项目文档：
- project.md — 项目计划文档
- soul.md — 愿景/价值观/反目标/风险
- memory/long-term.md — 长期记忆（最权威的进度追踪）
- memory/2026-05-15.md — 当日详细记录
- outputs/ — 6 份调研/测试文档

## 已知问题（4 个 P3 级别）

| ID | 描述 | 计划修复 |
|----|------|---------|
| K001 | AI 路由中 LOCAL_QWEN 模式回退到 DeepSeek（PIPL 风险，dev 环境已接受） | v0.2.0 接入本地 Qwen |
| K002 | CNKI 检索使用 web fallback（无公开 API） | v0.3.0 |
| K003 | GDPR 检查仅英文关键词匹配 | v0.2.0 |
| K004 | 移动端填答体验未优化 | v0.3.0 |

## 启动项目的方法

```bash
# 1. 启动 Docker Desktop
open -a Docker

# 2. 启动 PostgreSQL + Redis
cd /Users/wells/Documents/2512-PHD_PROJECT-v2/SSLens/projects/proj-1778694582034-hx08yv
docker compose up -d postgres redis

# 3. 运行数据库迁移
cd apps/api/core
python3 run_migrations.py

# 4. 启动后端 API（新终端）
cd apps/api/core
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 5. 启动前端（另一个新终端）
cd /Users/wells/Documents/2512-PHD_PROJECT-v2/SSLens/projects/proj-1778694582034-hx08yv
pnpm --filter web dev
```

前端：http://localhost:5173
后端 API 文档：http://localhost:8000/docs
测试账号：test@example.com / testpass123

## 关键技术决策（影响后续开发）

1. Python 3.9 兼容性：所有类型注解必须用 `from __future__ import annotations` 或 `Optional[X]` 而非 `X | None`
2. PostgreSQL 端口：Docker 映射到 5433（非默认 5432），数据库 URL 用 `postgresql+asyncpg://survey:survey@localhost:5433/survey_db`
3. bcrypt 版本锁定 4.0.x（passlib 1.7.4 不兼容 bcrypt 5.x）
4. shadcn/ui 组件按需安装：新页面如果用到新组件（如 Badge, Tabs, Table 等），需要先 `pnpm --filter web dlx shadcn@latest add <component>`
5. Alembic 迁移链：revision ID 使用短格式（如 "0003"），不是 UUID，确保 revision chain 连贯
6. CORS：后端允许 `http://localhost:5173`，前端 Vite 代理 `/api/*` 到后端

## 用户偏好

- 用户 Wells 是博士研究生，中文为主要沟通语言
- 偏好从代码层面（而非可视化）进行 debug
- 不要在没有明确要求的情况下创建文档文件（README 等）
- Commit 格式：conventional commits（feat:/fix:/docs:/test:/chore:）
- 代码风格：black 格式化，Google-style docstrings，type hints 必须

## 你的任务

1. 先确认当前代码是否能正常构建和运行（TypeScript 编译 + Python 导入检查）
2. 尝试 git push 到 GitHub（如有 SSH 问题，报告给用户）
3. 启动 Phase 3 剩余任务：从 T15「API 开放平台与导出完善」开始
4. 按 T15 → T16 → T17 顺序推进，每个任务完成后提交并推送

## 重要提醒

- 这个项目的所有代码在同一个 Git 仓库中，commit history 是连贯的 12 个 conventional commits
- project.md 中 Phase 3 的 T13/T14 标记为 ⬜ 但实际已完成（memory/long-term.md 是权威来源），请在适当时机更新 project.md
- 后端的 Python 测试分为两类：纯函数测试（不需要数据库）和集成测试（需要 PostgreSQL 运行），注意区分
- 前端的 TypeScript 检查命令：`cd apps/web && npx tsc --noEmit`
- 后端的 Python 语法检查：`python3 -m py_compile <file>`
```
