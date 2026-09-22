# 科研助手机器人形象迁移方案

> **日期**: 2026-07-14
> **原形象**: 黄豆 (soybean emoji — 21 个 GIF 表情动画)
> **新形象**: 科研助手机器人 (Research Assistant Bot)
> **原则**: 保持窗口布局、表情切换机制、状态机逻辑不变

---

## 1. 当前系统架构回顾

### 1.1 资源层

```
assets/emojis/
├── angry.gif        (499 KB)
├── confident.gif    (577 KB)
├── confused.gif     (1.19 MB)
├── cool.gif         (658 KB)
├── crying.gif       (708 KB)
├── delicious.gif    (867 KB)
├── embarrassed.gif  (667 KB)
├── funny.gif        (728 KB)
├── happy.gif        (585 KB)
├── kissy.gif        (676 KB)
├── laughing.gif     (1.21 MB)
├── loving.gif       (587 KB)
├── neutral.gif      (201 KB)  ← 默认/兜底
├── relaxed.gif      (923 KB)
├── sad.gif          (1.08 MB)
├── shocked.gif      (703 KB)
├── silly.gif        (505 KB)
├── sleepy.gif       (779 KB)
├── surprised.gif    (305 KB)
├── thinking.gif     (821 KB)
└── winking.gif      (671 KB)
```

21 个 GIF，总计约 16 MB。

### 1.2 数据流

```
服务端 LLM 消息 (JSON)
  ↓ type="llm", emotion="happy"
src/plugins/ui.py : UIPlugin.on_incoming_json()
  ↓ 提取 emotion 字段，调用 EmotionService
src/ui/gui/services/emotion_service.py : EmotionService.get_emotion_url()
  ↓ 按扩展名优先级查找: .gif → .png → .jpg → .jpeg → .webp
  ↓ 未找到回退 neutral → emoji "😉"
src/ui/gui/manager.py : ViewManager._on_update_emotion()
  ↓ 调用 MainModel.set_emotion_url()
src/ui/shared/models/main_model.py : MainModel.emotionUrl (QML Property)
  ↓ QML 信号通知
src/ui/gui/qml/windows/MainWindow.qml : AnimatedImage
  ↓ 渲染为 QML AnimatedImage (GIF) 或 Text (emoji 回退)
```

### 1.3 状态机（不修改）

```python
# src/constants/constants.py
class DeviceState(str, Enum):
    IDLE = "idle"           # 待命
    LISTENING = "listening"   # 聆听中
    SPEAKING = "speaking"     # 说话中
```

### 1.4 表情查找逻辑

```python
# src/ui/gui/services/emotion_service.py
EXTENSIONS = (".gif", ".png", ".jpg", ".jpeg", ".webp")

def _find_emotion_file(self, name: str) -> Optional[Path]:
    for ext in self.EXTENSIONS:
        file_path = self._emotion_dir / f"{name}{ext}"
        if file_path.exists():
            return file_path
    return None
```

---

## 2. 新形象资源目录结构

### 2.1 推荐方案：子目录隔离

在 `assets/emojis/` 下创建 `research_bot/` 子目录，原有黄豆资源备份到 `_soybean_backup/`：

```
assets/emojis/
├── _soybean_backup/           ← 原 21 个 GIF 备份 (保留不动)
│   ├── angry.gif
│   ├── happy.gif
│   └── ...
├── research_bot/              ← 科研机器人资源
│   ├── idle.gif        (或 .png/.webp)
│   ├── searching.gif
│   ├── reading.gif
│   ├── thinking.gif
│   ├── coding.gif
│   ├── reporting.gif
│   ├── success.gif
│   ├── error.gif
│   └── neutral.gif     ← 兜底/默认
└── neutral.gif / neutral.png  ← 根级兜底 (可选，EmotionService 回退用)
```

### 2.2 资源文件要求

| 参数 | 建议值 | 说明 |
|------|--------|------|
| 格式 | **GIF** (首选) 或 PNG/WebP | QML `AnimatedImage` 原生支持 GIF 动画；静态可用 PNG |
| 尺寸 | ≥ 200×200 px | EmotionDisplay: 200×200 隐式尺寸；MainWindow 动态缩放到 max(70%容器, 60px) |
| 比例 | 1:1 (正方形) | `fillMode: Image.PreserveAspectFit` |
| 背景 | 透明 (推荐) | 当前 EmotionDisplay 无背景色，透明可与主题融合 |
| 总大小 | ≤ 15 MB | 避免打包体积过大 |
| 命名 | `{state}.gif` | 严格小写，与映射名一致 |

---

## 3. 状态资源映射

