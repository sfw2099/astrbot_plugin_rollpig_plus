# -*- coding: utf-8 -*-
"""小猪资源管理（精简版）：加载内置 pig.json + image/，可选云端 manifest 同步。

阶段 1 仅提供基础图片；EX 差分立绘/文案在阶段 3 再接入。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("rollpig")


class RollPigResourceManager:
    """加载并缓存小猪资源列表与图片路径。"""

    def __init__(self, resource_dir: Path) -> None:
        self.resource_dir = resource_dir
        self.pig_list: list[dict[str, Any]] = []
        self.pig_map: dict[str, dict[str, Any]] = {}
        self._load_builtin()

    def _load_builtin(self) -> None:
        pig_path = self.resource_dir / "pig.json"
        if not pig_path.exists():
            logger.error("pig.json 缺失，小猪资源为空")
            return
        try:
            data = json.loads(pig_path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            logger.error(f"pig.json 解析失败: {e}")
            return
        if not isinstance(data, list):
            logger.error("pig.json 应为列表")
            return
        self.pig_list = [item for item in data if isinstance(item, dict) and item.get("id")]
        self.pig_map = {str(item["id"]): item for item in self.pig_list}

    def image_path(self, pig_id: str) -> Optional[Path]:
        """按 id 查找基础图片；支持多后缀。"""
        if not pig_id:
            return None
        image_dir = self.resource_dir / "image"
        for ext in ("png", "jpg", "jpeg", "webp", "gif"):
            f = image_dir / f"{pig_id}.{ext}"
            if f.exists():
                return f
        return None

    def image_file_is_decodable(self, image_file: Optional[Path]) -> bool:
        if image_file is None:
            return False
        try:
            from PIL import Image
            with Image.open(str(image_file)) as im:
                im.verify()
            return True
        except Exception:
            return False

    def resolve_pig_appearance(self, pig_data: dict, ex_level: int = 0) -> Any:
        """解析小猪外观。阶段 1 仅返回基础图片（无 EX 差分）。"""
        pig_id = str(pig_data.get("id", ""))
        return PigAppearance(
            pig_data=pig_data,
            requested_level=int(ex_level or 0),
            applied_level=0,
            image_path=self.image_path(pig_id),
            base_image_path=self.image_path(pig_id),
        )

    def newly_unlocked_variant_levels(self, pig_id: str, prev: int, cur: int) -> tuple[int, ...]:
        # 阶段 1 无 EX 差分
        return ()

    def variant_snapshot_fields(self, pig_id: str, level: int) -> frozenset[str]:
        return frozenset()


class PigAppearance:
    """小猪外观解析结果。"""

    def __init__(self, pig_data: dict, requested_level: int, applied_level: int,
                 image_path: Optional[Path], base_image_path: Optional[Path]) -> None:
        self.pig_data = pig_data
        self.requested_level = requested_level
        self.applied_level = applied_level
        self.image_path = image_path
        self.base_image_path = base_image_path
