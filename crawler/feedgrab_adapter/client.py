from __future__ import annotations

import asyncio
from typing import Any


class FeedgrabUnavailable(RuntimeError):
    """Raised when feedgrab is not installed or cannot read content."""


async def _read_url_async(url: str) -> Any:
    try:
        from feedgrab.reader import UniversalReader
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise FeedgrabUnavailable(
            "feedgrab is not installed. Install requirements or pip install 'feedgrab[mcp]'."
        ) from exc

    reader = UniversalReader()
    return await reader.read(url)


def read_url(url: str) -> Any:
    """Read one URL through feedgrab and return its UnifiedContent object."""
    try:
        return asyncio.run(_read_url_async(url))
    except FeedgrabUnavailable:
        raise
    except Exception as exc:
        raise FeedgrabUnavailable(str(exc)) from exc
