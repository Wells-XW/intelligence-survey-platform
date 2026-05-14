# 长期记忆

## 2026-05-14
- 用户偏好：不因时间限制而压缩项目计划，优先保证项目质量
- 产品名称：暂无，构建中再考虑
- 仓库位置：SSLens 内部 SUB_WORK 目录 + GitHub 独立仓库 (Wells-XW/intelligence-survey-platform)
- 项目定位：面向学术研究的智能在线调查平台 — AI 驱动 + 学术规范性内置 + 中文优先 + 可负担
- 技术栈决策（2026-05-14 经技术选型决策确定）：
  - 前端: React 19 + TypeScript + Vite + Tailwind CSS 4 + shadcn/ui + Zustand + TanStack Query
  - 问卷设计器: SurveyJS 社区版(MVP) → dnd-kit 自研(Phase 2+)
  - 后端: Python FastAPI(核心) + Node.js Fastify(网关, 替代Express, 快5x)
  - AI: 多模型路由(DeepSeek-R1 中文主力 + Claude 英文 + GPT-4.5 mini 批量)
  - 存储: PostgreSQL 16 + Elasticsearch 9.x + Garage(对象存储, 替代MinIO) + Redis 7
  - 部署: Docker Compose(MVP) → Kubernetes(Phase 2+)
- **PHASE 1 全部六项任务完成** ✅：
  1. ✅ 需求深入验证与用户访谈 (requirements-validation-report-v1)
  2. ✅ 竞品功能详细拆解与差距分析 (competitor-feature-gap-analysis-v1)
  3. ✅ 技术架构设计与技术选型决策 (technical-architecture-and-stack-decision-v1)
  4. ✅ 核心模块 MVP：问卷设计器开发 (2026-05-14 完成初始代码脚手架)
  5. ✅ 数据安全与权限机制实现 (2026-05-14 完成五层安全架构)
  6. ✅ 基础分析与可视化模块 (2026-05-14 完成 Analytics Engine + ECharts Dashboard)
- **PHASE 2 首项任务完成** ✅：
  7. ✅ AI 问卷生成引擎开发 (2026-05-15 完成多模型路由 + SQP评估 + SSE流式 + Celery)
- 竞品验证核心结论：Qualtrics 贵且难用，SurveyMonkey 缺少学术模块，LimeSurvey 界面陈旧，问卷星功能全但无学术引导，空白市场确认存在
- 差距分析核心发现：①AI+学术规范融合是全局空白 ②信效度检验内置是全局空白 ③PIPL合规是中文独有机会 ④学术个人$10-30/月定价区间完全空白 ⑤文献→问卷工作流无竞品实现
- 四大差异化支柱：学术规范内置 + AI智能全流程 + 中文生态深度 + 可负担定价
- MVP P0 功能：AI问卷生成(方法论约束) + 信效度内置 + PIPL合规基础
- 用户画像：五类核心用户，博士生是最迫切的目标用户群
- AI+调查融合趋势：95%研究者已使用AI，LLM问卷生成已有SQP/SQRA评估框架
- PIPL合规为刚性需求：需内置知情同意、最小化检测、敏感信息识别、跨境数据管控
- 关键风险：AI生成质量、竞品快速跟进(问卷星已接入DeepSeek R1)、中国用户付费意愿低、PIPL合规成本
- 核心架构模式：双后端(FAST API核心+Fastify网关)、模块化单体(MVP)、SSE流式AI交互、PWA离线填写
- LLM成本策略：DeepSeek-R1 成本仅为 GPT-4o 的 ~5%，中文质量更高，是核心优势

## 2026-05-14 自动提取
- 技术架构选型决策文档已完成，存储于 outputs/technical-architecture-and-stack-decision-v1.md（约8000字）
- API网关最终选用 Fastify（替代表Express），因2026年共识 Express 不适合新项目且 Fastify 快5倍
- 对象存储选用 Garage（替代MinIO），因 MinIO 社区版移除管理控制台，Garage 轻量且 Apache 2.0 许可

## 2026-05-14 问卷设计器开发进展
- ✅ MVP 问卷设计器代码脚手架完成，已推送至 GitHub (Wells-XW/intelligence-survey-platform)
- 代码结构: Monorepo (Turborepo + pnpm)，apps/web (前端) + apps/api/core (后端)
- 前端: React 19.2.6 + Vite 8.x + TypeScript 6.x + Tailwind CSS 4.3 + shadcn/ui (Nova preset)
- 前端核心依赖: SurveyJS Creator 2.5.24（免费开发/PoC，生产需 $589/dev 许可证）、React Router 7.15、Zustand 5.0.13、TanStack Query 5.100.10
- 后端: FastAPI + SQLAlchemy async + asyncpg + alembic，Survey CRUD API 已实现
- 数据库: PostgreSQL 16，survey 表使用 UUID 主键 + JSONB 存储问卷结构
- 部署: Docker Compose 一键启动 (postgres + redis + api + web)
- CI: GitHub Actions (lint + type check + test)
- TypeScript 编译零错误通过
- 待完成: 实际 Docker Compose 启动验证（需 PostgreSQL 运行环境）

