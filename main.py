# -*- coding: utf-8 -*-
"""今日小猪 · AstrBot 版（阶段 1：今日小猪 + 我的猪圈）。

基于 nonebot-plugin-rollpig-plus 移植，仅保留核心抽取功能。
"""

from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.api import logger, AstrBotConfig

from .core import store as store_mod
from .core.store import init_store
from .core.resource_manager import RollPigResourceManager
from .core.roll_flow import (
    resolve_daily_pig,
    build_pigsty_growth_summary,
    RECORDED_PIG_RESOURCE_MISSING_TEXT,
)
from .core.card_renderer import render_pig_card, render_pigsty_summary, render_help, _init_font_dir
from .core.catalog_renderer import render_catalog, render_weekly_summary
from .core.pighub_service import PigHubService, build_image_url
from .core.roast_flow import (
    build_self_roast,
    build_member_roast,
    self_roast_block_text,
)
from .core.roast_manager import RoastManager
from .core.models import RoastEvent
import astrbot.api.message_components as Comp
import asyncio
import random


@register("astrbot_plugin_rollpig_plus", "ALin", "今日小猪 Plus", "1.0.0")
class RollPigPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_rollpig_plus")
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)
        self.data_file = self.plugin_data_dir / "rollpig_data.json"

        # 资源目录（随插件分发）
        self.resource_dir = Path(__file__).parent / "resource"
        _init_font_dir(self.resource_dir)

        # 初始化 store 与资源管理器
        init_store(self.data_file)
        self.resource_manager = RollPigResourceManager(self.resource_dir)
        self.roast_manager = RoastManager(
            self, ai_enabled=self.config.get("roast_ai_enabled", False),
        )
        self.roast_cooldown_hours = int(self.config.get("roast_cooldown_hours", 8))
        self.roast_charge_max = int(self.config.get("roast_charge_max", 2))
        self.pighub = PigHubService(self.plugin_data_dir / "pighub_images.json")
        logger.info(
            f"[rollpig] 小猪资源已加载: {len(self.resource_manager.pig_list)} 只，"
            f"数据文件: {self.data_file}"
        )

    def _uid(self, event: AstrMessageEvent) -> str:
        return str(event.get_sender_id())

    def _uname(self, event: AstrMessageEvent) -> str:
        return event.get_sender_name() or f"用户{self._uid(event)}"

    @filter.command("今日小猪", alias={"今天是什么小猪", "抽小猪", "我的小猪"})
    async def roll_pig(self, event: AstrMessageEvent):
        """抽取今天的小猪"""
        user_id = self._uid(event)
        group_id = str(event.get_group_id() or "")
        if group_id and group_id != "None":
            store_mod.store.mark_group_active_user(group_id, user_id)
        resolution = resolve_daily_pig(
            user_id, group_id, self.resource_manager, include_progress=True,
        )
        if resolution.recorded_pig_missing:
            yield event.plain_result(RECORDED_PIG_RESOURCE_MISSING_TEXT)
            return
        if resolution.missing_resources or not resolution.pig:
            yield event.plain_result("猪圈塌房了（数据缺失）")
            return

        pig = resolution.pig
        image_path = self.resource_manager.image_path(str(pig.get("id", "")))
        # 渲染卡片
        card_path = self.plugin_data_dir / f"rollpig_card_{user_id}.png"
        try:
            render_pig_card(pig, image_path, card_path)
            has_image = card_path.exists()
        except Exception as e:
            logger.error(f"[rollpig] 卡片渲染失败: {e}")
            has_image = False

        # 成长提示
        extra = resolution.growth_text or ""
        if has_image:
            yield event.plain_result(f". 这是你的今日小猪：\n{extra}".strip())
            yield event.image_result(str(card_path))
        else:
            # 降级：文字卡
            text = (
                f"【今日小猪】\n名称：{pig.get('name', '未知小猪')}\n"
                f"描述：{pig.get('description', '无描述')}\n"
                f"解析：{pig.get('analysis', '无解析')}"
            )
            if extra:
                text = extra + "\n" + text
            yield event.plain_result(text)

        # 首次抽猪后结算预约（若该用户有被预约）
        if resolution.was_auto_created:
            async for m in self._deliver_reservations(event, user_id, pig):
                yield m

    async def _deliver_reservations(self, event: AstrMessageEvent, target_id: str, target_pig: dict):
        """目标抽猪后，结算针对他的预约烤猪（对所有参与者各烤一次）。"""
        import datetime
        today = datetime.date.today().isoformat()
        reservation = store_mod.store.get_roast_reservation(target_id, today)
        if not reservation or reservation["status"] != "pending":
            return
        target_name = reservation.get("target_name", f"用户{target_id}")
        origin = getattr(event, "unified_msg_origin", None)
        for participant in reservation["participants"]:
            pid = participant["user_id"]
            pname = participant["name"]
            # 参与者今日小猪
            attacker_pig_id = store_mod.store.get_daily_roll(pid)
            attacker_pig = self.resource_manager.pig_map.get(attacker_pig_id) if attacker_pig_id else None
            outcome = build_member_roast(
                attacker_pig, target_pig, pname, target_name, self.resource_manager,
            )
            text = outcome.plain_text or (
                f"🔥 {pname} 烤了【{target_name}】，出炉的是【{outcome.food_name}】！"
            )
            if origin:
                try:
                    await self.context.send_message(origin, MessageChain([Plain(text)]))
                except Exception:
                    pass
            elif outcome.render_data:
                async for m in self._roast_card(event, outcome.render_data):
                    yield m
        store_mod.store.complete_roast_reservation(target_id, today)

    @filter.command("我的猪圈")
    async def my_pigsty(self, event: AstrMessageEvent):
        """查看猪圈统计（图片渲染）"""
        user_id = self._uid(event)
        draw_state = store_mod.store.get_draw_state(user_id)
        total = len(self.resource_manager.pig_list)
        summary = build_pigsty_growth_summary(
            self._uname(event), draw_state, total,
            pig_name_of=lambda pid: self.resource_manager.pig_map.get(pid, {}).get("name", pid),
        )
        img_path = self.plugin_data_dir / f"rollpig_pigsty_{user_id}.png"
        try:
            render_pigsty_summary(summary, self._uname(event), img_path)
        except Exception as e:
            logger.error(f"[rollpig] 猪圈统计渲染失败: {e}")
            yield event.plain_result(summary)
            return
        yield event.image_result(str(img_path))

    # ================= 阶段 2：烤猪互动 =================

    def _extract_at_id(self, event: AstrMessageEvent) -> str:
        """提取消息中被 @ 的第一个用户 id。"""
        try:
            for seg in event.get_messages():
                if isinstance(seg, Comp.At):
                    return str(getattr(seg, "qq", ""))
        except Exception:
            pass
        import re
        raw = str(getattr(event, "message_str", "") or "")
        m = re.search(r"\[CQ:at,qq=(\d+)\]", raw)
        if m:
            return m.group(1)
        return ""

    async def _get_group_members(self, event: AstrMessageEvent, group_id: str) -> list[str]:
        """获取群成员 user_id 列表。"""
        try:
            info = await event.bot.api.call_action(
                "get_group_member_list", group_id=int(group_id),
            )
            data = info.get("data") if isinstance(info, dict) else info
            if isinstance(data, list):
                return [str(m.get("user_id")) for m in data if isinstance(m, dict) and m.get("user_id")]
        except Exception:
            pass
        return []

    async def _get_group_member_name(self, event: AstrMessageEvent, group_id: str, user_id: str) -> str:
        """获取群成员名片/昵称。"""
        try:
            info = await event.bot.api.call_action(
                "get_group_member_info", group_id=int(group_id), user_id=int(user_id),
            )
            data = info.get("data") if isinstance(info, dict) else info
            if isinstance(data, dict):
                return data.get("card") or data.get("nickname") or f"用户{user_id}"
        except Exception:
            pass
        return f"用户{user_id}"

    async def _roast_card(self, event: AstrMessageEvent, pig_data: dict, extra: str = ""):
        """渲染并发送烤猪结果卡片。"""
        image_path = self.resource_manager.image_path(str(pig_data.get("id", "")))
        card_path = self.plugin_data_dir / f"rollpig_roast_{self._uid(event)}.png"
        try:
            render_pig_card(pig_data, image_path, card_path)
            if extra:
                yield event.plain_result(extra)
            yield event.image_result(str(card_path))
        except Exception as e:
            logger.error(f"[rollpig] 烤猪卡片渲染失败: {e}")
            yield event.plain_result(extra + "\n" + str(pig_data.get("analysis", "")))

    @filter.command("今日烤猪")
    async def today_roast(self, event: AstrMessageEvent):
        """把自己的今日小猪做成料理"""
        uid = self._uid(event)
        group_id = str(event.get_group_id() or "")
        resolution = resolve_daily_pig(uid, group_id, self.resource_manager)
        if not resolution.pig:
            yield event.plain_result("你今天还没抽猪，先发送「今日小猪」再烤吧！")
            return
        block = self_roast_block_text(resolution.pig, self.resource_manager)
        if block:
            yield event.plain_result(block)
            return
        data, food = build_self_roast(resolution.pig, self.resource_manager)
        text = await self.roast_manager.get_roast_text(
            "self", attacker=self._uname(event), food=food,
        )
        if text:
            data["analysis"] = text
        async for m in self._roast_card(event, data):
            yield m

    @filter.command("烤群友")
    async def roast_member(self, event: AstrMessageEvent):
        """用魔法烤箱把群友做成烤猪；目标未抽猪时建立/加入预约"""
        uid = self._uid(event)
        group_id = str(event.get_group_id() or "")
        target_id = self._extract_at_id(event)
        if not target_id:
            yield event.plain_result("请 At 你要烤的群友！")
            return
        if target_id == uid:
            yield event.plain_result("对自己好一点，别自焚。请发送「今日烤猪」。")
            return
        import datetime
        today = datetime.date.today().isoformat()
        target_name = await self._get_group_member_name(event, group_id, target_id)

        # 检查是否已有预约
        reservation = store_mod.store.get_roast_reservation(target_id, today)
        if reservation and reservation["status"] == "pending":
            # 加入预约（免费）
            updated = store_mod.store.join_roast_reservation(
                target_id, today, uid, self._uname(event), group_id,
            )
            if any(p["user_id"] == uid for p in updated["participants"]):
                yield event.plain_result(
                    f"🔥 你已加入对【{target_name}】的预约烤猪，免费添柴！"
                    f"（当前 {len(updated['participants'])} 人，目标抽猪后统一结算）"
                )
            else:
                yield event.plain_result("预约人数已满（12 人）。")
            return

        # 消耗烤猪充能（发起即时烧烤或预约主厨）
        cd = store_mod.store.consume_roast_cooldown(
            uid, cooldown_seconds=self.roast_cooldown_hours * 3600,
            max_charges=self.roast_charge_max,
        )
        if not cd.allowed:
            remaining = cd.remaining_seconds
            minutes, seconds = divmod(remaining, 60)
            hours, minutes = divmod(minutes, 60)
            time_str = f"{hours}小时{minutes}分" if hours > 0 else f"{minutes}分{seconds}秒"
            yield event.plain_result(f"烧烤充能恢复中！还需要 {time_str} 恢复 1 次。")
            return
        # 目标今日小猪
        target_pig_id = store_mod.store.get_daily_roll(target_id)
        if not target_pig_id:
            # 目标未抽猪 → 建立预约（主厨已消耗充能）
            reservation = store_mod.store.create_roast_reservation(
                target_id=target_id, target_name=target_name,
                owner_id=uid, owner_name=self._uname(event),
                owner_pig_id=store_mod.store.get_daily_roll(uid) or "",
                group_id=group_id, date_str=today,
            )
            yield event.plain_result(
                f"📋 已为【{target_name}】建立预约烤猪（你是主厨）！"
                f"其他群友可发送「烤群友 @{target_name}」免费加入添柴，"
                f"目标抽猪后统一结算。（当前 {len(reservation['participants'])} 人）"
            )
            return
        target_pig = self.resource_manager.pig_map.get(target_pig_id)
        if not target_pig:
            yield event.plain_result("目标的小猪记录存在，但资源暂时缺失，请稍后再试。")
            return
        # 攻击者今日小猪
        attacker_pig_id = store_mod.store.get_daily_roll(uid)
        attacker_pig = self.resource_manager.pig_map.get(attacker_pig_id) if attacker_pig_id else None
        attacker_name = self._uname(event)
        outcome = build_member_roast(
            attacker_pig, target_pig, attacker_name, target_name, self.resource_manager,
        )
        # 记录事件
        if group_id:
            store_mod.store.append_roast_event(RoastEvent(
                event_type=outcome.event_type,
                attacker_id=uid, target_id=target_id,
                attacker_name=attacker_name, target_name=target_name,
                food=outcome.food_name, group_id=group_id,
            ))
        if outcome.event_type == "escape" or not outcome.render_data:
            yield event.plain_result(outcome.plain_text or "烧烤失败了！")
            return
        async for m in self._roast_card(event, outcome.render_data, outcome.extra_text):
            yield m

    @filter.command("加急生火")
    async def force_roast(self, event: AstrMessageEvent):
        """每日一次，强制成功烤群友"""
        uid = self._uid(event)
        group_id = str(event.get_group_id() or "")
        target_id = self._extract_at_id(event)
        if not target_id:
            yield event.plain_result("请 At 你要烤的群友！")
            return
        if target_id == uid:
            yield event.plain_result("对自己好一点，别自焚。请发送「今日烤猪」。")
            return
        if not store_mod.store.consume_force_usage(uid):
            yield event.plain_result("【加急生火】今天已经用过了，明天再来吧。")
            return
        target_name = await self._get_group_member_name(event, group_id, target_id)
        target_pig_id = store_mod.store.get_daily_roll(target_id)
        if not target_pig_id:
            yield event.plain_result(f"【{target_name}】今天还没抽猪，没法下嘴！")
            return
        target_pig = self.resource_manager.pig_map.get(target_pig_id)
        if not target_pig:
            yield event.plain_result("目标的小猪记录存在，但资源暂时缺失，请稍后再试。")
            return
        attacker_pig_id = store_mod.store.get_daily_roll(uid)
        attacker_pig = self.resource_manager.pig_map.get(attacker_pig_id) if attacker_pig_id else None
        attacker_name = self._uname(event)
        outcome = build_member_roast(
            attacker_pig, target_pig, attacker_name, target_name, self.resource_manager, force=True,
        )
        if group_id:
            store_mod.store.append_roast_event(RoastEvent(
                event_type="force_roast",
                attacker_id=uid, target_id=target_id,
                attacker_name=attacker_name, target_name=target_name,
                food=outcome.food_name, group_id=group_id,
            ))
        async for m in self._roast_card(event, outcome.render_data, outcome.extra_text):
            yield m

    @filter.command("小猪图鉴")
    async def catalog(self, event: AstrMessageEvent):
        """生成图片版收藏图鉴"""
        uid = self._uid(event)
        draw_state = store_mod.store.get_draw_state(uid)
        items = []
        for pig_id in draw_state.pig_ids:
            pig = self.resource_manager.pig_map.get(pig_id)
            if not pig:
                continue
            items.append({
                "pig": pig,
                "name": pig.get("name", pig_id),
                "ex_level": draw_state.expert_level_of(pig_id),
                "image_path": str(self.resource_manager.image_path(pig_id) or ""),
            })
        if not items:
            yield event.plain_result("你还没有收藏任何小猪，先发送「今日小猪」吧！")
            return
        img_path = self.plugin_data_dir / f"rollpig_catalog_{uid}.png"
        render_catalog(items, img_path)
        yield event.image_result(str(img_path))

    @filter.command("本周小猪")
    async def weekly_summary(self, event: AstrMessageEvent):
        """生成本周猪猪总结长图"""
        uid = self._uid(event)
        import datetime
        today = datetime.date.today()
        week_start = (today - datetime.timedelta(days=6)).isoformat()
        rolls = store_mod.store.get_user_rolls(uid, week_start)
        draw_state = store_mod.store.get_draw_state(uid)
        items = []
        for date_str, pig_id in sorted(rolls.items()):
            pig = self.resource_manager.pig_map.get(pig_id)
            if not pig:
                continue
            items.append({
                "date": date_str,
                "pig": pig,
                "name": pig.get("name", pig_id),
                "ex_level": draw_state.expert_level_of(pig_id),
            })
        img_path = self.plugin_data_dir / f"rollpig_week_{uid}.png"
        render_weekly_summary(self._uname(event), items, img_path)
        yield event.image_result(str(img_path))

    @filter.command("随机小猪", alias={"随机找猪", "随机猪"})
    async def random_pig(self, event: AstrMessageEvent, arg: str = ""):
        """从 PigHub 随机获取猪猪图，最多 10 张"""
        if not await self.pighub.ensure_ready():
            yield event.plain_result("连不上 PigHub，请稍后再试。")
            return
        try:
            count = int(arg) if arg.strip() else 1
        except ValueError:
            count = 1
        count = max(1, min(count, 10))
        selected = self.pighub.sample(count)
        if not selected:
            yield event.plain_result("PigHub 图片索引为空，请稍后再试。")
            return
        for pig in selected[:3]:
            url = build_image_url(pig)
            if url:
                yield event.image_result(url)
        if count > 3:
            yield event.plain_result(f"（共 {count} 张，最多展示 3 张）")

    @filter.command("找猪")
    async def find_pig(self, event: AstrMessageEvent, arg: str = ""):
        """按关键词搜索 PigHub 猪图"""
        keyword = arg.strip()
        if not keyword:
            yield event.plain_result("请加上关键词，如：/找猪 玩偶")
            return
        if not await self.pighub.ensure_ready():
            yield event.plain_result("连不上 PigHub，请稍后再试。")
            return
        found = self.pighub.search(keyword)
        if not found:
            yield event.plain_result(f"没找到叫「{keyword}」的猪。")
            return
        for pig in found[:3]:
            url = build_image_url(pig)
            if url:
                yield event.image_result(url)
        if len(found) > 3:
            yield event.plain_result(f"共找到 {len(found)} 张，最多展示 3 张。")

    @filter.command("昨日小猪")
    async def yesterday_pig(self, event: AstrMessageEvent):
        """查看昨天抽到的小猪"""
        uid = self._uid(event)
        import datetime
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        pig_id = store_mod.store.get_pig_by_date(uid, yesterday)
        if not pig_id:
            yield event.plain_result("你昨天没抽猪。")
            return
        pig = self.resource_manager.pig_map.get(pig_id)
        if not pig:
            yield event.plain_result("昨天那只猪暂时不在当前资源包里。")
            return
        image_path = self.resource_manager.image_path(str(pig.get("id", "")))
        card_path = self.plugin_data_dir / f"rollpig_yest_{uid}.png"
        try:
            render_pig_card(pig, image_path, card_path)
            yield event.plain_result(f"昨天你抽到的是：{pig.get('name', '未知')}")
            yield event.image_result(str(card_path))
        except Exception as e:
            logger.error(f"[rollpig] 昨日卡片渲染失败: {e}")
            yield event.plain_result(f"昨天你抽到的是：{pig.get('name', '未知')}")

    @filter.command("随机烤猪")
    async def random_roast(self, event: AstrMessageEvent):
        """从今日已抽猪的群成员中随机选目标烤"""
        uid = self._uid(event)
        group_id = str(event.get_group_id() or "")
        if not group_id or group_id == "None":
            yield event.plain_result("随机烤猪仅支持群聊~")
            return
        members = await self._get_group_members(event, group_id)
        if not members:
            yield event.plain_result("无法获取群成员列表，请稍后再试。")
            return
        # 今日已抽猪的成员（排除自己）
        candidates = []
        import datetime
        today = datetime.date.today().isoformat()
        for mid in members:
            if mid == uid:
                continue
            if store_mod.store.get_pig_by_date(mid, today):
                candidates.append(mid)
        if not candidates:
            yield event.plain_result("今天还没有群友抽猪，没人可烤！")
            return
        target_id = random.choice(candidates)
        target_name = await self._get_group_member_name(event, group_id, target_id)
        # 消耗攻击者充能
        cd = store_mod.store.consume_roast_cooldown(
            uid, cooldown_seconds=self.roast_cooldown_hours * 3600,
            max_charges=self.roast_charge_max,
        )
        if not cd.allowed:
            remaining = cd.remaining_seconds
            minutes, seconds = divmod(remaining, 60)
            hours, minutes = divmod(minutes, 60)
            time_str = f"{hours}小时{minutes}分" if hours > 0 else f"{minutes}分{seconds}秒"
            yield event.plain_result(f"烧烤充能恢复中！还需要 {time_str} 恢复 1 次。")
            return
        target_pig = self.resource_manager.pig_map.get(store_mod.store.get_daily_roll(target_id))
        if not target_pig:
            yield event.plain_result("目标的小猪记录存在，但资源暂时缺失，请稍后再试。")
            return
        attacker_pig_id = store_mod.store.get_daily_roll(uid)
        attacker_pig = self.resource_manager.pig_map.get(attacker_pig_id) if attacker_pig_id else None
        attacker_name = self._uname(event)
        outcome = build_member_roast(
            attacker_pig, target_pig, attacker_name, target_name, self.resource_manager,
        )
        if group_id:
            store_mod.store.append_roast_event(RoastEvent(
                event_type="random_roast",
                attacker_id=uid, target_id=target_id,
                attacker_name=attacker_name, target_name=target_name,
                food=outcome.food_name, group_id=group_id,
            ))
        if outcome.event_type == "escape" or not outcome.render_data:
            yield event.plain_result(outcome.plain_text or "烧烤失败了！")
            return
        async for m in self._roast_card(event, outcome.render_data, outcome.extra_text):
            yield m

    @filter.command("烤箱补货")
    async def roast_refill(self, event: AstrMessageEvent, arg: str = ""):
        """当日活跃用户发起烧烤次数补货投票"""
        uid = self._uid(event)
        group_id = str(event.get_group_id() or "")
        if not group_id or group_id == "None":
            yield event.plain_result("烤箱补货仅支持群聊~")
            return
        import datetime
        today = datetime.date.today().isoformat()
        # 发起人必须今日已抽猪
        if not store_mod.store.get_daily_roll(uid):
            yield event.plain_result("请先发送「今日小猪」抽猪，再发起补货。")
            return
        refill = store_mod.store.get_group_refill(group_id, today)
        if refill and refill["status"] == "voting":
            # 投票
            weight = 1
            if self._is_group_admin(event, group_id, uid):
                weight = 2
            store_mod.store.vote_group_refill(group_id, today, uid, weight)
            total = sum(refill["votes"].values())
            distinct = len(refill["votes"])
            yield event.plain_result(
                f"已投票！当前 {distinct} 人，{total} 票（需 {refill['required_votes']} 票）。"
            )
            return
        # 发起补货
        active_users = store_mod.store.get_group_active_users(group_id, today)
        if len(active_users) < 3:
            yield event.plain_result(f"今日活跃用户不足（当前 {len(active_users)} 人，需至少 3 人）。")
            return
        required_votes = max(2, (len(active_users) * 25 + 99) // 100)
        expires_at = (datetime.datetime.now() + datetime.timedelta(minutes=10)).isoformat(timespec="seconds")
        refill = store_mod.store.create_group_refill(
            group_id=group_id, initiator_id=uid,
            initiator_name=self._uname(event), date_str=today,
            required_votes=required_votes, expires_at=expires_at,
        )
        yield event.plain_result(
            f"🔋 已发起烤箱补货投票！10 分钟内达到 {required_votes} 票即可补货。"
            f"群友发送「烤箱补货」投票（群主/管理员双票）。"
        )
        # 启动定时结算
        asyncio.create_task(self._refill_timer(group_id, today))

    async def _refill_timer(self, group_id: str, date_str: str):
        """补货投票定时结算。"""
        try:
            await asyncio.sleep(600)
        except asyncio.CancelledError:
            return
        refill = store_mod.store.get_group_refill(group_id, date_str)
        if not refill or refill["status"] != "voting":
            return
        total = sum(refill["votes"].values())
        distinct = len(refill["votes"])
        if distinct >= 2 and total >= refill["required_votes"]:
            store_mod.store.complete_group_refill(group_id, date_str)
            for user_id in store_mod.store.get_group_active_users(group_id, date_str):
                store_mod.store.reset_roast_charges(user_id, self.roast_charge_max)
            self._refill_success = True
        else:
            store_mod.store.complete_group_refill(group_id, date_str)
            self._refill_success = False

    def _is_group_admin(self, event: AstrMessageEvent, group_id: str, user_id: str) -> bool:
        """判断是否群主/管理员（用配置 admins_id）。"""
        try:
            admins = self.config.get("admins_id", [])
            if str(user_id) in [str(x) for x in admins]:
                return True
        except Exception:
            pass
        return False

    @filter.command("带猪", alias={"小猪帮助", "帮助"})
    async def pig_help(self, event: AstrMessageEvent):
        """返回小猪指令图鉴图片"""
        commands = [
            ("今日小猪 / 今天是什么小猪", "抽取今天的小猪"),
            ("我的猪圈", "查看猪圈统计"),
            ("今日烤猪", "把自己的今日小猪做成料理"),
            ("烤群友 @目标", "用魔法烤箱烤群友"),
            ("加急生火 @目标", "每日一次强制成功烤群友"),
            ("小猪图鉴", "生成图片版收藏图鉴"),
            ("本周小猪", "生成本周猪猪总结长图"),
            ("随机小猪 [数量]", "从 PigHub 随机获取猪猪图"),
            ("找猪 关键词", "按关键词搜索 PigHub 猪图"),
            ("昨日小猪", "查看昨天抽到的小猪"),
            ("随机烤猪", "从今日已抽猪的群成员随机选目标烤"),
            ("烤箱补货", "当日活跃用户发起烧烤次数补货投票"),
        ]
        img_path = self.plugin_data_dir / "rollpig_help.png"
        render_help(commands, img_path)
        yield event.image_result(str(img_path))

    async def terminate(self):
        logger.info("今日小猪 Plus 插件已卸载")
