# 实时协作编辑 — 运行与验证指南

> **任务**: Phase 3 · Task 13.1 多人实时协作编辑
> **协议层**: WebSocket（presence + focus 软锁 + 保存广播）
> **编辑层冲突仲裁**: 沿用 T13.3 已有的乐观锁（`expected_version` + 409）

## 架构一览

```
+---------------+         +-------------------+        +---------+
| SurveyCreator | ←onSel→ | SurveyDesignerPage | ←ws→ |         |
| (SurveyJS)    |         |  + useCollabSocket |       |         |
+---------------+         +-------------------+        |         |
                                  |                    |         |
                                  |   PUT /surveys     | FastAPI |
                                  |   (X-Collab-Conn)  |  + WS   |
                                  v                    |         |
                          +-----------------+           |         |
                          | ConnectionMgr   | ↔broadcast|         |
                          | (in-process)    |           |         |
                          +-----------------+           +---------+
```

- 单进程 in-memory 连接表；多 worker 时把它换成 Redis pub/sub，public API 不变
- 同一用户开两个 tab 会有两条连接，UI 按 `user_id` 去重展示
- focus 锁 60s TTL，前端心跳每 30s 续期，断网最多 60s 后自动释放

## 协议（JSON）

| 方向 | type | payload |
|---|---|---|
| C→S | `auth` | `{token: "<JWT>"}` （首帧必发） |
| C→S | `focus.acquire` | `{question_id: "..."}` |
| C→S | `focus.release` | `{}` |
| C→S | `heartbeat` | `{}` |
| S→C | `auth.ok` | `{connection_id, color}` |
| S→C | `presence.snapshot` | `{users: [...]}` |
| S→C | `presence.join` | `{user: {...}}` |
| S→C | `presence.leave` | `{user_id, connection_id}` |
| S→C | `focus.update` | `{connection_id, user_id, display_name, color, question_id, expires_at}` |
| S→C | `survey.saved` | `{version, actor_user_id, updated_at}` |

关闭码：

| 码 | 含义 |
|---|---|
| 4400 | 协议错误（首帧非 auth、JSON 格式错误） |
| 4401 | 鉴权失败（token 缺失/失效/账号停用） |
| 4403 | 无 survey 访问权限 |
| 4404 | 路由未匹配（survey 不存在不会返回 4404，按 4403 处理） |

前端 4401/4403 不重连；其他关闭走指数退避（1s → 30s）。

## HTTP 协同：避免回响

`PUT /api/v1/surveys/{id}` 与 `POST .../versions/{vid}/restore` 都接受请求头 `X-Collab-Connection-Id`，当存在时 `survey.saved` 广播会跳过该连接。前端 `useSaveSurvey` 在每次保存自动附带当前 socket 的 connection_id。

## 启动开发环境

最快路径用 docker-compose（PostgreSQL / Redis / API / Web 一起起来）：

```
cp .env.example .env   # 仅在没有 .env 时
docker compose up -d --build
```

服务起来后：

| 端口 | 用途 |
|---|---|
| 5173 | Vite dev server (前端) |
| 8000 | FastAPI (含 /api/v1/ws/...) |
| 5432 | PostgreSQL |
| 6379 | Redis |

Vite proxy 已开 `ws: true`，所以浏览器访问 `ws://localhost:5173/api/v1/ws/...` 会被转发到后端。

仅手工跑后端：

```
cd apps/api/core
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

## 手工验证（多窗口实测）

1. 起两个浏览器窗口（或一个普通 + 一个隐身）
2. 用两个不同账号登录，让 A 把 survey 共享给 B（owner → editor，沿用 T13.3 ShareDialog）
3. A、B 同时打开同一份 survey 的 designer
4. 期望看到：
   - 工具栏右侧出现两个头像气泡，状态徽章绿色（已连接）
   - A 点击 Q1，B 屏幕底部出现「A 正在编辑题目 Q1」横幅；A 头像下出现绿色小圆点
   - A 切换到 Q2，B 的横幅切到 Q2
   - A `Cmd+S` 保存，B 这边弹出 toast「协作者已保存新版本…」并自动拉取最新内容
   - A 在 ConflictDialog 也能看到 409 兜底（让 A、B 都改完都按保存，第二个会触发 409）
5. 关闭 A 的 tab，B 端头像消失

## 常见问题

| 现象 | 排查 |
|---|---|
| 头像始终灰色（idle） | 浏览器 console 是否有 WebSocket connection failed 错误；后端 `/api/v1/ws/...` 是否能直连（`websocat ws://localhost:8000/api/v1/ws/surveys/<id>`）；JWT 是否在登录后写入 localStorage |
| 头像黄色（reconnecting）不停 | 后端日志通常会写 `ws_loop_error`；常见是 access token 已过期；刷新页面让 auth store 拿新 token 后会自动重连 |
| focus 横幅不消失 | 检查心跳是否被代理掐断；超过 60s 后端 reaper 会强制释放，刷新另一个 tab 应能恢复 |
| 405 Method Not Allowed | 多半因为 reverse proxy 没开 ws：dev 改 `vite.config.ts` 的 `proxy.ws`，prod 在 nginx/traefik 配置 `Upgrade` 头转发 |

## 自动化测试

```
cd apps/api/core
pytest tests/test_collaboration_ws.py -k "not test_ws_auth_required"
```

13 个单测覆盖 ConnectionManager 状态机（presence、focus、broadcast、send 失败容忍、color 循环），不需要数据库。完整 WS 握手 smoke test（`test_ws_auth_required`）需要 PostgreSQL 在 5432 上运行，与现有 `test_distribution.py` 集成测试同样要求。

## 后续演进点

- 真正的 CRDT（Y.js / pycrdt）做到字段级同时编辑而非题目级软锁
- Redis pub/sub 把 ConnectionManager 改造为多 worker 兼容
- presence 加上鼠标光标精细位置（cursor 消息已在协议预留）
- focus 历史审计写到 `audit_logs`（用于复盘谁改过什么题）
