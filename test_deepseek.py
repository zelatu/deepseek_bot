"""不接 QQ 也能测：验证 DeepSeek Key 是否可用 + 看鲸鱼娘人设效果。

用法：
    .venv\\Scripts\\python.exe test_deepseek.py          单次测试
    .venv\\Scripts\\python.exe test_deepseek.py -i       进入交互对话，Ctrl+C 退出
"""

import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location("persona", ROOT / "plugins/whale_chat/persona.py")
persona = importlib.util.module_from_spec(spec)
spec.loader.exec_module(persona)

env = dotenv_values(ROOT / ".env")
API_KEY = env.get("DEEPSEEK_API_KEY", "").strip()
API_BASE = env.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1").strip()
MODEL = env.get("DEEPSEEK_MODEL", "deepseek-chat").strip()
TEMPERATURE = float(env.get("WHALE_TEMPERATURE", "1.1"))

if not API_KEY:
    print("[x] .env 里的 DEEPSEEK_API_KEY 还是空的")
    print("    去 https://platform.deepseek.com 创建 Key，填进 .env 再跑一次")
    sys.exit(1)


async def ask(client: httpx.AsyncClient, messages: list[dict]) -> str:
    resp = await client.post(
        f"{API_BASE.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": TEMPERATURE,
            "max_tokens": 500,
        },
    )
    if resp.status_code != 200:
        print(f"[x] HTTP {resp.status_code}: {resp.text[:300]}")
        return ""
    return resp.json()["choices"][0]["message"]["content"].strip()


async def main() -> None:
    interactive = "-i" in sys.argv
    history: list[dict] = []

    async with httpx.AsyncClient(timeout=60) as client:
        if not interactive:
            print(f"模型: {MODEL}  接口: {API_BASE}\n")
            reply = await ask(client, persona.build_messages(persona.SYSTEM_PROMPT, [], "你好呀，你是谁？"))
            print(f"鲸鱼娘 > {reply}")
            return

        print("交互模式，直接输入说话，Ctrl+C 退出。输入 reset 清空上下文。\n")
        while True:
            try:
                text = input("你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n拜拜～")
                return
            if not text:
                continue
            if text == "reset":
                history.clear()
                print("[上下文已清空]\n")
                continue
            reply = await ask(client, persona.build_messages(persona.SYSTEM_PROMPT, history, text))
            if reply:
                print(f"鲸鱼娘 > {reply}\n")
                history.append({"role": "user", "content": text})
                history.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    asyncio.run(main())
