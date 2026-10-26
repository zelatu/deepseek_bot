"""鲸鱼娘 QQ 聊天插件：QQ 消息 → DeepSeek → 鲸鱼娘口吻回复。

记忆架构见 PLAN-记忆系统.md：
    人设（固定） → 事实（每天变一次） → 相关往事（每轮变） → 最近对话
"""

import asyncio

import httpx
from nonebot import get_plugin_config, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, PrivateMessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from pydantic import BaseModel

from . import memory as M
from . import storage as S
from .persona import SYSTEM_PROMPT, build_messages


class Config(BaseModel):
    # DeepSeek 密钥，去 platform.deepseek.com 申请
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    whale_temperature: float = 1.1
    # 每次带多少条历史消息（一问一答算 2 条）
    whale_max_history: int = 10
    whale_timeout: float = 60.0
    # 群聊里除了 @ 之外，以这个词开头也会触发
    whale_trigger_prefix: str = "鲸鱼"
    # 记忆开关。false 则退回纯内存模式（重启失忆）
    whale_memory_enabled: bool = True
    # 允许使用 /记忆 指令的 QQ 号，逗号分隔。留空则只允许私聊使用
    whale_admin_qq: str = ""


__plugin_meta__ = PluginMetadata(
    name="鲸鱼娘聊天",
    description="把 QQ 消息转发给 DeepSeek，用鲸鱼娘的口吻回复，带长期记忆",
    usage="私聊直接说话；群里 @我 或以「鲸鱼」开头；/记忆 查看记住的事",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

config = get_plugin_config(Config)

# 仅当 whale_memory_enabled=false 时使用的内存兜底
_fallback_history: dict[str, list[dict]] = {}


def _session_key(event: MessageEvent) -> str:
    """记忆作用域：按群或按人分开。个人使用阶段，群聊按群存。"""
    if isinstance(event, GroupMessageEvent):
        return f"group_{event.group_id}"
    return f"private_{event.user_id}"


def _is_admin(event: MessageEvent) -> bool:
    admins = [x.strip() for x in config.whale_admin_qq.split(",") if x.strip()]
    if admins:
        return str(event.user_id) in admins
    return isinstance(event, PrivateMessageEvent)


async def _is_for_me(event: MessageEvent) -> bool:
    if isinstance(event, PrivateMessageEvent):
        return True
    if isinstance(event, GroupMessageEvent):
        if event.is_tome():
            return True
        prefix = config.whale_trigger_prefix.strip()
        return bool(prefix) and event.get_plaintext().strip().startswith(prefix)
    return False


async def _is_admin_cmd(event: MessageEvent) -> bool:
    text = event.get_plaintext().strip()
    if not (text.startswith("/记忆") or text.startswith("/忘掉")):
        return False
    return _is_admin(event)


admin_cmd = on_message(rule=Rule(_is_admin_cmd), priority=5, block=True)
chat = on_message(rule=Rule(_is_for_me), priority=10, block=True)


async def _ask_deepseek(messages: list[dict]) -> str:
    if not config.deepseek_api_key:
        raise RuntimeError("还没配置 DEEPSEEK_API_KEY，去 .env 里填上再试")

    url = f"{config.deepseek_api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": config.deepseek_model,
        "messages": messages,
        "temperature": config.whale_temperature,
        "max_tokens": 500,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {config.deepseek_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=config.whale_timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if resp.status_code == 401:
        raise RuntimeError("DeepSeek 返回 401，API Key 不对或已失效")
    if resp.status_code == 402:
        raise RuntimeError("DeepSeek 账户余额不足，去平台充点钱")
    if resp.status_code != 200:
        raise RuntimeError(f"DeepSeek 返回 {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    usage = data.get("usage") or {}
    logger.info(
        f"[tokens] 缓存命中 {usage.get('prompt_cache_hit_tokens', 0)} / "
        f"未命中 {usage.get('prompt_cache_miss_tokens', 0)} / "
        f"输出 {usage.get('completion_tokens', 0)}"
    )
    return data["choices"][0]["message"]["content"].strip()


@admin_cmd.handle()
async def handle_admin_cmd(bot: Bot, event: MessageEvent):
    text = event.get_plaintext().strip()
    scope = _session_key(event)

    if text.startswith("/记忆清空"):
        n = await asyncio.to_thread(S.clear_facts, scope)
        await admin_cmd.finish(f"忘掉 {n} 条了……刚才说啥来着")

    if text.startswith("/忘掉"):
        keyword = text[3:].strip()
        if not keyword:
            await admin_cmd.finish("要忘掉什么呢？用法：/忘掉 香菜")
        n = await asyncio.to_thread(S.deactivate_fact, scope, keyword)
        await admin_cmd.finish(f"忘掉 {n} 条关于「{keyword}」的了" if n else f"我本来就没记住「{keyword}」")

    result = await asyncio.to_thread(M.format_facts, scope)
    await admin_cmd.finish(result)


@chat.handle()
async def handle_chat(bot: Bot, event: MessageEvent):
    text = event.get_plaintext().strip()

    prefix = config.whale_trigger_prefix.strip()
    if isinstance(event, GroupMessageEvent) and prefix and text.startswith(prefix):
        text = text[len(prefix) :].strip()
    elif isinstance(event, GroupMessageEvent) and event.is_tome():
        text = text.lstrip("\u3000 ").strip()

    scope = _session_key(event)
    user_id = str(event.user_id)

    if text in {"重置", "/reset", "清空"}:
        if config.whale_memory_enabled:
            await asyncio.to_thread(S.clear_facts, scope)
        else:
            _fallback_history.pop(scope, None)
        await chat.finish("唔……刚才聊的都忘掉啦")

    if not text:
        await chat.finish("叫我就是为了看我发呆吗……哼")

    try:
        if config.whale_memory_enabled:
            messages = await asyncio.to_thread(M.build_context, scope, text, config.whale_max_history * 2)
        else:
            history = _fallback_history.get(scope, [])
            messages = build_messages(SYSTEM_PROMPT, history, text)

        reply = await _ask_deepseek(messages)
    except asyncio.TimeoutError:
        logger.warning("DeepSeek 请求超时")
        await chat.finish("网有点卡，等会儿再跟我说一遍嘛")
    except Exception as exc:
        logger.error(f"对话失败: {exc}")
        await chat.finish(f"出问题了：{exc}")

    try:
        if config.whale_memory_enabled:
            await asyncio.to_thread(M.record_exchange, scope, user_id, text, reply)
        else:
            h = _fallback_history.setdefault(scope, [])
            h.append({"role": "user", "content": text})
            h.append({"role": "assistant", "content": reply})
            if len(h) > config.whale_max_history * 2:
                del h[: -config.whale_max_history * 2]
    except Exception as exc:
        logger.error(f"记忆写入失败: {exc}")

    logger.info(f"[{scope}] {text[:40]} -> {reply[:40]}")
    await chat.finish(reply[:800])
