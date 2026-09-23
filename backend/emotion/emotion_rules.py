"""Avatar 情绪规则.

移植自 Sakura123566/AI-coding，仅替换日志依赖，规则内容未改动。
"""

import copy
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AVATAR_IDLE = "待机"
AVATAR_IDLE_TIRED = "待机疲惫"
AVATAR_HAPPY = "开心"
AVATAR_COMFORTING = "温柔安抚"
AVATAR_EXPLAINING = "细心讲解"
AVATAR_DEEP_EXPLAINING = "细心讲解2"
AVATAR_SERIOUS_EXPLAINING = "严肃讲解"
AVATAR_CORRECTING = "严肃指正"
AVATAR_SEARCHING = "论文搜索"
AVATAR_READING = "阅读论文"
AVATAR_CODING = "编写代码"
AVATAR_COLLABORATING = "协作"
AVATAR_EUREKA = "灵光一现"

DEFAULT_AVATAR_STATE = AVATAR_IDLE

AVATAR_STATES = (
    AVATAR_IDLE,
    AVATAR_IDLE_TIRED,
    AVATAR_HAPPY,
    AVATAR_COMFORTING,
    AVATAR_EXPLAINING,
    AVATAR_DEEP_EXPLAINING,
    AVATAR_SERIOUS_EXPLAINING,
    AVATAR_CORRECTING,
    AVATAR_SEARCHING,
    AVATAR_READING,
    AVATAR_CODING,
    AVATAR_COLLABORATING,
    AVATAR_EUREKA,
)

SYSTEM_STATE_AVATAR_MAP: dict[str, str] = {
    "idle": AVATAR_IDLE,
    "searching": AVATAR_SEARCHING,
    "search": AVATAR_SEARCHING,
    "retrieving": AVATAR_SEARCHING,
    "reading": AVATAR_READING,
    "paper_reading": AVATAR_READING,
    "thinking": AVATAR_SERIOUS_EXPLAINING,
    "coding": AVATAR_CODING,
    "code": AVATAR_CODING,
    "collaborating": AVATAR_COLLABORATING,
    "tool_call": AVATAR_COLLABORATING,
    "mcp_tool": AVATAR_COLLABORATING,
    "reporting": AVATAR_EXPLAINING,
    "success": AVATAR_EUREKA,
    "task_success": AVATAR_EUREKA,
    "eureka": AVATAR_EUREKA,
    "done": AVATAR_EUREKA,
    "error": AVATAR_COMFORTING,
}

LEGACY_EMOTION_AVATAR_MAP: dict[str, str] = {
    "neutral": AVATAR_IDLE,
    "relaxed": AVATAR_IDLE,
    "sleepy": AVATAR_IDLE_TIRED,
    "silly": AVATAR_IDLE,
    "winking": AVATAR_IDLE,
    "embarrassed": AVATAR_IDLE,
    "happy": AVATAR_HAPPY,
    "confident": AVATAR_HAPPY,
    "cool": AVATAR_HAPPY,
    "delicious": AVATAR_HAPPY,
    "funny": AVATAR_HAPPY,
    "kissy": AVATAR_HAPPY,
    "laughing": AVATAR_HAPPY,
    "loving": AVATAR_HAPPY,
    "confused": AVATAR_SERIOUS_EXPLAINING,
    "surprised": AVATAR_SEARCHING,
    "sad": AVATAR_COMFORTING,
    "angry": AVATAR_CORRECTING,
    "shocked": AVATAR_CORRECTING,
    "crying": AVATAR_COMFORTING,
}

