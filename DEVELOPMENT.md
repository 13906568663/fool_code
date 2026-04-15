# Fool Code Python — 开发指南

> 本文档面向后续开发者，涵盖架构设计、模块职责、扩展方式、已知技术债与推荐改进方案。

---

## 目录

- [1. 项目概览](#1-项目概览)
- [2. 技术栈与依赖管理](#2-技术栈与依赖管理)
- [3. 目录结构与模块职责](#3-目录结构与模块职责)
- [4. 架构分层与依赖关系](#4-架构分层与依赖关系)
- [5. 核心数据流](#5-核心数据流)
- [6. 关键抽象与设计模式](#6-关键抽象与设计模式)
- [7. 如何扩展](#7-如何扩展)
- [8. 已知技术债与改进路线](#8-已知技术债与改进路线)
- [9. 开发与调试](#9-开发与调试)
- [10. 构建与发布](#10-构建与发布)

---

## 1. 项目概览

Fool Code 是一个 AI 编程助手桌面应用，采用 **Python 后端 + React 前端 + pywebview 桌面壳** 架构。

**核心能力**：
- 多轮对话 + 工具调用（Agent 循环，LLM 失败自动重试）
- 20+ 内置工具（文件操作、Shell、搜索、Web、子代理等）
- MCP 协议支持（stdio / SSE / HTTP / WebSocket 四种传输）
- 五级权限系统
- Hook 机制（Pre/Post/Stop/StopAgent）
- 会话压缩、记忆系统、Playbook 经验库
- 多模型提供商配置
- 文档附件支持（@file.docx / @file.xlsx / @file.csv 等自动转换）
- 图片附件 + HTTP URL 分发
- Computer Use 桌面控制（Rust 原生扩展，含坐标缩放和窗口管理）

---

## 2. 技术栈与依赖管理

### 2.1 包管理方式

| 项目 | 工具 |
|------|------|
| 包定义 | `pyproject.toml`（PEP 621） |
| 构建后端 | Hatchling |
| 依赖锁定 | `uv.lock`（由 `uv` 生成） |
| 虚拟环境 | `.venv/`（由 `uv` 管理） |

### 2.2 依赖分层

```toml
[project.dependencies]          # 运行时核心依赖（必须）
  fastapi, uvicorn, sse-starlette, httpx, pydantic, websockets

[project.optional-dependencies]
  desktop = ["pywebview"]       # 桌面壳（仅桌面模式需要）
  build   = ["pyinstaller"]     # 打包（仅构建时需要）
  dev     = [上述全部 + ruff, pytest]  # 开发全套
```

**Rust 原生扩展**（`fool_code/computer_use/_native/`）：
- 独立的 Cargo.toml + pyproject.toml，不在主 pyproject.toml 依赖树中
- 通过 `maturin develop --release` 编译安装到当前 venv
- 是**可选**的——未编译时 Computer Use 工具不注册，其他功能不受影响
- 运行时产物为 `fool_code_cu.pyd`（Windows）或 `.so`（Linux），无额外 Python 依赖

**设计决策**：`pywebview` 和 `pyinstaller` 不在核心依赖中，因为：
- 纯 server 模式不需要 pywebview（`start.py` / `--server-only`）
- 运行时不需要 pyinstaller
- 减少 CI 安装时间和依赖冲突风险

### 2.3 常用命令

```bash
# 安装全部依赖（开发用）
uv sync --all-extras

# 仅安装运行时依赖
uv sync

# 安装运行时 + 桌面壳
uv sync --extra desktop

# 添加新依赖
uv add <package>                    # 运行时依赖
uv add --optional dev <package>     # 开发依赖

# 编译 Rust 原生扩展（Computer Use，可选）
uv pip install maturin
cd fool_code/computer_use/_native
maturin develop --release
```

---

## 3. 目录结构与模块职责

```
fool_code/
├── __init__.py              # 包根，版本号
├── app.py                   # FastAPI 应用工厂 + 文件服务 API（~265 行）
├── main.py                  # 进程入口（桌面/server-only/sidecar 分发）
├── state.py                 # AppState + SessionStore + ChatSession（应用状态，~220 行）
├── types.py                 # 领域模型（Session/Message/ContentBlock 等，~280 行）
├── api_types.py             # HTTP 请求/响应 Pydantic 模型（~315 行）
├── events.py                # SSE 推送事件（WebEvent，~120 行）
│
├── routers/                 # API 路由（按领域拆分）
│   ├── __init__.py
│   ├── sessions.py          # 会话 CRUD + 压缩（~185 行，8 路由）
│   ├── chat.py              # SSE 对话 + 文档/图片附件 + 计划模式（~550 行，4 路由）
│   ├── settings.py          # 设置、模型、权限、工作区、技能、CU 配置（~350 行，13 路由）
│   ├── memory.py            # 记忆 + Playbook（~190 行，13 路由）
│   └── mcp_routes.py        # MCP 服务器管理 + 浏览器 MCP（~300 行，9 路由）
│
├── providers/               # LLM 提供商
│   ├── __init__.py
│   ├── openai_compat.py     # OpenAI 兼容 API 流式客户端
│   └── model_discovery.py   # 从 baseUrl/models 自动发现模型列表
│
├── runtime/                 # Agent 运行时（核心领域）
│   ├── __init__.py
│   ├── config.py            # 路径约定、settings.json 读写、环境变量
│   ├── providers_config.py  # 多提供商模型配置（settings.json 内 modelProviders）
│   ├── session.py           # Session JSON 持久化（JSON 快照）
│   ├── transcript.py        # JSONL 追加式持久化（主存储格式）
│   ├── conversation.py      # ConversationRuntime — 核心对话循环（~720 行）
│   ├── message_pipeline.py  # normalize_for_api / normalize_for_display 双管道（~380 行）
│   ├── content_store.py     # ContentStore — 外部文件管理（图片/计划/工具结果）
│   ├── tool_result_storage.py # 大型工具结果外部化 + ContentReplacementState
│   ├── file_converter.py    # 文档转换（docx/xlsx/csv/txt/md → Markdown 缓存，~300 行）
│   ├── prompt.py            # SystemPromptBuilder（OS/Git/指令文件/Memory/Playbook）
│   ├── compact.py           # 长对话压缩
│   ├── permissions.py       # 五级权限策略 + PermissionGate
│   ├── hooks.py             # HookRunner（shell hook 生命周期）
│   ├── usage.py             # Token 用量追踪
│   ├── memory.py            # 用户记忆文件读写、后台抽取
│   ├── playbook.py          # Playbook 经验库扫描/读写
│   ├── agent_types.py       # 内置子代理定义表
│   └── subagent.py          # 按角色选模型、子代理调用
│
├── tools/                   # 工具实现
│   ├── __init__.py
│   ├── tool_protocol.py     # ToolHandler 抽象基类 + ToolMeta/ToolResult/ToolContext
│   ├── registry.py          # ToolRegistry + build_tool_registry() 注册 20+ 内置工具
│   ├── bash.py              # Shell 执行（cmd/bash，后台任务支持）
│   ├── file_ops.py          # read_file / write_file / edit_file
│   ├── search.py            # glob_search / grep_search
│   ├── web.py               # WebFetch / WebSearch
│   ├── todo.py              # TodoWrite（结构化任务列表）
│   ├── skill.py             # Skill 加载
│   ├── notebook.py          # Jupyter notebook 编辑
│   ├── playbook.py          # Playbook 工具封装（调用 runtime.playbook）
│   ├── plan_mode.py         # SuggestPlanMode 工具
│   └── misc.py              # Sleep, Config, Agent, REPL, PowerShell, ToolSearch 等
│
├── computer_use/            # Windows 桌面控制（Rust + Python，自包含可选模块）
│   ├── __init__.py          # register_computer_use() 入口
│   ├── types.py             # DisplayInfo, AppInfo 等数据类型
│   ├── executor.py          # Rust 模块薄封装，graceful fallback
│   ├── tools.py             # 8 个 ToolHandler (截屏/点击/输入/按键/...)
│   ├── scaling.py           # 坐标缩放 + DPI 映射 + 多显示器坐标转换（~270 行）
│   ├── window_manager.py    # 窗口管理（查找/聚焦/枚举窗口）
│   ├── README.md            # 完整开发者文档
│   └── _native/             # Rust PyO3 原生扩展
│       ├── Cargo.toml       # 依赖: pyo3, enigo, windows, image, base64
│       ├── Cargo.lock
│       ├── pyproject.toml   # maturin 构建配置
│       └── src/
│           ├── lib.rs       # PyO3 模块入口
│           ├── screen.rs    # GDI BitBlt 截屏 → JPEG → base64
│           ├── display.rs   # 显示器枚举 + DPI 感知
│           ├── input.rs     # 鼠标键盘操作 (enigo + GetCursorPos)
│           ├── clipboard.rs # Win32 剪贴板读写
│           └── apps.rs      # 进程/窗口/注册表应用管理
│
├── mcp/                     # MCP 客户端（通用）
│   ├── __init__.py
│   ├── types.py             # JSON-RPC 消息结构、McpTool、McpToolCallResult
│   ├── manager.py           # McpServerManager — 多服务器生命周期 + 工具发现
│   ├── stdio.py             # stdio 传输（Content-Length 帧子进程）
│   ├── sse.py               # SSE 传输
│   ├── http_transport.py    # Streamable HTTP 传输
│   └── ws.py                # WebSocket 传输
│
└── internal_mcp/            # 内置 MCP 侧车服务
    ├── __init__.py
    ├── types.py             # InternalMcpServiceDefinition
    ├── registry.py          # 注册内置 MCP 服务
    └── browser_mcp/         # 浏览器 MCP 侧车
        ├── __init__.py
        ├── __main__.py      # 子进程 CLI 入口
        ├── manifest.py      # 工具清单 + 服务元数据
        ├── types.py         # BrowserMcpRuntimeConfig
        ├── launcher.py      # stdio 启动参数组装
        ├── server.py        # BrowserMcpServer 主逻辑
        ├── bridge_pool.py   # 浏览器桥连接池
        └── ws_server.py     # 桥 WebSocket 服务
```

### 模块大小参考

| 模块 | 行数 | 职责 | 评估 |
|------|------|------|------|
| `app.py` | ~265 | 应用工厂 + 生命周期 + MCP 初始化 + 文件服务 API | ✅ 合理 |
| `state.py` | ~220 | 应用状态 + 会话管理 | ✅ 良好 |
| `routers/chat.py` | ~550 | 对话 SSE + 文档/图片附件引用 + 计划模式 | 合理（含附件处理） |
| `routers/settings.py` | ~350 | 设置/模型/权限/工作区/CU 配置 | ✅ 良好 |
| `routers/mcp_routes.py` | ~300 | MCP 服务器管理 + 开关/断开 | ✅ 良好 |
| `routers/memory.py` | ~190 | 记忆 + Playbook | ✅ 良好 |
| `routers/sessions.py` | ~185 | 会话 CRUD + 压缩 | ✅ 良好 |
| `types.py` | ~280 | 领域模型 + 内容块 + document_block | ✅ 良好 |
| `api_types.py` | ~315 | HTTP 请求/响应 DTO | ✅ 良好 |
| `events.py` | ~120 | SSE 事件（含 document_attached） | ✅ 良好 |
| `conversation.py` | ~720 | Agent 循环（含 LLM 重试） | 合理（核心复杂度） |
| `message_pipeline.py` | ~380 | 双管道 + 文档块 + 图片 URL 分发 | 合理（管道逻辑） |
| `file_converter.py` | ~300 | 文档转换（docx/xlsx/csv → Markdown） | ✅ 良好 |
| `scaling.py` | ~270 | 坐标缩放 + DPI 映射 | ✅ 良好 |
| `registry.py` | ~695 | 工具注册 | 合理（声明式） |

---

## 4. 架构分层与依赖关系

### 4.1 四层架构

```
┌─────────────────────────────────────────────────────┐
│  入口层 (main.py)                                    │
│  进程启动、pywebview 桌面壳、sidecar 分发             │
├─────────────────────────────────────────────────────┤
│  应用层 (app.py + state.py)                          │
│  FastAPI 路由、SSE 推送、文件服务 API、应用状态管理      │
├─────────────────────────────────────────────────────┤
│  领域层 (runtime/ + tools/ + providers/)             │
│  对话循环、工具执行、LLM 调用、权限、Hook、记忆        │
├─────────────────────────────────────────────────────┤
│  基础设施层 (mcp/ + internal_mcp/ + types.py)        │
│  MCP 传输、JSON-RPC、数据模型、配置存储               │
└─────────────────────────────────────────────────────┘
```

### 4.2 模块依赖方向

```
types.py ← （被所有模块引用，零外部依赖）
    ↑
mcp/types.py ← mcp/*.py (传输实现)
    ↑
mcp/manager.py ← app.py (MCP 生命周期管理)
    ↑
runtime/config.py ← runtime/*.py, tools/*.py (配置读写)
    ↑
runtime/conversation.py ← app.py (对话循环)
    ↑
tools/registry.py ← app.py, runtime/ (工具注册与执行)
    ↑
state.py ← app.py (应用状态)
    ↑
app.py ← main.py (HTTP 路由)
```

### 4.3 循环依赖防护

项目中**无顶层循环导入**，通过以下手段避免：

- **延迟导入**：`runtime/config.py` 中 `read_api_config()` 延迟导入 `providers_config`
- **函数内导入**：`conversation.py`、`memory.py`、`prompt.py`、`registry.py` 中大量使用
- **`TYPE_CHECKING`**：`tool_protocol.py`、`conversation.py` 中用于类型注解

**规则**：新增模块时，如果出现循环依赖，优先使用函数内导入而非顶层导入。

---

## 5. 核心数据流

### 5.1 对话流程

```
用户消息 → POST /api/chat
  ↓
routers/chat.py: handle_chat()
  ↓ (新建后台线程)
_run_chat()
  ├── 获取 ChatSession + 提供商配置
  ├── 创建 OpenAICompatProvider + ContentStore
  ├── 解析 @file 引用：
  │   ├── _extract_image_refs() — 图片附件（jpg/png/...）
  │   └── _extract_document_refs() — 文档附件（docx/xlsx/csv/...）
  ├── 创建 ConversationRuntime
  └── runtime.run_turn(message)
        ↓
        ConversationRuntime._agent_loop()
        ├── 构建消息列表 (system prompt + history + user)
        ├── 调用 LLM API（流式）
        │   ├── text_delta → SSE "text" event
        │   └── tool_call → 进入工具循环
        │       ├── PermissionGate 检查
        │       ├── HookRunner.pre_tool()
        │       ├── ToolRegistry.execute() 或 McpServerManager.call_tool()
        │       ├── HookRunner.post_tool()
        │       └── SSE "tool_start" / "tool_end" events
        ├── LLM 返回 None 时自动重试（最多 2 次，指数退避）
        ├── 循环直到无工具调用或达到 MAX_ITERATIONS (50)
        ├── 自动 compaction 检查
        └── 后台 memory 抽取
  ↓
保存 Session → SSE "done" event
```

### 5.2 内容外部化流程

大型内容（图片、计划文档、大工具结果）不直接存储在 Session 消息中，
而是存入外部文件并用引用替代，保持上下文精简：

```
工具结果 > 阈值(10KB)?
  ├── 是 → ToolResultPersister.maybe_persist()
  │        ├── 存入 ~/.fool-code/tool-results/{session_id}/{hash}.txt
  │        └── 消息中替换为 preview + external_path 引用
  └── 否 → 原样保留

图片附件 → ContentStore.store_image()
  └── 存入 ~/.fool-code/image-cache/{session_id}/{image_id}.{ext}
  └── LLM 端通过 HTTP URL (/api/images/...) 或 base64 data-URI 访问

文档附件（@file.docx / @file.xlsx / @file.csv 等）
  → file_converter.process_file()
  ├── 转换为 Markdown，存入 ~/.fool-code/file-cache/{session_id}/file-{id}.{ext}.md
  ├── 消息中添加 document ContentBlock（external_path 指向 .md 文件）
  └── normalize_for_api() 时读取 Markdown 注入 LLM 上下文

计划文档 → ContentStore.write_plan(slug, text)
  └── 存入 ~/.fool-code/plans/{slug}.md
  └── 消息中替换为 plan_ref 块（preview = 步骤摘要）
```

消息管道通过 `normalize_for_api()` / `normalize_for_display()` 为 LLM API
和前端 UI 分别构建不同的消息视图。

### 5.3 计划模式生命周期

```
normal ──→ plan ──→ drafted ──→ executing ──→ completed ──→ normal
  ↑                     │
  └─── discard ─────────┘

1. 用户切换到 plan 模式 → conversation_mode="plan"
2. AI 生成计划（只读，写工具被阻止） → 保存为外部 .md 文件
3. plan_status="drafted" → 前端显示 PlanView + "执行计划"按钮
4. 用户点击执行 → conversation_mode="normal"，发送"请开始执行计划"
   系统提示注入计划全文 + TodoWrite 指令
5. plan_status="executing" → AI 逐步调用 TodoWrite 更新步骤进度
6. 执行完成 → plan_status="completed" → 所有步骤显示为已完成
```

plan_status 持久化到 JSONL transcript 和 Session JSON 中，刷新页面后状态可恢复。

### 5.4 会话持久化

采用双格式存储：
- **JSONL transcript**（主格式）：追加式写入，包含消息、标题、plan_slug、plan_status
- **JSON snapshot**（备份）：完整 Session 快照，兼容旧版本

启动时优先从 JSONL 恢复；旧版 JSON 自动迁移为 JSONL 并重命名为 `.json.bak`。

### 5.5 MCP 工具调用流程

```
LLM 返回 tool_call(name="mcp__server__tool_name")
  ↓
ConversationRuntime 识别为 MCP 工具
  ↓
McpServerManager.call_tool(qualified_name, arguments)
  ↓
查找 ManagedMcpTool → 获取 server_name + tool_name
  ↓
对应传输层 (stdio/sse/http/ws) 发送 JSON-RPC "tools/call"
  ↓
返回 McpToolCallResult → 转为 tool_result 消息
```

---

## 6. 关键抽象与设计模式

### 6.1 ToolHandler 协议

所有工具实现都遵循 `ToolHandler` 抽象基类：

```python
class ToolHandler(ABC):
    meta: ToolMeta          # 静态元数据（分类、只读、并发安全等）
    definition: ToolDefinition  # OpenAI function calling schema

    def is_enabled(self) -> bool: ...
    def validate_input(self, args) -> str | None: ...
    def execute(self, args, context: ToolContext) -> ToolResult: ...
```

对于简单工具，使用 `FunctionToolHandler` 适配器包装普通函数。
对于复杂工具（如 `TodoWriteHandler`、`SuggestPlanModeHandler`），直接继承 `ToolHandler`。

### 6.2 MCP 传输协议

所有 MCP 传输实现都遵循 `McpTransport` Protocol：

```python
class McpTransport(Protocol):
    async def start(self) -> None: ...
    async def initialize(self) -> dict: ...
    async def list_tools(self) -> list[McpTool]: ...
    async def call_tool(self, name, arguments) -> McpToolCallResult: ...
    async def shutdown(self) -> None: ...
    @property
    def is_initialized(self) -> bool: ...
```

### 6.3 权限模型

五级权限从低到高：`READ_ONLY → DEFAULT → WORKSPACE_WRITE → DANGER_FULL_ACCESS → DONT_ASK`

每个工具有 `ToolCategory` 分类（read_only / edit / execution / meta / mcp），
`PermissionPolicy` 根据当前模式决定是否自动放行。不放行时通过 `PermissionGate`
向前端发 SSE 事件等待用户确认。

### 6.4 AppState 单例

`AppState` 是应用的全局可变状态，包含：
- `workspace_root` — 当前工作区路径
- `store: SessionStore` — 内存中的会话管理
- `tool_registry` — 工具注册表
- `mcp_manager` — MCP 服务器管理器
- `permission_gate` — 权限门
- `hook_config` — Hook 配置
- `lock` — 线程锁（因 chat 在后台线程运行）

通过 `create_app()` 内的闭包被所有路由捕获。

---

## 7. 如何扩展

### 7.1 添加新工具

1. 在 `tools/` 下创建模块（如 `tools/my_tool.py`）
2. 实现工具函数或 `ToolHandler` 子类
3. 在 `tools/registry.py` 的 `build_tool_registry()` 中注册

```python
# tools/my_tool.py
def my_tool(args: dict) -> str:
    name = args.get("name", "")
    return f"Hello, {name}!"
```

```python
# registry.py 的 build_tool_registry() 中
from fool_code.tools.my_tool import my_tool

registry.register(
    "MyTool",
    my_tool,
    _td("MyTool", "Description", {"name": {"type": "string"}}, ["name"]),
    meta=_meta("MyTool", ToolCategory.READ_ONLY, read_only=True),
)
```

### 7.2 添加新 MCP 传输

1. 在 `mcp/` 下创建模块
2. 实现 `McpTransport` Protocol 的全部方法
3. 在 `mcp/manager.py` 的 `_create_transport()` 中添加分支
4. 更新 `SUPPORTED_TRANSPORTS` 集合

### 7.3 添加新 API 路由

在 `routers/` 下对应的路由模块中添加新路由。如需新建路由模块，创建 `create_xxx_router(state)` 工厂函数并在 `app.py` 的 `create_app()` 中通过 `app.include_router()` 注册。文件服务类 API（如图片/文件缓存）可直接在 `app.py` 中添加。

### 7.4 添加新 LLM 提供商

当前仅支持 OpenAI 兼容 API。如需添加新提供商：
1. 在 `providers/` 下创建模块
2. 实现与 `OpenAICompatProvider` 相同的接口（`chat_stream` 方法）
3. 在 `app.py` 的 `_run_chat()` 中根据配置选择提供商

### 7.5 添加新内置 MCP 侧车

1. 在 `internal_mcp/` 下创建新包（参考 `browser_mcp/`）
2. 定义 `manifest.py`（工具清单 + 服务元数据）
3. 在 `internal_mcp/registry.py` 中注册

---

## 8. 已知技术债与改进路线

### 8.1 优先级 P0（已完成 ✅）

#### `app.py` 路由拆分 ✅

已使用 FastAPI `APIRouter` + 工厂模式拆分为 5 个路由模块：

| 路由文件 | 路由数 | 职责 |
|----------|--------|------|
| `routers/sessions.py` | 8 | 会话 CRUD + 压缩 |
| `routers/chat.py` | 4 | SSE 对话 + 停止 + 计划模式 |
| `routers/settings.py` | 13 | 设置、模型、权限、工作区、技能、Computer Use 配置 |
| `routers/memory.py` | 13 | 记忆 + Playbook + 模型角色 |
| `routers/mcp_routes.py` | 9 | MCP 服务器 + 开关/断开 + 浏览器 MCP |
| `app.py`（非路由模块） | 6 | 图片/文件缓存/预览/转换 + 前端 fallback |

每个路由文件导出 `create_xxx_router(state)` 工厂函数，在 `app.py` 的
`create_app()` 中通过 `app.include_router()` 组装。

#### `types.py` 拆分 ✅

已按领域拆分为三个文件：

| 文件 | 内容 | 行数 |
|------|------|------|
| `types.py` | 领域模型（Session, Message, ContentBlock, ToolDefinition 等） | ~250 |
| `api_types.py` | HTTP 请求/响应 Pydantic 模型 | ~260 |
| `events.py` | WebEvent SSE 事件 | ~90 |

#### 内容外部化 ✅

将大型内容从 Session 消息中外部化，保持上下文精简：

| 新模块 | 职责 |
|--------|------|
| `runtime/content_store.py` | 统一管理外部文件（图片/计划/工具结果） |
| `runtime/tool_result_storage.py` | 大工具结果自动外部化 + 替换状态管理 |
| `runtime/message_pipeline.py` | `normalize_for_api` / `normalize_for_display` 双管道 |
| `runtime/transcript.py` | JSONL 追加式会话持久化（主格式） |

`types.py` 中 `ContentBlock` 新增 `external_path`、`preview`、`media_type` 等字段，
以及 `document_block()` 工厂方法用于文档附件。
`events.py` 新增 `document_attached` 事件类型。
`Session` 新增 `plan_slug`、`plan_status` 字段。

#### 计划模式生命周期持久化 ✅

`plan_status` (`none` → `drafted` → `executing` → `completed`) 持久化到
JSONL transcript 和 Session JSON，前端通过 API 读取并控制 PlanView 显示。

**修复的关键 bug**：
- `_run_chat` 中 `cs.session = runtime.session` 会覆盖已设置的 `plan_status`，
  因为 `runtime.session` 是执行前的深拷贝。修复：同步在 `runtime.session` 上设置状态。
- `executePlan()` 调用 `sendMessage` 时未传 `onDone` 回调，导致执行完成后
  前端不会 reload session，步骤状态停留在流式传输时的最后状态。修复：`executePlan`
  接受 `onDone` 参数，`App.tsx` 中传入 session 重载逻辑。

### 8.2 优先级 P1（后续迭代处理）

**问题**：`config_path()`、`sessions_path()`、`read_config_root()` 等函数接收
`_workspace_root: Path | None = None` 参数但完全不使用，源于初始设计想做
per-workspace 配置但后来改为全局 `app_data_root()`。

**方案 A（简化）**：移除所有 `_workspace_root` 参数，更新调用方  
**方案 B（完善）**：真正实现 per-workspace 配置，让参数生效

推荐方案 A，除非有明确的 per-workspace 配置需求。

#### 历史命名清理

- `APP_DIRNAME = ".fool-code"` 为当前统一目录名
- 配置路径使用 `config_dir()`
- 计划和 TODO 文件使用 `.fool-code` 前缀

保留 `_migrate_legacy_storage()` 做一次性迁移即可。

#### `write_config_root` 签名

**问题**：支持两种调用形式 `write_config_root(dict)` 和 `write_config_root(path, dict)`，
path 参数被忽略。使用 `@overload` 或简化为单参数。

### 8.3 优先级 P2（长期改进）

#### 测试体系

当前无任何测试文件。推荐按优先级添加：

1. **工具单元测试**（`tests/tools/`）— 各工具函数的输入输出验证
2. **Session 持久化测试** — compact、save/load 回环
3. **MCP 传输测试** — mock subprocess/HTTP，验证 JSON-RPC 协议
4. **API 集成测试** — FastAPI TestClient 对全部路由做冒烟测试

```bash
# 建议的测试目录结构
tests/
├── conftest.py           # 共享 fixture（临时目录、mock 配置等）
├── test_tools/
│   ├── test_bash.py
│   ├── test_file_ops.py
│   └── test_search.py
├── test_runtime/
│   ├── test_compact.py
│   ├── test_permissions.py
│   └── test_session.py
├── test_mcp/
│   └── test_manager.py
└── test_api/
    └── test_routes.py
```

#### 异步化

当前对话循环在后台线程 `threading.Thread` 中同步运行，通过 `asyncio.Queue` 桥接到
SSE 响应。长期可考虑将 `ConversationRuntime` 改为原生 async，消除线程切换开销。

#### 提供商抽象

当前 `OpenAICompatProvider` 是唯一提供商，且直接在 `_run_chat()` 中硬编码创建。
如果未来需要支持 Anthropic 原生 API、本地模型等，应引入 `ProviderProtocol`：

```python
class ProviderProtocol(Protocol):
    def chat_stream(self, messages, tools, ...) -> Iterator[StreamEvent]: ...
    def close(self) -> None: ...
```

---

## 9. 开发与调试

### 9.1 启动方式

```bash
# 桌面窗口模式（pywebview）
uv run python run.py

# 仅后端 + 自动打开浏览器
uv run python start.py

# 仅后端（不打开浏览器）
uv run python run.py --server-only

# Browser MCP 侧车模式（内部使用）
uv run python run.py --browser-mcp-sidecar
```

### 9.2 前端开发

```bash
cd desktop-ui
npm install
npm run dev       # Vite dev server（热更新）
npm run build     # 构建到 dist/
```

后端会自动从 `desktop-ui/dist/` 提供静态文件。开发时前端 dev server 独立运行，
通过 Vite 配置 proxy 到后端 API。

### 9.3 日志

```python
import logging
logger = logging.getLogger(__name__)
```

日志级别在 `main.py` 中设置为 `INFO`。调试时可修改为 `DEBUG`。

MCP 相关日志前缀为 `[MCP]`，方便过滤。

### 9.4 配置文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| 全局配置 | `~/.fool-code/settings.json` | API Key、模型、MCP 服务器等 |
| 会话存储 | `~/.fool-code/sessions/*.jsonl` | 每个会话一个 JSONL transcript |
| 会话快照 | `~/.fool-code/sessions/*.json` | JSON 备份（自动生成） |
| 计划文档 | `~/.fool-code/plans/*.md` | 外部化的计划 Markdown |
| 图片缓存 | `~/.fool-code/image-cache/{session}/` | 会话图片附件 |
| 文件缓存 | `~/.fool-code/file-cache/{session}/` | 文档转换后的 Markdown 缓存 |
| 工具结果 | `~/.fool-code/tool-results/{session}/` | 外部化的大型工具输出 |
| 技能目录 | `~/.fool-code/skills/` | 技能定义 |
| 记忆文件 | `~/.fool-code/memory/` | 用户记忆 |
| Playbook | `~/.fool-code/playbooks/` | 经验文档库 |
| 旧版目录 | `.fool-code/` | 应用配置与数据 |

---

## 10. 构建与发布

### 10.1 PyInstaller 打包

```bash
# 1. 构建前端
cd desktop-ui && npm run build && cd ..

# 2. 编译 Rust 扩展（如需 Computer Use 功能）
cd fool_code/computer_use/_native && maturin develop --release && cd ../../..

# 3. 打包 exe
uv run pyinstaller FoolCode.spec --noconfirm

# 产物在 dist/FoolCode.exe（单文件）
```

**注意事项**：
- Python 版本必须为 **3.11 ~ 3.13**（3.14 不兼容 pythonnet/pywebview）
- `FoolCode.spec` 已配置：
  - 打包 `desktop-ui/dist/` 到产物中
  - 所有 uvicorn/webview/websockets hidden imports
  - 应用图标 `desktop-ui/柴犬.ico`
- 打包后的 exe 是完全自包含的，用户无需安装 Python
- **Rust 扩展打包**：如果需要 Computer Use 功能，需在 spec 文件中添加：
  ```python
  # FoolCode.spec — 添加 Rust 原生扩展
  hiddenimports=['fool_code_cu']
  # 或在 binaries 中指定:
  binaries=[('.venv/Lib/site-packages/fool_code_cu/fool_code_cu.pyd', 'fool_code_cu')]
  ```
- 如果不需要 Computer Use，无需任何额外配置，打包流程与之前完全一致

### 10.2 环境变量

| 变量 | 说明 |
|------|------|
| `FOOL_CODE_HOME` | 覆盖 `~/.fool-code` 数据目录 |
| `FOOL_CODE_WORKSPACE_ROOT` | 覆盖默认工作区路径 |
| `FOOL_CODE_FRONTEND_DIR` | 覆盖前端静态文件目录 |
| `FOOL_CODE_SKIP_GIT_CONTEXT` | 跳过 Git 上下文收集（打包时自动设置） |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key（优先使用 settings.json） |
| `OPENAI_BASE_URL` | OpenAI 兼容 API Base URL |

---

## 附录 A：API 路由完整清单

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/status` | 状态 + 活跃会话 |
| POST | `/api/chat` | SSE 流式对话 |
| POST | `/api/chat/stop` | 停止当前对话（取消 Agent 循环） |
| GET | `/api/conversation-mode` | 获取对话模式 |
| POST | `/api/conversation-mode` | 设置对话模式（normal/plan） |
| GET | `/api/sessions` | 会话列表 |
| POST | `/api/sessions/new` | 新建会话 |
| GET | `/api/sessions/{id}` | 会话详情 |
| POST | `/api/sessions/{id}/model` | 设置会话模型 |
| POST | `/api/sessions/{id}/provider` | 设置会话提供商 |
| POST | `/api/sessions/{id}/switch` | 切换活跃会话 |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| POST | `/api/sessions/{id}/compact` | 压缩会话 |
| POST | `/api/permission` | 权限决策 |
| GET | `/api/permission-mode` | 获取权限模式 |
| POST | `/api/permission-mode` | 设置权限模式 |
| GET | `/api/settings` | 读取设置 |
| POST | `/api/settings` | 写入设置 |
| GET | `/api/models` | 预置模型列表 |
| POST | `/api/models/discover` | 动态发现模型 |
| GET | `/api/skills` | 技能列表 |
| GET | `/api/workspace` | 工作区信息 |
| POST | `/api/workspace` | 切换工作区 |
| GET | `/api/computer-use/config` | 获取 Computer Use 配置 |
| POST | `/api/computer-use/config` | 保存 Computer Use 配置 |
| GET | `/api/mcp-servers` | MCP 服务器列表 |
| GET | `/api/internal-mcp/browser` | 内置浏览器 MCP 状态 |
| POST | `/api/internal-mcp/browser` | 配置浏览器 MCP |
| POST | `/api/internal-mcp/browser/reconnect` | 重连浏览器 MCP |
| POST | `/api/mcp-servers/save` | 保存 MCP 服务器 |
| POST | `/api/mcp-servers/toggle` | 启用/禁用 MCP 服务器 |
| POST | `/api/mcp-servers/disconnect` | 断开 MCP 服务器连接 |
| POST | `/api/mcp-servers/delete` | 删除 MCP 服务器 |
| POST | `/api/mcp-servers/connect` | 连接 MCP 服务器 |
| GET | `/api/memory` | 记忆类型列表 |
| POST | `/api/memory/toggle` | 开关自动记忆 |
| GET | `/api/model-roles` | 模型角色配置 |
| POST | `/api/model-roles` | 保存模型角色 |
| GET | `/api/memory/{type}` | 读取记忆内容 |
| POST | `/api/memory/{type}` | 保存记忆内容 |
| GET | `/api/playbooks` | Playbook 分类列表 |
| POST | `/api/playbooks/category` | 创建 Playbook 分类 |
| DELETE | `/api/playbooks/category/{cat}` | 删除 Playbook 分类 |
| GET | `/api/playbooks/template` | Playbook 模板 |
| GET | `/api/playbooks/{cat}/{file}` | 读取 Playbook |
| POST | `/api/playbooks/{cat}/{file}` | 保存 Playbook |
| DELETE | `/api/playbooks/{cat}/{file}` | 删除 Playbook |
| GET | `/api/images/{session_id}/{filename}` | 提供会话图片文件 |
| GET | `/api/file-cache/{session_id}/{filename}` | 提供缓存的文档文件 |
| GET | `/api/file-content` | 读取文件缓存中的 Markdown 文本 |
| GET | `/api/file-preview` | 本地文件预览（图片等） |
| POST | `/api/file-process` | 文档转换（docx/xlsx/csv → Markdown） |
| GET | `/{path}` | 前端静态文件 fallback |

## 附录 B：内置工具清单

| 工具名 | 分类 | 只读 | 并发安全 | 所在文件 |
|--------|------|------|---------|---------|
| `bash` | execution | 动态判断 | ❌ | `bash.py` |
| `read_file` | read_only | ✅ | ✅ | `file_ops.py` |
| `write_file` | edit | ❌ | ❌ | `file_ops.py` |
| `edit_file` | edit | ❌ | ❌ | `file_ops.py` |
| `glob_search` | read_only | ✅ | ✅ | `search.py` |
| `grep_search` | read_only | ✅ | ✅ | `search.py` |
| `WebFetch` | read_only | ✅ | ✅ | `web.py` |
| `WebSearch` | read_only | ✅ | ✅ | `web.py` |
| `TodoWrite` | edit | ❌ | ❌ | `todo.py` |
| `Skill` | meta | ✅ | ✅ | `skill.py` |
| `Agent` | meta | ❌ | ❌ | `misc.py` |
| `Playbook` | meta | ✅ | ✅ | `playbook.py` |
| `ToolSearch` | meta | ✅ | ✅ | `registry.py` |
| `NotebookEdit` | edit | ❌ | ❌ | `notebook.py` |
| `Sleep` | meta | ✅ | ✅ | `misc.py` |
| `SendUserMessage` | meta | ✅ | ✅ | `misc.py` |
| `Brief` | meta | ✅ | ✅ | `misc.py` |
| `Config` | meta | ❌ | ❌ | `misc.py` |
| `StructuredOutput` | meta | ✅ | ✅ | `misc.py` |
| `REPL` | execution | ❌ | ❌ | `misc.py` |
| `PowerShell` | execution | 动态判断 | ❌ | `misc.py` |
| `SuggestPlanMode` | meta | ✅ | ✅ | `plan_mode.py` |
| `computer_screenshot` | meta | ✅ | ✅ | `computer_use/tools.py` |
| `computer_screenshot_region` | meta | ✅ | ✅ | `computer_use/tools.py` |
| `computer_click` | execution | ❌ | ❌ | `computer_use/tools.py` |
| `computer_type` | execution | ❌ | ❌ | `computer_use/tools.py` |
| `computer_key` | execution | ❌ | ❌ | `computer_use/tools.py` |
| `computer_scroll` | execution | ❌ | ❌ | `computer_use/tools.py` |
| `computer_drag` | execution | ❌ | ❌ | `computer_use/tools.py` |
| `computer_cursor_position` | meta | ✅ | ✅ | `computer_use/tools.py` |
