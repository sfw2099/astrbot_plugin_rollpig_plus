# -*- coding: utf-8 -*-
"""小猪抽猪规则（精简版）：今日小猪、EX 成长、保底权重、猪圈摘要。"""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import store as store_mod
from .models import (
    DailyRollResult,
    DrawState,
    expert_level_from_copies,
)
from .resource_manager import RollPigResourceManager


DUPLICATE_PITY_WEIGHT_STEP = 0.5
DUPLICATE_PITY_WEIGHT_CAP = 4.0
RECORDED_PIG_RESOURCE_MISSING_TEXT = (
    "你的今日小猪已经抽出来了，但当前 Bot 的小猪资源暂时缺失，请稍后再试。"
)

DAILY_ROLL_NEW_PIG_TEXTS = [
    "✨ 新猪入圈！今天抽到「{pig}」EX Lv.{level}！",
    "🎉 哇，是没见过的「{pig}」！已加入你的猪圈，EX Lv.{level}。",
]
DAILY_ROLL_DUPLICATE_SAME_LEVEL_TEXTS = [
    "🐷 又是「{pig}」，EX Lv.{level}，缘分不浅。",
    "🔁 重复的「{pig}」，EX Lv.{level}。",
]
DAILY_ROLL_DUPLICATE_LEVEL_UP_TEXTS = [
    "📈 「{pig}」升到 EX Lv.{new_level} 啦！",
    "🔥 「{pig}」EX Lv.{old_level} → {new_level}！",
]
DAILY_ROLL_VARIANT_LEVEL_UP_TEXTS = {
    "image": ["🎨 「{pig}」解锁新外观，EX Lv.{new_level}！"],
    "text": ["📝 「{pig}」解锁新文案，EX Lv.{new_level}！"],
    "image_text": ["✨ 「{pig}」解锁新外观和文案，EX Lv.{new_level}！"],
}


@dataclass(frozen=True)
class DailyPigResolution:
    pig: dict | None
    roll_result: DailyRollResult | None = None
    growth_text: str = ""
    missing_resources: bool = False
    recorded_pig_missing: bool = False
    ex_level: int | None = None

    @property
    def was_auto_created(self) -> bool:
        return bool(self.roll_result and self.roll_result.created)


def pick_daily_roll_candidate(user_id: str, resource_manager: RollPigResourceManager) -> dict:
    """按用户当前图鉴状态选择今日候选猪；连续重复越多，新猪权重越高。"""
    store = store_mod.store
    pig_list = resource_manager.pig_list
    draw_state = store.get_draw_state(user_id) if store else DrawState([], {})
    owned_pig_ids = set(draw_state.pig_ids)
    duplicate_streak = max(0, int(draw_state.duplicate_streak or 0))
    new_pig_bonus = min(duplicate_streak * DUPLICATE_PITY_WEIGHT_STEP, DUPLICATE_PITY_WEIGHT_CAP)

    weights = []
    for pig in pig_list:
        pig_id = str(pig.get("id", ""))
        is_unowned = pig_id and pig_id not in owned_pig_ids
        weights.append(1.0 + new_pig_bonus if is_unowned else 1.0)
    return random.choices(pig_list, weights=weights, k=1)[0]


def build_roll_growth_text(result: DailyRollResult, pig_data: dict) -> str:
    if not result.created:
        return ""
    pig_name = pig_data.get("name", "未知小猪")
    current_level = expert_level_from_copies(result.copies)
    if result.is_new_pig:
        return random.choice(DAILY_ROLL_NEW_PIG_TEXTS).format(pig=pig_name, level=current_level)
    previous_level = expert_level_from_copies(result.previous_copies)
    if previous_level == current_level:
        return random.choice(DAILY_ROLL_DUPLICATE_SAME_LEVEL_TEXTS).format(
            pig=pig_name, level=current_level,
        )
    return random.choice(DAILY_ROLL_DUPLICATE_LEVEL_UP_TEXTS).format(
        pig=pig_name, old_level=previous_level, new_level=current_level,
    )