TOOL_AVATAR_MAP: dict[str, str] = {
    "search_paper": AVATAR_SEARCHING,
    "search_arxiv": AVATAR_SEARCHING,
    "search_semantic_scholar": AVATAR_SEARCHING,
    "paper_search": AVATAR_SEARCHING,
    "multi_search": AVATAR_SEARCHING,
    "web_search": AVATAR_SEARCHING,
    "internet_search": AVATAR_SEARCHING,
    "search": AVATAR_SEARCHING,
    "query": AVATAR_SEARCHING,
    "retrieve": AVATAR_SEARCHING,
    "paper_summary": AVATAR_READING,
    "paper_analysis": AVATAR_READING,
    "paper_analyze": AVATAR_READING,
    "read_paper": AVATAR_READING,
    "read_file": AVATAR_READING,
    "file_read": AVATAR_READING,
    "paper_compare": AVATAR_READING,
    "paper_to_requirement": AVATAR_READING,
    "requirement_extract": AVATAR_READING,
    "requirement_extraction": AVATAR_READING,
    "research_workflow": AVATAR_COLLABORATING,
    "analysis": AVATAR_SERIOUS_EXPLAINING,
    "analyze": AVATAR_SERIOUS_EXPLAINING,
    "codex": AVATAR_CODING,
    "codex_tool": AVATAR_CODING,
    "codex_integration": AVATAR_CODING,
    "code_tool": AVATAR_CODING,
    "code": AVATAR_CODING,
    "coding": AVATAR_CODING,
    "generate_code": AVATAR_CODING,
    "modify_code": AVATAR_CODING,
    "develop": AVATAR_CODING,
    "development": AVATAR_CODING,
    "debug": AVATAR_SERIOUS_EXPLAINING,
    "tool_call": AVATAR_COLLABORATING,
    "mcp_tool": AVATAR_COLLABORATING,
    "agent_collaboration": AVATAR_COLLABORATING,
    "multi_agent": AVATAR_COLLABORATING,
    "weather": AVATAR_EXPLAINING,
    "calendar": AVATAR_EXPLAINING,
    "schedule": AVATAR_EXPLAINING,
    "alarm": AVATAR_COMFORTING,
    "music": AVATAR_HAPPY,
    "story": AVATAR_EXPLAINING,
    "translate": AVATAR_EXPLAINING,
    "translation": AVATAR_EXPLAINING,
    "news": AVATAR_EXPLAINING,
    "generate_week_report": AVATAR_EXPLAINING,
    "week_report": AVATAR_EXPLAINING,
    "weekly_report": AVATAR_EXPLAINING,
    "report": AVATAR_EXPLAINING,
}

TOOL_RESEARCH_STATE_MAP: dict[str, str] = {
    "search_paper": "searching",
    "search_arxiv": "searching",
    "search_semantic_scholar": "searching",
    "paper_search": "searching",
    "multi_search": "searching",
    "web_search": "searching",
    "paper_summary": "reading",
    "paper_analysis": "reading",
    "paper_analyze": "reading",
    "read_paper": "reading",
    "paper_compare": "reading",
    "paper_to_requirement": "reading",
    "requirement_extract": "reading",
    "requirement_extraction": "reading",
    "codex": "coding",
    "codex_tool": "coding",
    "codex_integration": "coding",
    "code_tool": "coding",
    "tool_call": "collaborating",
    "mcp_tool": "collaborating",
}

RESULT_STATUS_AVATAR_MAP: dict[str, str] = {
    "success": AVATAR_EUREKA,
    "succeeded": AVATAR_EUREKA,
    "complete": AVATAR_EUREKA,
    "completed": AVATAR_EUREKA,
    "done": AVATAR_EUREKA,
    "ok": AVATAR_EUREKA,
    "true": AVATAR_EUREKA,
    "task_success": AVATAR_EUREKA,
    "bug_resolved": AVATAR_EUREKA,
    "solution_confirmed": AVATAR_EUREKA,
    "key_paper_found": AVATAR_EUREKA,
    "error": AVATAR_COMFORTING,
    "failed": AVATAR_COMFORTING,
    "failure": AVATAR_COMFORTING,
    "exception": AVATAR_COMFORTING,
    "network_error": AVATAR_COMFORTING,
    "timeout": AVATAR_COMFORTING,
    "timed_out": AVATAR_COMFORTING,
    "false": AVATAR_COMFORTING,
    "config_error": AVATAR_CORRECTING,
    "path_error": AVATAR_CORRECTING,
    "api_key_error": AVATAR_CORRECTING,
    "dependency_missing": AVATAR_CORRECTING,
}

