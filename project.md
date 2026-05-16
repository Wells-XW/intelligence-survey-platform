# Intelligence Survey Platform（智能学术调查平台）

## 项目概述

基于 ChatGPT Deep Research 输出的竞品与需求调研报告，开发面向学术研究的智能在线调查平台。集成 AI 问卷设计、研究设计辅助、测量工具库、样本管理、数据质控、分析可视化、伦理合规提示、知识库检索等功能。

- **SUB_WORK 路径**: `04_SUB_WORK/2026-05-14-intelligence-survey-platform · 科研项目/`
- **分类**: 科研项目（产品开发实施）
- **与博士论文关系**: 独立项目
- **产出目标**: 可运行的 MVP 产品 → 正式发布
- **GitHub**: https://github.com/Wells-XW/intelligence-survey-platform

## 核心差异化

1. **学术规范性内置** — 问卷设计阶段即嵌入 AAPOR/APA 标准，信效度检验，伦理合规
2. **AI 驱动全流程** — 研究设计→问卷生成→数据分析→报告撰写，每个环节有 AI 助手
3. **风险自动检测** — 测量偏差、样本偏倚、伦理问题、数据泄露、统计误用实时提示
4. **中文优先 + 国际兼容** — 深度支持中国学术生态（PIPL、CNKI），同时兼容 GDPR

## 市场定位

**空白**: 尚无"AI 智能 + 学术规范 + 中文生态 + 可负担"的调查平台。

| 竞品 | 短板 |
|------|------|
| Qualtrics | $420/月起，中小企业/个人研究者负担不起 |
| SurveyMonkey | 无学术专用模块 |
| LimeSurvey | 界面陈旧，AI 薄弱 |
| 问卷星 | 缺少学术引导和 AI 能力 |
| Prolific | 仅做受试者招募，无问卷设计 |

## 技术栈（2026-05-14 经技术选型决策确定）

- **前端**: React 19 + TypeScript + Vite + Tailwind CSS 4 + shadcn/ui
  - 状态管理: Zustand (客户端) + TanStack Query (服务端)
  - 问卷设计器: SurveyJS 社区版 (MVP) → 基于 dnd-kit 自研 (Phase 2+)
  - 离线填写: PWA (Workbox + IndexedDB/Dexie.js)
- **后端**: Python FastAPI (核心逻辑/4 个微服务) + Node.js Fastify (API Gateway)
  - 异步任务: Celery + Redis (AI 生成/数据导出/统计分析)
  - 内部通信: HTTP REST (MVP) → gRPC (Phase 2+)
- **AI**: 多模型路由策略
  - 中文主力: DeepSeek-R1 (成本仅为 GPT-4o 的 5%，中文最优)
  - 英文分析: Claude Opus 4 (200K 上下文)
  - 批量检测: GPT-4.5 mini (低成本)
  - 敏感数据: 本地 Qwen3/Yi-Large (数据不出境)
  - 质量评估: SQP + SQRA 框架
- **知识库**: QMD + 文献检索 API (CNKI, PubMed, Semantic Scholar)
- **存储**: PostgreSQL 16 + Elasticsearch 9.x + Garage (对象存储) + Redis 7
- **部署**: Docker Compose (MVP) → Kubernetes (Phase 2+)

> **选型说明**: 详见 `outputs/technical-architecture-and-stack-decision-v1.md`
> 关键修正: Express → Fastify (快 5x, 2026 新项目标准), MinIO → Garage (社区版 Console 移除), 新增 Zustand/TanStack Query/SurveyJS/多模型路由策略

## 开发阶段

### Phase 1: 基础建设（2026-05 至 2026-10）✅ 6/6
- ✅ 需求验证与用户访谈 (task-1778697793535-wghzvv) P1 | 2026-05-15
- ✅ 竞品功能详细拆解与差距分析 (task-1778697793535-y07ngw) P2 | 2026-05-20
- ✅ 技术架构设计与技术选型决策 (task-1778697793535-vntvpp) P1 | 2026-06-01
- ✅ 核心模块 MVP：问卷设计器开发 (task-1778697793535-wwjanx) P1 | 2026-07-01
- ✅ 数据安全与权限机制实现 (task-1778697793535-swxh3z) P2 | 2026-08-01
- ✅ 基础分析与可视化模块 (task-1778697793535-z0soij) P2 | 2026-09-01

### Phase 2: AI 集成（2026-10 至 2027-02）✅ 5/5
- ✅ AI 问卷生成引擎开发 (task-1778697793535-sb3gfu) P1 | 2026-11-01
- ✅ 知识库与文献检索集成 (task-1778697793535-lnsgdh) P2 | 2026-12-01
- ✅ 数据质量控制模块 (task-1778697793535-54876m) P2 | 2026-12-15
- ✅ 伦理合规与风险提示引擎 (task-1778697793535-1gulsk) P2 | 2027-01-01
- ✅ MVP 内部测试与迭代 (task-1778697793535-zrx9cv) P1 | 2027-02-01

### Phase 3: 完善发布（2027-02 至 2027-09）
- ✅ 样本与发放管理模块 (task-1778697793535-t4qiew) P2 | 2027-04-01
- 🔄 协作与版本管理 (task-1778697793535-fwaxeh) P3 | 2027-05-01
  - ✅ T13.1 多人实时协作编辑（WebSocket 软锁 + presence + 保存广播）
  - ✅ T13.2 问卷版本历史（snapshot / diff / restore）
  - ✅ T13.3 权限控制与邀请链接（owner/editor/viewer + token 邀请 + 乐观锁冲突弹窗）
- ⬜ 测量工具箱开发 (task-1778697793535-z59yy3) P3 | 2027-06-01
- ⬜ API 开放平台与导出完善 (task-1778697793535-l6bjj2) P3 | 2027-07-01
- ⬜ Beta 公测与学术合作试点 (task-1778697793535-aw64h0) P1 | 2027-08-01
- ⬜ 商业模式验证与定价策略确定 (task-1778697793535-bvf12w) P2 | 2027-09-01

## 商业模式

- 学术用户: 基础免费/低价（学生半价，教师七折）
- 企业用户: 分档订阅（基础版 ¥数千/年，高级版 ¥数万/年）
- 按项目付费: 单次调查按响应量计费
- 增值服务: 样本配额、定制分析
