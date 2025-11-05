import json
import logging
from pathlib import Path
from typing import Dict, Iterable, List

from .sitemap import SitemapEntry
from .utils import extract_article_id


logger = logging.getLogger(__name__)


class UrlStore:
    """Handles persistence of sitemap URLs on disk for resume support."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def url_file(self, slug: str) -> Path:
        return self.base_dir / f"{slug}_urls.txt"

    def cursor_file(self, slug: str) -> Path:
        return self.base_dir / f"{slug}_cursor.txt"

    def load(self, slug: str) -> Dict[str, SitemapEntry]:
        file_path = self.url_file(slug)
        if not file_path.exists():
            return {}
        try:
            entries: Dict[str, SitemapEntry] = {}
            for line in file_path.read_text(encoding="utf-8").splitlines():
                entry = self._parse_line(line)
                if not entry:
                    continue
                entries[entry.dedupe_key] = entry
            return entries
        except Exception as exc:
            logger.error("Failed to read URL store %s: %s", file_path, exc)
            return {}

    def append_new(self, slug: str, entries: Iterable[SitemapEntry]) -> List[SitemapEntry]:
        existing = self.load(slug)
        new_entries: List[SitemapEntry] = []
        for entry in entries:
            key = entry.dedupe_key
            if key in existing:
                continue
            existing[key] = entry
            new_entries.append(entry)

        if not new_entries:
            return []

        file_path = self.url_file(slug)
        try:
            with file_path.open("a", encoding="utf-8") as file_handle:
                for entry in new_entries:
                    record = {"url": entry.url}
                    if entry.lastmod:
                        record["lastmod"] = entry.lastmod
                    if entry.article_id:
                        record["article_id"] = entry.article_id
                    file_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.error("Failed to write URL store %s: %s", file_path, exc)
            return []

        logger.info("Added %s new URLs to %s", len(new_entries), file_path)
        return new_entries

    def read_all(self, slug: str) -> List[SitemapEntry]:
        file_path = self.url_file(slug)
        if not file_path.exists():
            return []
        try:
            entries: List[SitemapEntry] = []
            for line in file_path.read_text(encoding="utf-8").splitlines():
                entry = self._parse_line(line)
                if entry:
                    entries.append(entry)
            return entries
        except Exception as exc:
            logger.error("Failed to read URL store %s: %s", file_path, exc)
            return []

    def get_cursor(self, slug: str) -> int:
        file_path = self.cursor_file(slug)
        if not file_path.exists():
            return 0
        try:
            value = int(file_path.read_text(encoding="utf-8").strip())
            return max(0, value)
        except Exception as exc:
            logger.warning("Failed to read cursor for %s (%s). Resetting to 0.", slug, exc)
            return 0

    def set_cursor(self, slug: str, position: int) -> None:
        file_path = self.cursor_file(slug)
        try:
            file_path.write_text(str(max(0, position)), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to persist cursor for %s: %s", slug, exc)

    @staticmethod
    def _parse_line(line: str) -> SitemapEntry | None:
        stripped = line.strip()
        if not stripped:
            return None
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                payload = json.loads(stripped)
                url = payload.get("url")
                if not url:
                    return None
                return SitemapEntry(
                    url=url,
                    lastmod=payload.get("lastmod"),
                    article_id=payload.get("article_id"),
                )
            except json.JSONDecodeError:
                return None
        # Legacy plain URL support
        return SitemapEntry(url=stripped, article_id=extract_article_id(stripped))