USER_CONTEXT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "correction": (
        "api key配置错误",
        "apikey配置错误",
        "api_key配置错误",
        "路径错误",
        "配置错误",
        "逻辑错误",
        "依赖缺失",
        "缺少依赖",
        "代码审查",
        "指出错误",
        "key错误",
        "invalid api key",
        "wrong path",
        "config error",
        "configuration error",
        "missing dependency",
        "code review",
    ),
    "positive": (
        "谢谢",
        "感谢",
        "太好了",
        "解决了",
        "成功了",
        "完成了",
        "厉害",
        "牛",
        "真棒",
        "不错",
        "thanks",
        "thank you",
        "great",
        "awesome",
        "nice",
    ),
    "negative": (
        "报错",
        "失败",
        "不行",
        "怎么办",
        "不会",
        "为什么",
        "有问题",
        "焦虑",
        "卡住",
        "崩了",
        "error",
        "failed",
        "failure",
        "why",
        "stuck",
    ),
    "debug": (
        "分析日志",
        "日志分析",
        "定位问题",
        "排查异常",
        "排查",
        "调试",
        "bug",
        "traceback",
        "stack trace",
        "debug",
        "log analysis",
    ),
    "deep_learning": (
        "生成计划书",
        "架构设计",
        "系统架构",
        "项目规划",
        "方案设计",
        "项目分析",
        "深度教学",
        "设计系统",
        "帮我设计",
        "design architecture",
        "system architecture",
        "project plan",
    ),
    "learning": (
        "什么是",
        "是什么",
        "怎么用",
        "教程",
        "讲解",
        "解释",
        "概念",
        "mcp",
        "gui",
        "pyqt",
        "pyside",
        "what is",
        "how to",
        "explain",
    ),
}

USER_CONTEXT_PRIORITY = (
    "correction",
    "positive",
    "negative",
    "debug",
    "deep_learning",
    "learning",
)

CONTEXT_AVATAR_MAP: dict[str, str] = {
    "correction": AVATAR_CORRECTING,
    "positive": AVATAR_HAPPY,
    "negative": AVATAR_COMFORTING,
    "debug": AVATAR_SERIOUS_EXPLAINING,
    "deep_learning": AVATAR_DEEP_EXPLAINING,
    "learning": AVATAR_EXPLAINING,
}

TEMPORARY_CONTEXT_CATEGORIES = (
    "positive",
    "negative",
)

TEMPORARY_RESULT_STATES = (
    AVATAR_HAPPY,
    AVATAR_COMFORTING,
    AVATAR_EUREKA,
)

MESSAGE_TOOL_FIELDS = (
    "tool_name",
    "tool",
    "name",
    "function",
    "action",
)

MESSAGE_TEXT_FIELDS = (
    "text",
    "content",
    "query",
    "message",
)

TASK_RESULT_FIELDS = (
    "status",
    "state",
    "result",
    "finish_reason",
)

IDLE_VARIANT_WEIGHTS: tuple[tuple[str, int], ...] = ()

TRANSITION_STATE_MAP: dict[tuple[str, str], str] = {}

DEFAULT_AVATAR_CONFIG: dict[str, Any] = {
    "idle_timeout": 60,
    "idle_check_interval": 1,
    "temporary_emotion_duration": 3,
    "error_avatar": AVATAR_COMFORTING,
    "success_avatar": AVATAR_HAPPY,
    "state_resource_map": {
        AVATAR_IDLE: "persona_idle",
        AVATAR_IDLE_TIRED: "persona_idle_tired",
        AVATAR_HAPPY: "persona_happy",
        AVATAR_COMFORTING: "persona_comforting",
        AVATAR_EXPLAINING: "persona_explain",
        AVATAR_DEEP_EXPLAINING: "persona_deep_explain",
        AVATAR_SERIOUS_EXPLAINING: "persona_serious_explain",
        AVATAR_CORRECTING: "persona_correction",
        AVATAR_SEARCHING: "workflow_searching",
        AVATAR_READING: "workflow_reading",
        AVATAR_CODING: "workflow_coding",
        AVATAR_COLLABORATING: "workflow_collaborating",
        AVATAR_EUREKA: "workflow_eureka",
    },
    "fallback_resource_map": {
        AVATAR_IDLE: "idle",
        AVATAR_IDLE_TIRED: "sleepy",
        AVATAR_HAPPY: "success",
        AVATAR_COMFORTING: "error",
        AVATAR_EXPLAINING: "searching",
        AVATAR_DEEP_EXPLAINING: "reading",
        AVATAR_SERIOUS_EXPLAINING: "thinking",
        AVATAR_CORRECTING: "error",
        AVATAR_SEARCHING: "searching",
        AVATAR_READING: "reading",
        AVATAR_CODING: "coding",
        AVATAR_COLLABORATING: "workflow_coding",
        AVATAR_EUREKA: "success",
    },
}


