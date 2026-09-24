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
    paper_source_order: list[str] = field(default_factory=lambda: ["arxiv", "crossref", "openalex"])
    http_timeout: int = 15
    scholarly_contact_email: str = ""          # OpenAlex/Crossref polite pool 联系邮箱
    source_cooldown_seconds: int = 300          # 429/406 后暂停该来源的秒数，0 表示关闭
    default_limit: int = 10
    max_limit: int = 30

    # ---- 多源检索调度 ----
    # parallel：并行问所有源，合并去重（摘要互补，默认）
    # fallback：按顺序串行问，第一个非空结果即返回（改造前的老行为）
    paper_search_mode: str = "parallel"
    paper_search_budget_seconds: float = 30.0   # parallel 总预算，超时未返回的源直接放弃
    # 已经有源返回结果后，最多再等这么久等剩下的源（它们可能补上摘要/DOI）。
    # 没有它的话，一个卡住的源会把每次检索都拖到"总预算"或"单源超时"为止。
    paper_search_grace_seconds: float = 4.0
    # 并行模式下单个源最多等多久。arXiv 从被墙的网络里 SSL 握手会一直挂着，
    # 不设上限的话它每次都能吃掉 20s+，把整次检索拖垮。MCP 走子进程另算（mcp_timeout）。
    paper_provider_timeout_seconds: int = 12
    # 缺摘要的论文用 DOI 去 OpenAlex 批量补摘要（一次请求最多 50 个 DOI）
    abstract_backfill_enabled: bool = True
    abstract_backfill_max: int = 20

    # ---- 通用上游保护（arXiv 以外的 OpenAlex / Crossref / Semantic Scholar）----
    # arXiv 有 arxiv_client 专属保护，这几个源之前是裸请求，429 就直接失败
    http_max_retries: int = 2                   # 单次请求最多重试几次（不含首次）
    http_backoff_base_seconds: float = 1.5      # 退避基数：等待 = 基数 × 2^次数
    http_max_backoff_seconds: float = 20.0      # 单次退避上限
    http_jitter_ratio: float = 0.3              # 抖动比例，避免多进程同时重试
    source_circuit_threshold: int = 3           # 连续失败几次后熔断
    source_circuit_cooldown_seconds: float = 120.0
    source_rate_limit_backend: str = "memory"   # memory | sqlite

    # ---- arXiv 统一出口：限速 / 重试 / 冷却 / 熔断 ----
    # 相邻两次 arXiv 请求的最小间隔（秒）。arXiv 官方建议 3 秒，别调小。
    arxiv_min_interval_seconds: float = 3.0
    arxiv_max_retries: int = 3                  # 单次请求最多重试几次（不含首次）
    arxiv_backoff_base_seconds: float = 2.0     # 退避基数：等待 = 基数 × 2^次数
    arxiv_max_backoff_seconds: float = 60.0     # 单次退避上限
    arxiv_jitter_ratio: float = 0.2             # 退避抖动比例，避免多个进程同时重试
    arxiv_cooldown_seconds: float = 300.0       # 429/406 后整条出口的冷却时长
    arxiv_circuit_threshold: int = 3            # 连续失败几次后熔断
    arxiv_circuit_cooldown_seconds: float = 120.0   # 熔断后多久进入半开探测
    arxiv_rate_limit_max_wait: float = 0.0      # 能容忍的最长限速等待（秒），0=无限等
    # 限速器后端：memory 只在单个进程内生效；sqlite 能管住 MCP 子进程，默认用它
    arxiv_rate_limit_backend: str = "sqlite"

    # ---- 论文搜索缓存（SQLite）----
    paper_cache_enabled: bool = True
    cache_db_path: str = ""                     # 留空用 backend/data/paper_cache.db
    paper_cache_ttl_search: int = 86400         # 搜索结果缓存 24 小时
    paper_cache_ttl_paper: int = 604800         # 论文元数据缓存 7 天
    paper_cache_max_entries: int = 2000         # 超出按最久未命中淘汰，防止无限增长
    paper_cache_stale_fallback: bool = True     # 数据源挂了时，是否允许返回过期缓存
    paper_cache_stale_ttl: int = 604800         # 过期缓存最多再保留多久可用于兜底

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

    def resolved_cache_db_path(self) -> str:
        """论文缓存 / 限速状态共用的 SQLite 文件位置，留空就落在 backend/data/ 下。"""
        return self.cache_db_path or str(ROOT / "backend" / "data" / "paper_cache.db")

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
            paper_source_order=_get_list("PAPER_SOURCE_ORDER", "arxiv,crossref,openalex"),
            http_timeout=_get_int("HTTP_TIMEOUT", 15),
            scholarly_contact_email=_get("SCHOLARLY_CONTACT_EMAIL"),
            source_cooldown_seconds=_get_int("SOURCE_COOLDOWN_SECONDS", 300),
            paper_search_mode=_get("PAPER_SEARCH_MODE", "parallel").lower(),
            paper_search_budget_seconds=_get_float("PAPER_SEARCH_BUDGET_SECONDS", 30.0),
            paper_search_grace_seconds=_get_float("PAPER_SEARCH_GRACE_SECONDS", 4.0),
            paper_provider_timeout_seconds=_get_int("PAPER_PROVIDER_TIMEOUT_SECONDS", 12),
            abstract_backfill_enabled=_get_bool("ABSTRACT_BACKFILL_ENABLED", True),
            abstract_backfill_max=_get_int("ABSTRACT_BACKFILL_MAX", 20),
            http_max_retries=_get_int("HTTP_MAX_RETRIES", 2),
            http_backoff_base_seconds=_get_float("HTTP_BACKOFF_BASE_SECONDS", 1.5),
            http_max_backoff_seconds=_get_float("HTTP_MAX_BACKOFF_SECONDS", 20.0),
            http_jitter_ratio=_get_float("HTTP_JITTER_RATIO", 0.3),
            source_circuit_threshold=_get_int("SOURCE_CIRCUIT_THRESHOLD", 3),
            source_circuit_cooldown_seconds=_get_float("SOURCE_CIRCUIT_COOLDOWN_SECONDS", 120.0),
            source_rate_limit_backend=_get("SOURCE_RATE_LIMIT_BACKEND", "memory").lower(),
            default_limit=_get_int("DEFAULT_LIMIT", 10),
            max_limit=_get_int("MAX_LIMIT", 30),
            arxiv_min_interval_seconds=_get_float("ARXIV_MIN_INTERVAL_SECONDS", 3.0),
            arxiv_max_retries=_get_int("ARXIV_MAX_RETRIES", 3),
            arxiv_backoff_base_seconds=_get_float("ARXIV_BACKOFF_BASE_SECONDS", 2.0),
            arxiv_max_backoff_seconds=_get_float("ARXIV_MAX_BACKOFF_SECONDS", 60.0),
            arxiv_jitter_ratio=_get_float("ARXIV_JITTER_RATIO", 0.2),
            arxiv_cooldown_seconds=_get_float("ARXIV_COOLDOWN_SECONDS", 300.0),
            arxiv_circuit_threshold=_get_int("ARXIV_CIRCUIT_THRESHOLD", 3),
            arxiv_circuit_cooldown_seconds=_get_float("ARXIV_CIRCUIT_COOLDOWN_SECONDS", 120.0),
            arxiv_rate_limit_max_wait=_get_float("ARXIV_RATE_LIMIT_MAX_WAIT", 0.0),
            arxiv_rate_limit_backend=_get("ARXIV_RATE_LIMIT_BACKEND", "sqlite").lower(),
            paper_cache_enabled=_get_bool("PAPER_CACHE_ENABLED", True),
            cache_db_path=_get("CACHE_DB_PATH"),
            paper_cache_ttl_search=_get_int("PAPER_CACHE_TTL_SEARCH", 86400),
            paper_cache_ttl_paper=_get_int("PAPER_CACHE_TTL_PAPER", 604800),
            paper_cache_max_entries=_get_int("PAPER_CACHE_MAX_ENTRIES", 2000),
            paper_cache_stale_fallback=_get_bool("PAPER_CACHE_STALE_FALLBACK", True),
            paper_cache_stale_ttl=_get_int("PAPER_CACHE_STALE_TTL", 604800),
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
