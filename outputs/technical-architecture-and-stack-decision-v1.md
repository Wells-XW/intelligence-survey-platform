# 技术架构设计与技术选型决策 v1.0

> **任务**: Phase 1 第三项 — 技术架构设计与技术选型决策 (task-1778697793535-vntvpp)
> **产出日期**: 2026-05-14
> **方法**: 多源网络检索（框架对比 / 架构案例 / 行业报告 / 技术文档）+ 竞品技术栈逆向 + 架构模式分析
> **状态**: 完成

---

## 目录

一、架构总览与核心原则
二、C4 架构模型（Context → Container → Component）
三、前端技术选型
四、后端技术选型
五、AI/ML 管线架构
六、数据存储选型
七、安全与合规架构
八、部署与运维架构
九、API 设计规范
十、开发工具链
十一、风险与缓解
十二、实施路线图

---

## 一、架构总览与核心原则

### 1.1 一句话架构定位

**双后端（FastAPI 核心 + Fastify 网关）+ React 前端 + PostgreSQL/Elasticsearch/MinIO 三层存储 + Docker/K8s 部署**，以 AI 管线为中轴的学术调查 SaaS 平台。

### 1.2 架构原则

| # | 原则 | 说明 | 来源 |
|---|------|------|------|
| P1 | **API First** | 所有功能通过 API 暴露，前端是 API 的消费者；支持第三方集成 | 产品定位（Phase 3 API 平台） |
| P2 | **PIPL/GDPR by Design** | 数据合规从架构层嵌入，非事后补救 | 合规刚需（PIPL 最高罚 5000 万） |
| P3 | **Modular Monolith First** | MVP 阶段模块化单体，避免过早微服务化 | CNCF 2025: 42% 企业在合并微服务回单体 |
| P4 | **AI 管线可观测** | 所有 LLM 调用记录 token 消耗、延迟、质量评分 | AI 成本控制 + 质量迭代 |
| P5 | **中文一等公民** | 全文搜索、NLP、UI 均深度支持中文 | 核心差异化 |
| P6 | **Offline-Capable Core** | 问卷填写支持离线（PWA），适用于现场调研场景 | 用户场景（田野调查） |

### 1.3 关键约束

| 约束 | 影响 |
|------|------|
| 个人项目，1-2 人开发 | 技术栈不宜过广，优先全栈 TypeScript/Python 双语言 |
| 初始预算有限 | 优先开源/自托管方案，避免高额云服务费 |
| 学术用户低容忍度 | 稳定性 > 功能丰富度，核心流程不能出错 |
| PIPL 数据本地化 | 中国用户数据必须存储在中国境内服务器 |
| 2026 年竞品 AI 化窗口 | 6 个月内必须有可用 MVP，12 个月形成差异化 |

---

## 二、C4 架构模型

### 2.1 Level 1: Context（系统上下文）

```mermaid
C4Context
    title 系统上下文图 — Intelligence Survey Platform

    Person(Researcher, "学术研究者", "博士生/教授/研究机构")
    Person(Respondent, "受访者", "填写问卷的参与者")
    
    System(ISPSystem, "Intelligence Survey Platform", "AI驱动的学术调查平台")
    
    System_Ext(LLM, "LLM API", "OpenAI / DeepSeek / Claude")
    System_Ext(CNKI, "CNKI API", "中国知网文献检索")
    System_Ext(PubMed, "PubMed / Semantic Scholar", "英文学术文献检索")
    System_Ext(Email, "邮件/短信服务", "问卷分发通知")
    System_Ext(WeChat, "微信生态", "问卷分发渠道")
    
    Rel(Researcher, "设计问卷、分析数据、导出报告", ISPSystem, "HTTPS")
    Rel(Respondent, "填写并提交问卷", ISPSystem, "HTTPS")
    Rel(ISPSystem, "调用AI生成/分析/质控", LLM, "HTTPS/API Key")
    Rel(ISPSystem, "检索文献/量表", CNKI, "HTTPS/API")
    Rel(ISPSystem, "检索英文学术文献", PubMed, "HTTPS/API")
    Rel(ISPSystem, "发送问卷邀请和提醒", Email, "SMTP/API")
    Rel(ISPSystem, "微信内问卷分发", WeChat, "HTTPS/JS-SDK")
```

### 2.2 Level 2: Container（容器视图）