def normalize_rule_key(value: str) -> str:
    """归一化规则键."""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def load_avatar_config(config_path: Path | None = None) -> dict[str, Any]:
    """加载 Avatar 配置，文件缺失时使用内置默认值."""
    path = config_path or Path(__file__).with_name("avatar_config.json")
    config = copy.deepcopy(DEFAULT_AVATAR_CONFIG)
    if not path.is_file():
        return config

    try:
        file_config = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Avatar 配置加载失败: {e}")
        return config

    if not isinstance(file_config, dict):
        return config
    return _merge_dict(config, file_config)


def normalize_avatar_state(
    value: Any,
    default: str = DEFAULT_AVATAR_STATE,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    """把外部状态名归一到导师人格 Avatar 状态."""
    if not isinstance(value, str) or not value.strip():
        return default

    state = value.strip()
    if state in AVATAR_STATES:
        return state

    resolved_config = config or load_avatar_config()
    state_resource_map = _get_str_map(resolved_config, "state_resource_map")
    if state in state_resource_map:
        return state

    key = normalize_rule_key(state)
    aliases = _avatar_state_aliases(resolved_config)
    return aliases.get(key, default)


def get_avatar_resource_name(
    avatar_state: str,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    """获取人格状态对应的首选资源名."""
    resolved_config = config or load_avatar_config()
    state = normalize_avatar_state(avatar_state, config=resolved_config)
    state_resource_map = _get_str_map(resolved_config, "state_resource_map")
    return state_resource_map.get(state, DEFAULT_AVATAR_CONFIG["state_resource_map"][state])


def get_avatar_fallback_resource_name(
    avatar_state: str,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    """获取人格状态对应的旧资源回退名."""
    resolved_config = config or load_avatar_config()
    state = normalize_avatar_state(avatar_state, config=resolved_config)
    fallback_map = _get_str_map(resolved_config, "fallback_resource_map")
    return fallback_map.get(
        state,
        DEFAULT_AVATAR_CONFIG["fallback_resource_map"][state],
    )


def _avatar_state_aliases(config: dict[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {
        **{normalize_rule_key(state): state for state in AVATAR_STATES},
        **SYSTEM_STATE_AVATAR_MAP,
        **LEGACY_EMOTION_AVATAR_MAP,
        **TOOL_AVATAR_MAP,
        **RESULT_STATUS_AVATAR_MAP,
        "待机疲劳": AVATAR_IDLE_TIRED,
        "疲惫": AVATAR_IDLE_TIRED,
        "开心": AVATAR_HAPPY,
        "温柔": AVATAR_COMFORTING,
        "安抚": AVATAR_COMFORTING,
        "细心讲解": AVATAR_EXPLAINING,
        "细心讲解_2": AVATAR_DEEP_EXPLAINING,
        "细心讲解2": AVATAR_DEEP_EXPLAINING,
        "严肃讲解": AVATAR_SERIOUS_EXPLAINING,
        "严肃指正": AVATAR_CORRECTING,
        "论文搜索": AVATAR_SEARCHING,
        "论文检索": AVATAR_SEARCHING,
        "搜索论文": AVATAR_SEARCHING,
        "阅读论文": AVATAR_READING,
        "论文阅读": AVATAR_READING,
        "编写代码": AVATAR_CODING,
        "代码编写": AVATAR_CODING,
        "协作": AVATAR_COLLABORATING,
        "灵光一现": AVATAR_EUREKA,
        "eureka": AVATAR_EUREKA,
    }

    for state, resource_name in _get_str_map(config, "state_resource_map").items():
        aliases[normalize_rule_key(resource_name)] = state
    for state, resource_name in _get_str_map(config, "fallback_resource_map").items():
        aliases[normalize_rule_key(resource_name)] = state
    return aliases


def _get_str_map(config: dict[str, Any], key: str) -> dict[str, str]:
    value = config.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(map_key): str(map_value)
        for map_key, map_value in value.items()
        if isinstance(map_key, str) and isinstance(map_value, str)
    }


def _merge_dict(default: dict[str, Any], custom: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(default)
    for key, value in custom.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result
