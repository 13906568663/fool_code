# Fool Code (Python)

一个面向桌面场景的 AI 编程助手，采用 **Python + FastAPI + React + pywebview** 架构实现。  
支持 OpenAI 兼容模型、工具调用、权限控制、多会话管理、MCP 扩展，并可打包为 Windows 可执行程序。

---

## 灵感来源

- **Claude Code**：借鉴了“对话 + 工具调用 + 权限确认”的交互范式，以及工程化代理工作流体验
- **Hermes（部分设计）**：参考了技能沉淀/复用思路，用于构建本地 Skill Store 与技能创建链路
- **本项目扩展**：在桌面形态下强化了本地记忆系统、MCP 多协议接入、可选 Computer Use 能力，并重做了更有交互感的宠物系统

---

## 项目特性

- 桌面应用体验：`pywebview` 承载前端，默认本地启动 FastAPI 服务
- 实时流式对话：基于 SSE 推送文本增量、工具调用结果、状态事件
- 工具系统：内置文件读写、搜索、Shell、Notebook、Web 等工具
- 权限体系：5 级权限模式，支持细粒度的工具执行确认
- 多会话管理：会话创建、切换、删除、压缩（长对话整理）
- MCP 集成：支持 `stdio`、`sse`、`http`、`ws` 多传输协议
- 可选原生能力：Rust + PyO3 扩展提供 Windows Computer Use 工具
- 技能创建与检索：支持批量扫描导入技能、语义检索、关系图谱、反馈闭环
- 记忆系统（特色）：支持结构化记忆 + MAGMA 情节记忆，长期上下文可回溯和查询
- 聊天宠物系统：宠物可在聊天区域内上下活动，并与聊天输入/输出过程形成轻量交互反馈

---

## 特色能力说明

### 1) 技能创建（Skill Store）

- 支持从工作区扫描技能文档并导入到本地 Skill Store
- 支持技能启用/停用、置顶、元信息编辑、关系查看、重建索引
- 支持语义检索（embedding）+ 关键词融合召回，提升命中率
- 支持记录使用反馈，便于后续优化技能质量与排序策略

### 2) 记忆系统（Memory + MAGMA）

- **静态记忆层**：按类型维护可编辑记忆（偏好、规则、上下文信息）
- **情节记忆层（MAGMA）**：把历史事件写入本地记忆图，支持事件、实体、节点查询
- **开关可控**：可在设置中独立启停自动记忆与 MAGMA
- **本地优先**：记忆数据默认保存在本机目录，便于审计、备份与迁移

### 3) 聊天宠物系统（UI Buddy）

- 相比传统静态挂件式宠物，这套实现更强调与聊天界面的联动感
- 宠物在聊天框区域内可进行上下活动，降低长时间对话过程的单调感
- 通过轻量动画和状态反馈提升“陪伴感”，但不干扰主工作流
- 作为 UI 层能力独立实现，便于后续扩展更多动作和交互事件

![UI Buddy 在聊天区交互演示](docs/images/ui-buddy-chat.png)

---

## 技术栈

- **后端**: FastAPI, Uvicorn, Pydantic, sse-starlette
- **前端**: React 18, Vite, TailwindCSS（目录：`desktop-ui`）
- **桌面壳**: pywebview
- **请求/模型**: httpx + OpenAI 兼容 API
- **原生扩展（可选）**: Rust, PyO3, maturin
- **包管理**: uv
- **构建打包**: PyInstaller

---

## 项目结构

```text
fool-code-python/
├─ fool_code/                # Python 主代码
│  ├─ app.py                 # FastAPI 应用与 API 路由
│  ├─ main.py                # 桌面入口（启动服务 + webview）
│  ├─ runtime/               # 对话运行时、权限、配置、会话持久化
│  ├─ tools/                 # 内置工具实现与注册
│  ├─ mcp/                   # MCP 客户端与多传输协议支持
│  ├─ computer_use/          # Computer Use 能力（可选，含 Rust 扩展）
│  └─ ...                    # 其他核心模块
├─ desktop-ui/               # 前端工程（React + Vite）
├─ tests/                    # 测试用例
├─ run.py                    # 启动桌面模式
├─ start.py                  # 启动开发模式（浏览器）
└─ pyproject.toml            # Python 项目配置
```

---

## 环境要求