### 3.1 8 个新状态 → 资源文件

| 状态名 | 文件名 | 含义 | 触发场景 |
|--------|--------|------|----------|
| `idle` | `idle.gif` | 待命中 (呼吸灯/眨眼) | 设备 State.IDLE，默认状态 |
| `searching` | `searching.gif` | 搜索中 (转动眼球/扫描) | LLM 工具调用：搜索 |
| `reading` | `reading.gif` | 阅读中 (文档/眼镜) | LLM 工具调用：read_file |
| `thinking` | `thinking.gif` | 思考中 (计算/沉思) | LLM 推理阶段 |
| `coding` | `coding.gif` | 编码中 (键盘输入) | LLM 工具调用：写代码 |
| `reporting` | `reporting.gif` | 汇报中 (幻灯片/图表) | LLM 生成报告 |
| `success` | `success.gif` | 成功 (绿色勾/星星) | 操作成功完成 |
| `error` | `error.gif` | 错误 (红色叉/警告) | 操作失败/网络错误 |

### 3.2 旧表情 → 新状态映射表

当服务端仍返回旧的 21 种 emotion 名称时，通过映射表转换：

```python
EMOTION_MAP = {
    # --- 服务端原始情绪 → 新状态 ---
    "neutral":      "idle",
    "relaxed":      "idle",
    "sleepy":       "idle",
    "silly":        "idle",
    "embarrassed":  "idle",
    "winking":      "idle",

    "searching":    "searching",   # 直通
    "reading":      "reading",     # 直通
    "thinking":     "thinking",    # 直通
    "confused":     "thinking",

    "coding":       "coding",      # 直通
    "reporting":    "reporting",   # 直通

    "happy":        "success",
    "confident":    "success",
    "cool":         "success",
    "delicious":    "success",
    "funny":        "success",
    "kissy":        "success",
    "laughing":     "success",
    "loving":       "success",

    "sad":          "error",
    "angry":        "error",
    "shocked":      "error",
    "surprised":    "error",
    "crying":       "error",

    # --- 新状态直通 ---
    "idle":         "idle",
    "success":      "success",
    "error":        "error",
}
```

### 3.3 设备状态联动（可选增强）

将底层的 `DeviceState` 也映射到表情：

| DeviceState | → 建议表情 |
|-------------|-----------|
| `IDLE` | `idle` |
| `LISTENING` | `searching` (正在聆听/录音) |
| `SPEAKING` | `reporting` (正在播放语音) |

---

## 4. 需要修改的文件清单

### 4.1 必须修改 (最小化方案)

| # | 文件 | 修改内容 | 风险 |
|---|------|----------|------|
| 1 | `src/plugins/ui.py` | 添加 `EMOTION_MAP` 字典；修改 `on_incoming_json()` 中 emotion 取值逻辑，使用 `EMOTION_MAP.get(raw_emotion, "idle")` | 🟢 低 |
| 2 | `src/ui/gui/services/emotion_service.py` | `_emotion_dir` 改为 `get_assets_dir() / "emojis" / "research_bot"` (指向子目录)；或扩展支持子目录查找；可同时保留对子目录 `research_bot/` 的查找 | 🟢 低 |

### 4.2 可选修改 (增强方案)

| # | 文件 | 修改内容 | 风险 |
|---|------|----------|------|
| 3 | `src/ui/gui/services/emotion_service.py` | `EXTENSIONS` 调整优先级 (如 PNG 优先于 GIF)；添加 `clear_cache()` + `preload()` 用于热切换 | 🟡 中 |
| 4 | `src/plugins/ui.py` | `on_device_state_changed()` 中加入设备状态→表情的联动映射 | 🟡 中 |
| 5 | `src/ui/gui/qml/windows/MainWindow.qml` | 如需调整表情显示区域大小或添加过渡动画 | 🟡 中 |
| 6 | `src/ui/gui/qml/components/EmotionDisplay.qml` | 同上 | 🟡 中 |

### 4.3 不需要修改的文件

| 文件 | 原因 |
|------|------|
| `src/constants/constants.py` | DeviceState 枚举不变 |
| `src/core/state_manager.py` | 状态管理逻辑不变 |
| `src/core/event_bus.py` | 事件定义不变 |
| `src/ui/shared/events.py` | UIEmotionUpdate 数据类不变 |
| `src/ui/shared/models/main_model.py` | MainModel.emotionUrl 属性不变 |
| `src/ui/gui/manager.py` | ViewManager 事件订阅和转发不变 |
| `src/ui/gui/qml/panels/EmotionPanel.qml` | ChatPanel 引用不变 |
| `src/ui/cli/display.py` | CLI 仅文本渲染，不受影响 |
| `build.json` / `py-xiaozhi.spec` | 已包含 `assets:assets`，新增子目录自动打包 |
| `src/utils/resource_finder.py` | get_assets_dir() 不变 |

