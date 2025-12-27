import re
from datetime import datetime
from urllib.parse import urlparse


_POST_ID_PATTERN = re.compile(r"-post(\d+)\.html?$", re.IGNORECASE)


def slugify_host(url: str) -> str:
    """Convert a sitemap URL into a filesystem-friendly slug."""
    netloc = urlparse(url).netloc.lower()
    if not netloc:
        return "unknown"
    slug = re.sub(r"[^a-z0-9]+", "_", netloc)
    return slug.strip("_") or "unknown"


def extract_article_id(url: str) -> str | None:
    """Extract canonical article identifier from SGGP-style URLs."""
    match = _POST_ID_PATTERN.search(url)
    if not match:
        return None
    return match.group(1)


def parse_w3c_datetime(value: str | None) -> datetime | None:
    """Parse W3C/ISO8601 datetime strings to timezone-aware datetime."""
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None
