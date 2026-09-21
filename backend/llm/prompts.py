"""提示词：要求模型只输出契约里那 6 个字段的严格 JSON。"""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """你是一名科研导航助手，帮助刚入门的学生快速了解一个研究方向。

你的输入是：一个研究主题 + 一组真实检索到的论文（带编号 P1、P2...）。
你的输出是：一份"研究导航报告"，必须严格符合下面的 JSON 结构，不要输出任何解释、不要 Markdown 代码块。

JSON 结构（字段名必须用英文，值用简体中文）：
{
  "overview": "字符串：这个方向在做什么、解决什么问题（150-260字）",
  "themes": [
    {"name": "主题簇名称", "description": "这个主题在做什么（40-90字）", "paper_ids": ["P1", "P3"]}
  ],
  "research_trends": ["趋势1", "趋势2", "趋势3"],
  "reading_path": [
    {"step": 1, "paper_ids": ["P1"], "reason": "为什么先读这篇（30-60字）"}
  ],
  "exploration_questions": ["值得继续查证的问题1", "问题2", "问题3"],
  "limitations": "字符串：检索范围与归纳方法的局限提示（40-80字）"
}

硬性要求：
1. themes 建议 3-5 个，reading_path 建议 3-5 步，research_trends 与 exploration_questions 各 3-5 条。
2. 所有 paper_ids 只能引用我给你的编号，禁止编造论文标题、作者或编号。
3. 归纳必须基于我给的论文；如果信息不足以支撑某个结论，就少写，不要脑补。
4. exploration_questions 是"可以继续去查证的问题"，不要写成"已被证实的研究空白"。
5. limitations 必须提醒用户核对原文、检索范围有限、AI 归纳可能出错。
6. 只输出 JSON，不要任何多余文字。"""


def build_user_prompt(keyword: str, papers: list[dict[str, Any]], abstract_max_chars: int = 600) -> str:
    lines = [f"研究主题：{keyword}", "", f"检索到 {len(papers)} 篇论文（仅以下这些，不得编造）：", ""]
    for p in papers:
        year = p.get("year") or "年份未知"
        source = p.get("source") or "来源未知"
        authors = "、".join((p.get("authors") or [])[:3]) or "作者未知"
        abstract = (p.get("abstract") or "该来源未提供摘要。").strip().replace("\n", " ")
        if len(abstract) > abstract_max_chars:
            abstract = abstract[:abstract_max_chars] + "…"
        lines.append(f"[{p['id']}] {p['title']}")
        lines.append(f"    年份：{year}｜来源：{source}｜作者：{authors}")
        lines.append(f"    摘要：{abstract}")
        lines.append("")
    lines.append("请基于以上论文生成研究导航报告，只输出 JSON。")
    return "\n".join(lines)


REPAIR_SUFFIX = """\n\n你上一次的输出无法解析为合法 JSON，错误是：{error}
请重新输出，严格要求：
1. 只输出一个 JSON 对象，不要代码块、不要注释、不要多余文字；
2. 字段名与之前要求完全一致；
3. paper_ids 只能使用我给出的编号。"""
