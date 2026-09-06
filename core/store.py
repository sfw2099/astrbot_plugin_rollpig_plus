# -*- coding: utf-8 -*-
"""小猪本地存储（精简版）：每日抽取 + 图鉴进度，直接读写 JSON 文件。

提供 roll_flow.py 所需的接口：
- get_daily_roll / get_or_create_daily_roll / get_draw_state
- mark_group_roll_seen / complete_daily_roll_snapshot
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from .models import (
    DailyRollResult,
    DailyRollSnapshot,
    DrawState,
    PigProgress,
    expert_level_from_copies,
)


class LocalStore:
    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path
        self._lock = threading.Lock()
        self._data: dict = {"users": {}, "group_seen": {}}

    def _load(self) -> None:
        if self.data_path.exists():
            try:
                self._data = json.loads(self.data_path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {"users": {}, "group_seen": {}}
        else:
            self._data = {"users": {}, "group_seen": {}}

    def _save(self) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.data_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.data_path)

    def _user(self, user_id: str) -> dict:
        u = self._data.setdefault("users", {}).setdefault(str(user_id), {})
        u.setdefault("daily", {})          # {date_str: pig_id}
        u.setdefault("collection", {})     # {pig_id: {copies, first_obtained_at}}
        u.setdefault("duplicate_streak", 0)
        return u

    # ================= 每日抽取 =================

    def get_daily_roll(self, user_id: str, date_str: Optional[str] = None) -> Optional[str]:
        self._load()
        daily = self._user(user_id)["daily"]
        if not date_str:
            # 无日期时取最近一天
            if not daily:
                return None
            date_str = max(daily.keys())
        return daily.get(date_str)

    def get_or_create_daily_roll(
        self,
        user_id: str,
        proposed_pig_id: str,
        date_str: Optional[str] = None,
        group_id: str = "",
    ) -> DailyRollResult:
        with self._lock:
            self._load()
            u = self._user(user_id)
            daily = u["daily"]
            if not date_str:
                import datetime
                date_str = datetime.date.today().isoformat()
            # 已有当天记录
            if date_str in daily:
                pig_id = daily[date_str]
                return DailyRollResult(
                    pig_id=pig_id,
                    created=False,
                    is_new_pig=False,
                    copies=0,
                )
            # 首次抽取
            collection = u["collection"]
            prev_copies = int(collection.get(proposed_pig_id, {}).get("copies", 0))
            is_new = proposed_pig_id not in collection
            if is_new:
                import datetime
                collection[proposed_pig_id] = {
                    "copies": 1,
                    "first_obtained_at": datetime.datetime.now().isoformat(timespec="seconds"),
                }
            else:
                collection[proposed_pig_id]["copies"] += 1
            prev_streak = int(u.get("duplicate_streak", 0))
            streak = prev_streak + 1 if not is_new else 0
            u["duplicate_streak"] = streak
            daily[date_str] = proposed_pig_id
            self._save()
            return DailyRollResult(
                pig_id=proposed_pig_id,
                created=True,
                is_new_pig=is_new,
                previous_copies=prev_copies,
                copies=int(collection[proposed_pig_id]["copies"]),
                previous_duplicate_streak=prev_streak,
                duplicate_streak=streak,
            )

    def get_draw_state(self, user_id: str) -> DrawState:
        self._load()
        collection = self._user(user_id)["collection"]
        progress = {}
        for pig_id, info in collection.items():
            progress[pig_id] = PigProgress(
                copies=int(info.get("copies", 0)),
                first_obtained_at=info.get("first_obtained_at"),
            )
        return DrawState(
            pig_ids=list(collection.keys()),
            progress=progress,
            duplicate_streak=int(self._user(user_id).get("duplicate_streak", 0)),
        )

    def mark_group_roll_seen(self, user_id: str, pig_id: str, group_id: str,
                             date_str: Optional[str] = None) -> None:
        self._load()
        if not date_str:
            import datetime
            date_str = datetime.date.today().isoformat()
        seen = self._data.setdefault("group_seen", {}).setdefault(str(group_id), {})
        seen.setdefault(date_str, []).append(str(user_id))
        self._save()

    def complete_daily_roll_snapshot(self, user_id: str, snapshot: DailyRollSnapshot) -> bool:
        # 阶段 1 仅保留基础抽取结果，无需扩展快照
        return False

    # ================= 图鉴 =================

    def get_user_collection(self, user_id: str) -> list[str]:
        self._load()
        return list(self._user(user_id)["collection"].keys())

    def get_pig_by_date(self, user_id: str, date_str: str) -> Optional[str]:
        self._load()
        return self._user(user_id)["daily"].get(date_str)

    def get_daily_rolls(self, date_str: Optional[str] = None) -> dict[str, str]:
        self._load()
        result = {}
        for uid, u in self._data.get("users", {}).items():
            daily = u.get("daily", {})
            if date_str:
                if date_str in daily:
                    result[uid] = daily[date_str]
            else:
                if daily:
                    result[uid] = daily[max(daily.keys())]
        return result


# 单例，由 main.py 在插件初始化时设置
store: Optional[LocalStore] = None


def init_store(data_path: Path) -> LocalStore:
    global store
    store = LocalStore(data_path)
    return store
