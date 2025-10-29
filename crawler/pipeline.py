import logging
from pathlib import Path
from typing import Iterable, List, Sequence

from sqlalchemy.orm import sessionmaker

from .sitemap import SitemapCrawler
from .storage import UrlStore
from .utils import slugify_host
from .article import ArticleCrawler


logger = logging.getLogger(__name__)


class CrawlPipeline:
    """End-to-end pipeline orchestrator for sitemap URL collection and article ingestion."""

    def __init__(
        self,
        stored_urls_dir: Path,
        session_factory: sessionmaker,
        allowed_extensions: Sequence[str] | None = None,
        sitemap_include_patterns: Sequence[str] | None = None,
    ) -> None:
        self.url_store = UrlStore(stored_urls_dir)
        self.sitemap_crawler = SitemapCrawler(
            allowed_extensions=allowed_extensions,
            include_patterns=sitemap_include_patterns,
        )
        self.article_crawler = ArticleCrawler(session_factory=session_factory)

    def _fetch_sitemap_urls(
        self,
        sitemap_urls: Iterable[str],
        slug_filter: Sequence[str] | None = None,
    ) -> dict[str, List[str]]:
        urls_by_slug: dict[str, List[str]] = {}
        allowed_slugs = set(slug_filter) if slug_filter else None

        for sitemap_url in sitemap_urls:
            slug = slugify_host(sitemap_url)
            if allowed_slugs and slug not in allowed_slugs:
                logger.debug("Skipping sitemap %s because slug %s not in filter", sitemap_url, slug)
                continue

            logger.info("Processing sitemap %s (slug=%s)", sitemap_url, slug)
            urls = self.sitemap_crawler.fetch_urls(sitemap_url)
            logger.info("Fetched %s URLs from %s", len(urls), sitemap_url)
            if urls:
                urls_by_slug.setdefault(slug, []).extend(urls)
        return urls_by_slug

    def collect_urls(self, sitemap_urls: Iterable[str], slug_filter: Sequence[str] | None = None) -> int:
        """Collect and persist article URLs for each sitemap URL."""
        total_new = 0
        urls_by_slug = self._fetch_sitemap_urls(sitemap_urls, slug_filter=slug_filter)
        for slug, urls in urls_by_slug.items():
            new_urls = self.url_store.append_new(slug, urls)
            total_new += len(new_urls)
        return total_new

    def ingest_articles(
        self,
        slug_filter: Sequence[str] | None = None,
        max_urls_per_site: int | None = None,
        max_total_urls: int | None = None,
    ) -> dict[str, int]:
        """Crawl stored URLs and persist articles into the database."""
        processed_summary: dict[str, int] = {}
        allowed_slugs = set(slug_filter) if slug_filter else None
        processed_total = 0

        for file_path in sorted(self.url_store.base_dir.glob("*_urls.txt")):
            slug = file_path.stem.replace("_urls", "")
            if allowed_slugs and slug not in allowed_slugs:
                continue

            urls = self.url_store.read_all(slug)
            if not urls:
                continue

            start_index = self.url_store.get_cursor(slug)
            if start_index >= len(urls):
                logger.info("All URLs already processed for %s (cursor=%s, total=%s)", slug, start_index, len(urls))
                continue

            urls = urls[start_index:]
            logger.debug("Resuming %s at index %s (%s remaining URLs)", slug, start_index, len(urls))

            if max_urls_per_site is not None:
                urls = urls[:max_urls_per_site]

            if max_total_urls is not None:
                remaining = max_total_urls - processed_total
                if remaining <= 0:
                    break
                urls = urls[:remaining]

            success_count = 0
            logger.info("Crawling %s URLs for slug=%s", len(urls), slug)
            current_index = start_index

            for url in urls:
                stored = self.article_crawler.crawl(url)
                if stored:
                    success_count += 1
                processed_total += 1
                current_index += 1
                self.url_store.set_cursor(slug, current_index)
                if max_total_urls is not None and processed_total >= max_total_urls:
                    logger.info("Reached global crawl limit (%s). Stopping.", max_total_urls)
                    break

            processed_summary[slug] = success_count
            if max_total_urls is not None and processed_total >= max_total_urls:
                break
        return processed_summary

    def crawl_from_sitemaps(
        self,
        sitemap_urls: Iterable[str],
        slug_filter: Sequence[str] | None = None,
        max_urls_per_site: int | None = None,
        store_urls: bool = False,
        max_total_urls: int | None = None,
    ) -> dict[str, int]:
        """Fetch URLs from sitemaps and crawl them immediately."""
        urls_by_slug = self._fetch_sitemap_urls(sitemap_urls, slug_filter=slug_filter)
        summary: dict[str, int] = {}
        processed_total = 0

        for slug, urls in urls_by_slug.items():
            if max_urls_per_site is not None:
                urls = urls[:max_urls_per_site]

            if max_total_urls is not None:
                remaining = max_total_urls - processed_total
                if remaining <= 0:
                    break
                urls = urls[:remaining]

            if store_urls:
                self.url_store.append_new(slug, urls)

            success_count = 0
            logger.info("Directly crawling %s URLs for slug=%s", len(urls), slug)
            for url in urls:
                stored = self.article_crawler.crawl(url)
                if stored:
                    success_count += 1
                processed_total += 1
                if max_total_urls is not None and processed_total >= max_total_urls:
                    logger.info("Reached global crawl limit (%s). Stopping.", max_total_urls)
                    break
            summary[slug] = success_count
            if max_total_urls is not None and processed_total >= max_total_urls:
                break
        return summary
