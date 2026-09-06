# -*- coding: utf-8 -*-
"""小猪卡片渲染（精简版）：头像 + 名称 + 描述 + 性格分析。

内置思源黑体（SourceHanSansSC-Medium.otf）与 ZCOOL 快乐体，优先加载插件内置字体，
确保 Docker/Linux 服务器也能正常显示中文。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


# 去除 emoji（思源黑体/默认字体不支持，显示为豆腐块）
_EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\u202E\u3030\u303D]"
)


def _strip_emoji(text: str) -> str:
    return _EMOJI_PATTERN.sub("", text)


_FONT_DIR = None


def _init_font_dir(resource_dir: Path) -> None:
    global _FONT_DIR
    _FONT_DIR = resource_dir / "fonts"


def _load_font(size: int, *, bold: bool = False, title: bool = False) -> ImageFont.FreeTypeFont:
    """按顺序尝试字体：内置思源黑体/ZCOOL → 系统字体 → 默认。

    title=True 时优先用 ZCOOL 快乐体（标题风格）。
    """
    candidates = []
    if _FONT_DIR is not None:
        if title:
            candidates.append(_FONT_DIR / "ZCOOLKuaiLe-Regular.ttf")
        candidates.append(_FONT_DIR / "SourceHanSansSC-Medium.otf")
    candidates += [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
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

    # 名称（标题字体）
    name_font = _load_font(54, bold=True, title=True)
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


def render_pigsty_summary(summary: str, user_name: str, output_path: Path) -> Path:
    """渲染「我的猪圈」统计长图。summary 为多行文本（渲染前去除 emoji）。"""
    width = 700
    pad = 30
    line_h = 48
    font = _load_font(30)
    title_font = _load_font(40, bold=True, title=True)

    summary = _strip_emoji(summary)
    lines = [ln for ln in summary.splitlines() if ln.strip()]
    height = pad * 2 + 70 + len(lines) * line_h

    img = Image.new("RGB", (width, height), (250, 250, 252))
    draw = ImageDraw.Draw(img)

    draw.text((width // 2, 20), f"猪圈主人：{_strip_emoji(user_name)}", fill=(40, 40, 40), font=title_font, anchor="mt")

    y = pad + 70
    for line in lines:
        draw.text((pad + 10, y), line, fill=(60, 60, 60), font=font)
        y += line_h

    img.save(str(output_path), "PNG")
    return output_path
