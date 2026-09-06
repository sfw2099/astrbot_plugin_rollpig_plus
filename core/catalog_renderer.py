# -*- coding: utf-8 -*-
"""图鉴与总结渲染（精简版）：小猪图鉴网格、本周小猪总结长图。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .card_renderer import _load_font, _strip_emoji, _text_width


def render_catalog(items: list[dict], output_path: Path, per_page: int = 12) -> Path:
    """渲染小猪图鉴网格。items 为 [{pig, ex_level, name}]。"""
    cols = 3
    cell_w, cell_h = 230, 260
    pad = 20
    header_h = 60

    pages = [items[i:i + per_page] for i in range(0, len(items), per_page)] or [[]]
    page = pages[0]
    rows = (len(page) + cols - 1) // cols if page else 1

    width = pad * 2 + cols * cell_w + (cols - 1) * pad
    height = pad + header_h + rows * (cell_h + pad)

    img = Image.new("RGB", (width, height), (250, 250, 252))
    draw = ImageDraw.Draw(img)

    title_font = _load_font(32, bold=True, title=True)
    draw.text((width // 2, 18), f"小猪图鉴（已收集 {len(items)} 只）", fill=(40, 40, 40), font=title_font, anchor="mt")

    name_font = _load_font(20)
    lv_font = _load_font(18)

    for idx, item in enumerate(page):
        col = idx % cols
        row = idx // cols
        x = pad + col * (cell_w + pad)
        y = pad + header_h + row * (cell_h + pad)

        # 卡片背景
        draw.rounded_rectangle([x, y, x + cell_w, y + cell_h], radius=10,
                               fill=(255, 255, 255), outline=(210, 210, 215), width=1)

        # 猪图（缩放居中）
        pig = item.get("pig", {})
        img_path = item.get("image_path")
        avatar = None
        if img_path and Path(img_path).exists():
            try:
                avatar = Image.open(str(img_path)).convert("RGBA")
                avatar.thumbnail((cell_w - 20, cell_h - 70))
                aw, ah = avatar.size
                img.paste(avatar, (x + (cell_w - aw) // 2, y + 10), mask=avatar)
            except Exception:
                pass
        if not avatar:
            draw.rectangle([x + 20, y + 10, x + cell_w - 20, y + cell_h - 60],
                           fill=(245, 245, 248), outline=(200, 200, 205), width=1)

        # 名称 + EX Lv.
        name = _strip_emoji(str(item.get("name", "未知")))
        nw = _text_width(draw, name, name_font)
        draw.text((x + (cell_w - nw) // 2, y + cell_h - 44), name, fill=(40, 40, 40), font=name_font)
        lv = f"EX Lv.{item.get('ex_level', 0)}"
        lw = _text_width(draw, lv, lv_font)
        draw.text((x + (cell_w - lw) // 2, y + cell_h - 22), lv, fill=(150, 100, 40), font=lv_font)

    img.save(str(output_path), "PNG")
    return output_path


def render_weekly_summary(user_name: str, items: list[dict], output_path: Path) -> Path:
    """渲染本周小猪总结长图。items 为 [{date, pig, name, ex_level}]。"""
    width = 700
    pad = 30
    line_h = 46
    font = _load_font(26)
    title_font = _load_font(36, bold=True, title=True)

    lines = [f"{item['date']} 抽到【{_strip_emoji(item['name'])}】EX Lv.{item['ex_level']}" for item in items]
    if not lines:
        lines = ["本周还没抽猪，明天开始吧！"]

    height = pad * 2 + 80 + len(lines) * line_h
    img = Image.new("RGB", (width, height), (250, 250, 252))
    draw = ImageDraw.Draw(img)

    draw.text((width // 2, 20), f"本周小猪 · {_strip_emoji(user_name)}", fill=(40, 40, 40), font=title_font, anchor="mt")

    y = pad + 80
    for line in lines:
        draw.text((pad + 10, y), line, fill=(60, 60, 60), font=font)
        y += line_h

    img.save(str(output_path), "PNG")
    return output_path
