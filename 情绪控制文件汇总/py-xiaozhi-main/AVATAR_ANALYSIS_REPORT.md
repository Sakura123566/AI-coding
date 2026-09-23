# py-xiaozhi 智能体形象迁移分析报告

> **日期**: 2026-07-14
> **目标**: 将当前黄色圆形表情 (黄豆 emoji GIF) 替换为科研助手机器人形象
> **附件**: `C:\Users\dista\Desktop\c645d2fa00f60d94dc11a0138a195b9a`

---

## 1. 当前黄豆资源文件位置

所有表情资源集中存放在:

```
assets/emojis/
```

包含 **21 个 GIF 动画文件** (总计约 16 MB):

| 文件名 | 大小 | 用途推测 |
|--------|------|----------|
| `angry.gif` | 499 KB | 生气 |
| `confident.gif` | 577 KB | 自信 |
| `confused.gif` | 1.19 MB | 困惑 |
| `cool.gif` | 658 KB | 酷 |
| `crying.gif` | 708 KB | 大哭 |
| `delicious.gif` | 867 KB | 好吃 |
| `embarrassed.gif` | 667 KB | 尴尬 |
| `funny.gif` | 728 KB | 搞笑 |
| `happy.gif` | 585 KB | 开心 |
| `kissy.gif` | 676 KB | 亲亲 |
| `laughing.gif` | 1.21 MB | 大笑 |
| `loving.gif` | 587 KB | 喜欢 |
| `neutral.gif` | 201 KB | 中性 (默认/兜底) |
| `relaxed.gif` | 923 KB | 放松 |
| `sad.gif` | 1.08 MB | 悲伤 |
| `shocked.gif` | 703 KB | 震惊 |
| `silly.gif` | 505 KB | 傻笑 |
| `sleepy.gif` | 779 KB | 困倦 |
| `surprised.gif` | 305 KB | 惊讶 |
| `thinking.gif` | 821 KB | 思考 |
| `winking.gif` | 671 KB | 眨眼 |

---

## 2. 当前表情资源在哪里

与第 1 节相同——所有表情 GIF 文件位于:

```
assets/emojis/
```

这是项目中唯一的智能体形象资源目录。通过 `src/utils/resource_finder.py` 的 `get_assets_dir()` 函数解析路径，EmotionService 直接在此目录下按名称查找文件。

---

## 3. 当前状态机逻辑在哪里

项目采用 **三层架构**: 常量定义 → 状态管理器 → UI 插件

### 3.1 设备状态枚举

**文件**: `src/constants/constants.py` (第 35-38 行)

```python
class DeviceState(str, Enum):
    IDLE = "idle"          # 待命
    LISTENING = "listening" # 聆听中
    SPEAKING = "speaking"   # 说话中
```

### 3.2 状态管理器

**文件**: `src/core/state_manager.py`

- `StateManager` 类管理设备状态
- 通过 `EventBus` 广播 `DEVICE_STATE_CHANGED` 事件
- 提供 `is_idle()`, `is_listening()`, `is_speaking()` 查询方法

### 3.3 UI 插件 (核心调度层)

**文件**: `src/plugins/ui.py`

- `UIPlugin` 类监听 `DEVICE_STATE_CHANGED` 事件
- `on_device_state_changed()` 更新 UI 状态文本
- `on_incoming_json()` 处理来自服务端的 `type: "llm"` 消息，提取 `emotion` 字段

### 3.4 事件定义

**文件**: `src/core/event_bus.py` (第 62 行)

```python
UI_UPDATE_EMOTION = "ui_update_emotion"  # 更新表情
```

### 3.5 事件数据类

**文件**: `src/ui/shared/events.py` (第 17-20 行)

```python
@dataclass
class UIEmotionUpdate:
    emotion: str
```

---

## 4. 当前情绪如何映射到图片

### 4.1 完整数据流

```
服务端 LLM 消息 (JSON)
  ↓ type="llm", emotion="happy"
UIPlugin.on_incoming_json()           [src/plugins/ui.py:105]
  ↓ 提取 emotion 字段
EventBus.emit(UI_UPDATE_EMOTION, UIEmotionUpdate(emotion="happy"))
  ↓
┌─────────────────┬──────────────────┬──────────────────┐
│  GUI ViewManager │  CLI ViewManager │ GPIO ViewManager │
│  [gui/manager.py]│  [cli/manager.py]│ [gpio/manager.py]│
└────────┬─────────┴────────┬─────────┴────────┬─────────┘
         ↓                  ↓                  ↓
  EmotionService       CLIDisplay           仅日志输出
  .get_emotion_url()   .update_emotion()
         ↓                  ↓
  查找文件:              更新仪表盘:
  assets/emojis/         _dash_emotion
  {name}.gif             = "happy"
         ↓
  返回 file:// URL
         ↓
  MainModel.set_emotion_url()
         ↓
  QML AnimatedImage 播放 GIF
```