```mermaid
C4Container
    title 容器视图 — Intelligence Survey Platform

    Person(Researcher, "学术研究者", "Web/Mobile")
    Person(Respondent, "受访者", "Web/Mobile/PWA")
    
    Container_Boundary(Frontend, "前端") {
        Container(WebApp, "Web Application", "React 19 + TypeScript", "问卷设计器 / 分析仪表盘 / 管理后台")
        Container(SurveyApp, "Survey Taking App", "React + PWA", "问卷填写界面，支持离线")
        Container(AdminApp, "Admin Dashboard", "React", "用户管理 / 系统监控 / 计费")
    }
    
    Container_Boundary(APIGateway, "API 网关") {
        Container(FastifyGW, "API Gateway", "Fastify + TypeScript", "路由 / 认证 / 限流 / 日志")
    }
    
    Container_Boundary(CoreBackend, "核心后端") {
        Container(FastAPI, "Core API", "FastAPI + Python 3.12", "问卷CRUD / 用户管理 / 数据导出")
        Container(AIService, "AI Service", "FastAPI + Celery", "AI生成 / 分析 / 质控 / 追问")
        Container(SearchService, "Search Service", "FastAPI", "文献检索 / 知识库 / 量表检索")
        Container(AnalyticsService, "Analytics Service", "FastAPI + Celery", "统计分析 / 信效度 / 报告生成")
    }
    
    Container_Boundary(DataStore, "数据存储") {
        ContainerDb(PostgreSQL, "PostgreSQL 16", "关系型数据库", "用户 / 问卷 / 回复 / 项目")
        Container(Elasticsearch, "Elasticsearch 9.x", "搜索引擎", "全文搜索 / 分析 / 向量搜索")
        Container(MinIO, "MinIO", "对象存储", "文件附件 / 导出文件 / 备份")
        Container(Redis, "Redis 7", "缓存/队列", "Session / 缓存 / Celery Broker")
    }
    
    Container_Boundary(External, "外部服务") {
        System_Ext(LLM, "LLM API", "GPT-4o / DeepSeek-R1 / Claude")
        System_Ext(Literature, "文献API", "CNKI / PubMed / Semantic Scholar")
    }
    
    Rel(Researcher, "使用", WebApp, "HTTPS")
    Rel(Respondent, "填写", SurveyApp, "HTTPS")
    Rel(WebApp, "API请求", FastifyGW, "HTTPS/REST")
    Rel(SurveyApp, "API请求", FastifyGW, "HTTPS/REST")
    Rel(FastifyGW, "路由", FastAPI, "内部gRPC/HTTP")
    Rel(FastifyGW, "路由", AIService, "内部gRPC/HTTP")
    Rel(FastifyGW, "路由", SearchService, "内部gRPC/HTTP")
    Rel(FastifyGW, "路由", AnalyticsService, "内部gRPC/HTTP")
    Rel(FastAPI, "读写", PostgreSQL, "TCP/SQL")
    Rel(SearchService, "查询", Elasticsearch, "TCP/HTTP")
    Rel(AIService, "调用", LLM, "HTTPS")
    Rel(SearchService, "调用", Literature, "HTTPS")
```

### 2.3 Level 3: Component（核心问卷设计器组件视图）

```mermaid
C4Component
    title 组件视图 — 问卷设计器 (Survey Designer)

    Container_Boundary(Designer, "Survey Designer SPA") {
        Component(Dashboard, "Dashboard", "React", "项目列表 / 模板市场 / 最近编辑")
        Component(Editor, "Editor Canvas", "React + dnd-kit", "拖拽式问卷编辑主界面")
        Component(Toolbox, "Question Toolbox", "React", "题型面板 / 量表库 / 模板")
        Component(PropertyPanel, "Property Panel", "React", "题目属性编辑 / 逻辑设置 / 校验规则")
        Component(AIAssistant, "AI Assistant Panel", "React + SSE", "AI生成 / 建议 / 质量检测结果")
        Component(Preview, "Preview Panel", "React", "实时预览（桌面+移动端）")
        Component(LogicEditor, "Logic Editor", "React", "条件分支 / 跳题 / 配额管理")
    }
    
    Container_Boundary(API, "Backend Services") {
        Component(SurveyAPI, "Survey CRUD API", "FastAPI", "问卷的创建/读取/更新/删除")
        Component(QuestionBankAPI, "Question Bank API", "FastAPI", "量表库 / 认证题库")
        Component(AIGenAPI, "AI Generation API", "FastAPI + Celery", "AI问卷生成 / 题项建议")
        Component(ValidationAPI, "Validation API", "FastAPI", "学术规范检查 / 偏差检测")
    }
    
    Rel(Editor, "拖拽操作", Toolbox, "组件通信")
    Rel(Editor, "选中题目→", PropertyPanel, "状态同步(Zustand)")
    Rel(Editor, "调用AI", AIAssistant, "SSE流式")
    Rel(AIAssistant, "生成请求→", AIGenAPI, "HTTPS/SSE")
    Rel(PropertyPanel, "保存→", SurveyAPI, "HTTPS/REST")
    Rel(Editor, "自动保存→", SurveyAPI, "HTTPS/REST")
    Rel(ValidationAPI, "检查→", AIGenAPI, "内部调用")
```

---

## 三、前端技术选型

### 3.1 核心技术栈

| 技术 | 版本 | 角色 | 选型理由 |
|------|------|------|---------|
| **React** | 19.x | UI 框架 | 生态最成熟，SurveyJS 原生支持，招聘容易 |
| **TypeScript** | 5.x | 类型系统 | 复杂问卷逻辑必需类型安全 |
| **Vite** | 6.x | 构建工具 | 比 Webpack 快 10-100x，ESM 原生 |
| **React Router** | 7.x | 路由 | 标准选择，支持数据加载 |
| **TanStack Query** | 5.x | 服务端状态 | 缓存/重试/乐观更新，减少 80% 手写状态管理代码 |
| **Zustand** | 5.x | 客户端状态 | 轻量（<1KB），比 Redux 简洁，适合编辑器复杂状态 |
| **Tailwind CSS** | 4.x | 样式框架 | 与 shadcn/ui 深度绑定，原子化 CSS 主流 |
| **shadcn/ui** | latest | UI 组件库 | 2026 年 React UI 库首选：复制源码而非 npm 依赖，完全可控 |

### 3.2 UI 组件库选型对比

| 维度 | shadcn/ui | Ant Design | MUI | 胜出 |
|------|-----------|------------|-----|------|
| **哲学** | 复制源码，完全控制 | 企业级开箱即用 | Material Design 规范 | shadcn/ui（学术产品需要独特视觉语言） |
| **体积** | 按需，无额外依赖 | 大（~1.2MB gzip） | 大（~300KB gzip） | shadcn/ui |
| **定制性** | 极高（源码在手） | 中（token 系统） | 高（theme object） | shadcn/ui |
| **可访问性** | Radix UI 原语（优秀） | 一般 | 良好 | shadcn/ui |
| **中文支持** | 无特殊优化（但无碍） | 优秀（阿里出品） | 一般 | Ant Design（仅限中文本地化组件如日期选择器） |
| **Tailwind 集成** | 原生 | 不兼容 | 需额外插件 | shadcn/ui |
| **学术风设计** | 极佳（中性简约） | 企业/后台感强 | Google 风，不学术 | shadcn/ui |