---

## 5. 详细修改内容 (伪代码级)

### 5.1 `src/plugins/ui.py` — 添加 emotion 映射

**修改位置**：`on_incoming_json()` 方法，约第 104–108 行

**当前代码**：
```python
elif msg_type == "llm":
    if emotion := message.get("emotion"):
        if self.view_manager:
            if self._is_gui:
                url = self.view_manager._emotion_service.get_emotion_url(emotion)
                self.view_manager.main_model.set_emotion_url(url)
            else:
                self.view_manager.set_emotion(emotion)
```

**修改后**：
```python
# 在类体中添加映射表 (约 Class definition 之后)
EMOTION_MAP = {
    "neutral": "idle",   "relaxed": "idle",   "sleepy": "idle",
    "silly": "idle",     "embarrassed": "idle","winking": "idle",
    "happy": "success",  "confident": "success","cool": "success",
    "delicious": "success","funny": "success",  "kissy": "success",
    "laughing": "success","loving": "success",
    "sad": "error",      "angry": "error",     "shocked": "error",
    "surprised": "error","crying": "error",
    "confused": "thinking","thinking": "thinking",
    "idle": "idle",      "success": "success", "error": "error",
    "searching": "searching","reading": "reading","coding": "coding",
    "reporting": "reporting",
}

# 修改 on_incoming_json 中的 emotion 处理
elif msg_type == "llm":
    if raw_emotion := message.get("emotion"):
        emotion = self.EMOTION_MAP.get(raw_emotion, "idle")  # ← 新增
        if self.view_manager:
            if self._is_gui:
                url = self.view_manager._emotion_service.get_emotion_url(emotion)
                self.view_manager.main_model.set_emotion_url(url)
            else:
                self.view_manager.set_emotion(emotion)
```

### 5.2 `src/ui/gui/services/emotion_service.py` — 指向子目录

**修改位置**：`__init__` 方法，约第 26 行

**当前代码**：
```python
self._emotion_dir = get_assets_dir() / "emojis"
```

**方案 A（推荐 — 简单直接）**：
```python
self._emotion_dir = get_assets_dir() / "emojis" / "research_bot"
```

**方案 B（多皮肤兼容）**：
```python
self._skin = "research_bot"  # 可改为配置驱动
self._emotion_dir = get_assets_dir() / "emojis" / self._skin
```

**方案 C（保持根目录兼容 + 子目录优先）**：
```python
self._skin_dir = get_assets_dir() / "emojis" / "research_bot"
self._root_dir = get_assets_dir() / "emojis"
# 在 _find_emotion_file 中先查子目录，再查根目录
```

---

## 6. 重新打包 EXE 步骤

### 6.1 环境要求