def resolve_daily_pig(
    user_id: str,
    group_id: str = "",
    resource_manager: RollPigResourceManager | None = None,
    *,
    include_progress: bool = False,
) -> DailyPigResolution:
    """取得用户今日形态；没有记录时自动抽取并更新图鉴进度。"""
    store = store_mod.store
    if store is None or resource_manager is None:
        return DailyPigResolution(pig=None, missing_resources=True)

    pig_id = store.get_daily_roll(user_id)
    current_pig = resource_manager.pig_map.get(pig_id) if pig_id else None
    if current_pig:
        if group_id:
            store.mark_group_roll_seen(user_id, current_pig["id"], group_id)
        ex_level = None
        if include_progress:
            draw_state = store.get_draw_state(user_id)
            ex_level = draw_state.expert_level_of(current_pig["id"])
        return DailyPigResolution(pig=current_pig, ex_level=ex_level)

    if pig_id:
        return DailyPigResolution(pig=None, missing_resources=True, recorded_pig_missing=True)

    if not resource_manager.pig_list:
        return DailyPigResolution(pig=None, missing_resources=True)

    proposed_pig = pick_daily_roll_candidate(user_id, resource_manager)
    roll_result = store.get_or_create_daily_roll(user_id, proposed_pig["id"], group_id=group_id)
    pig = resource_manager.pig_map.get(roll_result.pig_id)
    if pig is None:
        return DailyPigResolution(pig=None, missing_resources=True, recorded_pig_missing=True)
    return DailyPigResolution(
        pig=pig,
        roll_result=roll_result,
        growth_text=build_roll_growth_text(roll_result, pig) if include_progress else "",
        ex_level=expert_level_from_copies(roll_result.copies) if include_progress else None,
    )


def build_pigsty_growth_summary(
    user_name: str, draw_state: DrawState, total_pigs: int,
    pig_name_of=None,
) -> str:
    if pig_name_of is None:
        pig_name_of = lambda pig_id: pig_id
    user_count = len(draw_state.pig_ids)
    percent = int((user_count / total_pigs) * 100) if total_pigs > 0 else 0

    ranked_progress = sorted(
        draw_state.progress.items(),
        key=lambda item: (-item[1].copies, item[1].first_obtained_at or "", item[0]),
    )
    favorite_line = "🐷 本命猪：暂无"
    top_repeat_line = "⭐ 高等级小猪：暂无重复猪，猪圈还很清新"
    max_level = 0
    maxed_count = 0
    if ranked_progress:
        levels = [progress.expert_level for _, progress in ranked_progress]
        max_level = max(levels)
        maxed_count = sum(1 for level in levels if level >= 5)
        favorite_id, favorite_progress = ranked_progress[0]
        favorite_name = pig_name_of(favorite_id)
        favorite_line = f"🐷 本命猪：【{favorite_name}】EX Lv.{favorite_progress.expert_level}（累计 {favorite_progress.copies} 次）"
        repeat_items = [(pid, prog) for pid, prog in ranked_progress if prog.copies >= 2][:5]
        if repeat_items:
            parts = [f"【{pig_name_of(pid)}】EX Lv.{prog.expert_level}" for pid, prog in repeat_items]
            top_repeat_line = "⭐ 高等级小猪：" + "、".join(parts)

    if draw_state.duplicate_streak > 0:
        streak_line = f"🔥 连续重复：{draw_state.duplicate_streak} 次（新猪气息正在靠近）"
    else:
        streak_line = "🔥 连续重复：0 次（下一只从平常心开始）"

    footer_line = "发送「今日小猪」开始收集。" if user_count <= 0 else "发送「小猪图鉴」查看图片版完整图鉴。"

    return (
        f"【我的猪圈统计】\n"
        f"👑 猪圈主人：{user_name}\n"
        f"📦 已收集：{user_count} / {total_pigs} 只\n"
        f"📈 收藏率：{percent}%\n"
        f"🏅 最高等级：EX Lv. {max_level}｜满级 {maxed_count} 只\n"
        f"{favorite_line}\n"
        f"{top_repeat_line}\n"
        f"{streak_line}\n"
        f"━━━━━━━━━━━━━━\n"
        f"{footer_line}"
    )
