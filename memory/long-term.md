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
