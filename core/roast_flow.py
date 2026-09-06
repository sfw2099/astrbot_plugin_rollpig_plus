# -*- coding: utf-8 -*-
"""烤猪规则（精简版）：今日烤猪、烤群友、随机烤猪、加急生火。

判定：成功 60% / 逃脱 30% / 反噬 10%。
特殊形态（人类/熟食/吃掉了/卖掉了）不可被烤。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .resource_manager import RollPigResourceManager


@dataclass(frozen=True)
class RoastOutcome:
    event_type: str  # success / escape / backfire
    render_data: Optional[dict] = None
    plain_text: str = ""
    extra_text: str = ""
    food_name: str = ""


# ---------- 内置文案 ----------
ROAST_SUCCESS_TEXTS = [
    "【{target}】被烤成了【{food}】，香气四溢！",
    "🔥 {attacker} 把【{target}】送上了烤架，出炉的是【{food}】！",
]
ROAST_ESCAPE_TEXTS = [
    "【{target}】挣脱了烤架，溜了！",
    "😱 {attacker} 扑了个空，【{target}】跑了！",
]
ROAST_BACKFIRE_TEXTS = [
    "{attacker} 想烤【{target}】，结果自己变成了【{food}】！",
    "反噬！{attacker} 被自己的魔法烤箱烤成了【{food}】！",
]
SELF_ROAST_TEXTS = [
    "今天的你被做成了【{food}】……生活终于对你下手了。",
    "你把自己烤成了【{food}】，真香！",
]

# 不可烤形态提示
HUMAN_BLOCK = "你是人类形态，烤架拒绝处理。"
EATEN_BLOCK = "你已经是「吃掉了」形态了，别再烤了。"
SOLD_BLOCK = "你已经是「卖掉了」形态了。"
FOOD_BLOCK = "你已经是【{shape}】了，别鞭尸了。"

FORCE_LIMIT_TEXT = "【加急生火】今天已经用过了，明天再来吧。"


def pick_food_pig(resource_manager: RollPigResourceManager) -> dict:
    """随机取一个熟食模板（从 pig_rules.json 的 food_pigs）。"""
    food_ids = _food_ids(resource_manager)
    if not food_ids:
        # 回退：用常见的可烤猪
        food_ids = ["roasted-pig", "bacon", "mc_porkchop", "pork-skewer"]
    food_id = random.choice(food_ids)
    food = resource_manager.pig_map.get(food_id)
    if not food:
        # 任选一只非特殊形态的猪
        normal = [p for p in resource_manager.pig_list if p.get("id") not in _special_ids(resource_manager)]
        return random.choice(normal) if normal else {"id": "pig", "name": "烤猪", "description": "烤猪", "analysis": "烤猪"}
    return food


def _food_ids(rm: RollPigResourceManager) -> list[str]:
    rules = rm.resource_dir / "pig_rules.json"
    import json
    try:
        data = json.loads(rules.read_text(encoding="utf-8-sig"))
        return list(data.get("food_pigs", []))
    except Exception:
        return []


def _special_ids(rm: RollPigResourceManager) -> set[str]:
    rules = rm.resource_dir / "pig_rules.json"
    import json
    try:
        data = json.loads(rules.read_text(encoding="utf-8-sig"))
        ids = set()
        for key in ("food_pigs", "human_pigs", "eaten_pigs", "sold_pigs"):
            ids.update(data.get(key, []))
        return ids
    except Exception:
        return set()


def _is_special(pig: Optional[dict], rm: RollPigResourceManager) -> bool:
    if not pig:
        return False
    return str(pig.get("id", "")) in _special_ids(rm)


def build_self_roast(pig_data: dict, rm: RollPigResourceManager) -> tuple[dict, str]:
    """今日烤猪：返回 (熟食卡片数据, 熟食名)。"""
    food = pick_food_pig(rm)
    text = random.choice(SELF_ROAST_TEXTS).format(food=food.get("name", "烤猪"))
    data = dict(food)
    data["analysis"] = text
    return data, food.get("name", "烤猪")


def build_member_roast(
    attacker_pig: Optional[dict],
    target_pig: dict,
    attacker_name: str,
    target_name: str,
    rm: RollPigResourceManager,
    force: bool = False,
) -> RoastOutcome:
    """烤群友判定。force=True 强制成功（加急生火）。"""
    food = pick_food_pig(rm)
    food_name = food.get("name", "烤猪")

    if force:
        data = dict(food)
        data["analysis"] = random.choice(ROAST_SUCCESS_TEXTS).format(
            attacker=attacker_name, target=target_name, food=food_name)
        return RoastOutcome(event_type="success", render_data=data, food_name=food_name)

    roll = random.randint(1, 100)
    if roll <= 60:
        data = dict(food)
        data["analysis"] = random.choice(ROAST_SUCCESS_TEXTS).format(
            attacker=attacker_name, target=target_name, food=food_name)
        return RoastOutcome(event_type="success", render_data=data, food_name=food_name)
    if roll <= 90:
        return RoastOutcome(
            event_type="escape",
            plain_text=random.choice(ROAST_ESCAPE_TEXTS).format(
                attacker=attacker_name, target=target_name),
        )
    # 反噬
    if _is_special(attacker_pig, rm):
        return RoastOutcome(
            event_type="backfire",
            plain_text=random.choice(ROAST_BACKFIRE_TEXTS).format(
                attacker=attacker_name, target=target_name, food=food_name),
        )
    data = dict(food)
    data["analysis"] = random.choice(ROAST_BACKFIRE_TEXTS).format(
        attacker=attacker_name, target=target_name, food=food_name)
    return RoastOutcome(event_type="backfire", render_data=data, food_name=food_name)


def self_roast_block_text(pig_data: Optional[dict], rm: RollPigResourceManager) -> Optional[str]:
    """今日烤猪的拦截提示；可烤时返回 None。"""
    if not pig_data:
        return None
    pid = str(pig_data.get("id", ""))
    rules = rm.resource_dir / "pig_rules.json"
    import json
    try:
        data = json.loads(rules.read_text(encoding="utf-8-sig"))
    except Exception:
        data = {}
    if pid in data.get("human_pigs", []):
        return HUMAN_BLOCK
    if pid in data.get("eaten_pigs", []):
        return EATEN_BLOCK
    if pid in data.get("sold_pigs", []):
        return SOLD_BLOCK
    if pid in data.get("food_pigs", []):
        return FOOD_BLOCK.format(shape=pig_data.get("name", "熟食"))
    return None