- Python 3.10+
- `pip install -r requirements.txt`
- PyInstaller (已在 requirements 中)
- Windows: 可能需安装 [Inno Setup](http://jrsoftware.org/isinfo.php) (用于生成安装包)

### 6.2 Windows EXE 打包命令

```powershell
# 方案 1: 使用 PyInstaller 直接打包
pyinstaller py-xiaozhi.spec

# 方案 2: 使用 release.py 脚本 (会自动更新版本号)
python release.py

# 方案 3: 使用 build.json (如果项目有对应的构建工具)
python -m unifypy build --config build.json
```

### 6.3 关键检查

打包前确认：

1. `py-xiaozhi.spec` 中 `datas` 已包含 `('assets', 'assets')`
2. `build.json` 中 `pyinstaller.add_data` 已包含 `"assets:assets"`
3. `assets/emojis/research_bot/` 目录及其所有文件存在
4. 备份 `assets/emojis/_soybean_backup/` 可选 (打包时会被包含但不影响功能)

### 6.4 输出位置

- PyInstaller: `dist/py-xiaozhi/` (包含 `py-xiaozhi.exe`)
- 安装包 (Windows): `dist/` 下 `.exe` 安装程序

### 6.5 验证步骤

```powershell
# 1. 开发模式验证 (不需要打包)
python main.py

# 2. 构建
pyinstaller py-xiaozhi.spec

# 3. 运行打包后的 EXE
.\dist\py-xiaozhi\py-xiaozhi.exe

# 4. 检查资源是否正确包含
# 表情文件应在 dist/py-xiaozhi/assets/emojis/research_bot/ 下
Get-ChildItem dist\py-xiaozhi\assets\emojis\research_bot\
```

---

## 7. 实施检查清单

### 阶段 1: 准备资源

- [ ] 获取/生成 9 个状态素材文件 (8 个状态 + 1 个 neutral)
- [ ] 统一格式为 GIF (或 PNG，如需动画则必须 GIF)
- [ ] 统一尺寸 ≥ 200×200 px
- [ ] 文件命名: `idle.gif`, `searching.gif`, `reading.gif`, `thinking.gif`, `coding.gif`, `reporting.gif`, `success.gif`, `error.gif`, `neutral.gif`

### 阶段 2: 资源部署

- [ ] 备份原黄豆资源: `Move assets/emojis/*.gif → assets/emojis/_soybean_backup/`
- [ ] 创建机器人资源目录: `mkdir assets/emojis/research_bot`
- [ ] 放入新的 9 个 GIF 文件到 `assets/emojis/research_bot/`

### 阶段 3: 代码修改

- [ ] 修改 `src/plugins/ui.py`: 添加 `EMOTION_MAP` + 修改 emotion 取值
- [ ] 修改 `src/ui/gui/services/emotion_service.py`: 指向 `emojis/research_bot/`

### 阶段 4: 验证

- [ ] 开发模式运行验证 (`python main.py`)
- [ ] 测试各状态表情是否正确显示
- [ ] 测试旧 emotion 名称映射是否正确
- [ ] 测试 neutral 回退机制
- [ ] 确认窗口布局未变

### 阶段 5: 打包

- [ ] 执行 `pyinstaller py-xiaozhi.spec`
- [ ] 验证打包后 EXE 表情正常
- [ ] 检查 `assets/emojis/research_bot/` 已包含在 dist 中

---

## 8. 注意事项

### 8.1 关于提供的参考图片

用户提供的参考图片路径 `C:\Users\dista\Desktop\c645d2fa00f60d94dc11a0138a195b9a` 当前不可访问。需要确认：

- 是否为可用的机器人形象原图
- 文件是否被移动或重命名
- 是否需要基于原图用 AI 生成各状态的变体

### 8.2 GIF 动画建议

建议为 `research_bot` 目录生成 **GIF 格式** 动画，因为：
- 当前 QML 使用 `AnimatedImage` 组件，原生支持 GIF 播放
- `EmotionDisplay.qml` 中 `playing: true` 自动播放
- 静态 PNG 需额外修改 QML 为 `Image` 组件

如果使用静态 PNG，则需要在 `assets/emojis/` 根目录保留一个 `neutral.gif` 作为 `AnimatedImage` 的兼容方案，或将 EmotionDisplay 改为同时支持 `Image` + `AnimatedImage`。

### 8.3 回滚方案

```powershell
# 快速回滚到黄豆形象
Remove-Item -Recurse assets/emojis/research_bot
Move-Item assets/emojis/_soybean_backup/*.gif assets/emojis/
# Git revert src/plugins/ui.py 和 src/ui/gui/services/emotion_service.py
git checkout -- src/plugins/ui.py src/ui/gui/services/emotion_service.py
```

---

## 附录: 关键文件索引 (完整)

| 文件 | 角色 | 是否需修改 |
|------|------|-----------|
| `assets/emojis/*.gif` | 原始黄豆 GIF 资源 | 备份不动 |
| `assets/emojis/research_bot/*.gif` | **新机器人资源** | 新增目录 |
| `src/plugins/ui.py` | 添加 EMOTION_MAP | ✅ **是** |
| `src/ui/gui/services/emotion_service.py` | 指向子目录 | ✅ **是** |
| `src/ui/gui/manager.py` | ViewManager 事件中转 | ❌ 否 |
| `src/ui/shared/events.py` | UIEmotionUpdate 数据类 | ❌ 否 |
| `src/ui/shared/models/main_model.py` | emotionUrl 属性 | ❌ 否 |
| `src/ui/gui/qml/windows/MainWindow.qml` | 主窗口 AnimatedImage | ❌ 否 |
| `src/ui/gui/qml/components/EmotionDisplay.qml` | 表情显示组件 | ❌ 否 |
| `src/core/event_bus.py` | UI_UPDATE_EMOTION 事件 | ❌ 否 |
| `src/core/state_manager.py` | DeviceState 管理 | ❌ 否 |
| `src/constants/constants.py` | DeviceState 枚举 | ❌ 否 |
| `src/utils/resource_finder.py` | get_assets_dir() | ❌ 否 |
| `build.json` | 打包配置 | ❌ 否 |
| `py-xiaozhi.spec` | PyInstaller spec | ❌ 否 |
| `release.py` | 发版脚本 | ❌ 否 |
