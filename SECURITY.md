# Security Policy

## Secrets

- 永远不要提交 `.env`、API Key、JWT 密钥或平台 Token。
- 生产密钥只放在部署平台的 Secret/Environment Variables 中。
- 前端只能使用 `VITE_API_BASE_URL`，不得包含任何模型密钥。

## Important incident note

本仓库早期版本曾提交 `.env`，即使该文件已从当前提交中删除，历史提交仍可能包含旧值。所有曾经出现在该文件中的模型密钥、Token 或认证密钥都应视为已泄露，并立即在对应平台轮换。

清理 Git 历史需要团队统一后执行历史重写和强制推送；轮换密钥不能省略，因为第三方缓存、Fork 或克隆仍可能保留旧历史。