**决策**: **shadcn/ui 为主**，个别复杂组件（如中文本地化 DatePicker、复杂表格）可复用 Ant Design 对应组件。

### 3.3 问卷设计器技术选型

| 方案 | 描述 | 优点 | 缺点 | 决策 |
|------|------|------|------|------|
| **SurveyJS** | 开源 React 问卷构建器 | 成熟（8年）、React 原生、JSON Schema、Theme Editor、MIT 协议 | 商业功能需付费（Survey Creator $499/开发者） | ✅ **MVP 首选** |
| **自研 dnd-kit** | 基于 dnd-kit 自建拖拽编辑器 | 完全控制、无授权费 | 开发量大（估计 3-6 个月） | ⚠️ **长期方向** |
| **React Form Builder (Coltorapps)** | 开源拖拽表单构建器 | 轻量、基于 shadcn/ui | 不成熟、功能少 | ❌ |
| **react-jsonschema-form** | JSON Schema → 表单渲染 | 标准化、成熟 | 非问卷专用、UI 受限 | ❌ |

**决策**: 
- **MVP (Phase 1)**: 采用 **SurveyJS** 社区版作为问卷设计器基础，节省 3-6 个月开发时间
- **差异化层**: 在 SurveyJS 之上自定义 AI 助手面板、学术规范检查面板、量表库侧边栏
- **Phase 2+**: 当差异化需求超出 SurveyJS 扩展能力时，基于 dnd-kit 自研问卷编辑器，实现完全定制化

### 3.4 PWA 离线问卷填写

| 技术 | 用途 |
|------|------|
| **Workbox** | Service Worker 缓存策略 |
| **IndexedDB (Dexie.js)** | 离线回复暂存 |
| **Background Sync** | 网络恢复后自动同步 |

### 3.5 前端项目结构

```
frontend/
├── apps/
│   ├── web/                  # 研究者 Web 应用
│   │   ├── src/
│   │   │   ├── features/     # 功能模块
│   │   │   │   ├── survey-designer/  # 问卷设计器
│   │   │   │   ├── analytics/        # 数据分析
│   │   │   │   ├── sample/           # 样本管理
│   │   │   │   └── project/          # 项目管理
│   │   │   ├── components/   # 共享组件
│   │   │   ├── hooks/        # 共享 Hooks
│   │   │   ├── stores/       # Zustand stores
│   │   │   └── lib/          # 工具函数
│   │   └── ...
│   ├── survey/               # 问卷填写应用（独立部署）
│   │   └── src/
│   └── admin/                # 管理后台
├── packages/
│   ├── ui/                   # shadcn/ui 组件库
│   ├── shared/               # 共享类型、常量
│   └── survey-engine/        # 问卷渲染引擎（与 SurveyJS 交互）
└── ...
```

---

## 四、后端技术选型

### 4.1 双后端架构

```
┌──────────────────────────────────────┐
│         Fastify API Gateway           │
│  (Node.js 24 + TypeScript)           │
│  ─ 认证/授权 (JWT + RBAC)            │
│  ─ 限流 (rate-limit)                 │
│  ─ 请求日志/审计                      │
│  ─ WebSocket (实时通知)               │
│  ─ API 版本管理                       │
└──────────┬───────────────────────────┘
           │
    ┌──────┴──────┬──────────┬──────────────┐
    ▼             ▼          ▼              ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐
│ FastAPI │ │ FastAPI │ │ FastAPI │ │ FastAPI  │
│ Core    │ │ AI Svc  │ │ Search  │ │ Analytics│
│ (问卷   │ │ (AI生成 │ │ (文献   │ │ (统计分析│
│  CRUD)  │ │ /分析)  │ │ 检索)   │ │ /信效度) │
└────┬────┘ └────┬────┘ └────┬────┘ └────┬─────┘
     │          │          │           │
     ▼          ▼          ▼           ▼
┌──────────────────────────────────────────┐
│            Data Layer                     │
│  PostgreSQL | Elasticsearch | MinIO | Redis│
└──────────────────────────────────────────┘
```

### 4.2 为什么是 Fastify 而非 Express？

| 维度 | Express | Fastify | 结论 |
|------|---------|---------|------|
| **性能** | 基线 | **5x 更快** | Fastify 大胜 |
| **插件系统** | 中间件（无序） | 封装插件（有序、可组合） | Fastify 更优 |
| **Schema 验证** | 需第三方（joi/zod） | 内置 JSON Schema | Fastify |
| **TypeScript** | 需 @types/express | 原生支持 | Fastify |
| **可观测性** | 需手动集成 | 内置 metrics/logging | Fastify |
| **2026 社区共识** | "不再适合新项目" | **Node.js 新项目首选** | Fastify |
| **生态成熟度** | 最大 | 快速增长 | Express（但 Fastify 已够用） |

**决策**: **Fastify** 作为 API 网关。2026 年 Express 已被行业共识认为不适合新项目（Fastify 5x 更快，Node.js 20 即将 EOL）。

**注意**: 原始 project.md 中提到 "Node.js Express"，本报告建议修正为 **Node.js Fastify**。

### 4.3 Python 后端核心 — FastAPI

| 维度 | FastAPI | Django | Flask | 结论 |
|------|---------|--------|-------|------|
| **AI/ML 集成** | 原生（Python 生态） | Python 生态 | Python 生态 | 三者均可，FastAPI 异步最优 |
| **性能** | 高（Starlette + Uvicorn） | 中（同步 ORM） | 低 | FastAPI |
| **自动 API 文档** | ✅ OpenAPI + Swagger | 需 DRF 扩展 | 需扩展 | FastAPI |
| **类型安全** | Pydantic v3（原生） | 需 mypy 插件 | 无 | FastAPI |
| **异步支持** | 原生 async/await | 3.1+ 支持但仍重 | 有限 | FastAPI |
| **GitHub Stars** | 88,000+（追赶 Django） | ~80,000 | ~68,000 | 基本持平 |
| **LLM 生态** | LangChain / LlamaIndex 原生集成 | 支持但非最优 | 支持 | FastAPI |
| **学习曲线** | 低 | 高 | 低 | FastAPI |

