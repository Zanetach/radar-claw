"""Legacy compatibility exports for the renamed Beeclaw adapter package.

Use crawler.beeclaw_adapter for new code.
"""

from crawler.beeclaw_adapter import (
    FeedgrabUnavailable,
    feedgrab_health,
    provider_catalog,
    read_url,
    unified_content_to_item,
)

__all__ = [
    "FeedgrabUnavailable",
    "feedgrab_health",
    "provider_catalog",
    "read_url",
    "unified_content_to_item",
]
