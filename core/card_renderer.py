# -*- coding: utf-8 -*-
"""小猪卡片渲染（精简版）：头像 + 名称 + 描述 + 性格分析。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except Exception:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines = []
    cur = ""
    for ch in text:
        cur += ch
        if _text_width(draw, cur, font) > max_w:
            lines.append(cur[:-1])
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def render_pig_card(pig_data: dict, image_path: Optional[Path], output_path: Path) -> Path:
    """渲染小猪卡片并保存到 output_path。返回 output_path。"""
    width, height = 700, 900
    bg = (255, 255, 255)
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    pig_id = str(pig_data.get("id", ""))
    name = str(pig_data.get("name", "未知小猪"))
    desc = str(pig_data.get("description", "无描述"))
    analysis = str(pig_data.get("analysis", "无解析"))

    # 头像
    avatar = None
    if image_path and image_path.exists():
        try:
            avatar = Image.open(str(image_path)).convert("RGBA")
        except Exception:
            avatar = None
    avatar_size = 320
    avatar_x = (width - avatar_size) // 2
    avatar_y = 80
    if avatar:
        avatar.thumbnail((avatar_size, avatar_size))
        img.paste(avatar, (avatar_x, avatar_y), mask=avatar)
    else:
        draw.rectangle([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size],
                       fill=(245, 245, 248), outline=(200, 200, 205), width=2)

    # 名称
    name_font = _load_font(54, bold=True)
    name_w = _text_width(draw, name, name_font)
    draw.text(((width - name_w) // 2, avatar_y + avatar_size + 30), name, fill=(0, 0, 0), font=name_font)

    # 描述
    desc_font = _load_font(30)
    desc_w = _text_width(draw, desc, desc_font)
    draw.text(((width - desc_w) // 2, avatar_y + avatar_size + 110), desc, fill=(85, 85, 85), font=desc_font)

    # 分析（换行）
    analysis_font = _load_font(26)
    max_w = int(width * 0.85)
    lines = _wrap_text(draw, analysis, analysis_font, max_w)
    line_h = 40
    start_y = avatar_y + avatar_size + 180
    for i, line in enumerate(lines):
        lw = _text_width(draw, line, analysis_font)
        draw.text(((width - lw) // 2, start_y + i * line_h), line, fill=(51, 51, 51), font=analysis_font)

    img.save(str(output_path), "PNG")
    return output_path
