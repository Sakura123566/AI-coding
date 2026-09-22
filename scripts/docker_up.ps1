$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".env")) {
    throw "缺少 .env。请先复制 .env.example 或配置平台环境变量。"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "未找到 Docker。请先安装 Docker Desktop 或使用平台远程构建。"
}

docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw "Docker Compose 启动失败。" }

for ($i = 0; $i -lt 40; $i++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
        if ($health.status -eq "ok") {
            Write-Host "Research Navigator 后端已就绪：" -ForegroundColor Green
            $health | ConvertTo-Json -Depth 4
            exit 0
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
throw "容器已启动，但健康检查未通过。请运行 docker compose logs backend 查看日志。"