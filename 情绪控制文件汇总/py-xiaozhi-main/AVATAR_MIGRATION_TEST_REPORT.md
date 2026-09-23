# Avatar Migration 测试报告

> 日期：2026-07-14
> 范围：IntelliConnect Research Assistant Avatar Migration，资源层、Emotion 映射层、GUI 资源加载层。

## 变更摘要

- 已创建 `assets/emojis_backup/`，备份原黄豆 GIF 资源 21 个。
- 已生成 8 个 Research Assistant Avatar GIF：
  - `idle.gif`
  - `searching.gif`
  - `reading.gif`
  - `thinking.gif`
  - `coding.gif`
  - `reporting.gif`
  - `success.gif`
  - `error.gif`
- 已将 active `assets/emojis/` 中 21 个旧 emotion 文件名覆盖为新 Avatar 状态副本，避免旧路径漏出黄豆形象。
- 已新增共享映射模块 `src/ui/shared/emotion_mapping.py`。
- 已更新 `src/plugins/ui.py`，支持从 `emotion`、工具名字段、MCP `tools/call` payload 中解析 Avatar 状态。
- 已更新 `src/ui/gui/services/emotion_service.py`，资源加载前统一映射 emotion，并优先回退到 `idle.gif`。

## 自动验证结果

| 验证项 | 结果 | 说明 |
| --- | --- | --- |
| 旧资源备份 | 通过 | `assets/emojis_backup/` 中 GIF 数量为 21 |
| 8 个核心状态资源 | 通过 | 均存在于 `assets/emojis/` |
| GIF 尺寸 | 通过 | 8 个核心状态均为 `512 x 512` |
| GIF 动画帧 | 通过 | 8 个核心状态均为 16 帧 |
| GIF 透明背景 | 通过 | 8 个核心状态均包含透明索引 |
| 旧 emotion 兼容文件 | 通过 | active `assets/emojis/` 中旧 emotion 文件名已映射为新 Avatar 副本 |
| Emotion 映射 | 通过 | 覆盖 `neutral/happy/confused/surprised/angry` 等旧值 |
| 科研工具名映射 | 通过 | 覆盖 `search_paper/paper_summary/paper_compare/paper_to_requirement/Codex Tool/generate_week_report` |
| MCP payload 解析 | 通过 | 可从 `tools/call.params.name` 解析状态 |
| Python 语法校验 | 通过 | `py_compile` 通过 |
| Ruff 静态检查 | 未执行 | 当前运行时没有 `ruff` 模块或可执行文件 |
| EXE 生成 | 未通过 | 本机 PyInstaller 可启动，但系统 Python 缺少 PySide6、qasync、paho、sounddevice、numpy、aiohttp、opuslib 等运行依赖，未产出 `dist/py-xiaozhi` |
| GUI 启动验证 | 未执行 | 受同一依赖缺失影响，当前环境无法完成 GUI/EXE 启动验收 |

## 映射抽样

| 输入 | 输出状态 |
| --- | --- |
| `neutral` | `idle` |
| `happy` | `success` |
| `confused` | `thinking` |
| `surprised` | `searching` |
| `angry` | `error` |
| `search_paper` | `searching` |
| `paper_summary` | `reading` |
| `paper_compare` | `thinking` |
| `paper_to_requirement` | `thinking` |
| `Codex Tool` | `coding` |
| `generate_week_report` | `reporting` |

## 验收状态

| 验收标准 | 状态 |
| --- | --- |
| 8 个 Avatar 状态资源成功加载 | 通过资源级校验 |
| 原有黄豆资源完成备份 | 通过 |
| Emotion 映射正常工作 | 通过自动映射校验 |
| 状态切换无异常 | 通过映射层校验，未进行 GUI 实机验证 |
| 所有 MCP Tool 正常运行 | 未改 MCP 功能，未进行全量工具实机验证 |
| GUI 无报错 | 未执行 |
| EXE 可正常启动 | 未通过，EXE 未生成 |
| 全流程测试通过 | 未执行端到端 GUI/EXE 流程 |

## 阻塞项

- 当前系统 Python 缺少项目运行依赖，导致 PyInstaller 未能生成最终 EXE。
- 当前工作目录的 `.git/` 为空目录，无法用 Git 对比或还原历史版本。

## 建议后续

1. 在完整项目运行环境中安装 GUI/音频/协议依赖后重新执行打包。
2. 用真实服务端消息或 MCP `tools/call` 消息验证 GUI 动态切换。
3. 若需要发布包，建议先修正项目打包配置，避免旧 `.spec` 中的 macOS 绝对路径影响 Windows 构建。
