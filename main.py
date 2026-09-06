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
from .core.card_renderer import render_pig_card, render_pigsty_summary, _init_font_dir
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
        """用魔法烤箱把群友做成烤猪"""
        uid = self._uid(event)
        group_id = str(event.get_group_id() or "")
        target_id = self._extract_at_id(event)
        if not target_id:
            yield event.plain_result("请 At 你要烤的群友！")
            return
        if target_id == uid:
            yield event.plain_result("对自己好一点，别自焚。请发送「今日烤猪」。")
            return
        # 消耗烤猪充能
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
            yield event.plain_result(f"【{target_id}】今天还没抽猪，没法下嘴！")
            return
        target_pig = self.resource_manager.pig_map.get(target_pig_id)
        if not target_pig:
            yield event.plain_result("目标的小猪记录存在，但资源暂时缺失，请稍后再试。")
            return
        # 攻击者今日小猪
        attacker_pig_id = store_mod.store.get_daily_roll(uid)
        attacker_pig = self.resource_manager.pig_map.get(attacker_pig_id) if attacker_pig_id else None
        attacker_name = self._uname(event)
        target_name = f"用户{target_id}"
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
        if outcome.event_type == "escape":
            yield event.plain_result(outcome.plain_text or "对方逃脱了！")
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
        target_pig_id = store_mod.store.get_daily_roll(target_id)
        if not target_pig_id:
            yield event.plain_result(f"【{target_id}】今天还没抽猪，没法下嘴！")
            return
        target_pig = self.resource_manager.pig_map.get(target_pig_id)
        if not target_pig:
            yield event.plain_result("目标的小猪记录存在，但资源暂时缺失，请稍后再试。")
            return
        attacker_pig_id = store_mod.store.get_daily_roll(uid)
        attacker_pig = self.resource_manager.pig_map.get(attacker_pig_id) if attacker_pig_id else None
        attacker_name = self._uname(event)
        target_name = f"用户{target_id}"
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

    @filter.command("随机小猪")
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

    async def terminate(self):
        logger.info("今日小猪 Plus 插件已卸载")
