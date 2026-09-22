"""全局配置：全部来自环境变量 / 项目根目录 .env 文件。

规则：任何密钥都只走环境变量，不写死在代码里，也不会返回给前端。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def _load_dotenv(path: Path = ENV_FILE) -> None:
    """极简 .env 加载器：不额外引入 python-dotenv 依赖。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 已存在的真实环境变量优先级更高（方便 CI / 命令行覆盖）
        os.environ.setdefault(key, value)


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)))
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    return _get(name, "true" if default else "false").lower() in ("1", "true", "yes", "on")


def _get_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in _get(name, default).split(",") if x.strip()]


def _get_json(name: str, default: str = "{}") -> dict[str, str]:
    raw = _get(name, default)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


@dataclass
class Settings:
    # 服务
    environment: str = "development"              # development | production
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    # 论文来源
    paper_source: str = "auto"                       # auto | arxiv | openalex | semanticscholar | crossref | mock | mcp
    paper_source_order: list[str] = field(default_factory=lambda: ["arxiv", "openalex", "crossref"])
    http_timeout: int = 15
    default_limit: int = 10
    max_limit: int = 30

    # MCP：两种形态二选一
    mcp_transport: str = "auto"                      # stdio | http | sse | auto
    mcp_command: list[str] = field(default_factory=list)   # stdio：["npx","-y","@xxx/mcp-server"]
    mcp_url: str = ""                                # http/sse：托管 MCP 的网址端点
    mcp_headers: dict[str, str] = field(default_factory=dict)  # 额外请求头，JSON
    mcp_auth_token: str = ""                         # Bearer token，等价 Authorization 头
    mcp_tool_name: str = ""
    mcp_timeout: int = 45

    # 大模型
    llm_provider: str = "mock"                       # openai | mock
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3
    llm_timeout: int = 90
    llm_json_mode: bool = True

    # 提示词里每篇摘要的最大长度，防止超长把上下文撑爆
    abstract_max_chars: int = 600
    abstract_translation_enabled: bool = True
    abstract_translation_max_papers: int = 12
    abstract_translation_batch_size: int = 6
    abstract_summary_max_chars: int = 180

    # 结果缓存：同一主题重复查询不再重复检索 + 重复调模型
    cache_enabled: bool = True
    cache_ttl: int = 600          # 缓存有效期（秒）
    cache_max_entries: int = 64   # 最多缓存多少条，超出按最近最少使用淘汰

    # 日志
    log_level: str = "INFO"       # DEBUG | INFO | WARNING | ERROR

    # ---- 用户系统（注册登录 / 对话 / 记忆 / 画像 / 知识图谱对接）----
    db_path: str = ""                        # SQLite 文件路径，留空用 backend/data/app.db
    auth_secret: str = "research-navigator-dev-secret"   # JWT 签名密钥，生产必须换
    auth_token_ttl: int = 604800             # token 有效期（秒），默认 7 天
    min_password_len: int = 6

    # 对话与记忆
    chat_window: int = 6                     # 短期上下文保留几轮
    memory_top_k: int = 8                    # 每次对话最多注入多少条长期记忆
    memory_half_life_days: float = 35.0      # 记忆新鲜度半衰期（天）
    profile_min_sample: int = 5              # 少于这个样本量就判定"数据不足"

    # 关键词 / 知识图谱
    kg_min_times: int = 2                    # 至少出现几次才对外暴露
    kg_min_weight: float = 0.2               # 权重下限，过滤噪声
    kg_default_limit: int = 200
    report_timezone_offset_hours: float = 8.0

    def mcp_http_headers(self) -> dict[str, str]:
        """MCP 端点要带的请求头：自定义头 + Bearer token。"""
        headers = dict(self.mcp_headers)
        if self.mcp_auth_token and "authorization" not in {k.lower() for k in headers}:
            headers["Authorization"] = f"Bearer {self.mcp_auth_token}"
        return headers

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        cmd = _get("MCP_COMMAND")
        return cls(
            environment=_get("ENVIRONMENT", "development").lower(),
            host=_get("HOST", "127.0.0.1"),
            port=_get_int("PORT", 8000),
            cors_origins=_get_list("CORS_ORIGINS", "*"),
            paper_source=_get("PAPER_SOURCE", "auto").lower(),
            paper_source_order=_get_list("PAPER_SOURCE_ORDER", "arxiv,openalex,crossref"),
            http_timeout=_get_int("HTTP_TIMEOUT", 15),
            default_limit=_get_int("DEFAULT_LIMIT", 10),
            max_limit=_get_int("MAX_LIMIT", 30),
            mcp_transport=_get("MCP_TRANSPORT", "auto").lower(),
            mcp_command=cmd.split() if cmd else [],
            mcp_url=_get("MCP_URL"),
            mcp_headers=_get_json("MCP_HEADERS"),
            mcp_auth_token=_get("MCP_AUTH_TOKEN"),
            mcp_tool_name=_get("MCP_TOOL_NAME"),
            mcp_timeout=_get_int("MCP_TIMEOUT", 45),
            llm_provider=_get("LLM_PROVIDER", "mock").lower(),
            llm_base_url=_get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            llm_api_key=_get("LLM_API_KEY"),
            llm_model=_get("LLM_MODEL", "gpt-4o-mini"),
            llm_temperature=_get_float("LLM_TEMPERATURE", 0.3),
            llm_timeout=_get_int("LLM_TIMEOUT", 90),
            llm_json_mode=_get_bool("LLM_JSON_MODE", True),
            abstract_translation_enabled=_get_bool("ABSTRACT_TRANSLATION_ENABLED", True),
            abstract_translation_max_papers=_get_int("ABSTRACT_TRANSLATION_MAX_PAPERS", 12),
            abstract_translation_batch_size=_get_int("ABSTRACT_TRANSLATION_BATCH_SIZE", 6),
            abstract_summary_max_chars=_get_int("ABSTRACT_SUMMARY_MAX_CHARS", 180),
            cache_enabled=_get_bool("CACHE_ENABLED", True),
            cache_ttl=_get_int("CACHE_TTL", 600),
            cache_max_entries=_get_int("CACHE_MAX_ENTRIES", 64),
            log_level=_get("LOG_LEVEL", "INFO").upper(),
            db_path=_get("DB_PATH"),
            auth_secret=_get("AUTH_SECRET", "research-navigator-dev-secret"),
            auth_token_ttl=_get_int("AUTH_TOKEN_TTL", 604800),
            min_password_len=_get_int("MIN_PASSWORD_LEN", 6),
            chat_window=_get_int("CHAT_WINDOW", 6),
            memory_top_k=_get_int("MEMORY_TOP_K", 8),
            memory_half_life_days=_get_float("MEMORY_HALF_LIFE_DAYS", 35.0),
            profile_min_sample=_get_int("PROFILE_MIN_SAMPLE", 5),
            kg_min_times=_get_int("KG_MIN_TIMES", 2),
            kg_min_weight=_get_float("KG_MIN_WEIGHT", 0.2),
            kg_default_limit=_get_int("KG_DEFAULT_LIMIT", 200),
            report_timezone_offset_hours=_get_float("REPORT_TIMEZONE_OFFSET_HOURS", 8.0),
        )


settings = Settings.from_env()
