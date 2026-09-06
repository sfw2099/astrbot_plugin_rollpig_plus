# -*- coding: utf-8 -*-
"""烤猪文案生成（精简版）：无 AI 时用内置文案，启用 AI 时用 AstrBot provider 生成。"""

from __future__ import annotations

import random
from typing import Optional

# 内置文案池（AI 不可用时的回退）
_SUCCESS = [
    "【{target}】被烤成了【{food}】，香气四溢！",
    "🔥 {attacker} 把【{target}】送上了烤架，出炉的是【{food}】！",
]
_ESCAPE = [
    "【{target}】挣脱了烤架，溜了！",
]
_BACKFIRE = [
    "{attacker} 想烤【{target}】，结果自己变成了【{food}】！",
]
_SELF = [
    "今天的你被做成了【{food}】……生活终于对你下手了。",
]

_SYSTEM_PROMPT = (
    "你是小猪烧烤的文案作者，擅长写简短幽默的烤猪文案。"
    "只输出一句 30 字以内的文案，不要解释。"
)


class RoastManager:
    def __init__(self, plugin=None, ai_enabled: bool = False) -> None:
        self.plugin = plugin
        self.ai_enabled = ai_enabled

    async def _ai_text(self, prompt: str) -> Optional[str]:
        if not self.ai_enabled or not self.plugin:
            return None
        try:
            prov_id = await self.plugin.context.get_current_chat_provider_id(None)
            if not prov_id:
                return None
            resp = await self.plugin.context.llm_generate(
                chat_provider_id=prov_id, prompt=prompt, system_prompt=_SYSTEM_PROMPT,
            )
            return (resp.completion_text or "").strip()
        except Exception:
            return None

    async def get_roast_text(self, scene: str, **kw) -> str:
        """scene ∈ success/escape/backfire/self；kw 含 attacker/target/food。"""
        attacker = kw.get("attacker", "")
        target = kw.get("target", "")
        food = kw.get("food", "烤猪")
        prompt = f"烤猪场景：{scene}。攻击者 {attacker}，目标 {target}，成品 {food}。"
        ai = await self._ai_text(prompt)
        if ai:
            return ai
        pool = {
            "success": _SUCCESS, "escape": _ESCAPE,
            "backfire": _BACKFIRE, "self": _SELF,
        }.get(scene, _SUCCESS)
        return random.choice(pool).format(attacker=attacker, target=target, food=food)
