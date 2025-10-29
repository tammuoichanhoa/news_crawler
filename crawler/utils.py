import re
from urllib.parse import urlparse


def slugify_host(url: str) -> str:
    """Convert a sitemap URL into a filesystem-friendly slug."""
    netloc = urlparse(url).netloc.lower()
    if not netloc:
        return "unknown"
    slug = re.sub(r"[^a-z0-9]+", "_", netloc)
    return slug.strip("_") or "unknown"