- Python `>=3.11,<3.14`
- Node.js `>=18`（前端开发/构建）
- 推荐操作系统：Windows 10/11（Computer Use 主要面向 Windows）
- 可选：Rust toolchain（需要编译原生扩展时）

---

## 快速开始

### 1) 克隆与安装依赖

```bash
git clone https://github.com/13906568663/fool_code.git
cd fool_code_python
uv sync
```

### 2) 安装前端依赖（首次）

```bash
cd desktop-ui
npm install
cd ..
```

### 3) 启动项目

```bash
# 桌面模式（优先）
uv run python run.py

# 浏览器模式（开发常用）
uv run python start.py

# 仅后端服务
uv run python run.py --server-only
```

---

## 配置说明

应用启动后可在 UI 设置里配置模型，也可直接维护本地配置文件：

- 用户级：`~/.fool-code/settings.json`
- 项目级：`.fool-code/settings.json`

最小配置示例：

```json
{
  "api": {
    "provider": "openai",
    "apiKey": "sk-xxx",
    "baseUrl": "https://api.openai.com/v1",
    "model": "gpt-4o"
  }
}
```

### 进阶配置（向量库与记忆）

项目包含两套本地向量检索能力（由 Rust 原生模块提供）：

- **MAGMA 向量记忆库**：`~/.fool-code/data/magma.db`
- **Skill Store 向量库**：`~/.fool-code/data/skills.db`

可通过配置控制开关与 embedding 模型：

```json
{
  "autoMemoryEnabled": true,
  "magmaMemoryEnabled": true,
  "skillStoreEnabled": true,
  "embeddingConfig": {
    "baseUrl": "https://api.openai.com/v1",
    "apiKey": "sk-xxx",
    "model": "text-embedding-3-small"
  }
}
```

说明：

- `autoMemoryEnabled`：控制通用自动记忆开关
- `magmaMemoryEnabled`：控制 MAGMA 情节记忆是否启用
- `skillStoreEnabled`：控制 Skill Store 是否启用
- `embeddingConfig`：用于语义检索/向量写入的独立 embedding 配置

---

## 开发指南

### 运行测试

```bash
uv run pytest
```

### 代码质量（如安装了 ruff）

```bash
uv run ruff check .
```

### 前端开发

```bash
cd desktop-ui
npm run dev
```

### 构建前端资源

```bash
cd desktop-ui
npm run build
cd ..
```

---

## 打包发布（Windows）

```bash
uv run pyinstaller fool_code.spec --noconfirm
```

输出目录示例：

- `dist/FoolCode/`

说明：

- 打包前请先完成前端构建（`desktop-ui/dist`）
- 若需要 Computer Use 原生能力，请先编译对应 Rust 扩展

---

## Computer Use（可选能力）

`fool_code/computer_use/_native` 提供 Rust 扩展源码。  
如果你需要截图、点击、键入、拖拽等桌面自动化能力，可按模块文档进行构建和集成。

相关说明见：

- `fool_code/computer_use/README.md`

---

## Roadmap（计划）

- [ ] 完善跨平台适配（Linux/macOS）
- [ ] 增强模型供应商配置体验
- [ ] 增加更多开箱即用 MCP 模板
- [ ] 补齐更系统化的 E2E 测试
- [ ] 持续优化桌面交互与性能

---

## 贡献指南

欢迎 Issue / PR。

建议流程：

1. Fork 仓库并创建功能分支
2. 提交变更并补充必要测试
3. 保持提交清晰（推荐小步提交）
4. 发起 PR，描述改动动机与验证方式

如果改动较大，建议先开 Issue 讨论方向。

---

## 安全与隐私

- API Key 仅保存在本地配置文件，请勿提交到仓库
- 请确保 `.env`、本地日志、编译产物等敏感/临时文件被忽略
- 开启危险权限模式前，请确认当前工作区可信

---

## 许可证

本项目倾向于**尽可能宽松的开源方式**，允许他人自由使用、修改、再分发。  
建议采用 `The Unlicense`（或 `CC0-1.0`）作为许可证，以表达“基本不设限制”的授权意图。

> 提示：即便是超宽松授权，也建议补充免责声明条款（软件按“现状”提供，不承担担保责任）。

---

## 致谢

感谢所有提出建议、提交问题与贡献代码的开发者。  
如果这个项目对你有帮助，欢迎点个 Star 支持。

