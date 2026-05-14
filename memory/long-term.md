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
- PHASE 1 前三项任务已完成：
  1. ✅ 需求深入验证与用户访谈 (requirements-validation-report-v1)
  2. ✅ 竞品功能详细拆解与差距分析 (competitor-feature-gap-analysis-v1)
  3. ✅ 技术架构设计与技术选型决策 (technical-architecture-and-stack-decision-v1)
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
-
