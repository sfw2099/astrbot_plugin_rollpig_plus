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
    CooldownConsumeResult,
    RoastEvent,
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
        u.setdefault("roasted", [])        # 被烤成过的熟食 id 列表
        return u

    # ================= 每日抽取 =================

    def get_daily_roll(self, user_id: str, date_str: Optional[str] = None) -> Optional[str]:
        self._load()
        daily = self._user(user_id)["daily"]
        if not date_str:
            # 无日期时按「今天」判断（跨天自然重置）
            import datetime
            date_str = datetime.date.today().isoformat()
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
        if not date_str:
            # 无日期时按「今天」
            import datetime
            date_str = datetime.date.today().isoformat()
        result = {}
        for uid, u in self._data.get("users", {}).items():
            daily = u.get("daily", {})
            if date_str in daily:
                result[uid] = daily[date_str]
        return result

    # ================= 烤猪 =================

    def consume_roast_cooldown(
        self,
        user_id: str,
        now_ts: Optional[float] = None,
        cooldown_seconds: Optional[int] = None,
        max_charges: Optional[int] = None,
    ) -> CooldownConsumeResult:
        """消耗一次烤猪充能；不足时返回剩余冷却时间。"""
        import time
        now = now_ts or time.time()
        cooldown_seconds = int(cooldown_seconds or 8 * 3600)
        max_charges = int(max_charges or 2)
        with self._lock:
            self._load()
            u = self._user(user_id)
            roast = u.setdefault("roast", {})
            charges = int(roast.get("charges", max_charges))
            next_recover = float(roast.get("next_recover", 0))
            if charges <= 0:
                # 恢复充能（按冷却时间恢复 1 次）
                if now >= next_recover:
                    charges = 1
                    next_recover = now + cooldown_seconds
                else:
                    remaining = int(next_recover - now)
                    return CooldownConsumeResult(
                        allowed=False, remaining_seconds=remaining,
                        charges_left=0, max_charges=max_charges,
                        next_recover_seconds=remaining,
                    )
            else:
                charges -= 1
                if charges == max_charges - 1:
                    next_recover = now + cooldown_seconds
            roast["charges"] = charges
            roast["next_recover"] = next_recover
            self._save()
            return CooldownConsumeResult(
                allowed=True, charges_left=charges, max_charges=max_charges,
            )

    def reset_roast_charges(self, user_id: str, max_charges: Optional[int] = None) -> None:
        """重置烤猪充能到上限（烤箱补货成功用）。"""
        import time
        max_charges = int(max_charges or 2)
        with self._lock:
            self._load()
            roast = self._user(user_id).setdefault("roast", {})
            roast["charges"] = max_charges
            roast["next_recover"] = 0
            self._save()

    def consume_force_usage(self, user_id: str, date_str: Optional[str] = None) -> bool:
        """消耗每日一次的「加急生火」；当天已用则返回 False。"""
        import datetime
        if not date_str:
            date_str = datetime.date.today().isoformat()
        with self._lock:
            self._load()
            u = self._user(user_id)
            force = u.setdefault("force", {})
            if force.get("date") == date_str:
                return False
            force["date"] = date_str
            self._save()
            return True

    def append_roast_event(self, event: RoastEvent) -> None:
        """记录一次烤猪事件（供日报/统计）；并给被烤成目标玩家记入「烤成图鉴」。"""
        import datetime
        import uuid
        with self._lock:
            self._load()
            events = self._data.setdefault("events", [])
            events.append({
                "event_type": event.event_type,
                "attacker_id": event.attacker_id,
                "target_id": event.target_id,
                "attacker_name": event.attacker_name,
                "target_name": event.target_name,
                "food": event.food,
                "group_id": event.group_id,
                "event_id": event.event_id or str(uuid.uuid4()),
                "created_at": event.created_at or datetime.datetime.now().isoformat(timespec="seconds"),
            })
            # 被做成料理的形态记录到被烤成者（target）名下；仅目标真正被做成食物的成功类事件
            record_types = {"success", "force_roast", "random_roast", "self_roast"}
            if event.food and event.target_id and event.event_type in record_types:
                target = self._user(event.target_id)
                if event.food not in target["roasted"]:
                    target["roasted"].append(event.food)
            self._save()

    def get_roasted(self, user_id: str) -> list[str]:
        """返回该玩家被烤成过的熟食 id 列表。"""
        self._load()
        return list(self._user(user_id).get("roasted", []))

    def get_user_rolls(self, user_id: str, start_date: Optional[str] = None) -> dict[str, str]:
        """返回某用户从 start_date 起的 {date_str: pig_id}（按日期升序）。"""
        self._load()
        daily = self._user(user_id)["daily"]
        result = {d: p for d, p in daily.items() if not start_date or d >= start_date}
        return dict(sorted(result.items()))

    # ================= 预约烤猪 =================

    def get_roast_reservation(self, target_id: str, date_str: str) -> Optional[dict]:
        self._load()
        return self._data.setdefault("reservations", {}).get(f"{target_id}|{date_str}")

    def create_roast_reservation(self, *, target_id, target_name, owner_id, owner_name,
                                 owner_pig_id, group_id, date_str) -> dict:
        import uuid
        with self._lock:
            self._load()
            key = f"{target_id}|{date_str}"
            reservations = self._data.setdefault("reservations", {})
            if key in reservations:
                return reservations[key]
            reservation = {
                "reservation_id": str(uuid.uuid4()),
                "date": date_str,
                "group_id": group_id,
                "target_id": target_id,
                "target_name": target_name,
                "owner_id": owner_id,
                "owner_name": owner_name,
                "owner_pig_id": owner_pig_id,
                "participants": [{"user_id": owner_id, "name": owner_name}],
                "status": "pending",
            }
            reservations[key] = reservation
            self._save()
            return reservation

    def join_roast_reservation(self, target_id: str, date_str: str,
                               user_id: str, name: str, group_id: str) -> Optional[dict]:
        with self._lock:
            self._load()
            key = f"{target_id}|{date_str}"
            reservation = self._data.setdefault("reservations", {}).get(key)
            if not reservation:
                return None
            if len(reservation["participants"]) >= 12:
                return reservation
            if any(p["user_id"] == user_id for p in reservation["participants"]):
                return reservation
            reservation["participants"].append({"user_id": user_id, "name": name})
            self._save()
            return reservation

    def complete_roast_reservation(self, target_id: str, date_str: str) -> Optional[dict]:
        with self._lock:
            self._load()
            key = f"{target_id}|{date_str}"
            reservation = self._data.setdefault("reservations", {}).get(key)
            if not reservation:
                return None
            reservation["status"] = "delivered"
            self._save()
            return reservation

    # ================= 烤箱补货 =================

    def mark_group_active_user(self, group_id: str, user_id: str, date_str: Optional[str] = None) -> None:
        import datetime
        if not date_str:
            date_str = datetime.date.today().isoformat()
        with self._lock:
            self._load()
            active = self._data.setdefault("group_active", {}).setdefault(str(group_id), {}).setdefault(date_str, [])
            if str(user_id) not in active:
                active.append(str(user_id))
            self._save()

    def get_group_active_users(self, group_id: str, date_str: Optional[str] = None) -> set[str]:
        import datetime
        if not date_str:
            date_str = datetime.date.today().isoformat()
        self._load()
        return set(self._data.setdefault("group_active", {}).get(str(group_id), {}).get(date_str, []))

    def get_group_refill(self, group_id: str, date_str: Optional[str] = None) -> Optional[dict]:
        import datetime
        if not date_str:
            date_str = datetime.date.today().isoformat()
        self._load()
        return self._data.setdefault("refills", {}).get(f"{group_id}|{date_str}")

    def create_group_refill(self, *, group_id, initiator_id, initiator_name, date_str,
                            required_votes, expires_at) -> dict:
        import uuid
        import datetime
        with self._lock:
            self._load()
            key = f"{group_id}|{date_str}"
            refills = self._data.setdefault("refills", {})
            refill = {
                "request_id": str(uuid.uuid4()),
                "date": date_str,
                "group_id": group_id,
                "initiator_id": initiator_id,
                "initiator_name": initiator_name,
                "votes": {initiator_id: 1},
                "status": "voting",
                "required_votes": required_votes,
                "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "expires_at": expires_at,
            }
            refills[key] = refill
            self._save()
            return refill

    def vote_group_refill(self, group_id: str, date_str: str, user_id: str, weight: int = 1) -> Optional[dict]:
        import datetime
        if not date_str:
            date_str = datetime.date.today().isoformat()
        with self._lock:
            self._load()
            key = f"{group_id}|{date_str}"
            refill = self._data.setdefault("refills", {}).get(key)
            if not refill:
                return None
            refill["votes"][str(user_id)] = max(refill["votes"].get(str(user_id), 0), weight)
            self._save()
            return refill

    def complete_group_refill(self, group_id: str, date_str: str) -> Optional[dict]:
        import datetime
        if not date_str:
            date_str = datetime.date.today().isoformat()
        with self._lock:
            self._load()
            key = f"{group_id}|{date_str}"
            refill = self._data.setdefault("refills", {}).get(key)
            if not refill:
                return None
            refill["status"] = "completed"
            self._save()
            return refill


# 单例，由 main.py 在插件初始化时设置
store: Optional[LocalStore] = None


def init_store(data_path: Path) -> LocalStore:
    global store
    store = LocalStore(data_path)
    return store
