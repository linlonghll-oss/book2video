# TEST：book2video 全量 Bug 测试报告

| 字段 | 内容 |
|------|------|
| **文档版本** | v1.0 |
| **状态** | Published |
| **作者** | 测试 |
| **创建日期** | 2026-07-28 |
| **最后更新** | 2026-07-28 |
| **关联项目** | book2video |
| **关联文档** | 无（基于当前代码库全量审查） |

---

**测试日期**: 2026-07-28
**项目路径**: `/Users/didi/WorkBuddy/Book/book2video/`
**技术栈**: FastAPI + SQLAlchemy(async) + SQLite (后端) / Next.js 14 + React 18 + TypeScript + Tailwind (前端)

---

## 测试概览

| 测试项 | 结果 |
|--------|------|
| Python 语法编译 | ✅ 全部通过 (14 文件) |
| TypeScript 类型检查 (`tsc --noEmit`) | ✅ 通过，0 错误 |
| ESLint 检查 | ❌ 2 Error + 6 Warning |
| 单元测试 | ⚠️ tests 目录为空，无任何测试用例 |
| 后端代码审查 | 发现 29 个问题 (P0: 2, P1: 6, P2: 12, P3: 9) |
| 前端代码审查 | 发现 30 个问题 (P0: 1, P1: 9, P2: 12, P3: 8) |

**Bug 总计: 59 个** (P0 致命: 3 / P1 严重: 15 / P2 一般: 24 / P3 建议: 17)

---

## ESLint 检查结果

### Errors (2)
| 文件 | 行号 | 规则 | 说明 |
|------|------|------|------|
| `SlideDrawer.tsx` | 9:3 | `@typescript-eslint/no-unused-vars` | `X` 导入但未使用 |
| `SlideDrawer.tsx` | 255:9 | `@typescript-eslint/no-unused-vars` | `scheduleSave` 赋值但未使用 |

### Warnings (6)
| 文件 | 行号 | 规则 | 说明 |
|------|------|------|------|
| `NoteDetail.tsx` | 283:6 | `react-hooks/exhaustive-deps` | useEffect 缺少依赖 `imageConfigs` |
| `NoteDetail.tsx` | 283:7 | `react-hooks/exhaustive-deps` | useEffect 依赖数组中有复杂表达式 |
| `NoteDetail.tsx` | 747:36 | `@next/next/no-img-element` | 应使用 `<Image />` 替代 `<img>` |
| `NoteDetail.tsx` | 747:125 | `@next/next/no-img-element` | 同上 |
| `SlideDrawer.tsx` | 184:6 | `react-hooks/exhaustive-deps` | useEffect 缺少依赖 `imageConfigs` |
| `SlideDrawer.tsx` | 611:29 | `@next/next/no-img-element` | 应使用 `<Image />` 替代 `<img>` |

---

## P0 — 致命级 Bug (3 个)

### 后端 #1 — API Key 仅用 Base64 编码存储，无真实加密
- **文件**: `app/routers/config.py:18-20` + `app/config.py:6`
- **问题**: `_encrypt_api_key` 只是 Base64 编码，任何能访问数据库的人都能直接解码获取所有 API Key。`ENCRYPTION_KEY` 已定义但从未使用。
- **修复建议**: 使用 AES-256-GCM 或 Fernet 加密。

### 后端 #2 — SSE 流中 DB Session 的并发安全风险
- **文件**: `app/routers/workflow.py:767-834`, `873-993`
- **问题**: SSE `event_stream()` 生成器在端点返回后才执行，内部执行大量 DB 写操作（删除旧素材、添加新素材、commit）。客户端中途断连会导致 DB 处于半提交状态。同一 note_id 的多个流式端点并发调用时互相删除/创建素材，导致数据损坏。
- **修复建议**: SSE 流内不应直接操作 DB，应先完成所有操作再一次性提交；对同一 note_id 加锁。

### 前端 #1 — SWR 缓存数据被 `.sort()` 原地篡改
- **文件**: `web/src/components/NoteDetail.tsx:410-412`
- **问题**: `videos?.sort(...)` 直接修改 SWR 缓存中的数组，破坏数据一致性。
- **修复建议**: 使用 `[...videos].sort(...)` 创建副本再排序。

---

## P1 — 严重级 Bug (15 个)

### 后端

| # | 文件 | 问题 |
|---|------|------|
| 3 | `refiner.py:90`, `optimizer.py:217`, `material_gen.py:545`, `slide_gen.py:694` | httpx.AsyncClient(verify=False) 资源泄漏，从未关闭 |
| 4 | `workflow.py:599` | 上传文件无大小限制，直接读入内存，可能 OOM |
| 5 | `workflow.py:44` | `update_script` 使用无验证的 `body: dict`，绕过 Pydantic 验证 |
| 6 | `config.py:256-262` | TTS 测试只创建对象就返回成功，未实际生成音频验证 |
| 7 | `main.py:43` | StaticFiles 使用相对路径且无鉴权，所有文件对外公开 |
| 8 | `workflow.py:602` | 上传文件名未做安全校验，可上传 .html 造成 XSS |

### 前端

