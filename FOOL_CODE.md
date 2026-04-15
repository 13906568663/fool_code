# Fool Code — Python Desktop AI 编程助手

## 项目概述

Fool Code 是一个 AI 编程助手桌面应用，采用 Python 实现。
采用 **FastAPI 后端 + React 前端 + pywebview 桌面壳** 架构，LLM 提供商仅支持 OpenAI 兼容 API。

## 技术栈

| 层 | 技术 |
|----|------|
| 桌面壳 | pywebview 6.x（Windows 使用 EdgeChromium/WinForms） |
| HTTP 后端 | FastAPI + Uvicorn |
| SSE 推送 | sse-starlette |
| LLM 调用 | httpx（流式 OpenAI chat/completions） |
| 数据模型 | Pydantic 2.x |
| 前端 | React 18 + Vite + Tailwind（复用 `desktop-ui/`） |
| 包管理 | uv |
| 打包 | PyInstaller |
| 原生扩展 | Rust + PyO3 + maturin（Computer Use 模块，可选） |
| Python | 3.11 ~ 3.13（3.14 不支持，因 pythonnet 限制） |

## 目录结构

```
fool-code-python/
├── fool_code/
│   ├── app.py                  # FastAPI 主应用，全部 17 个 API 路由
│   ├── main.py                 # 桌面入口（uvicorn + pywebview）
│   ├── types.py                # Pydantic 数据模型 + WebEvent
│   ├── providers/
│   │   └── openai_compat.py    # OpenAI 兼容 LLM 流式客户端
│   ├── runtime/
│   │   ├── config.py           # 配置读写、settings.json、环境变量
│   │   ├── session.py          # Session JSON 持久化
│   │   ├── conversation.py     # ConversationRuntime 核心对话循环
│   │   ├── permissions.py      # 5 级权限系统 (PermissionPolicy + PermissionGate)
│   │   ├── hooks.py            # HookRunner (Pre/Post/Stop/StopAgent)
│   │   ├── usage.py            # UsageTracker 令牌用量与费用追踪
│   │   ├── compact.py          # Session 压缩（长对话摘要）
│   │   └── prompt.py           # SystemPromptBuilder（OS/Git/指令文件）
│   ├── tools/
│   │   ├── registry.py         # ToolRegistry + 20 个内置工具注册
│   │   ├── bash.py             # bash 工具（后台任务、超时、结构化输出）
│   │   ├── file_ops.py         # read_file / write_file / edit_file
│   │   ├── search.py           # glob_search / grep_search（全参数）
│   │   ├── web.py              # WebFetch / WebSearch
│   │   ├── todo.py             # TodoWrite
│   │   ├── skill.py            # Skill（加载 SKILL.md）
│   │   ├── notebook.py         # NotebookEdit（Jupyter .ipynb）
│   │   └── misc.py             # Sleep, SendUserMessage, Config, REPL, PowerShell, Agent, ToolSearch, StructuredOutput
│   ├── computer_use/           # Windows 桌面控制（Rust + Python，可选）
│   │   ├── __init__.py         # register_computer_use() 入口
│   │   ├── executor.py         # Rust 模块薄封装 + graceful fallback
│   │   ├── tools.py            # 8 个 ToolHandler
│   │   └── _native/            # Rust PyO3 原生扩展源码
│   │       ├── Cargo.toml
│   │       ├── pyproject.toml  # maturin 构建配置
│   │       └── src/            # screen.rs, input.rs, apps.rs, clipboard.rs, display.rs
│   └── mcp/
│       ├── manager.py          # McpServerManager（多协议路由）
│       ├── types.py            # JSON-RPC / McpTool / McpToolCallResult
│       ├── stdio.py            # stdio 传输（子进程 Content-Length 帧）
│       ├── sse.py              # SSE 传输（GET 接收 + POST 发送）
│       ├── http_transport.py   # Streamable HTTP 传输（Mcp-Session-Id）
│       └── ws.py               # WebSocket 传输（双向 JSON-RPC）
├── run.py                      # 快捷启动脚本
├── start.py                    # 纯 server 模式（自动开浏览器）
├── fool_code.spec              # PyInstaller 打包配置
├── fool_code.ico               # 应用图标（柴犬）
├── fool_code_icon.png          # 图标 PNG 源文件
├── pyproject.toml              # 项目配置 + 依赖声明
└── .fool-code/
    └── settings.json           # 本地 API 配置
```