### 4.2 EmotionService 文件查找逻辑

**文件**: `src/ui/gui/services/emotion_service.py` (第 57-62 行)

```python
EXTENSIONS = (".gif", ".png", ".jpg", ".jpeg", ".webp")

def _find_emotion_file(self, name: str) -> Optional[Path]:
    for ext in self.EXTENSIONS:
        file_path = self._emotion_dir / f"{name}{ext}"
        if file_path.exists():
            return file_path
    return None
```

- 按扩展名优先级: `.gif` → `.png` → `.jpg` → `.jpeg` → `.webp`
- 未找到时回退到 `neutral`
- 最终回退到 emoji 字符 `😉`

### 4.3 QML 显示组件

**文件**: `src/ui/gui/qml/windows/MainWindow.qml` (第 63-78 行)

```qml
AnimatedImage {
    source: parent.currentEmotionUrl
    fillMode: Image.PreserveAspectFit
    playing: true
    visible: ... indexOf("file://") === 0
}
Text {
    text: parent.currentEmotionUrl  // emoji fallback
    visible: ... indexOf("file://") !== 0
}
```

### 4.4 关键发现: emotion 值来源

服务端发送的 `emotion` 字段值是**自由字符串**，`EmotionService` 直接将字符串用作文件名查找。因此服务端支持的所有 emotion 值都是潜在的文件名。当前 21 个 GIF 文件名可能对应服务端支持的 emotion 值集合。

---

## 5. 当前资源格式

| 格式 | 数量 | 用途 |
|------|------|------|
| **GIF** | 21 个 | 智能体表情动画 (主要) |
| PNG | 1 个 | 应用图标 (`assets/icon.png`) |
| SVG | 1 个 | AtomGit 徽标 (`assets/AtomGit.svg`) |
| ICN | 1 个 | macOS 图标 (`assets/icon.icns`) |
| OGG | 多个 | 多语言 TTS 提示音 (`assets/sounds/`) |

**EmotionService 支持的扩展名** (优先级顺序): `.gif` > `.png` > `.jpg` > `.jpeg` > `.webp`

当前仅使用 `.gif` 格式的表情资源。

---

## 6. 更换科研机器人需要修改的文件

### 6.1 必须修改 (核心逻辑)

| # | 文件 | 修改内容 | 影响范围 |
|---|------|----------|----------|
| 1 | `assets/emojis/` | **替换为科研机器人资源** (同名 GIF 或 PNG) | 资源层 |
| 2 | `src/plugins/ui.py` | 第 105 行 `on_incoming_json()` — 在 emotion 映射阶段加入科研机器人的 8 种状态映射转换 | 核心逻辑层 |

### 6.2 建议修改 (可选优化)

| # | 文件 | 修改内容 | 影响范围 |
|---|------|----------|----------|
| 3 | `src/ui/gui/services/emotion_service.py` | 扩展支持目录，支持子目录结构 (如 `avatars/research_bot/`) | 资源查找 |
| 4 | `src/ui/gui/qml/components/EmotionDisplay.qml` | 如果机器人需要不同尺寸或动画行为 | QML 显示 |
| 5 | `src/ui/gui/qml/windows/MainWindow.qml` | 同上，主窗口的内嵌表情显示 | QML 显示 |
| 6 | `src/ui/cli/display.py` | CLI 模式仅显示文本 emotion 名，**无需修改** (无视觉效果) | — |
| 7 | `src/ui/gpio/manager.py` | 同上，**无需修改** (仅日志) | — |
| 8 | `build.json` / `py-xiaozhi.spec` | `assets:assets` 已包含整个 assets 目录，**无需修改** | — |

### 6.3 不需要修改的文件

| 文件 | 原因 |
|------|------|
| `src/core/state_manager.py` | 状态管理逻辑不变，仅管理 IDLE/LISTENING/SPEAKING 三种设备状态 |
| `src/core/event_bus.py` | 事件定义不变 |
| `src/ui/shared/events.py` | `UIEmotionUpdate` 数据类不变 |
| `src/ui/shared/models/main_model.py` | 模型属性不变 (仍然存储 emotionUrl) |
| `src/utils/resource_finder.py` | 资源路径解析不变 |

---

## 7. 8 种状态设计

### 7.1 映射策略