| # | 文件 | 问题 |
|---|------|------|
| 2 | `NoteDetail.tsx:422-426` | `run()` 函数缺少 catch，错误被完全吞没，用户无反馈 |
| 3 | `ConfigModal.tsx:151,188-199` | LLM 配置表单与已保存配置通过数组下标关联，删除后索引错位 |
| 4 | `NoteDetail.tsx:173,202` + `SlideDrawer.tsx:92,111` | debounce 定时器未在组件卸载时清理，内存泄漏 |
| 5 | `ConfigModal.tsx:106-149` | configs 变化时 useEffect 重置所有表单，未保存的编辑丢失 |
| 6 | `NoteDetail.tsx:371` + `SlideDrawer.tsx:198` | SWR revalidate 时 effect 覆盖用户正在编辑的 segments |
| 7 | `store.ts:22` | `setFolderId` 隐式清除 `currentNoteId`，待保存内容可能丢失 |
| 8 | `NoteDetail.tsx:749-750` | 内联 fetch 调用绕过 API 模块，删除操作不检查响应状态 |
| 9 | `ConfigModal.tsx:218-227` | `handleTest` 不检查 HTTP 状态码，服务器错误被当结果处理 |
| 10 | `ConfigModal.tsx:192` | `handleRemoveLlm` 使用原生 fetch 而非 apiDelete，不检查响应 |

---

## P2 — 一般级 Bug (24 个，节选关键项)

### 后端 (12 个)
- **同步阻塞**: async 函数内执行 PIL/OpenCV/文件操作阻塞事件循环 (material_gen, video_extract, slide_gen, composer)
- **两步 commit**: 先删旧素材 commit 再创建新 commit，中间失败导致数据丢失 (workflow.py 多处)
- **refine 返回值**: 非 "error" 的未知 status 仍访问 `refined["title"]` 可能 KeyError (workflow.py:130)
- **并发无隔离**: 同一 note 的多个工作流端点无锁，并发修改导致数据不一致
- **N+1 删除**: 逐条 await db.delete(m) 循环，应批量 DELETE (workflow.py 多处)
- **TTS 串行**: for 循环逐个调用 edge_tts，应 asyncio.gather 并行 (workflow.py:419-441)
- **关键帧串行**: 逐帧调用 FFmpeg 子进程 (video_extract.py:111-131)
- **Folder N+1**: 深度查询逐层 DB 查询 (folders.py:12-24)
- **ANTHROPIC_API_KEY fallback 逻辑错误** (optimizer.py:206-212)
- **compose_video 异常后 DB 未回滚** (workflow.py:650-671)
- **DB Session 无异常回滚** (notes.py, folders.py, workflow.py 多数端点)
- **SSE 流长时间持有 DB Session** (workflow.py:767-834, 873-993)

### 前端 (12 个)
- **TestResult 组件在渲染函数内部定义**，每次 re-render 重新创建 (ConfigModal.tsx:229)
- **STATUS_LABEL 缺少多个状态**：subtitles_ready, ai_video_ready, slides_ready 等 (NoteList.tsx:9-15)
- **computeDiff 每次 render 重算**，O(m×n) LCS 算法未 memoize (NoteDetail.tsx:299)
- **FormatToolbar 通过 document.querySelector 操作 DOM** (NoteDetail.tsx:35-73)
- **硬编码 localhost:8001 URL**，部署后媒体资源无法加载 (NoteDetail + SlideDrawer 多处)
- **多处空 catch 块**静默吞没错误 (FolderSidebar, NoteList, NoteDetail, SlideDrawer)
- **formatDate 未处理无效日期**，可能显示 "NaN:NaN" (NoteList.tsx:38)
- **素材操作按钮 processing 时未禁用** (NoteDetail.tsx:748)
- **Note.status 类型为 string** 而非联合类型 (types.ts:19)
- **Segment 类型声明与实际用法不一致** (types.ts vs NoteDetail.tsx)
- **note?.id 作为唯一 useEffect 依赖**，SWR 刷新后不同步 (NoteDetail + SlideDrawer)
- **SlideDrawer 缺少关闭按钮**，无 Escape 键支持 (SlideDrawer.tsx:309)

---

## P3 — 建议级 Bug (17 个，节选)

- FolderUpdate.name 必填不符合 PATCH 语义
- NoteUpdate.status 无值域校验
- `_get_model_config` 返回类型标注不准确且未使用
- 配置默认值空字符串导致静默 dry-run
- CORS allow_origins 硬编码
- 可交互 div 缺少 a11y 属性 (role, tabIndex, onKeyDown)
- img 标签 alt 为空
- configs?.find() 在同一 render 中重复调用十多次
- fetcher 未处理网络错误和 JSON 解析错误
- API 请求无超时控制
- page.tsx 使用 store 解构而非 selector 导致过度渲染
- NoteDetail 和 SlideDrawer 大量重复代码
- tailwind.config.ts content 路径包含不存在的 ./src/pages/

---

## 优先修复建议

### 必须立即修复 (Top 5)
1. **API Key 加密** (P0 后端#1) — 安全红线，Base64 不是加密
2. **SSE 流 DB 并发安全** (P0 后端#2) — 数据完整性风险
3. **SWR 缓存 sort 篡改** (P0 前端#1) — 一行代码修复
4. **httpx.AsyncClient 资源泄漏** (P1 后端#3) — 生产环境稳定性
5. **run() 缺少 catch + 定时器未清理** (P1 前端#2,#4) — 用户体验和数据安全

### 迭代修复
- 补全错误处理和用户反馈
- 修复硬编码 URL
- 添加单元测试（当前测试覆盖率 0%）
- 补全状态标签和类型定义
- 优化 N+1 查询和串行处理

---

## 变更记录

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|----------|------|
| 2026-07-28 | v1.0 | 初始版本：全量代码审查 + ESLint + tsc 检查 | 测试 |