## API 路由表

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/status` | 模型名、就绪状态、活跃会话、是否已配置 |
| POST | `/api/chat` | SSE 流式对话（text/tool_call/permission/done） |
| GET | `/api/sessions` | 会话列表 + 活跃 ID |
| POST | `/api/sessions/new` | 新建会话 |
| GET | `/api/sessions/{id}` | 会话详情（消息列表） |
| POST | `/api/sessions/{id}/switch` | 切换活跃会话 |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| POST | `/api/sessions/{id}/compact` | 压缩会话 |
| POST | `/api/permission` | 权限决策（allow/deny/always） |
| GET | `/api/settings` | 读取设置 |
| POST | `/api/settings` | 写入设置 |
| GET | `/api/models` | 可用模型列表 |
| GET | `/api/skills` | 工作区技能列表 |
| GET | `/api/mcp-servers` | MCP 服务器状态 |
| POST | `/api/mcp-servers/save` | 保存 MCP 配置 |
| POST | `/api/mcp-servers/delete` | 删除 MCP 服务器 |
| POST | `/api/mcp-servers/connect` | 连接并发现工具 |
| GET | `/api/workspace` | 当前工作区 |
| POST | `/api/workspace` | 切换工作区 |

## 20 个内置工具

| 工具名 | 权限等级 | 功能 |
|--------|----------|------|
| `bash` | DangerFullAccess | 执行 shell 命令 |
| `read_file` | ReadOnly | 读取文件内容 |
| `write_file` | WorkspaceWrite | 写入文件 |
| `edit_file` | WorkspaceWrite | 编辑文件（支持 replace_all） |
| `glob_search` | ReadOnly | 文件名模式搜索 |
| `grep_search` | ReadOnly | 文件内容正则搜索（全参数） |
| `WebFetch` | ReadOnly | 抓取网页内容 |
| `WebSearch` | ReadOnly | 网络搜索 |
| `TodoWrite` | WorkspaceWrite | 管理结构化任务列表 |
| `Skill` | ReadOnly | 加载技能定义 |
| `Agent` | DangerFullAccess | 启动子代理 |
| `ToolSearch` | ReadOnly | 搜索可用工具 |
| `NotebookEdit` | WorkspaceWrite | 编辑 Jupyter notebook |
| `Sleep` | ReadOnly | 等待指定时长 |
| `SendUserMessage` | ReadOnly | 发送消息给用户 |
| `Brief` | ReadOnly | SendUserMessage 别名 |
| `Config` | WorkspaceWrite | 读写应用设置 |
| `StructuredOutput` | ReadOnly | 返回结构化 JSON |
| `REPL` | DangerFullAccess | 执行代码片段 |
| `PowerShell` | DangerFullAccess | 执行 PowerShell 命令 |

### Computer Use 工具（Windows，可选 — 需 Rust 扩展）

| 工具名 | 权限等级 | 功能 |
|--------|----------|------|
| `computer_screenshot` | ReadOnly | 全屏截图 |
| `computer_screenshot_region` | ReadOnly | 区域截图 |
| `computer_click` | DangerFullAccess | 鼠标点击 |
| `computer_type` | DangerFullAccess | 键盘输入文本 |
| `computer_key` | DangerFullAccess | 按键/组合键 |
| `computer_scroll` | DangerFullAccess | 滚动 |
| `computer_drag` | DangerFullAccess | 拖拽 |
| `computer_cursor_position` | ReadOnly | 获取光标位置 |

## MCP 协议支持

支持 4 种传输类型（超越 Rust 原版的纯 stdio）：

| 类型 | 配置 `type` 值 | 说明 |
|------|---------------|------|
| stdio | `stdio` | 子进程 JSON-RPC（默认） |
| SSE | `sse` | GET 接收 + POST 发送 |
| HTTP | `http` | Streamable HTTP（2025-03-26 规范） |
| WebSocket | `ws` / `websocket` | 双向 WebSocket JSON-RPC |

## 权限系统

5 级权限模式（从低到高）：

1. **READ_ONLY** — 只允许只读操作
2. **DEFAULT** — 只读自动放行，写操作需用户确认
3. **WORKSPACE_WRITE** — 工作区写操作自动放行
4. **DANGER_FULL_ACCESS** — 全部自动放行
5. **DONT_ASK** — 完全不询问

每个工具有默认所需权限级别，`PermissionPolicy` 根据当前模式决定是否自动放行。

## 配置文件

配置路径：`~/.fool-code/settings.json` 或项目目录下 `.fool-code/settings.json`

```json
{
  "api": {
    "provider": "openai",
    "apiKey": "sk-xxx",
    "baseUrl": "https://api.openai.com/v1",
    "model": "gpt-4o"
  },
  "hooks": {
    "PreToolUse": "echo pre",
    "PostToolUse": "echo post",
    "Stop": "echo stop"
  },
  "mcpServers": {
    "my-server": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "my-mcp-server"]
    }
  }
}
```

## 核心对话流程

```
用户发消息 → POST /api/chat
  → ConversationRuntime.run_turn()
    → 构建消息列表（system prompt + history + user message）
    → 调用 OpenAI 兼容 API（流式）
    → 收到 text_delta → SSE 推送给前端
    → 收到 tool_call → 权限检查 → Pre hook → 执行工具 → Post hook → SSE 推送结果
    → 循环直到无工具调用或达到最大迭代（25 次）
    → 自动 compaction 检查
    → 保存 session → SSE 推送 done + usage