**决策**: **FastAPI** 作为核心后端。Python 在 AI/ML 领域不可替代，FastAPI 是 2026 年 Python API 框架首选。

### 4.4 异步任务队列

| 方案 | 适用场景 | 优势 | 劣势 |
|------|---------|------|------|
| **Celery + Redis** | 重量级异步任务 | 成熟（15年）、分布式、监控（Flower） | 配置复杂、Redis 依赖 |
| **FastAPI BackgroundTasks** | 轻量快速任务 | 零配置、内置 | 无持久化、无重试、进程内 |
| **ARQ** | 中量级任务 | Python 原生、简单 | 仅 Redis、社区小 |
| **RQ** | 中量级任务 | 简单易用 | 仅 Redis、功能少于 Celery |

**决策**: 
- **轻量任务**（发送邮件、日志写入）: FastAPI `BackgroundTasks`
- **重量任务**（AI 问卷生成、大规模数据导出、统计分析）: **Celery + Redis**
- **AI 任务特殊性**: AI 生成类任务需要支持 SSE（Server-Sent Events）实时进度推送，Celery 任务通过 Redis Pub/Sub 或 WebSocket 回传进度

### 4.5 内部服务通信

| 阶段 | 方案 | 理由 |
|------|------|------|
| **MVP** | HTTP REST（内部 localhost） | 简单、可调试、无额外基础设施 |
| **Phase 2+** | gRPC（Protocol Buffers） | 高性能、强类型契约、适合多服务 |

---

## 五、AI/ML 管线架构

### 5.1 多模型路由策略

```mermaid
flowchart TD
    Request["AI 请求"] --> Router{"模型路由<br/>(任务类型+成本)"}
    
    Router -->|"问卷生成<br/>(质量优先)"| GPT4["GPT-4o<br/>(高质量/贵)"]
    Router -->|"问卷生成<br/>(中文优先)"| DeepSeek["DeepSeek-R1<br/>(中文强/便宜)"]
    Router -->|"文献分析<br/>(长上下文)"| Claude["Claude Opus 4<br/>(200K上下文)"]
    Router -->|"质量检测<br/>(批量/低成本)"| Mini["GPT-4.5 mini<br/>(便宜/快速)"]
    Router -->|"敏感数据<br/>(本地处理)"| Local["本地模型<br/>(数据不出境)"]
    
    GPT4 --> Response["AI Response"]
    DeepSeek --> Response
    Claude --> Response
    Mini --> Response
    Local --> Response
    
    Response --> Audit["审计日志<br/>(token/延迟/质量)"]
    Audit --> Cache["Response Cache<br/>(相同提示去重)"]
```

### 5.2 LLM 提供商对比（2026年中）

| 模型 | 输入 $/1M tokens | 输出 $/1M tokens | 上下文窗口 | 中文质量 | 推荐用途 |
|------|-----------------|-----------------|-----------|---------|---------|
| **GPT-4o** | $2.50 | $10.00 | 128K | ⭐⭐⭐⭐ | 高质量英文生成 |
| **GPT-4.5 mini** | $0.15 | $0.60 | 128K | ⭐⭐⭐ | 批量检测、低成本任务 |
| **Claude Opus 4** | $15.00 | $75.00 | 200K | ⭐⭐⭐ | 长文献分析 |
| **Claude Sonnet 4** | $3.00 | $15.00 | 200K | ⭐⭐⭐ | 中档推理 |
| **DeepSeek-R1** | ¥1.00 | ¥4.00 (~$0.14/$0.54) | 64K | ⭐⭐⭐⭐⭐ | **中文问卷生成首选** |
| **DeepSeek-V3** | ¥0.50 | ¥2.00 (~$0.07/$0.27) | 64K | ⭐⭐⭐⭐⭐ | 中文批量处理 |
| **本地模型** | 0 | 0 (算力成本) | 取决于 GPU | ⭐⭐⭐ | 敏感数据场景 |

**策略**: 
- **中文问卷生成**: DeepSeek-R1 作为主力（成本仅为 GPT-4o 的 5%，中文质量更高）
- **英文文献分析**: Claude Opus 4（200K 上下文适合长论文）
- **质量检测/批量**: GPT-4.5 mini（成本极低）
- **敏感数据（PIPL）**: 本地部署 Qwen3 或 Yi-Large

### 5.3 AI 服务内部架构

```mermaid
flowchart LR
    subgraph "AI Service"
        Orchestrator["AI Orchestrator<br/>(任务分解+模型路由)"]
        
        subgraph "Prompts"
            SysPrompts["System Prompts<br/>(方法论约束)"]
            FewShot["Few-Shot Examples<br/>(学术规范示例)"]
        end
        
        subgraph "Quality Gates"
            SQP["SQP 评估<br/>(问卷质量)"]
            SQRA["SQRA 评估<br/>(回复分析)"]
            BiasCheck["Bias Detection<br/>(偏差检测)"]
        end
        
        subgraph "Output Processors"
            Formatter["问卷格式化<br/>(JSON Schema)"]
            Citationer["引用注入<br/>(文献格式)"]
            Translator["中文润色"]
        end
    end
    
    Orchestrator --> GPT4 & DeepSeek & Claude & Mini
    SysPrompts --> Orchestrator
    FewShot --> Orchestrator
    Orchestrator --> SQP & SQRA & BiasCheck
    SQP & SQRA & BiasCheck --> Formatter & Citationer & Translator
```

