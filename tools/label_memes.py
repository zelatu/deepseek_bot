"""给表情包打情绪标签（纯规则，不调 API）。

台词里本来就带情绪词（「气鼓鼓」「委屈落泪」「眉开眼笑」），
用关键词映射到 8 个类别即可，比让模型判断更稳定也更便宜。

用法：python tools/label_memes.py
已有 emotion 字段的会跳过，可反复运行。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "assets" / "emo_index.json"

# 只认「台词」情绪词表情包 这种格式，避免把角色名当情绪
_EMO_TAIL = re.compile(r"[』」]([^』」]{1,14}?)表情包\s*$")

RULES: dict[str, list[str]] = {
    "happy": ["笑", "开心", "夸", "棒", "赞", "好耶", "喜", "欢乐", "元气", "萌"],
    "angry": ["气鼓鼓", "生气", "愤怒", "不满", "炸毛", "火大", "凶"],
    "sad": ["委屈", "哭", "难过", "伤心", "落泪", "沮丧", "失落", "瘪嘴"],
    "speechless": ["无语", "尴尬", "沉默", "无奈", "白眼", "汗", "吃瓜", "窥屏"],
    "surprised": ["惊", "慌", "吓", "疑惑", "懵", "心虚", "震", "不解"],
    "smug": ["得意", "嚣张", "傲", "理直气壮", "嘚瑟", "自信", "挑衅"],
    "shy": ["害羞", "羞", "脸红", "紧张", "羞涩"],
}


def classify(caption: str) -> str | None:
    # 优先看「台词」后面那段情绪词，最准
    m = _EMO_TAIL.search(caption)
    if m:
        tail = m.group(1)
        for emo, words in RULES.items():
            if any(w in tail for w in words):
                return emo
    # 退一步在整句里找
    for emo, words in RULES.items():
        if any(w in caption for w in words):
            return emo
    return None


def main() -> None:
    items = json.loads(INDEX.read_text(encoding="utf-8"))

    labeled = 0
    for it in items:
        if it.get("emotion"):
            continue
        emo = classify(it["caption"])
        if emo:
            it["emotion"] = emo
            labeled += 1

    INDEX.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    dist = Counter(it.get("emotion", "unlabeled") for it in items)
    print(f"本次打标 {labeled} 条，总计 {len(items)} 条")
    for k, v in dist.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