```

## 开发命令

```bash
# 安装依赖
uv sync

# 开发模式（浏览器）
uv run python start.py

# 开发模式（桌面窗口）
uv run python run.py

# 仅启动后端
uv run python run.py --server-only

# 编译 Rust 扩展（Computer Use，可选）
uv pip install maturin
cd fool_code/computer_use/_native && maturin develop --release

# 打包 exe
uv run pyinstaller fool_code.spec --noconfirm

# 输出目录
dist/FoolCode/FoolCode.exe
```

## 打包注意事项

- Python 版本必须为 **3.11 ~ 3.13**（3.14 不兼容 pythonnet/pywebview）
- 前端必须先构建：在 `desktop-ui/` 下 `npm run build`
- `fool_code.spec` 已配置自动打包前端 `dist/` 目录
- 打包后的 `dist/FoolCode/` 是完整可分发目录，无需安装 Python
- **Computer Use（可选）**：如需桌面控制功能，需额外安装 Rust 工具链和 maturin，
  先 `maturin develop --release` 编译 Rust 扩展，再在 spec 文件中加入 `fool_code_cu.pyd`

## 与 Rust 原版的对比

| 特性 | Rust | Python | 说明 |
|------|------|--------|------|
| API 路由 | 17 | 19 | Python 多了 compact 和 workspace 端点 |
| 内置工具 | 20 | 20 | 完全对齐 |
| Agent 核心 | 完整 | 完整 | 多轮循环、自动压缩、stop verifier |
| 权限系统 | 5 级 | 5 级 | 完全对齐 |
| Hooks | 4 种 | 4 种 | Pre/Post/Stop/StopAgent |
| MCP 传输 | 仅 stdio | 4 种 | Python 超越原版 |
| LLM 提供商 | 多个 | OpenAI 兼容 | 按需求仅保留一个 |
| 插件系统 | 半成品 | 不实现 | Rust 自身也未完全接入 |
| LSP 上下文 | 未接入 | 不实现 | Rust 自身也未使用 |
| 斜杠命令 | 28 个 | 不实现 | CLI 交互功能，桌面应用不需要 |

## 吉祥物

项目吉祥物是一只柴犬（Shiba Inu），SVG 源文件在 `柴犬.svg`，应用图标在 `fool_code.ico`。