**关键设计**:
1. **System Prompt 模板化**: 问卷生成的 System Prompt 注入学术方法论约束（AAPOR 标准、信效度要求、PIPL 合规）
2. **Few-Shot 示例库**: 预置各学科（心理学、社会学、教育学、管理学）的高质量问卷示例
3. **输出后处理**: AI 生成的问卷自动经过 JSON Schema 验证、引用格式标准化、中文术语规范化
4. **SQP/SQRA 评估**: 集成欧洲 SQP 编码系统和 SQRA 框架，对 AI 生成的问卷进行自动质量评分

### 5.4 AI 功能管线

```
用户输入 (自然语言RQ)
  → AI Orchestrator (分解任务)
    → [并行]
      ├─→ LLM: 文献检索 → 量表提取
      ├─→ LLM: 问卷结构生成 (维度→指标→题项)
      └─→ LLM: 方法论建议 (研究方法→样本→分析计划)
    → [汇合]
  → Quality Gates:
      ├─→ SQP: 题目质量评分
      ├─→ Bias Detection: 引导性/双管/歧义检测
      ├─→ Reliability Sim: 基于历史数据的信度预估
      └─→ PIPL Check: 敏感信息识别
  → 问卷 JSON Assembly
  → SurveyJS Renderer (前端实时预览)
```

---

## 六、数据存储选型

### 6.1 存储矩阵

| 存储 | 角色 | 数据类型 | 选型理由 |
|------|------|---------|---------|
| **PostgreSQL 16** | 主数据库 | 用户、项目、问卷结构、回复、权限 | ACID、JSONB 灵活 Schema、PGVector 可选、生态最成熟 |
| **Elasticsearch 9.x** | 搜索引擎 | 问卷全文、回复文本、文献索引、分析聚合 | 中文分词优秀（IK Analyzer）、聚合分析、向量搜索（HNSW + BBQ）、9.x 内存降 95% |
| **MinIO** | 对象存储 | 导出文件（PDF/Excel/SPSS）、上传附件、备份 | S3 兼容、自托管无出口费、性能优秀 |
| **Redis 7** | 缓存/队列 | Session、热点数据缓存、Celery Broker、限流计数 | 标准选择，支持持久化 |

### 6.2 为什么是 Elasticsearch 而非纯 PostgreSQL 搜索？

| 维度 | PostgreSQL Full-Text | Elasticsearch |
|------|---------------------|---------------|
| **中文分词** | 需手动配置（zhparser） | IK Analyzer 开箱即用 |
| **搜索性能** | 大表慢（12s+ for 2.8TB 数据） | 亚秒级（sub-20ms） |
| **聚合分析** | SQL GROUP BY | Aggregation Framework（强力 100x） |
| **向量搜索** | pgvector 扩展 | 原生 HNSW + BBQ 量化（95% 内存节省） |
| **运营复杂度** | 无额外运维 | 需独立集群 |
| **开源协议** | PostgreSQL License | Elastic License (9.x，有限制) |

**决策**: 
- **结构化业务数据**（用户、项目、权限）→ PostgreSQL
- **问卷内容搜索 + 回复文本分析 + 分析聚合** → Elasticsearch 9.x
- **MVP 阶段可选**: 如果运维资源极度有限，可先用 PostgreSQL `pgvector` + `zhparser` 替代 Elasticsearch，Phase 2 再迁移

### 6.3 MinIO 选型注意（2026年重要变化）

**关键事件**: MinIO 在 2025-2026 年间将管理控制台从社区版移除，仅保留只读对象浏览器。这对自托管运维有显著影响。

| 替代方案 | 优点 | 缺点 | MVP 推荐 |
|---------|------|------|---------|
| **MinIO** (仍可选) | 高性能、S3 兼容、社区大 | Console 移除需 CLI 管理 | ⚠️ |
| **Garage** | 轻量（Rust 编写）、Apache 2.0、完整 Web UI | S3 功能覆盖度低于 MinIO（无 ACL/Policy） | ✅ **MVP 推荐** |
| **SeaweedFS** | 功能全、Apache 2.0、适合小文件 | 运维复杂 | ⚠️ |
| **AWS S3** | 零运维 | 出口费、成本不可控 | ❌ |

**决策**: 
- **MVP 阶段**: **Garage**（轻量、真正开源、有 Web UI），满足问卷附件和导出文件存储需求
- **Phase 2+**: 若需要完整 S3 API（ACL、Bucket Policy、Versioning），迁移到 MinIO

### 6.4 PostgreSQL 核心 Schema（简化版）

```sql
-- 核心实体关系

-- 用户与权限
users (id, email, role, institution, subscription_tier, pipi_region)
projects (id, owner_id, title, methodology, status, created_at)

-- 问卷结构 (JSONB 存储灵活性 + 关系型保证约束)
surveys (id, project_id, title, schema_jsonb, version, status)
survey_questions (id, survey_id, question_type, content, options_jsonb, 
                  validation_rules, logic_rules, position)
scale_library (id, name, discipline, cronbach_alpha, items_jsonb, citations)

-- 回复 (时序分区表，按月份分区)
responses (id, survey_id, respondent_id, answers_jsonb, 
           started_at, completed_at, duration_seconds, quality_score)
response_quality_flags (response_id, flag_type, severity, detection_method)

-- AI 审计
ai_call_logs (id, user_id, model, prompt_hash, tokens_in, tokens_out, 
              latency_ms, cost_cents, quality_score, created_at)

-- PIPL 合规
consent_records (id, respondent_id, survey_id, consent_type, 
                 ip_address_hash, consented_at)
data_deletion_requests (id, user_id, status, requested_at, completed_at)
sensitive_data_log (id, survey_id, field_path, data_category, 
                    protection_level)
```

---

## 七、安全与合规架构

### 7.1 PIPL 合规架构要求

