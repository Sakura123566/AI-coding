"""关键词抽取：检索主题 + 对话内容 → 归一化 → 权重 → 落库。

两条设计原则：
1. **候选可以来自模型，权重必须由代码算**。模型负责"这段在说什么"，
   频率、新鲜度、来源可信度由公式决定 —— 保证可解释、可复现，也防止模型张口报数。
2. **模型挂了也要有输出**。退回规则抽取（领域词典 + n-gram + 停用词过滤），
   质量差一些，但链路不断，且低质量词会被 kg_min_times / kg_min_weight 自然过滤掉。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable

from ..config import Settings, settings
from ..db import days_since, now_iso
from ..logging_setup import get_logger
from ..repo import list_keywords, upsert_keyword
from .llm_json import LLMJsonError, call_json

log = get_logger("keyword")

# ----------------------------- 词典 -----------------------------
# 领域词典：命中即认为是有效关键词，并顺带定类别
DOMAIN_TERMS: dict[str, str] = {
    # 方法与模型
    "图神经网络": "method", "神经网络": "method", "深度学习": "method", "机器学习": "method",
    "知识图谱": "method", "大模型": "method", "多模态": "method",
    "强化学习": "method", "迁移学习": "method", "联邦学习": "method", "对比学习": "method",
    "自监督": "method", "Transformer": "method", "扩散模型": "method", "生成对抗网络": "method",
    "注意力机制": "method", "预训练": "method", "微调": "method", "检索增强": "method",
    "蒸馏": "method", "图嵌入": "method", "表示学习": "method", "因果推断": "method",
    "graph neural network": "method", "gnn": "method", "knowledge graph": "method",
    "large language model": "method", "llm": "method", "multimodal": "method",
    "reinforcement learning": "method", "transfer learning": "method",
    "federated learning": "method", "contrastive learning": "method",
    "self-supervised": "method", "transformer": "method", "diffusion model": "method",
    "retrieval augmented": "method", "rag": "method", "representation learning": "method",
    # 任务与方向
    "推荐系统": "domain", "自然语言处理": "domain", "计算机视觉": "domain",
    "语音识别": "domain", "时间序列": "domain", "异常检测": "domain", "目标检测": "domain",
    "图像分割": "domain", "机器翻译": "domain", "问答系统": "domain", "文本分类": "domain",
    "情感分析": "domain", "漏洞检测": "domain", "药物发现": "domain", "自动驾驶": "domain",
    "recommender system": "domain", "natural language processing": "domain", "nlp": "domain",
    "computer vision": "domain", "object detection": "domain", "time series": "domain",
    "anomaly detection": "domain", "machine translation": "domain", "question answering": "domain",
    # 数据与评测
    "数据集": "dataset", "基准测试": "dataset", "benchmark": "dataset", "dataset": "dataset",
    "消融实验": "task", "综述": "task", "survey": "task", "复现": "task",
}

# 别名 → 规范词（给知识图谱做实体合并用，同一个概念只出一个节点）
ALIASES: dict[str, str] = {
    "gnn": "graph neural network",
    "gnns": "graph neural network",
    "图神经网络": "graph neural network",
    "graph neural networks": "graph neural network",
    "llm": "large language model",
    "llms": "large language model",
    "大模型": "large language model",
    "大语言模型": "large language model",
    "large language models": "large language model",
    "nlp": "natural language processing",
    "自然语言处理": "natural language processing",
    "rag": "retrieval augmented generation",
    "检索增强": "retrieval augmented generation",
    "检索增强生成": "retrieval augmented generation",
    "kg": "knowledge graph",
    "知识图谱": "knowledge graph",
    "推荐系统": "recommender system",
    "推荐算法": "recommender system",
    "cv": "computer vision",
    "计算机视觉": "computer vision",
    "强化学习": "reinforcement learning",
    "联邦学习": "federated learning",
    "迁移学习": "transfer learning",
    "对比学习": "contrastive learning",
    "扩散模型": "diffusion model",
    "transformer": "transformer",
    "transformers": "transformer",
    "多模态": "multimodal",
    "multimodal learning": "multimodal",
    "知识蒸馏": "knowledge distillation",
    "蒸馏": "knowledge distillation",
}

STOPWORDS_ZH = {
    "的", "了", "是", "在", "和", "与", "及", "对", "我", "你", "他", "她", "它", "们",
    "这", "那", "有", "就", "都", "也", "很", "要", "会", "能", "可以", "说", "个", "中",
    "为", "以", "上", "下", "里", "后", "前", "吧", "呢", "啊", "吗", "什么", "怎么",
    "如何", "为什么", "哪些", "最近", "一下", "帮我", "请问", "谢谢", "一篇", "这个",
    "那个", "现在", "目前", "一些", "相关", "方面", "问题", "东西", "情况", "时候",
}
STOPWORDS_EN = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "to", "for", "with",
    "about", "is", "are", "was", "were", "be", "been", "this", "that", "these", "those",
    "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her", "its",
    "please", "help", "want", "need", "can", "could", "would", "should", "how", "what",
    "why", "when", "which", "who", "some", "any", "new", "latest", "recent", "paper",
    "papers", "research", "study", "survey", "me", "find", "look", "show", "tell",
}
BAD_CHARS = set("的了是在和与及对我你这那有就都很也要会能说个中为以上下吧呢啊吗")
# 出现在术语"两端"就基本说明这是从句子上切下来的碎片，不是词
BAD_EDGE = BAD_CHARS | set("么什哪些来着入更很又再还把被让给人去做到过")

# 抽出来也没信息量的泛词：它们不该进知识图谱当节点
GENERIC_TERMS = {
    "应用", "研究方向", "方向", "进展", "论文", "文献", "问题", "方法", "技术", "模型",
    "系统", "研究", "综述", "入门", "优势", "不足", "区别", "对比", "最新", "现状",
    "内容", "概念", "原理", "流程", "步骤", "结果", "效果", "数据", "实验", "总结",
    "research", "paper", "papers", "study", "approach", "method", "methods", "system",
    "systems", "model", "models", "result", "results", "work", "works", "review",
}
MAX_ZH_LEN = 8        # 中文术语最长 8 个字，超过基本就是句子了
MAX_EN_WORDS = 3      # 英文术语最长 3 个单词

ZH_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")
EN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}(?:\s+[A-Za-z][A-Za-z0-9+#.\-]{1,}){0,2}")


# ----------------------------- 归一化 -----------------------------
def normalize_term(term: str) -> str:
    text = (term or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(".,;:!?，。；：！？、（）()[]【】\"'")
    return text


def canonical(term: str) -> str:
    norm = normalize_term(term)
    return ALIASES.get(norm, norm)


def guess_category(term: str) -> str:
    norm = normalize_term(term)
    if norm in DOMAIN_TERMS:
        return DOMAIN_TERMS[norm]
    for key, cat in DOMAIN_TERMS.items():
        if key in norm or norm in key:
            return cat
    return "other"


# ----------------------------- 规则抽取 -----------------------------
def _zh_grams(text: str, known: set[str] | None = None, dict_only: bool = False) -> list[str]:
    """中文候选：优先词典里有的词，其次从句子里切出来的片段（但必须不像句子碎片）。

    dict_only=True 时只认词典里有的词——没有模型帮忙判断时，宁可少抽也不要往
    知识图谱里塞"究什么方"这种碎片。
    """
    known = known or set()
    counter: Counter[str] = Counter()
    for seg in ZH_RE.findall(text):
        for n in (4, 3, 2):
            for i in range(len(seg) - n + 1):
                gram = seg[i : i + n]
                if gram in STOPWORDS_ZH or BAD_CHARS & set(gram):
                    continue
                if gram[0] in BAD_EDGE or gram[-1] in BAD_EDGE:
                    continue      # "什么方向""方向来着"这类碎片直接丢
                counter[gram] += 1
    # 排序：词典里的词最优先，然后按频次与长度
    def rank(item: tuple[str, int]) -> tuple:
        gram, freq = item
        return (0 if gram in DOMAIN_TERMS or gram in known else 1, -freq, -len(gram), gram)

    ranked = sorted(counter.items(), key=rank)
    picked: list[str] = []
    for gram, _ in ranked:
        if dict_only and gram not in DOMAIN_TERMS and gram not in known:
            continue
        if any(gram in p or p in gram for p in picked):
            continue
        picked.append(gram)
        if len(picked) >= 3:
            break
    return picked


def _en_terms(text: str) -> list[str]:
    counter: Counter[str] = Counter()
    for phrase in EN_RE.findall(text):
        norm = normalize_term(phrase)
        if len(norm) < 3 or norm in STOPWORDS_EN:
            continue
        if any(w in STOPWORDS_EN for w in norm.split()[:1]):
            continue
        counter[norm] += 1
    return [t for t, _ in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]


def rule_extract(text: str, known: set[str] | None = None,
                 dict_only: bool = False) -> list[tuple[str, str]]:
    """不依赖模型的兜底抽取：领域词典 → 英文词组 → 中文 n-gram。"""
    low = (text or "").lower()
    found: list[tuple[str, str]] = []
    for term, cat in DOMAIN_TERMS.items():
        if term.lower() in low and len(term) >= 2:
            found.append((term, cat))
    for term in _en_terms(text or ""):
        found.append((term, guess_category(term)))
    for gram in _zh_grams(text or "", known, dict_only=dict_only):
        found.append((gram, guess_category(gram)))

    # 去重（归一化后）并且限流，避免一条消息塞进十几个噪声词
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for term, cat in found:
        key = canonical(term)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append((term, cat))
        if len(result) >= 6:
            break
    return result


# ----------------------------- 模型抽取 -----------------------------
KEYWORD_SYSTEM = """你是科研关键词抽取器。只输出一个 JSON 对象，不要任何解释文字。
结构：{"terms":[{"term":"关键词","category":"method|domain|dataset|task|other"}]}
要求：
1. 最多 5 个，必须是名词性术语；
2. 中文术语 2-8 个字，英文术语 1-3 个单词，超过就说明你写成句子了，必须拆开或删掉；
3. 一次只写一个概念，不要写"图神经网络 推荐系统"这种组合短语；
4. 不要输出"应用/研究方向/进展/论文"这类没有信息量的泛词；
5. 不要输出与科研无关的词。"""

KEYWORD_USER = "从下面这段用户消息里抽取科研关键词：\n{text}"


def llm_extract(cfg: Settings, text: str) -> list[tuple[str, str]]:
    data = call_json(cfg, KEYWORD_SYSTEM, KEYWORD_USER.format(text=(text or "")[:1500]))
    raw = data.get("terms")
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        if not term:
            continue
        cat = str(item.get("category") or "").strip().lower()
        out.append((term, cat if cat in {"method", "domain", "dataset", "task", "other"} else guess_category(term)))
    return out[:5]


def _split_valid(raw: str) -> list[str]:
    """把一个候选词拆/过滤成合格术语：中英混排的短语拆开，长句与泛词直接丢掉。"""
    term = normalize_term(raw)
    if not term:
        return []
    # 模型爱写"图神经网络 推荐系统"这种组合：拆开分别判断
    if " " in term and re.search(r"[\u4e00-\u9fff]", term):
        out: list[str] = []
        for part in term.split():
            out.extend(_split_valid(part))
        return out
    if term in GENERIC_TERMS or term in STOPWORDS_ZH or term in STOPWORDS_EN:
        return []
    zh_len = len(re.findall(r"[\u4e00-\u9fff]", term))
    words = term.split()
    if zh_len:
        if " " in term or not (2 <= zh_len <= MAX_ZH_LEN):
            return []
        if len(term) > MAX_ZH_LEN + 4:      # 中英混排且过长
            return []
        return [term]
    if not (1 <= len(words) <= MAX_EN_WORDS) or len(term) < 3:
        return []
    if any(len(w) < 2 for w in words):
        return []
    return [term]


def clean_terms(terms: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """统一清洗入口：所有来源的候选词都要过这一层才允许落库。"""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for display, category in terms:
        for term in _split_valid(display):
            key = canonical(term)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append((term, category or guess_category(term)))
    return out


def extract_terms(text: str, cfg: Settings | None = None,
                  known: set[str] | None = None) -> tuple[list[tuple[str, str]], str]:
    """返回 (候选词列表, 抽取方式)；方式用于日志，方便判断模型有没有在工作。"""
    cfg = cfg or settings
    try:
        terms = clean_terms(llm_extract(cfg, text))
        if terms:
            return terms, "llm"
    except LLMJsonError as e:
        log.info("关键词模型抽取不可用，走规则兜底：%s", e)
    # 兜底时中文只认词典里的词：没有模型把关，碎片宁可不抽
    return clean_terms(rule_extract(text, known, dict_only=True)), "rule"


# ----------------------------- 权重 -----------------------------
def compute_weight(times: int, last_seen_at: str | None, source_type: str, max_times: int) -> float:
    """权重 = 0.45×频率 + 0.35×新鲜度 + 0.20×来源可信度。

    search（主动检索）比 chat（随口提及）更能代表真实兴趣，所以给更高的来源分。
    """
    mt = max(1, int(max_times or 1))
    freq = math.log(1 + max(0, int(times))) / math.log(1 + mt)
    half_life = max(1.0, settings.memory_half_life_days)
    freshness = 0.5 ** (days_since(last_seen_at or now_iso()) / half_life)
    source = 1.0 if source_type == "search" else 0.7
    return round(0.45 * freq + 0.35 * freshness + 0.20 * source, 3)


# ----------------------------- 落库 -----------------------------
def record_terms(
    user_id: int,
    terms: Iterable[tuple[str, str]],
    source_type: str,
    source_id: str,
) -> list[str]:
    """把一批候选词写入 keywords 表（同词累加次数），返回本次实际写入的词。"""
    terms = clean_terms(terms)      # 落库前统一清洗：长句、泛词一律拦下
    rows = list_keywords(user_id, limit=1000, min_times=1, min_weight=0.0)
    times_map = {r["term"]: int(r["times"]) for r in rows}
    display_times = {r["display_term"]: int(r["times"]) for r in rows}
    max_times = max(times_map.values(), default=1)

    written: list[str] = []
    for display, category in terms:
        term = canonical(display)
        if not term or len(term) > 60:
            continue
        # 子串压制：已经有更长的高频词（"图神经网络"）时，别再记一个"神经网络"
        if any(display != other and display in other and times >= 2
               for other, times in display_times.items()):
            continue
        times = times_map.get(term, 0) + 1
        weight = compute_weight(times, now_iso(), source_type, max(max_times, times))
        upsert_keyword(
            user_id=user_id,
            term=term,
            display_term=(display or term).strip()[:60],
            category=category or guess_category(term),
            source_type=source_type,
            source_id=str(source_id),
            weight=weight,
        )
        display_times[(display or term).strip()] = times
        times_map[term] = times
        max_times = max(max_times, times)
        written.append(term)
    return written


def extract_from_search(user_id: int, event_id: int, keyword: str,
                        resolved_keyword: str | None, cfg: Settings | None = None) -> list[str]:
    """检索记录本身就是高质量关键词，不需要模型——直接用主题词与其英文检索词。"""
    cfg = cfg or settings
    terms: list[tuple[str, str]] = []
    for raw in (keyword, resolved_keyword):
        text = (raw or "").strip()
        if not text:
            continue
        terms.append((text, guess_category(text)))
    # 主题比较长时再抽一层（"图神经网络在推荐系统冷启动上的应用" → 拆出两个方向）
    if len(keyword or "") > 12:
        extra, _ = extract_terms(keyword, cfg)
        terms.extend(extra)
    return record_terms(user_id, terms, "search", f"s{event_id}")


def extract_from_message(user_id: int, message_id: int, text: str,
                         cfg: Settings | None = None) -> list[str]:
    rows = list_keywords(user_id, limit=500, min_times=1, min_weight=0.0)
    known = {r["term"] for r in rows} | {r["display_term"] for r in rows}
    terms, _ = extract_terms(text, cfg or settings, known=known)
    return record_terms(user_id, terms, "chat", f"m{message_id}")


def recompute_weights(user_id: int) -> int:
    """时间会衰减权重，隔一段时间整体重算一次，保证对外接口里的权重不失真。"""
    rows = list_keywords(user_id, limit=2000, min_times=1, min_weight=0.0)
    max_times = max((int(r["times"]) for r in rows), default=1)
    for row in rows:
        weight = compute_weight(int(row["times"]), row["last_seen_at"], row["source_type"], max_times)
        from ..db import execute  # 局部导入：避免与 db 初始化顺序纠缠

        execute("UPDATE keywords SET weight = ? WHERE id = ?", (weight, row["id"]))
    return len(rows)