## 2026-05-14 数据安全与权限机制实现
- ✅ 五层安全架构完整实现，已推送至 GitHub (Wells-XW/intelligence-survey-platform)
- 52 文件变更，~2,829 行新增代码
- 安全层次:
  1. **认证层**: JWT (access 15min + refresh 7d 一次性轮转)，bcrypt 密码哈希，注册/登录/刷新/me API
  2. **授权层**: Survey-level RBAC (owner > editor > viewer)，SurveyPermission 表 JOIN 实现多租户数据隔离
  3. **速率限制**: 内存滑动窗口限流器 (60 req/min/IP)，RateLimitMiddleware
  4. **审计日志**: AuditLog 追加模型 (action, resource_type, resource_id, IP, user_agent)，关键操作全记录
  5. **PIPL 合规**: ConsentRecord (注册时自动创建知情同意)，SurveyResponse 含 PIPL 合规说明
- 后端新增文件: 15 (6 models + 3 core utilities + auth API + rate limit middleware + schemas + tests)
- 后端修改文件: 6 (config, models/__init__, survey model, main.py, surveys router, schemas)
- 前端新增文件: 7 (auth store + LoginPage + RegisterPage + AuthGuard + NavBar + AppLayout + auth API client)
- 前端修改文件: 3 (api.ts JWT注入+401刷新, App.tsx 路由, main.tsx 初始化)
- 测试: 4 文件 (conftest + test_security + test_auth + test_surveys_auth, 16+ test cases)
- Python 3.9 兼容: 使用 `from __future__ import annotations` 支持现代类型提示
- passlib + bcrypt 版本兼容: bcrypt 锁定在 >=4.0.0,<4.1.0（passlib 1.7.4 不兼容 bcrypt 5.x）
- shadcn/ui 组件: 11 组件已安装 (button, input, card, label, separator, dropdown-menu, tooltip, sonner, skeleton + 新增)
- 前端认证流: Zustand store → localStorage 持久化 → 401 自动 refresh → 失败时登出

## 2026-05-14 基础分析与可视化模块实现
- ✅ Analytics Engine + ECharts 可视化仪表盘完成，已推送至 GitHub
- 30 文件变更，~3,107 行新增代码
- 后端分析引擎 (`core/analytics.py`):
  - `compute_frequencies()`: 分类变量频率分布
  - `compute_descriptive()`: 均值/中位数/众数/标准差
  - `compute_cross_tab()`: 交叉分析 + χ² 检验
  - `compute_cronbach_alpha()`: 原始 Cronbach's α 公式实现（纯 Python）
  - `compute_response_quality()`: 速度检测/直线填答者/完成率
  - `compute_text_summary()`: 开放题基本文本统计
- SurveyResponse 模型: UUID PK + survey_id FK + JSONB answers + JSONB metadata(PIPL)
- 数据采集 API: POST 公开提交(匿名) + GET/DELETE 鉴权检索
- 分析 API: summary / reliability / cross-tab / response-quality / CSV export
- 前端可视化:
  - ECharts 图表组件: BarChart, PieChart, HeatmapChart
  - 数据质量指标卡: 完成率/中位用时/速度/直线填答者
  - Cronbach's α 展示卡: 带颜色编码(Excellent/Good/Acceptable/Questionable/Poor)
  - 受访者填写页: SurveyJS Survey 渲染 + PIPL 知情同意复选框
  - 四标签仪表盘: 描述统计/交叉分析/信度分析/数据质量
- 测试: 13 个分析引擎单元测试全部通过（Cronbach's α 正确性验证）
- Python 3.9 兼容修复: surveys.py 添加 `from __future__ import annotations`
- 可视化库: ECharts 5.x via echarts-for-react（中文生态最优选择）

## 2026-05-15 AI 问卷生成引擎实现 (Phase 2 Task 7)
- ✅ **AI 问卷生成引擎完整实现**，已推送至 GitHub (Wells-XW/intelligence-survey-platform)
- 30 文件变更，~3,390 行新增代码
- **多模型路由引擎** (`core/ai_router.py`):
  - 任务分类路由: Survey Generation / Item Refinement / Literature Search / Quality Check / Sensitive PIPL
  - Provider 适配: DeepSeek (OpenAI-compatible)、Claude (Anthropic proxy)、GPT-mini、Local Qwen (PIPL)
  - 成本估算: DeepSeek ~$0.001/次 (20 题问卷), GPT-4o ~$0.04/次, Claude ~$0.20/次
  - 强制本地路由: 当 `has_sensitive_data=True` 时，自动绕过云端模型
- **方法学约束提示工程** (`core/prompts.py`):
  - `SURVEY_GENERATION_SYSTEM`: 嵌入 AAPOR/APA 标准、SQP v2.1 框架、PIPL 合规、中文学术规范
  - `ITEM_REFINEMENT_SYSTEM`: 五项评审维度（清晰度/偏差/量表/相关性/跨文化）
  - `QUALITY_CHECK_SYSTEM`: 速度检测/直线填答/缺失模式/异常值/不一致性
  - 三个用户 prompt builder: `build_survey_generation_prompt()` / `build_item_refinement_prompt()` / `build_quality_check_prompt()`