```mermaid
flowchart TD
    subgraph "数据采集层"
        Consent["知情同意管理<br/>(模板+签署+记录)"]
        Minimize["最小化检测<br/>(过度收集警告)"]
        Sensitive["敏感信息识别<br/>(单独同意触发)"]
    end
    
    subgraph "数据存储层"
        Isolation["数据分区<br/>(中国/境外用户隔离)"]
        Encrypt["加密<br/>(传输TLS+存储AES-256)"]
        Anonymize["去标识化<br/>(分析数据集)"]
    end
    
    subgraph "数据管理层"
        Access["数据主体权利<br/>(查阅/更正/删除/导出)"]
        Audit["审计日志<br/>(完整不可篡改)"]
        Retention["保留策略<br/>(自动清理到期数据)"]
    end
    
    subgraph "跨境传输层"
        Assess["安全评估<br/>(自动风险分级)"]
        SCC["标准合同条款<br/>(自动生成)"]
        LocalFirst["本地化优先<br/>(中国用户数据不出境)"]
    end
    
    Consent --> Isolation
    Minimize --> Encrypt
    Sensitive --> Anonymize
    Isolation --> Access
    Encrypt --> Audit
    Anonymize --> Retention
    Access --> Assess
    Audit --> SCC
    Retention --> LocalFirst
```

### 7.2 安全技术实现

| 层 | 技术 | 说明 |
|----|------|------|
| **传输安全** | TLS 1.3 | 全站 HTTPS |
| **存储加密** | AES-256-GCM | 数据库加密 + 文件加密 |
| **认证** | JWT (access 15min + refresh 7d) | OAuth2 兼容，支持 ORCID 登录 |
| **授权** | RBAC (Owner/Admin/Editor/Viewer) | 项目级 + 问卷级双层权限 |
| **API 安全** | Rate Limiting + CORS + CSP | Fastify 插件实现 |
| **审计日志** | 不可篡改日志（append-only 表） | 满足 PIPL 第 53 条 |
| **数据脱敏** | 动态脱敏（基于角色） | 导出时自动脱敏 IP/个人信息 |
| **漏洞扫描** | OWASP ZAP + Dependabot | CI/CD 集成 |

### 7.3 GDPR 额外要求（国际版）

| 要求 | 实现 |
|------|------|
| DPO（数据保护官） | 可配置 DPO 联系信息 |
| DPIA（数据保护影响评估） | 问卷设计阶段自动生成 DPIA 草稿 |
| Cookie Consent | 前端 Cookie 同意横幅 |
| Right to be Forgotten | 一键数据删除（含所有关联数据） |

---

## 八、部署与运维架构

### 8.1 部署拓扑

```mermaid
flowchart TD
    subgraph "DNS + CDN"
        Cloudflare["Cloudflare<br/>(CDN + DDoS + WAF)"]
    end
    
    subgraph "Kubernetes Cluster"
        subgraph "Ingress"
            Nginx["Nginx Ingress<br/>(TLS Termination)"]
        end
        
        subgraph "Frontend Pods"
            WebPod["Web App<br/>(React SPA)"]
            SurveyPod["Survey App<br/>(PWA)"]
        end
        
        subgraph "Backend Pods"
            GatewayPod["API Gateway<br/>(Fastify ×2)"]
            CorePod["Core API<br/>(FastAPI ×3)"]
            AIPod["AI Service<br/>(FastAPI ×2)"]
            SearchPod["Search Service<br/>(FastAPI ×1)"]
            AnalyticsPod["Analytics Service<br/>(FastAPI ×1)"]
        end
        
        subgraph "Workers"
            CeleryWorker["Celery Worker<br/>(×3, AI任务)"]
            CronJobs["CronJobs<br/>(报告/清理)"]
        end
    end
    
    subgraph "Data Services (StatefulSet)"
        PG[("PostgreSQL<br/>Primary + Replica")]
        ES[("Elasticsearch<br/>3-Node Cluster")]
        MinIO[("MinIO/Garage<br/>Single Node")]
        Redis[("Redis<br/>Sentinel")]
    end
    
    Cloudflare --> Nginx
    Nginx --> WebPod & SurveyPod
    Nginx --> GatewayPod
    GatewayPod --> CorePod & AIPod & SearchPod & AnalyticsPod
    CorePod --> PG & ES & MinIO
    AIPod --> Redis & PG
    SearchPod --> ES
    AnalyticsPod --> PG & ES
    CeleryWorker --> Redis & PG & MinIO
```

### 8.2 MVP 阶段简化部署

MVP 阶段（个人开发者，预算有限）建议先跳过 Kubernetes，采用更简单的方案：

```
Phase 1 (MVP):
  Docker Compose 单机部署
  ┌──────────────────────────────────────┐
  │  Nginx (反向代理 + 静态文件)          │
  │  ├─ Web App (React 静态文件)          │
  │  ├─ Survey App (PWA 静态文件)         │
  │  └─ API Gateway (Fastify :3000)      │
  │      ├─ Core API (FastAPI :8000)     │
  │      ├─ AI Service (FastAPI :8001)   │
  │      ├─ Celery Worker                │
  │      ├─ PostgreSQL :5432             │
  │      ├─ Elasticsearch :9200          │
  │      ├─ Garage/MinIO :9000           │
  │      └─ Redis :6379                  │
  └──────────────────────────────────────┘

Phase 2+ (规模化):
  Kubernetes (GKE/AKS/EKS 或自托管 K3s)
```

### 8.3 CI/CD 流水线

```mermaid
flowchart LR
    Git["GitHub<br/>Push/PR"] --> Lint["Lint & Type Check<br/>(black, pylint, eslint, tsc)"]
    Lint --> Test["Tests<br/>(pytest, vitest, E2E Playwright)"]
    Test --> Build["Build<br/>(Docker Images)"]
    Build --> Registry["Container Registry<br/>(GitHub Container Registry)"]
    Registry --> Deploy["Deploy<br/>(ArgoCD / Docker Compose)"]
    Deploy --> Monitor["Monitor<br/>(Prometheus + Grafana)"]
```

