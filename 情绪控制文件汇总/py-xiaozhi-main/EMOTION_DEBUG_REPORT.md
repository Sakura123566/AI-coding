# 情绪调试报告

> 日期：2026-07-15
> 阶段：Phase 5.4 Emotion Debug

## 新增调试点

`EmotionService.get_emotion_url()` 每次完成资源选择后会记录：

```json
{
  "time": "",
  "user_input": "",
  "workflow_state": "",
  "persona_state": "",
  "selected_gif": "",
  "actual_gif_path": "",
  "requested_emotion": "",
  "avatar_state": "",
  "resource_name": "",
  "fallback_name": ""
}
```

## 日志位置

运行时日志写入：

```text
get_log_dir() / "emotion_debug.log"
```

Windows 下通常位于：

```text
C:\Users\<user>\AppData\Local\<app_name>\logs\emotion_debug.log
```

## 缓存刷新

为降低 QML `AnimatedImage` 缓存导致“资源已替换但画面不刷新”的概率，本阶段做了两处处理：

- 本地 GIF URL 会携带文件修改时间 query：`file:///.../workflow_searching.gif?v=...`
- `MainWindow.qml` 和 `EmotionDisplay.qml` 的 `AnimatedImage.cache` 已设为 `false`

## 诊断方法

如果 EXE 仍显示旧图，优先检查：

1. `emotion_debug.log` 中的 `actual_gif_path`
2. 该路径对应 GIF 的文件大小和修改时间
3. EXE 是否已经重新打包
4. `selected_gif` 是否为 `workflow_*` 或 `persona_*` 新资源
