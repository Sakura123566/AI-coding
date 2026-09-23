# Avatar 资源审计

> 日期：2026-07-15
> 阶段：Phase 5.4 Avatar Resource Repair

## 资源来源

- 用户提供的情绪 GIF 目录：`C:\Users\dista\Desktop\a情绪`
- 运行时资源目录：`assets/emojis`
- GUI 加载入口：`src/ui/gui/services/emotion_service.py`
- QML 播放入口：
  - `src/ui/gui/qml/windows/MainWindow.qml`
  - `src/ui/gui/qml/components/EmotionDisplay.qml`

## 源目录文件

`C:\Users\dista\Desktop\a情绪` 当前包含 12 个 GIF：

| 源文件 | 运行时主资源名 |
| --- | --- |
| `待机.gif` | `persona_idle.gif` |
| `待机疲惫.gif` | `persona_idle_tired.gif` |
| `开心.gif` | `persona_happy.gif` |
| `温柔安抚.gif` | `persona_comforting.gif` |
| `细心讲解.gif` | `persona_explain.gif` |
| `细心讲解2.gif` | `persona_deep_explain.gif` |
| `严肃讲解.gif` | `persona_serious_explain.gif` |
| `严肃指正.gif` | `persona_correction.gif` |
| `论文搜索.gif` | `workflow_searching.gif` |
| `阅读论文.gif` | `workflow_reading.gif` |
| `编写代码.gif` | `workflow_coding.gif` |
| `灵光一现.gif` | `workflow_eureka.gif` |

## 兼容覆盖

已把同一批资源同步到旧 emotion 文件名，避免服务端或旧映射直接请求 `happy.gif`、`searching.gif`、`success.gif` 等文件时回到旧黄豆形象。

关键覆盖关系：

| 旧/通用文件名 | 新来源 |
| --- | --- |
| `idle.gif`, `neutral.gif`, `relaxed.gif` | `待机.gif` |
| `happy.gif`, `confident.gif`, `cool.gif`, `laughing.gif` | `开心.gif` |
| `sad.gif`, `crying.gif`, `error.gif` | `温柔安抚.gif` |
| `angry.gif`, `shocked.gif` | `严肃指正.gif` |
| `searching.gif`, `surprised.gif` | `论文搜索.gif` |
| `reading.gif` | `阅读论文.gif` |
| `coding.gif` | `编写代码.gif` |
| `success.gif` | `灵光一现.gif` |

## 资源加载链路

```text
UIPlugin
  -> EmotionEngine
  -> UIEmotionUpdate.emotion
  -> ViewManager._set_avatar_state()
  -> EmotionService.get_emotion_url()
  -> assets/emojis/{resource_name}.gif
  -> MainModel.emotionUrl
  -> QML AnimatedImage.source
```

## 审计结论

- P0 资源目录已确认：运行时使用 `assets/emojis`，不是桌面源目录。
- 新 GIF 已同步到 `assets/emojis`，会被现有 PyInstaller 配置打包。
- `协作.gif` 当前未在源目录中提供；`协作` 状态首选 `workflow_collaborating.gif`，缺失时回退到 `workflow_coding.gif`。
- `EmotionService` 已记录 `actual_gif_path`，用于定位 EXE 实际加载的 GIF。
