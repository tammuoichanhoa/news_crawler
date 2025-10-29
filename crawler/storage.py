import logging
from pathlib import Path
from typing import Iterable, List, Set


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

    def load(self, slug: str) -> Set[str]:
        file_path = self.url_file(slug)
        if not file_path.exists():
            return set()
        try:
            contents = {line.strip() for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()}
            return contents
        except Exception as exc:
            logger.error("Failed to read URL store %s: %s", file_path, exc)
            return set()

    def append_new(self, slug: str, urls: Iterable[str]) -> List[str]:
        existing = self.load(slug)
        new_urls = [url for url in urls if url not in existing]
        if not new_urls:
            return []

        file_path = self.url_file(slug)
        try:
            with file_path.open("a", encoding="utf-8") as file_handle:
                for url in new_urls:
                    file_handle.write(f"{url}\n")
        except Exception as exc:
            logger.error("Failed to write URL store %s: %s", file_path, exc)
            return []

        logger.info("Added %s new URLs to %s", len(new_urls), file_path)
        return new_urls

    def read_all(self, slug: str) -> List[str]:
        file_path = self.url_file(slug)
        if not file_path.exists():
            return []
        try:
            return [line.strip() for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()]
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
