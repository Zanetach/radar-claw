from __future__ import annotations

import mimetypes
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .models import FetchResult


DEFAULT_MEDIA_DIR = Path("data/media")


def safe_path_part(value: str | None) -> str:
    text = (value or "unknown").strip()
    text = re.sub(r"[\\/:*?\"<>|#]+", "-", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip(".- ") or "unknown"


def extension_from_response(url: str, content_type: str | None) -> str:
    path_ext = Path(urllib.parse.urlparse(url).path).suffix
    if path_ext and len(path_ext) <= 8:
        return path_ext
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    return guessed or ".bin"


def download_url(url: str, target_without_ext: Path, *, timeout: int = 60) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "RadarCrawler/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type")
        ext = extension_from_response(url, content_type)
        target = target_without_ext.with_suffix(ext)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.read())
        return {
            "local_path": str(target),
            "local_url": "/" + str(target).replace("\\", "/"),
            "content_type": content_type,
            "bytes": target.stat().st_size,
        }


def download_fetch_result_media(
    result: FetchResult,
    *,
    account: dict[str, Any],
    media_root: Path = DEFAULT_MEDIA_DIR,
    max_assets_per_item: int = 12,
) -> dict[str, int]:
    downloaded = 0
    failed = 0
    for item in result.items:
        if not item.media_assets:
            continue
        item_dir = (
            media_root
            / item.platform
            / safe_path_part(account.get("account_handle") or account.get("account_name"))
            / safe_path_part(item.original_content_id)
        )
        for index, asset in enumerate(item.media_assets[:max_assets_per_item], start=1):
            source_url = asset.get("download_url") or asset.get("url")
            if not source_url or not str(source_url).startswith(("http://", "https://")):
                continue
            try:
                local = download_url(str(source_url), item_dir / f"asset-{index}")
                asset.update(local)
                downloaded += 1
            except Exception as exc:
                asset["download_error"] = str(exc)
                failed += 1
    return {"downloaded": downloaded, "failed": failed}
