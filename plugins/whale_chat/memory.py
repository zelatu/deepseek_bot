"""记忆编排：把存储、向量检索、人设拼成一次请求的 messages。

请求结构（顺序不能乱，前两段稳定才能命中 DeepSeek 的上下文缓存）：
    [system] 人设（永不改动）
    [system] 已知事实（每天最多变一次）
    [system] 可能相关的往事（每轮变，但这部分本来就短）
    [user/assistant] 最近若干轮
    [user] 当前这句话
"""

from __future__ import annotations

from . import embedding as E
from . import storage as S
from .persona import SYSTEM_PROMPT

RELATED_TOP_K = 4
RELATED_MIN_SCORE = 0.35
FACTS_CHAR_BUDGET = 900  # 事实块字符上限，防止画像无限膨胀


def _facts_block(scope: str) -> str:
    facts = S.list_facts(scope)
    if not facts:
        return ""

    lines: list[str] = []
    used = 0
    for f in facts:
        line = f"- {f['content']}"
        if used + len(line) > FACTS_CHAR_BUDGET:
            break
        lines.append(line)
        used += len(line)

    if not lines:
        return ""
    return "【关于对方你已经知道的事】\n" + "\n".join(lines)


def _related_block(scope: str, query: str, exclude_ids: set[int]) -> str:
    """向量检索相关往事。失败时静默返回空字符串，不影响正常对话。"""
    try:
        candidates = S.messages_with_embedding(scope)
        if not candidates:
            return ""

        candidates = [c for c in candidates if c["id"] not in exclude_ids]
        if not candidates:
            return ""

        import numpy as np

        matrix = np.vstack([E.from_blob(c["embedding"]) for c in candidates])
        qv = E.embed_query(query)
        hits = E.top_k(qv, matrix, RELATED_TOP_K, RELATED_MIN_SCORE)
        if not hits:
            return ""

        lines = [f"- {candidates[i]['content'][:120]}" for i, _ in hits]
        return "【可能相关的往事，仅供参考，不必强行提及】\n" + "\n".join(lines)
    except Exception:
        return ""


def build_context(scope: str, current_text: str, recent_limit: int = 10) -> list[dict]:
    recent = S.recent_messages(scope, recent_limit)
    recent_ids = {m["id"] for m in recent}

    system_parts = [SYSTEM_PROMPT]
    facts = _facts_block(scope)
    if facts:
        system_parts.append(facts)
    related = _related_block(scope, current_text, recent_ids)
    if related:
        system_parts.append(related)

    messages: list[dict] = [{"role": "system", "content": "\n\n".join(system_parts)}]
    for m in recent:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": current_text})
    return messages


def record_exchange(scope: str, user_id: str | None, user_text: str, reply: str) -> None:
    """落库 + 向量化。同步函数，调用方请用 asyncio.to_thread 包一层。"""
    msg_id = S.add_message(scope, user_id, "user", user_text)
    S.add_message(scope, user_id, "assistant", reply)
    try:
        vec = E.embed_passages([user_text])[0]
        S.set_embedding(msg_id, E.to_blob(vec))
    except Exception:
        pass  # 向量化失败不影响对话，只是这条搜不到


def format_facts(scope: str) -> str:
    facts = S.list_facts(scope)
    if not facts:
        return "我现在什么都没记住呢……多聊几句嘛"

    lines = ["我记住这些了："]
    for i, f in enumerate(facts, 1):
        tag = f"（{f['category']}）" if f.get("category") and f["category"] != "其他" else ""
        exp = "　[短期]" if f.get("temporal") else ""
        lines.append(f"{i}. {f['content']}{tag}{exp}")
    return "\n".join(lines)