### 8.4 可观测性栈

| 组件 | 技术 | 用途 |
|------|------|------|
| **Metrics** | Prometheus + Grafana | 系统指标（CPU/内存/QPS/延迟） |
| **Logging** | Loki + Promtail | 结构化日志聚合 |
| **Tracing** | OpenTelemetry + Jaeger | 分布式追踪（Phase 2+） |
| **Alerting** | Grafana AlertManager | 异常告警（错误率/延迟/LLM成本） |
| **AI 专属** | 自建 LLM Cost Dashboard | Token 消耗、模型质量、缓存命中率 |

---

## 九、API 设计规范

### 9.1 API 风格

| 维度 | 决策 |
|------|------|
| **风格** | RESTful（主）+ SSE（AI 流式） |
| **版本** | URL 前缀 `/api/v1/` |
| **格式** | JSON（请求/响应） |
| **文档** | OpenAPI 3.1（FastAPI 自动生成）+ Swagger UI |
| **认证** | Bearer JWT |
| **分页** | Cursor-based（`page_token`） |
| **错误** | RFC 7807 Problem Details |

### 9.2 核心 API 端点设计

```
# 问卷管理
POST   /api/v1/surveys                    # 创建问卷
GET    /api/v1/surveys                    # 问卷列表（分页、搜索、筛选）
GET    /api/v1/surveys/{id}               # 问卷详情
PUT    /api/v1/surveys/{id}               # 更新问卷
DELETE /api/v1/surveys/{id}               # 删除问卷
POST   /api/v1/surveys/{id}/publish       # 发布问卷
POST   /api/v1/surveys/{id}/close         # 关闭问卷

# AI 功能
POST   /api/v1/ai/generate-survey         # AI 生成问卷（SSE 流式返回进度）
POST   /api/v1/ai/generate-questions      # AI 生成题项
POST   /api/v1/ai/check-quality           # AI 质量检测
POST   /api/v1/ai/suggest-methodology     # AI 方法论建议
POST   /api/v1/ai/analyze-open-ended      # AI 开放题分析

# 回复管理
POST   /api/v1/surveys/{id}/responses     # 提交回复
GET    /api/v1/surveys/{id}/responses     # 回复列表
GET    /api/v1/surveys/{id}/responses/export  # 导出回复

# 分析
GET    /api/v1/surveys/{id}/analytics/summary    # 摘要统计
GET    /api/v1/surveys/{id}/analytics/reliability # 信度分析
GET    /api/v1/surveys/{id}/analytics/cross-tab   # 交叉分析

# 知识库
GET    /api/v1/kb/search                  # 文献/量表搜索
GET    /api/v1/kb/scales                  # 量表库
GET    /api/v1/kb/scales/{id}             # 量表详情（含信效度历史数据）

# 合规
GET    /api/v1/compliance/pipi/consent-template  # 知情同意模板
GET    /api/v1/compliance/pipi/check-survey/{id} # PIPL 合规检查
```

### 9.3 SSE 流式协议（AI 生成）

```
POST /api/v1/ai/generate-survey
Content-Type: application/json

{
  "research_question": "...",
  "discipline": "psychology",
  "methodology": "quantitative_survey",
  "language": "zh-CN"
}

--- Response (SSE) ---
event: progress
data: {"stage": "literature_search", "progress": 0.2, "message": "正在检索相关量表..."}

event: progress
data: {"stage": "structure_generation", "progress": 0.4, "message": "正在生成问卷结构..."}

event: question
data: {"type": "new_question", "index": 1, "content": {...}}

event: quality_check
data: {"type": "warning", "message": "第3题可能存在双重否定，建议修改", "severity": "medium"}

event: complete
data: {"survey_id": "xxx", "stats": {"questions": 25, "estimated_duration": 480}}
```

---

## 十、开发工具链

### 10.1 代码管理

| 工具 | 用途 |
|------|------|
| **GitHub** | 代码托管 + Issues + Actions |
| **Conventional Commits** | 提交规范 (`feat:`, `fix:`, `docs:`) |
| **Changesets** | 版本管理和 Changelog |

### 10.2 代码质量

| 语言 | Linter | Formatter | Type Check | Test |
|------|--------|-----------|------------|------|
| **Python** | pylint | black (88行宽) | mypy (strict) | pytest + coverage |
| **TypeScript** | ESLint | Prettier | tsc --strict | Vitest |
| **YAML/Docker** | yamllint / hadolint | prettier | — | — |

### 10.3 Monorepo 管理

| 工具 | 用途 |
|------|------|
| **Turborepo** | 构建缓存、并行任务 |
| **pnpm** | 包管理（节省磁盘、严格依赖） |
| **Make** | 顶层任务编排（`make test`, `make build`） |

### 10.4 环境变量管理

```
# .env.example (提交到 Git，不含真实密钥)
DATABASE_URL=postgresql://user:pass@localhost:5432/survey
REDIS_URL=redis://localhost:6379/0
ELASTICSEARCH_URL=http://localhost:9200
MINIO_ENDPOINT=localhost:9000
OPENAI_API_KEY=sk-xxx
DEEPSEEK_API_KEY=sk-xxx
CLAUDE_API_KEY=sk-ant-xxx
JWT_SECRET=xxx
PIPL_REGION=cn  # cn | eu | global
```

---

## 十一、风险与缓解

| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|------|------|------|---------|
| R1 | **SurveyJS 社区版功能不足以支撑差异化** | 中 | 高 | 提前验证扩展点；预留 4 周自研问卷编辑器时间 |
| R2 | **LLM 成本失控** | 中 | 中 | 缓存相同提示、模型降级策略、成本预算告警 |
| R3 | **MinIO AGPL 协议风险** | 低 | 中 | 若仅内部使用无影响；若分发则用 Garage 替代 |
| R4 | **PIPL 合规缺陷导致罚款** | 低 | 极高 | Phase 1 就咨询数据合规律师；默认加密+最小化 |
| R5 | **Elasticsearch 运维复杂度超预期** | 中 | 中 | MVP 可先用 pgvector 替代；Phase 2 再评估 ES |
| R6 | **单点故障（单机 Docker Compose）** | 高 | 中 | 做每日自动备份；设计时就考虑无状态服务 |
| R7 | **竞品窗口期压缩** | 中 | 高 | MVP 聚焦 3 个核心差异化功能（AI+规范+合规） |
| R8 | **中文分词质量不足** | 低 | 中 | Elasticsearch IK Analyzer + 定期更新词库 |

---

## 十二、实施路线图

### 12.1 技术选型时间线

```
Phase 1 (M1-M5): 基础建设
  M1-M2: Docker Compose 开发环境搭建
         PostgreSQL Schema 设计 + 迁移脚本
         FastAPI + Fastify 基础框架
         React + shadcn/ui 项目脚手架
         CI/CD（GitHub Actions → Docker Compose 部署）
  
  M2-M4: SurveyJS 问卷设计器集成
         AI 问卷生成 MVP（DeepSeek-R1 + SSE 流式）
         JWT 认证 + RBAC 权限
         PWA 离线问卷填写
  
  M4-M5: 信效度分析（Cronbach α + 基础统计）
         PIPL 合规基础（知情同意 + 最小化检测）
         数据导出（SPSS/Excel/CSV）
         MVP 内部测试

Phase 2 (M6-M10): AI 集成
  M6-M8: 多模型路由 + 质量评估（SQP/SQRA）
         知识库集成（CNKI/PubMed/Semantic Scholar）
         量表库构建
         数据质控（AI 检测无效回复）
  
  M8-M10: 伦理合规引擎
          Kubernetes 迁移准备
          自研问卷编辑器 PoC

Phase 3 (M11-M18): 完善发布
  M11-M14: 样本管理 + 配额控制
          协作编辑（OT/CRDT）
          自研问卷编辑器（如需要）
  
  M14-M18: API 开放平台
          Beta 公测
          性能优化 + 安全审计
```

### 12.2 关键里程碑

| 里程碑 | 时间 | 交付物 |
|--------|------|--------|
| **M0: 环境就绪** | 第 1 月 | Docker Compose 一键启动全栈 |
| **M1: 问卷 MVP** | 第 3 月 | 可创建、编辑、发布、填写问卷 |
| **M2: AI MVP** | 第 5 月 | AI 生成问卷 + 质量检测 |
| **M3: MVP Release** | 第 6 月 | MVP 内部测试版就绪 |
| **M4: AI 全功能** | 第 10 月 | 全流程 AI 集成 |
| **M5: Beta Launch** | 第 18 月 | Beta 公测 |

---

## 十三、对原始 project.md 的技术栈修正建议

基于本报告的深入调研，建议对原始 project.md 中的技术栈进行以下修正：

| 原始选型 | 修正建议 | 理由 |
|---------|---------|------|
| Node.js **Express** | Node.js **Fastify** | 2026年 Express 已不适合新项目，Fastify 快 5x |
| ~~MinIO~~ | **Garage**（MVP） | MinIO 社区版移除 Console，Garage 更轻量且 Apache 2.0 |
| 未指定 UI 库 | **shadcn/ui** | 2026年 React UI 首选，完全可控，学术风中性 |
| 未指定状态管理 | **Zustand + TanStack Query** | 编辑器复杂状态 + 服务端缓存的黄金组合 |
| 未指定问卷编辑器 | **SurveyJS（MVP）→ 自研** | 先快速验证，再差异化自研 |
| 未指定任务队列 | **Celery + Redis** | AI 重量任务必需 |
| 未指定 LLM 策略 | **DeepSeek-R1 主力 + 多模型路由** | 中文强+成本低，是核心竞争力 |
| 未指定部署策略 | **Docker Compose（MVP）→ K8s** | 个人项目先简单后复杂 |

---

## 附录 A: 技术调研来源

### 框架对比
- Second Talent: "FastAPI vs Node.js: Usage, Speed and Popularity in 2026"
- Codelli: "FastAPI vs Node.js for your MVP in 2026"
- MarsDevs: "FastAPI vs Node.js for AI Backends in 2026"
- Reddit r/node: "Is Fastify a Good Choice in 2025?"
- Fastify Official: fastify.io

### 前端
- UI Bakery: "5 Top UI Component Libraries for React in 2026"
- Hashbyt: "19 Best React UI Component Libraries for SaaS (2026)"
- Developer Way: "React State Management in 2025: What You Actually Need"
- Syncfusion: "Top 5 React State Management Tools in 2026"
- SurveyJS: surveyjs.io

### AI/LLM
- Menlo VC: "2025 Mid-Year LLM Market Update"
- AI Conexio: "LLM Integration Technical Guide 2026"
- Langbase: "Top 5 LLM API providers in 2025"
- FastAPI+LLM SaaS Template Series (Towards AI)

### 基础设施
- CNCF 2025 Cloud Native Survey
- Docker: "2025 State of App Dev Report"
- Elasticsearch 9.x Release Notes
- MinIO Alternatives 2026 (Lucidity, ProductImpossible)

### 合规
- PIPL: personalinformationprotectionlaw.com
- Hawksford: "Understanding China's PIPL"
- GDPR vs PIPL Comparison (DataGuidance)

---

*本报告由 NIUMA/Newmax AI 通过多源网络检索和系统化架构分析生成，数据截至 2026-05-14。技术选型基于当前行业最佳实践，建议在实施前对关键依赖（SurveyJS、Garage）进行 PoC 验证。*
