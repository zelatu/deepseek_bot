"""离线提炼：把对话压成事实，写进 facts 表。

用法：
    python distill.py                自动判断，新对话不足 30 条就跳过
    python distill.py --force        忽略阈值，强制提炼
    python distill.py --scope group_123   只处理指定会话
    python distill.py --list         看各会话有多少待提炼消息

建议用 Windows 任务计划每天跑一次，脚本自己决定要不要真干活。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).parent

# 直接加载模块文件，绕开包 __init__.py（它需要 NoneBot 环境）
_spec = importlib.util.spec_from_file_location("whale_storage", ROOT / "plugins/whale_chat/storage.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

MIN_NEW_MESSAGES = 30

env = dotenv_values(ROOT / ".env")
API_KEY = env.get("DEEPSEEK_API_KEY", "").strip()
API_BASE = env.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1").strip()
MODEL = env.get("DEEPSEEK_MODEL", "deepseek-chat").strip()

DISTILL_PROMPT = """你是记忆整理助手。下面是一段用户与 AI 的聊天记录，请提取「值得长期记住的事实」。

严格要求：
1. 只提取对话中**明确出现**的信息。不要推测、不要脑补、不要把玩笑当事实。
2. 每条不超过 20 个字，用第三人称陈述，例如「不吃香菜」「养了只猫叫豆豆」。
3. 分类规则：
   - 长期：不会随时间改变（姓名、喜好、宠物、职业、居住地、性格）
   - 短期：有时效（正在做的事、近期计划），必须给 days（多少天后失效）
   - 一次性：情绪、临时状态、当天的琐事 —— **一律不要提取**
4. 如果这段对话里没有任何值得记住的信息，返回空数组 []。

输出纯 JSON 数组，不要任何解释文字，格式：
[{"content": "不吃香菜", "category": "长期", "temporal": false, "days": 0},
 {"content": "在准备面试", "category": "短期", "temporal": true, "days": 30}]
"""


def call_llm(transcript: str) -> list[dict]:
    if not API_KEY:
        raise RuntimeError(".env 里没有 DEEPSEEK_API_KEY")

    resp = httpx.post(
        f"{API_BASE.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": DISTILL_PROMPT},
                {"role": "user", "content": transcript},
            ],
            "temperature": 0.2,
            "max_tokens": 800,
        },
        timeout=90,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    raw = resp.json()["choices"][0]["message"]["content"].strip()
    # 容错：模型有时会包 ```json 代码块
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.lower().startswith("json") else raw
    raw = raw.strip()

    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        print(f"  [!] 模型输出不是合法 JSON，跳过：{raw[:120]}")
        return []


def process_scope(scope: str, force: bool = False) -> None:
    cursor = S.get_distill_cursor(scope)
    new_msgs = S.messages_after(scope, cursor)

    if not new_msgs:
        print(f"[{scope}] 没有新对话，跳过")
        return

    if len(new_msgs) < MIN_NEW_MESSAGES and not force:
        print(f"[{scope}] 新对话 {len(new_msgs)} 条 < {MIN_NEW_MESSAGES}，暂不提炼")
        return

    print(f"[{scope}] 处理 {len(new_msgs)} 条新对话...")
    lines = []
    for m in new_msgs:
        who = "用户" if m["role"] == "user" else "鲸鱼娘"
        lines.append(f"{who}: {m['content']}")
    transcript = "\n".join(lines)[-6000:]  # 控制输入长度

    facts = call_llm(transcript)
    if not facts:
        print("  没提炼出可记住的内容")
    else:
        added = 0
        for f in facts:
            content = str(f.get("content", "")).strip()
            if not content or len(content) > 40:
                continue
            days = int(f.get("days") or 0) if f.get("temporal") else None
            result = S.add_fact(
                scope=scope,
                content=content,
                category=str(f.get("category") or "其他"),
                temporal=bool(f.get("temporal")),
                days=days,
            )
            if result:
                added += 1
                print(f"  + {content}")
        print(f"  新增 {added} 条（重复的已跳过）")

    S.prune_facts(scope, keep=80)
    S.set_distill_cursor(scope, new_msgs[-1]["id"])
    print(f"  进度已记录到 message #{new_msgs[-1]['id']}")


def main() -> None:
    args = sys.argv[1:]
    force = "--force" in args
    target = None
    if "--scope" in args:
        target = args[args.index("--scope") + 1]

    scopes = [target] if target else S.all_scopes()

    if "--list" in args:
        print(f"{'会话':<28} {'待提炼':>6} {'已有事实':>8}")
        for sc in scopes:
            cursor = S.get_distill_cursor(sc)
            pending = len(S.messages_after(sc, cursor))
            print(f"{sc:<28} {pending:>6} {len(S.list_facts(sc, include_expired=True)):>8}")
        return

    if not scopes:
        print("还没有任何对话记录")
        return

    for sc in scopes:
        try:
            process_scope(sc, force=force)
        except Exception as exc:
            print(f"[{sc}] 失败: {exc}")


if __name__ == "__main__":
    main()