由于 emotion 值来自服务端 `type: "llm"` 消息，建议在 `UIPlugin.on_incoming_json()` 中增加一层**本地映射**，将服务端的原始 emotion 值映射为科研机器人的 8 种状态。

### 7.2 状态定义

| 状态 | 文件名/ID | 视觉含义 | 触发时机 |
|------|-----------|----------|----------|
| **idle** | `idle.gif` | 机器人待机，呼吸灯闪烁 | 空闲等待、连接断开 |
| **searching** | `searching.gif` | 眼睛转动扫描，天线闪烁 | 收到搜索请求、联网查询 |
| **reading** | `reading.gif` | 眼睛移动阅读，翻书动画 | 接收/解析文本内容 |
| **thinking** | `thinking.gif` | 沉思姿态，齿轮转动 | LLM 推理中 |
| **coding** | `coding.gif` | 敲键盘/代码流动 | 代码生成执行 |
| **reporting** | `reporting.gif` | 展示报告/图表 | TTS 输出中 |
| **success** | `success.gif` | 点赞/发光/庆祝 | 任务成功完成 |
| **error** | `error.gif` | 红色警告/摇头 | 出错/失败 |

### 7.3 服务端 emotion 值映射表 (预估)

```python
EMOTION_MAP = {
    # 服务端原始值 → 科研机器人状态
    "neutral":  "idle",
    "happy":    "success",
    "thinking": "thinking",
    "confused": "thinking",
    "confident":"success",
    "sad":      "error",
    "angry":    "error",
    "shocked":  "error",
    "surprised":"searching",
    "cool":     "success",
    "crying":   "error",
    "delicious":"success",
    "embarrassed":"idle",
    "funny":    "success",
    "kissy":    "success",
    "laughing": "success",
    "loving":   "success",
    "relaxed":  "idle",
    "silly":    "idle",
    "sleepy":   "idle",
    "winking":  "idle",
    # 新增直接映射 (如果服务端支持)
    "searching":"searching",
    "reading":  "reading",
    "coding":   "coding",
    "reporting": "reporting",
}
```

### 7.4 增强建议: 设备状态联动

可在 `UIPlugin` 中根据 `DeviceState` 做二次映射:

```python
STATE_EMOTION_MAP = {
    DeviceState.IDLE:      "idle",
    DeviceState.LISTENING: "searching",
    DeviceState.SPEAKING:  "reporting",
}
```

即: 设备状态提供基础表情，LLM emotion 消息提供更细粒度的覆盖。

---

## 8. 资源目录结构

### 8.1 推荐方案: 最小侵入 (替换现有 emojis 目录)

```text
assets/
├── icon.png                  # 保持不变
├── icon.icns                 # 保持不变
├── AtomGit.svg               # 保持不变
├── xiaozhi.manifest          # 保持不变
├── emojis/                   # ← 替换为科研机器人资源
│   ├── idle.gif              # 待机
│   ├── searching.gif         # 搜索中
│   ├── reading.gif           # 阅读中
│   ├── thinking.gif          # 思考中
│   ├── coding.gif            # 编码中
│   ├── reporting.gif         # 报告中
│   ├── success.gif           # 成功
│   ├── error.gif             # 错误
│   └── neutral.gif           # 兜底 (指向 idle 的副本)
└── sounds/                   # 保持不变
```

**优点**: 零代码改动 (资源层直接替换)、与现有架构完全兼容。
**缺点**: 如果服务端直接发送 "happy"/"sad" 等值，需要映射层。

### 8.2 推荐方案: 增加映射层 (更灵活)

```text
assets/
├── emojis/                   # 保持原有 21 个 GIF (回退兼容)
├── avatars/                  # ← 新增科研机器人目录
│   └── research_bot/
│       ├── idle.gif
│       ├── searching.gif
│       ├── reading.gif
│       ├── thinking.gif
│       ├── coding.gif
│       ├── reporting.gif
│       ├── success.gif
│       ├── error.gif
│       └── neutral.gif
...
```

此时需要修改 `EmotionService` 使其支持子目录。

### 8.3 高级方案: 多皮肤架构

```text
assets/
├── avatars/
│   ├── default/              # 原 emojis 目录迁移
│   │   ├── happy.gif
│   │   ├── ...
│   │   └── neutral.gif
│   └── research_bot/         # 科研机器人
│       ├── idle.gif
│       ├── ...
│       └── error.gif
```

需要在 `EmotionService` 中加入 avatar 切换逻辑，并可能在设置面板加入 Avatar 选择项。

---

## 9. 迁移方案

### 阶段 1: 准备资源 (0 代码修改)

