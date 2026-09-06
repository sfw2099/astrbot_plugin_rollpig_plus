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
from .core.card_renderer import render_pig_card


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

        # 初始化 store 与资源管理器
        init_store(self.data_file)
        self.resource_manager = RollPigResourceManager(self.resource_dir)
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
        """查看猪圈统计"""
        user_id = self._uid(event)
        draw_state = store_mod.store.get_draw_state(user_id)
        total = len(self.resource_manager.pig_list)
        summary = build_pigsty_growth_summary(
            self._uname(event), draw_state, total,
            pig_name_of=lambda pid: self.resource_manager.pig_map.get(pid, {}).get("name", pid),
        )
        yield event.plain_result(summary)

    async def terminate(self):
        logger.info("今日小猪 Plus 插件已卸载")
