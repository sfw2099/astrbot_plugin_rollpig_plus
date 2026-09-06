# -*- coding: utf-8 -*-
"""PigHub 猪图索引服务（精简版）：拉取社区猪图索引并缓存，支持随机/搜索。"""

from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx


PIGHUB_ORIGIN = "https://pighub.top/"
PIGHUB_IMAGE_BASE_URL = "https://pighub.top/data/"
PIGHUB_API_URLS = (
    "https://pighub.top/api/images?sort=2&limit=200",
    "https://pighub.top/api/all-images",
)
PIGHUB_CACHE_TTL = 12 * 3600
PIGHUB_TIMEOUT = 10.0


def _normalize(item: Any) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    thumbnail = item.get("thumbnail") or item.get("image_url")
    if not isinstance(thumbnail, str) or not thumbnail:
        return None
    filename = item.get("filename") or thumbnail.split("/")[-1]
    return {
        "thumbnail": thumbnail,
        "title": str(item.get("title") or filename or "未命名小猪"),
        "filename": str(filename or ""),
    }


def _parse_payload(data: Any) -> list[dict]:
    if not isinstance(data, dict):
        raise ValueError("PigHub 返回结构异常")
    raw = data.get("data") if isinstance(data.get("data"), list) else data.get("images")
    if not isinstance(raw, list):
        raise ValueError("PigHub 缺少 data/images")
    return [n for n in (_normalize(x) for x in raw) if n]


def build_image_url(pig: dict) -> Optional[str]:
    thumbnail = pig.get("thumbnail")
    if not thumbnail:
        return None
    if thumbnail.startswith(("http://", "https://")):
        url = thumbnail
    elif thumbnail.startswith("/"):
        url = urljoin(PIGHUB_ORIGIN, thumbnail)
    else:
        url = PIGHUB_IMAGE_BASE_URL + thumbnail.split("/")[-1]
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%"), parts.query, parts.fragment))


class PigHubService:
    def __init__(self, cache_file: Path) -> None:
        self.cache_file = cache_file
        self.images: list[dict] = []
        self.last_loaded: float = 0.0
        self._load_cache()

    def _load_cache(self) -> None:
        if not self.cache_file.exists():
            return
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            imgs = [n for n in (_normalize(x) for x in data.get("images", [])) if n]
            if imgs:
                self.images = imgs
                self.last_loaded = float(data.get("cached_at", 0))
        except Exception:
            pass

    def _save_cache(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps({"cached_at": int(self.last_loaded), "images": self.images},
                       ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    def is_fresh(self) -> bool:
        return bool(self.images and (time.time() - self.last_loaded) < PIGHUB_CACHE_TTL)

    async def ensure_ready(self) -> bool:
        if self.is_fresh():
            return True
        return await self.refresh()

    async def refresh(self) -> bool:
        headers = {"User-Agent": "RollPig-Plus/1.0 (+astrbot)"}
        try:
            async with httpx.AsyncClient(timeout=PIGHUB_TIMEOUT, headers=headers) as client:
                for url in PIGHUB_API_URLS:
                    try:
                        resp = await client.get(url)
                        resp.raise_for_status()
                        self.images = _parse_payload(resp.json())
                        self.last_loaded = time.time()
                        await asyncio.to_thread(self._save_cache)
                        return True
                    except Exception:
                        continue
        except Exception:
            pass
        return bool(self.images)

    def sample(self, count: int) -> list[dict]:
        if not self.images:
            return []
        return random.sample(self.images, min(count, len(self.images)))

    def search(self, keyword: str) -> list[dict]:
        kw = keyword.lower()
        return [x for x in self.images if kw in str(x.get("title", "")).lower()
                or kw in str(x.get("filename", "")).lower()]