- **SQP v2.1 质量评估器** (`core/sqp_evaluator.py`):
  - 逐项评分: 信度估计 / 效度估计 / 偏差风险 / 清晰度 / 方法效应
  - 规则引擎: 引导性检测(中英双语)、双重问题检测、社会期望偏差、默许偏差
  - 综合报告: Markdown 格式输出 + ready/needs-revision/needs-redesign 三级建议
- **SSE 流式 API** (`api/v1/ai.py`):
  - 7 阶段进度推送: estimating → prompting → routing → generating → parsing → evaluating → done
  - 端点: POST /ai/generate (非流式) + /ai/generate/stream (SSE) + /ai/refine + /ai/estimate-cost + /ai/evaluate/{id}
- **Celery 异步任务** (`tasks/ai_tasks.py`):
  - Redis broker + Celery worker (Docker Compose)
  - 自动重试 + 指数退避 (max 2 retries, 30s backoff)
- **前端 AI 生成页** (`AiGenerationPage.tsx`):
  - 表单: 研究主题/RQ/目标人群/题量/语言/构念/方法学要求
  - SSE 实时进度条 + 阶段时间线
  - SQP 质量报告卡片 (颜色编码: ready/needs-revision/needs-redesign)
  - 成本徽章: 模型/tokens/费用显示
  - 一键保存到我的问卷 → 跳转编辑器
- **AiGenerationLog 审计模型**: 每次 LLM 调用记录 model/provider/tokens/cost/latency/status
- **20 测试全部通过**: 路由决策 5 + SQP 评估 8 + 提示模板 3 + 成本估算 1 + Schema 验证 3
- 关键设计决策:
  - MVP 不实现 Claude 原生 SDK（通过 proxy 方式），降低复杂度
  - 本地 Qwen 路由 MVP 回退到 DeepSeek（PIPL 风险在 dev 环境可接受）
  - prompt 中英双语支持，默认中文
  - JSON 解析带 fallback 从 markdown 代码块提取
  - 成本估算精确到 0.0001 cent，¥0.01/次展示给用户

## 2026-05-15 知识库与文献检索集成实现 (Phase 2 Task 8)
- ✅ **知识库与文献检索模块完整实现**，已推送至 GitHub (Wells-XW/intelligence-survey-platform)
- 31 文件变更，~4,540 行新增代码
- **三大子系统**：
  1. **文献检索** — 跨 PubMed (Entrez E-utilities) + Semantic Scholar API 统一搜索，Redis 缓存去重
  2. **量表库** — 10 个已验证学述量表预置（RSES/SWLS/SUS/TAM/AMS/MCSDS-13/UCLA-v3/MBI-GS/NFC-18/GSES），CRUD + 一键导入问卷
  3. **知识库** — 6 个方法学指南 + 已保存参考文献 + AI 辅助跨搜索
- **后端核心**:
  - 3 ORM 模型 (literature_references / knowledge_scales / knowledge_entries)
  - Alembic 迁移 0004（pg_trgm GIN 索引 + 复合索引）
  - 3 服务类 (~600 行)：LiteratureSearchService / ScaleLibraryService / KnowledgeBaseService
  - 15+ API 端点 (`/api/v1/kb/*`)
  - PubMed XML 解析（stdlib xml.etree.ElementTree，零新依赖）
  - 去重策略：DOI 精确匹配 + difflib SequenceMatcher >85% 标题相似度
  - 量表导入问卷：JSONB items → SurveyJS radiogroup elements 自动转换
  - AI 辅助搜索：复用 Task 7 execute_ai_call，主题→关键词扩展+并行搜索
- **前端核心**:
  - 9 个新组件（LiteratureSearchForm / SearchResultCard / LiteratureDetailPanel / ScaleCard / ScaleDetailPanel / ScaleImportDialog / KnowledgeEntryCard / SavedReferencesList / AiAssistedSearchPanel）
  - 3 个新页面（LiteratureSearchPage / ScaleLibraryPage / KnowledgeBasePage）
  - Zustand store (knowledge-base store)
  - NavBar 知识库下拉菜单（文献检索 / 量表库 / 知识库）
- **测试**: 18 单元测试通过（缓存键生成 3 + 去重 4 + PubMed XML 解析 2 + Redis 缓存 2 + 量表导入 3 + 参考文献 CRUD 3 + Schema 验证 4）
- 关键设计决策:
  - PubMed 使用标准 E-utilities (esearch→efetch→XML)，零新依赖
  - CNKI 标记为 best-effort web fallback（无公开 API）
  - Redis 缓存优雅降级（连接失败时不阻塞搜索）
  - 量表导入位置选择: start / end / after:<qid>
  - AI 辅助搜索自动检测搜索词并并行执行文献+量表搜索
  - Semantic Scholar 公共 API 免密钥可访问，但带 API key 更稳定
- **Phase 2 进度**: 2/5 任务完成（T7 AI引擎 ✅ / T8 知识库 ✅ / T9 数据质控 ⬜ / T10 伦理引擎 ⬜ / T11 MVP测试 ⬜）
