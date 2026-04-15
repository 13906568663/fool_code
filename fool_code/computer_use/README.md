# Computer Use — Windows 桌面控制子包

> 面向后续开发者的完整技术文档。涵盖架构、构建流程、API 参考、扩展方式和故障排查。

---

## 目录

- [1. 概述](#1-概述)
- [2. 架构设计](#2-架构设计)
- [3. 环境准备与构建](#3-环境准备与构建)
- [4. 目录结构](#4-目录结构)
- [5. Rust 原生模块 API 参考](#5-rust-原生模块-api-参考)
- [6. Python 工具层 API 参考](#6-python-工具层-api-参考)
- [7. 数据流：截图如何到达 LLM](#7-数据流截图如何到达-llm)
- [8. 如何扩展](#8-如何扩展)
- [9. 打包与分发](#9-打包与分发)
- [10. 故障排查](#10-故障排查)
- [11. 卸载](#11-卸载)

---

## 1. 概述

Computer Use 是一个**自包含**的 Python 子包，为 Fool Code 提供 Windows 桌面控制能力。
AI 助手可以通过工具调用来截屏、移动鼠标、键盘输入、管理应用窗口等——实现"计算机使用"（Computer Use）。

**设计原则**：
- **独立性**：所有代码集中在 `fool_code/computer_use/` 下，对外部代码的改动最小化
- **可选性**：Rust 扩展未编译时，应用正常启动，仅跳过 Computer Use 工具注册
- **可删除性**：删除目录 + 移除 registry.py 中 6 行代码即可完全卸载

**技术栈**：

| 层 | 技术 | 说明 |
|----|------|------|
| 底层控制 | Rust + Win32 API | 截屏(GDI BitBlt)、显示器枚举(DPI-aware) |
| 输入模拟 | Rust + enigo 0.3 | 鼠标/键盘操作，跨平台库的 Windows 后端 |
| 应用管理 | Rust + Win32 API | 进程枚举(ToolHelp32)、注册表、ShellExecute |
| 剪贴板 | Rust + Win32 API | CF_UNICODETEXT 读写 |
| Python 桥接 | PyO3 0.23 | Rust → Python 函数导出 |
| 构建工具 | maturin 1.x | Rust-Python 混合包构建 |
| 图片编码 | image + base64 | RGB → JPEG → base64（可调质量） |

---

## 2. 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│  LLM (OpenAI / 兼容 API)                                    │
│  ← tool_result 含 image_url(base64 JPEG)                    │
├─────────────────────────────────────────────────────────────┤
│  message_pipeline.py                                        │
│  ToolResult.images → multimodal content (image_url block)   │
├─────────────────────────────────────────────────────────────┤
│  conversation.py                                            │
│  ToolResult → ContentBlock(type="image", inline_data=b64)   │
├─────────────────────────────────────────────────────────────┤
│  tools.py — 8 个 ToolHandler                                 │
│  ScreenshotTool, ClickTool, TypeTool, KeyTool, ...          │
├─────────────────────────────────────────────────────────────┤
│  executor.py — Python 薄封装层                               │
│  graceful fallback (AVAILABLE = True/False)                  │
├─────────────────────────────────────────────────────────────┤
│  fool_code_cu — Rust PyO3 原生扩展 (.pyd / .so)              │
│  screen.rs | input.rs | apps.rs | clipboard.rs | display.rs │
├─────────────────────────────────────────────────────────────┤
│  Windows OS                                                  │
│  GDI / SendInput / ToolHelp32 / Registry / Clipboard API    │
└─────────────────────────────────────────────────────────────┘
```

### 关键设计决策

1. **为什么用 Rust 而不是 ctypes/pywin32？**
   - 性能：截屏操作涉及大量内存拷贝和 JPEG 编码，Rust release 模式下速度比纯 Python 快 10-50x
   - 安全：Rust 编译期检查 Win32 API 参数类型，减少运行时段错误
   - 依赖：enigo 库提供成熟的跨平台输入模拟，比自己调 SendInput 更可靠

2. **为什么 JPEG 而不是 PNG？**
   - LLM 视觉模型对 JPEG 和 PNG 处理效果一致
   - JPEG 在 quality=75 时，base64 大小约为 PNG 的 1/5~1/10，大幅减少 token 消耗

3. **为什么 base64 内联而不是文件引用？**
   - 截图是短生命周期数据，不需要持久存储
   - 内联传输避免了文件系统清理问题
   - 通过 `ContentBlock.inline_data` 与已有的 `external_path`（用户上传图片）区分

---

## 3. 环境准备与构建

### 3.1 前置条件

| 依赖 | 最低版本 | 检查命令 |
|------|---------|---------|
| Rust toolchain | stable 1.70+ | `rustc --version` |
| Python | 3.11 ~ 3.13 | `python --version` |
| maturin | 1.0+ | `maturin --version`（安装后） |
| Visual Studio Build Tools | 2019+ | `cl` 可用（Rust 编译 Windows API 需要） |

### 3.2 安装 maturin

```bash
# 使用 uv（推荐，与项目包管理一致）
uv pip install maturin --python .venv/Scripts/python.exe

# 或使用 pip
pip install maturin
```

### 3.3 编译 Rust 扩展

```bash
cd fool_code/computer_use/_native

# 开发模式（直接安装到当前 venv，推荐日常开发）
maturin develop --release

# 如果 maturin 找不到 Python，手动指定：
$env:PYO3_PYTHON = "D:\workPath\fool-code-python\.venv\Scripts\python.exe"
$env:VIRTUAL_ENV = "D:\workPath\fool-code-python\.venv"
maturin develop --release
```

### 3.4 验证安装

```python
import fool_code_cu

# 基础功能验证
print(fool_code_cu.get_display_size())    # {'display_id': ..., 'width': 1920, ...}
print(fool_code_cu.get_cursor_position()) # (x, y)

# 截屏验证
b64, w, h = fool_code_cu.screenshot(50)
print(f"Screenshot: {w}x{h}, base64 length: {len(b64)}")

# 前台窗口检测
print(fool_code_cu.get_foreground_app())  # {'pid': ..., 'title': ..., 'exe': ...}
```

### 3.5 构建 wheel 包（用于分发）

```bash
cd fool_code/computer_use/_native

# 构建 wheel（不安装到当前环境）
maturin build --release

# 产物在 target/wheels/ 下，如：
# fool_code_cu-0.1.0-cp313-cp313-win_amd64.whl
```

---

## 4. 目录结构

```
fool_code/computer_use/
├── __init__.py          # 入口：register_computer_use(registry) 函数
├── types.py             # 数据类型定义（DisplayInfo, AppInfo 等）
├── executor.py          # Rust 模块薄封装，graceful fallback
├── tools.py             # 8 个 ToolHandler 实现
├── README.md            # 本文档
│
└── _native/             # Rust PyO3 原生扩展源码
    ├── Cargo.toml       # Rust 依赖声明
    ├── Cargo.lock       # Rust 依赖锁定
    ├── pyproject.toml   # maturin 构建配置
    └── src/
        ├── lib.rs       # PyO3 模块入口，注册所有导出函数
        ├── screen.rs    # 截屏：GDI BitBlt → RGB → JPEG → base64
        ├── display.rs   # 显示器枚举：EnumDisplayMonitors + DPI 感知
        ├── input.rs     # 鼠标键盘：enigo 封装 + Win32 GetCursorPos
        ├── clipboard.rs # 剪贴板：CF_UNICODETEXT 读写
        └── apps.rs      # 应用管理：进程列表、注册表应用、ShellExecute
```

### 对外部文件的改动（共 4 个文件、约 25 行）

| 文件 | 改动 | 说明 |
|------|------|------|
| `tools/registry.py` | +6 行 | `is_windows` 时条件导入并注册 |
| `tools/tool_protocol.py` | +1 行 | `ToolResult` 添加 `images: list[str]` 字段 |
| `types.py` | +1 行 | `ContentBlock` 添加 `inline_data: str \| None` 字段 |
| `runtime/conversation.py` | +7 行 | tool result 附加 image blocks |
| `runtime/message_pipeline.py` | +16 行 | tool result 支持多模态 image_url 内容 |

---

## 5. Rust 原生模块 API 参考

模块名：`fool_code_cu`（编译后为 `fool_code_cu.pyd`）

### 截屏

| 函数 | 签名 | 返回值 | 说明 |
|------|------|--------|------|
| `screenshot` | `(quality=75) → (str, int, int)` | (base64_jpeg, width, height) | 全屏截图 |
| `screenshot_region` | `(x, y, w, h, quality=75) → (str, int, int)` | (base64_jpeg, width, height) | 区域截图 |

`quality` 参数范围 1~100，推荐 50~75，越低文件越小但画质越差。

### 显示器

| 函数 | 签名 | 返回值 |
|------|------|--------|
| `get_display_size` | `() → dict` | `{display_id, width, height, scale_factor, origin_x, origin_y}` |
| `list_displays` | `() → list[dict]` | 所有显示器列表，字段同上 |

### 鼠标

| 函数 | 签名 | 说明 |
|------|------|------|
| `move_mouse` | `(x, y)` | 移动光标到绝对坐标 |
| `click` | `(x, y, button="left", count=1)` | 点击。button: left/right/middle |
| `mouse_down` | `()` | 按下左键 |
| `mouse_up` | `()` | 释放左键 |
| `scroll` | `(x, y, dx, dy)` | 在 (x,y) 处滚动。dy>0 向上 |
| `drag` | `(to_x, to_y, from_x=None, from_y=None)` | 拖拽。from 为 None 时从当前位置开始 |
| `get_cursor_position` | `() → (int, int)` | 获取当前光标位置 |

### 键盘

| 函数 | 签名 | 说明 |
|------|------|------|
| `key` | `(key_sequence, repeat=1)` | 按键组合，如 `"ctrl+c"`、`"alt+tab"` |
| `type_text` | `(text)` | 输入文本字符串（支持 Unicode） |
| `hold_key` | `(keys, duration_ms)` | 按住键一段时间，keys 为字符串列表 |

**支持的键名**：`ctrl`/`control`、`alt`、`shift`、`meta`/`win`、`enter`/`return`、`tab`、`space`、`backspace`、`delete`、`escape`/`esc`、`up`/`down`/`left`/`right`、`home`、`end`、`pageup`、`pagedown`、`f1`~`f12`、`capslock`，以及所有单字符（如 `a`、`1`、`/`）。

### 剪贴板

| 函数 | 签名 | 说明 |
|------|------|------|
| `read_clipboard` | `() → str` | 读取剪贴板文本（无文本时返回空字符串） |
| `write_clipboard` | `(text)` | 写入文本到剪贴板 |

### 应用管理

| 函数 | 签名 | 返回值 |
|------|------|--------|
| `get_foreground_app` | `() → dict \| None` | `{pid, title, exe}` 或 None |
| `list_running_apps` | `() → list[dict]` | `[{pid, name, exe}]` 所有进程 |
| `list_installed_apps` | `() → list[dict]` | `[{name, path, exe}]` 从注册表读取 |
| `open_app` | `(exe_path)` | 通过 ShellExecute 打开应用 |
| `app_under_point` | `(x, y) → dict \| None` | 坐标下的窗口信息 |

---

## 6. Python 工具层 API 参考

以下工具在 AI 对话中可被 LLM 调用：

| 工具名 | 分类 | 只读 | 并发安全 | 说明 |
|--------|------|------|---------|------|
| `computer_screenshot` | meta | ✅ | ✅ | 全屏截图，返回 JPEG 图片 |
| `computer_screenshot_region` | meta | ✅ | ✅ | 区域截图 |
| `computer_click` | execution | ❌ | ❌ | 鼠标点击 |
| `computer_type` | execution | ❌ | ❌ | 键盘输入文本 |
| `computer_key` | execution | ❌ | ❌ | 按键/组合键 |
| `computer_scroll` | execution | ❌ | ❌ | 滚动 |
| `computer_drag` | execution | ❌ | ❌ | 拖拽 |
| `computer_cursor_position` | meta | ✅ | ✅ | 获取光标位置 |

所有 execution 类工具需要用户权限确认（遵循全局权限策略）。

---

## 7. 数据流：截图如何到达 LLM

```
1. LLM 调用 computer_screenshot 工具
      ↓
2. ScreenshotTool.execute()
      ↓ 调用
3. executor.screenshot(quality=75)
      ↓ 调用
4. fool_code_cu.screenshot(75)  ← Rust 原生函数
      ↓ GDI BitBlt 截屏 → RGB → JPEG 编码 → base64
5. 返回 (base64_str, width, height)
      ↓
6. ToolResult(output="Screenshot: 1920x1080", images=[base64_str])
      ↓
7. conversation.py: 为 tool_result 消息追加 ContentBlock(type="image", inline_data=base64)
      ↓
8. message_pipeline.py normalize_for_api():
   tool result 消息被转换为:
   {
     "role": "tool",
     "tool_call_id": "...",
     "content": [
       {"type": "text", "text": "Screenshot: 1920x1080"},
       {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
     ]
   }
      ↓
9. LLM 收到截图，分析屏幕内容，决定下一步操作
```

---

## 8. 如何扩展

### 8.1 添加新的 Rust 函数

1. 在 `_native/src/` 对应模块中添加 `#[pyfunction]` 函数
2. 在 `_native/src/lib.rs` 中 `m.add_function(wrap_pyfunction!(...))` 注册
3. 在 `executor.py` 中添加 Python 封装函数
4. 重新 `maturin develop --release`

### 8.2 添加新的 Python 工具

1. 在 `tools.py` 中定义新的 `ToolHandler` 子类
2. 将类添加到 `ALL_TOOLS` 列表
3. 无需其他改动，`__init__.py` 会自动遍历注册

### 8.3 添加 Cargo 依赖

编辑 `_native/Cargo.toml`，添加依赖后重新构建。如果用到新的 `windows` crate feature，
在 `[dependencies.windows]` 的 `features` 列表中添加。

常用 Windows feature 参考：
- `Win32_Graphics_Gdi` — GDI 绑定（截屏）
- `Win32_UI_WindowsAndMessaging` — 窗口消息（GetCursorPos、GetForegroundWindow）
- `Win32_System_Threading` — 进程操作（OpenProcess、QueryFullProcessImageName）
- `Win32_System_Registry` — 注册表操作
- `Win32_UI_HiDpi` — DPI 感知（GetDpiForMonitor）

---

## 9. 打包与分发

### 9.1 开发模式（本机调试）

```bash
cd fool_code/computer_use/_native
maturin develop --release
```

这会编译 `.pyd` 并直接安装到当前 venv，修改 Rust 代码后重新执行即可。

### 9.2 构建 wheel 分发

```bash
maturin build --release
# 产物: target/wheels/fool_code_cu-0.1.0-cp313-cp313-win_amd64.whl
```

wheel 文件可以通过 `pip install xxx.whl` 安装到任何兼容的 Python 环境。

**注意**：wheel 是平台和 Python 版本绑定的（如 `cp313-win_amd64` 表示 CPython 3.13 + Windows x64）。如需支持多版本需分别构建。

### 9.3 PyInstaller 打包

PyInstaller 打包时，需要确保 `fool_code_cu.pyd` 被包含在产物中：

```python
# FoolCode.spec 中添加 hiddenimport
hiddenimports=['fool_code_cu']

# 或手动指定 binary
binaries=[
    (r'.venv\Lib\site-packages\fool_code_cu\fool_code_cu.pyd', 'fool_code_cu'),
]
```

也可以在 spec 文件的 `datas` 或 `binaries` 中直接包含 `.pyd` 文件。
打包后无需安装 Rust 或 maturin，`.pyd` 是自包含的动态链接库。

### 9.4 与纯 Python 打包的区别

| 项目 | 之前（纯 Python） | 现在（Python + Rust） |
|------|-------------------|---------------------|
| 运行时依赖 | `pip install -e .` | 额外需要 `maturin develop --release` |
| 构建环境 | 仅 Python + uv | 额外需要 Rust toolchain + VS Build Tools |
| wheel 分发 | 纯 Python wheel（universal） | 平台绑定 wheel（需按 OS+Python 版本构建） |
| PyInstaller | 直接打包 | 需在 spec 中加 `fool_code_cu.pyd` |
| CI/CD | 仅需 Python 镜像 | 需 Rust + Python 双工具链镜像 |
| 可选性 | — | Rust 扩展是可选的，缺失时 Computer Use 功能不可用，其他功能不受影响 |

### 9.5 CI/CD 建议

```yaml
# GitHub Actions 示例片段
- uses: actions-rust-lang/setup-rust-toolchain@v1
- uses: actions/setup-python@v5
  with:
    python-version: '3.13'
- run: pip install maturin
- run: cd fool_code/computer_use/_native && maturin build --release
```

---

## 10. 故障排查

### maturin develop 报错 "no Python 3.x interpreter found"

设置环境变量指向正确的 Python 路径：

```powershell
$env:PYO3_PYTHON = "D:\path\to\.venv\Scripts\python.exe"
$env:VIRTUAL_ENV = "D:\path\to\.venv"
maturin develop --release
```

### cargo check 报错 "link.exe not found" 或 MSVC 相关错误

安装 Visual Studio Build Tools，确保勾选了"使用 C++ 的桌面开发"工作负载。
或安装 Visual Studio Community 也可以。

### 运行时 ImportError: cannot import fool_code_cu

Rust 扩展未编译或未安装到当前 venv。执行：

```bash
cd fool_code/computer_use/_native
maturin develop --release
```

### 截图返回黑屏

可能原因：
- 远程桌面（RDP）会话中 GDI 截屏有限制
- DPI 缩放导致坐标偏移（scale_factor != 1.0 时需换算）

### 键盘输入中文乱码

`type_text` 使用 enigo 的 Unicode 输入，应能正确处理中文。如果不行，
尝试先将文本写入剪贴板再用 `key("ctrl+v")` 粘贴。

---

## 11. 卸载

完全移除 Computer Use 功能只需 3 步：

1. **删除目录**：`rm -r fool_code/computer_use/`

2. **移除注册代码**（`tools/registry.py` 中删除以下代码块）：
   ```python
   # --- Computer Use (Windows, optional — remove this block to uninstall) ---
   if is_windows:
       try:
           from fool_code.computer_use import register_computer_use
           register_computer_use(registry)
       except Exception:
           pass
   ```

3. **卸载 Python 包**：`pip uninstall fool_code_cu`

对 `tool_protocol.py`、`types.py`、`conversation.py`、`message_pipeline.py` 的改动
可以保留（它们是向后兼容的泛化改动，不依赖 Computer Use 包的存在）。