1. **生成/获取科研机器人的 8 个状态 GIF/PNG 文件**
   - 使用附件中的科研机器人形象作为基础
   - 为每个状态 (`idle`, `searching`, `reading`, `thinking`, `coding`, `reporting`, `success`, `error`) 创建对应的动画
   - 建议格式: **GIF** (与现有架构一致，QML `AnimatedImage` 原生支持)
   - 建议尺寸: 200×200 px 以上 (与其他元素协调)
   - 文件命名: `{state}.gif`

2. **放入 `assets/emojis/` 目录**
   ```powershell
   # 备份原有资源
   Move-Item assets/emojis assets/emojis_backup
   # 创建新目录并放入资源
   New-Item -ItemType Directory assets/emojis
   Copy-Item <科研机器人GIF目录>/* assets/emojis/
   ```

### 阶段 2: 最小化修改 (推荐起步方案)

3. **修改 `src/plugins/ui.py` — 添加 emotion 映射**

   在 `UIPlugin` 类中添加映射表，修改 `on_incoming_json()` 方法:

   ```python
   # 在类体中添加
   EMOTION_MAP = {
       "neutral": "idle", "happy": "success", "thinking": "thinking",
       "confused": "thinking", "confident": "success", "sad": "error",
       "angry": "error", "shocked": "error", "surprised": "searching",
       "cool": "success", "crying": "error", "delicious": "success",
       "embarrassed": "idle", "funny": "success", "kissy": "success",
       "laughing": "success", "loving": "success", "relaxed": "idle",
       "silly": "idle", "sleepy": "idle", "winking": "idle",
       # 直通映射
       "searching": "searching", "reading": "reading",
       "coding": "coding", "reporting": "reporting",
       "success": "success", "error": "error", "idle": "idle",
   }

   # 修改 on_incoming_json (约第 104-108 行)
   # emotion = message.get("emotion")
   # ↓ 改为:
   raw_emotion = message.get("emotion")
   emotion = self.EMOTION_MAP.get(raw_emotion, "idle")
   ```

4. **修改 `src/ui/gui/services/emotion_service.py` — 支持 PNG 优先**

   如果你拿到的是 PNG 而不是 GIF:

   ```python
   EXTENSIONS = (".png", ".gif", ".jpg", ".jpeg", ".webp")  # PNG 优先
   ```

### 阶段 3: 可选增强

5. **设备状态联动** — 在 `on_device_state_changed()` 中加入状态→表情映射
6. **多皮肤支持** — 重构 `EmotionService` 支持 `avatars/{skin_name}/` 目录结构
7. **设置面板** — 在 Settings 中添加 Avatar 选择 UI

### 影响范围评估

| 修改范围 | 文件数 | 风险等级 |
|----------|--------|----------|
| 仅替换资源文件 | 0 个 .py 文件 | 🟢 极低 |
| 替换资源 + 映射层 | 1 个 .py 文件 | 🟢 低 |
| 完整多皮肤架构 | 3-5 个 .py + 1-2 个 .qml | 🟡 中 |

### 回滚方案

- 恢复 `assets/emojis/` 目录到原始内容
- Git revert `src/plugins/ui.py` 修改

---

## 附录: 关键文件索引

| 文件 | 角色 |
|------|------|
| `assets/emojis/*.gif` | 当前表情 GIF 资源 |
| `src/plugins/ui.py` | UIPlugin — emotion 处理和转发 |
| `src/ui/gui/services/emotion_service.py` | EmotionService — 文件名→URL 映射 |
| `src/ui/gui/manager.py` | GUI ViewManager — 订阅事件、更新模型 |
| `src/ui/gui/qml/windows/MainWindow.qml` | 主窗口 QML — AnimatedImage 渲染 |
| `src/ui/gui/qml/components/EmotionDisplay.qml` | EmotionDisplay 组件 |
| `src/ui/gui/qml/panels/EmotionPanel.qml` | 表情面板 (ChatPanel 中) |
| `src/ui/shared/events.py` | UIEmotionUpdate 数据类 |
| `src/ui/shared/models/main_model.py` | MainModel — emotionUrl 属性 |
| `src/core/event_bus.py` | Events 枚举 + EventBus |
| `src/core/state_manager.py` | StateManager — DeviceState 管理 |
| `src/constants/constants.py` | DeviceState 枚举 |
| `src/ui/cli/display.py` | CLI 终端显示 (emotion 仅用于文本渲染) |
| `src/ui/cli/manager.py` | CLI ViewManager |
| `src/ui/gpio/manager.py` | GPIO ViewManager |
| `src/utils/resource_finder.py` | get_assets_dir() |
| `build.json` / `py-xiaozhi.spec` | 打包配置 (assets 目录已包含) |
