# -*- coding: utf-8 -*-
"""小猪数据模型（精简版，仅保留阶段 1 所需）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


MAX_EXPERT_LEVEL = 5


def expert_level_from_copies(copies: int) -> int:
    """根据累计抽取次数计算 EX Lv.；异常或旧数据统一钳制到 0～5。"""
    return min(max(int(copies or 0) - 1, 0), MAX_EXPERT_LEVEL)


@dataclass(frozen=True)
class PigProgress:
    copies: int = 0
    first_obtained_at: Optional[str] = None

    @property
    def expert_level(self) -> int:
        return expert_level_from_copies(self.copies)


@dataclass(frozen=True)
class DrawState:
    pig_ids: list[str]
    progress: dict[str, PigProgress]
    duplicate_streak: int = 0

    def copies_of(self, pig_id: str) -> int:
        item = self.progress.get(pig_id)
        return int(item.copies) if item else 0

    def expert_level_of(self, pig_id: str) -> int:
        return expert_level_from_copies(self.copies_of(pig_id))


@dataclass(frozen=True)
class DailyRollSnapshot:
    date_str: str
    pig_id: str
    is_new_pig: Optional[bool] = None
    previous_copies: Optional[int] = None
    copies_after_roll: Optional[int] = None
    collection_size_after_roll: Optional[int] = None
    resource_version: str = ""
    resolved_variant_level: Optional[int] = None
    resolved_image_name: str = ""
    unlocked_variant_levels: tuple[int, ...] = ()
    unlocked_variant_fields: frozenset[str] = frozenset()

    @property
    def outcome_available(self) -> bool:
        return all(
            value is not None
            for value in (
                self.is_new_pig,
                self.previous_copies,
                self.copies_after_roll,
                self.collection_size_after_roll,
            )
        )


@dataclass(frozen=True)
class DailyRollResult:
    pig_id: str
    created: bool
    is_new_pig: bool = False
    previous_copies: int = 0
    copies: int = 0
    previous_duplicate_streak: int = 0
    duplicate_streak: int = 0
    snapshot: Optional[DailyRollSnapshot] = None

    def __iter__(self):
        yield self.pig_id
        yield self.created
