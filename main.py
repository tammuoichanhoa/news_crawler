import argparse
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
from typing import Callable, Sequence

from crawler.article import ArticleCrawler
from crawler.pipeline import CrawlPipeline
from crawler.throttle import RequestThrottler
from db.session import create_session_factory

GENK_SITEMAP_EXCLUDE_PATTERNS = [
    "*genk.vn/sitemaps/category.rss",
    "*genk.vn/google-news-sitemap.xml",
    "*genk.vn/latestnews-sitemap.xml",
]

KENH14_SITEMAP_EXCLUDE_PATTERNS = [
    "*kenh14.vn/sitemaps/category.rss",
    "*kenh14.vn/google-news-sitemap.xml",
    "*kenh14.vn/latestnews-sitemap.xml",
]
CAFEBIZ_SITEMAP_EXCLUDE_PATTERNS = [
    "*cafebiz.vn/sitemaps/category.rss",
    "*cafebiz.vn/google-news-sitemap.xml",
    "*cafebiz.vn/latestnews-sitemap.xml",
]
TINNHANHCHUNGKHOAN_SITEMAP_EXCLUDE_PATTERNS = [
    "*tinnhanhchungkhoan.vn/sitemaps/categories.xml",
    "*tinnhanhchungkhoan.vn/sitemaps/topics.xml",
]

GIADINH_SUCKHOEDOISONG_SITEMAP_EXCLUDE_PATTERNS = [
    "*giadinh.suckhoedoisong.vn/sitemaps/category.rss",
    "*giadinh.suckhoedoisong.vn/google-news-sitemap.xml",
    "*giadinh.suckhoedoisong.vn/latestnews-sitemap.xml",
]

VNECONOMY_SITEMAP_EXCLUDE_PATTERNS = [
    "*vneconomy.vn/sitemap/categories.xml",
    "*vneconomy.vn/sitemap/latest-news.xml",
    "*vneconomy.vn/sitemap/google-news.xml",
]
DANTRI_SITEMAP_EXCLUDE_PATTERNS = [
    "*dantri.com.vn/sitemaps/categories.xml",
    "*dantri.com.vn/sitemaps/topics.xml",
]

BAODAUTU_SITEMAP_EXCLUDE_PATTERNS = [
    "*baodautu.vn/sitemaps/categories.xml",
]

NHANDAN_SITEMAP_EXCLUDE_PATTERNS = [
    "*nhandan.vn/sitemaps/categories.xml",
   "*nhandan.vn/sitemaps/topics.xml",
    "*nhandan.vn",
]

ANNINHTHUDO_SITEMAP_EXCLUDE_PATTERNS = [
    "*anninhthudo.vn/sitemaps/categories.xml",
    "*anninhthudo.vn/sitemaps/topics.xml",
]

DAIBIEUNHANDAN_SITEMAP_EXCLUDE_PATTERNS = [
    "*daibieunhandan.vn/sitemap-article-daily.xml",
    "*daibieunhandan.vn/sitemap-news.xml",
    "*daibieunhandan.vn/sitemap-category.xml",
    "*daibieunhandan.vn/sitemap-event.xml",
]

CONGLY_SITEMAP_EXCLUDE_PATTERNS = [
    "*congly.vn/sitemap-article-daily.xml",
    "*congly.vn/sitemap-category.xml",
    "*congly.vn/sitemap-event.xml",
]

CAFEF_SITEMAP_EXCLUDE_PATTERNS = [
    "*cafef.vn/sitemaps/category.rss",
    "*cafef.vn/google-news-sitemap.xml",
    "*cafef.vn/latest-news-sitemap.xml",
]

VTV_SITEMAP_EXCLUDE_PATTERNS = [
    "*vtv.vn/sitemaps/category.rss",
    "*vtv.vn/google-news-sitemap.xml",
    "*vtv.vn/latest-news-sitemap.xml",
]

VIETNAMNET_SITEMAP_EXCLUDE_PATTERNS = [
    "*vietnamnet.vn/sitemap-categories.xml",
    "*vietnamnet.vn/sitemap-news.xml",
    "*vietnamnet.vn/sitemap-image.xml",
    "*vietnamnet.vn/sitemap-video.xml",
    "*vietnamnet.vn/sitemap-tags*.xml",
]

SOHA_SITEMAP_EXCLUDE_PATTERNS = [
    "*soha.vn/sitemaps/category.rss",
    "*soha.vn/google-news-sitemap.xml",
    "*soha.vn/latest-news-sitemap.xml",
]

BAOXAYDUNG_SITEMAP_EXCLUDE_PATTERNS = [
    "*baoxaydung.vn/sitemap/category.xml",
    "*baoxaydung.vn/google-news-sitemap.xml",
    "*baoxaydung.vn/latest-news-sitemap.xml",
    "*baoxaydung.vn/video-news.xml",
    "*baoxaydung.vn/event.xml",
]

BAOPHAPLUAT_SITEMAP_EXCLUDE_PATTERNS = [
    "*baophapluat.vn/sitemaps/categories.xml",
    "*baophapluat.vn/sitemaps/latest-articles.xml",
    "*baophapluat.vn/sitemaps/google-news.xml",
]

BNEWS_SITEMAP_EXCLUDE_PATTERNS = [
    "*://bnews.vn",
    "*://bnews.vn/",
    "*://bnews.vn/photo/trang-1.html",
    "*://bnews.vn/video/trang-1.html",
    "*://bnews.vn/sitemap/categories.xml",
]

BAODONGNAI_SITEMAP_EXCLUDE_PATTERNS = [
    "*baodongnai.com.vn/sitemaps/index.cate.xml",
    "*baodongnai.com.vn/sitemaps/index.lastest.xml",
]

DEFAULT_SITEMAP_EXCLUDE_PATTERNS = (
    GENK_SITEMAP_EXCLUDE_PATTERNS
    + KENH14_SITEMAP_EXCLUDE_PATTERNS
    + CAFEBIZ_SITEMAP_EXCLUDE_PATTERNS
    + GIADINH_SUCKHOEDOISONG_SITEMAP_EXCLUDE_PATTERNS
    + VNECONOMY_SITEMAP_EXCLUDE_PATTERNS
    + DANTRI_SITEMAP_EXCLUDE_PATTERNS
    + BAODAUTU_SITEMAP_EXCLUDE_PATTERNS
    + NHANDAN_SITEMAP_EXCLUDE_PATTERNS
    + ANNINHTHUDO_SITEMAP_EXCLUDE_PATTERNS
    + DAIBIEUNHANDAN_SITEMAP_EXCLUDE_PATTERNS
    + CONGLY_SITEMAP_EXCLUDE_PATTERNS
    + CAFEF_SITEMAP_EXCLUDE_PATTERNS
    + VTV_SITEMAP_EXCLUDE_PATTERNS
    + VIETNAMNET_SITEMAP_EXCLUDE_PATTERNS
    + SOHA_SITEMAP_EXCLUDE_PATTERNS
    + BAOXAYDUNG_SITEMAP_EXCLUDE_PATTERNS
    + BAOPHAPLUAT_SITEMAP_EXCLUDE_PATTERNS
    + BNEWS_SITEMAP_EXCLUDE_PATTERNS
    + BAODONGNAI_SITEMAP_EXCLUDE_PATTERNS
)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def read_sitemap_list(file_path: Path) -> list[str]:
    if not file_path.exists():
        raise FileNotFoundError(f"Sitemaps file not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip() and not line.startswith("#")]


def read_url_list(file_path: Path) -> list[str]:
    if not file_path.exists():
        raise FileNotFoundError(f"URL file not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as handle:
        seen: set[str] = set()
        urls: list[str] = []
        for line in handle:
            url = line.strip()
            if not url or url.startswith("#") or url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def build_default_sitemap_include_patterns(sitemap_urls: list[str] | None) -> list[str]:
    """
    Ensure genk.vn sitemap crawling focuses on daily sitemap files while leaving other hosts untouched.
    """
    if not sitemap_urls:
        return []

    hosts = {urlparse(url).netloc for url in sitemap_urls if url}
    include_patterns: list[str] = []
    for host in hosts:
        normalized_host = host.lower()
        if normalized_host.endswith("genk.vn"):
            include_patterns.append(f"*://{host}/StaticSitemaps/*")
        else:
            include_patterns.append(f"*://{host}/*")
    return include_patterns


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl sitemap URLs and ingest news articles into the database.")

    parser.add_argument("--sitemaps-file", default="sitemaps.txt", help="Path to file containing sitemap URLs.")
    parser.add_argument(
        "--stored-urls-dir",
        default="stored_urls",
        help="Directory where sitemap URLs should be cached.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. If omitted, DATABASE_URL environment variable is used.",
    )
    parser.add_argument(
        "--urls-file",
        default="resume_url.txt",
        help="Path to a text file containing article URLs to crawl directly.",
    )
    parser.add_argument(
        "--use-url-file",
        action="store_true",
        help="Skip sitemap processing and crawl article URLs listed in --urls-file.",
    )
    parser.add_argument(
        "--allowed-extension",
        action="append",
        help="Restrict collected URLs to the given file extensions (e.g. --allowed-extension .html).",
    )
    parser.add_argument(
        "--sitemap-include",
        action="append",
        help="Only follow child sitemaps whose URL matches these glob patterns (e.g. --sitemap-include '*sitemap-article*').",
    )
    parser.add_argument(
        "--sitemap-exclude",
        action="append",
        help="Skip child sitemaps whose URL matches these glob patterns (e.g. --sitemap-exclude '*categories*').",
    )
    parser.add_argument("--user-agent", help="Override the HTTP User-Agent header for outbound requests.")
    parser.add_argument(
        "--direct-crawl",
        action="store_true",
        help="Fetch sitemap URLs and crawl articles immediately without caching URLs to disk.",
    )
    parser.add_argument(
        "--store-urls",
        action="store_true",
        help="Persist collected URLs to disk when using --direct-crawl (helps resume later).",
    )
    parser.add_argument(
        "--url-export",
        help="Optional path to write a deduplicated list of all cached URLs (txt file).",
    )
    parser.add_argument(
        "--max-urls-per-site",
        type=int,
        default=None,
        help="Limit number of URLs to crawl per site when ingesting articles.",
    )
    parser.add_argument(
        "--max-total-urls",
        type=int,
        default=None,
        help="Limit the total number of URLs crawled across all sites in a run.",
    )
    parser.add_argument(
        "--slug",
        action="append",
        help="Restrict article crawling to specific site slugs (derived from sitemap domain).",
    )
    parser.add_argument("--skip-url-collection", action="store_true", help="Skip sitemap fetching and reuse cached URLs.")
    parser.add_argument("--skip-article-ingest", action="store_true", help="Skip article crawling stage.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument(
        "--min-request-delay",
        type=float,
        default=0.0,
        help="Minimum delay (seconds) to wait between HTTP requests.",
    )
    parser.add_argument(
        "--max-request-delay",
        type=float,
        default=None,
        help="Maximum delay (seconds) to wait between HTTP requests. Defaults to the minimum delay if omitted.",
    )
    parser.add_argument(
        "--url-include",
        action="append",
        help="Only keep URLs whose value matches these glob patterns (e.g. --url-include '*-post*.html').",
    )
    parser.add_argument(
        "--url-exclude",
        action="append",
        help="Skip URLs whose value matches these glob patterns (e.g. --url-exclude '*category*').",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of concurrent workers for article crawling.",
    )

    return parser.parse_args()


def crawl_urls_concurrently(
    urls: Sequence[str],
    crawler_factory: Callable[[], ArticleCrawler],
    workers: int,
) -> int:
    """Crawl URLs concurrently and return the number of stored articles."""
    if not urls:
        return 0

    worker_count = max(1, workers)
    crawler_local = threading.local()

    def get_crawler() -> ArticleCrawler:
        crawler = getattr(crawler_local, "instance", None)
        if crawler is None:
            crawler = crawler_factory()
            crawler_local.instance = crawler
        return crawler

    def crawl_single(url: str) -> bool:
        return get_crawler().crawl(url)

    success_count = 0
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_url = {executor.submit(crawl_single, url): url for url in urls}
        for future in as_completed(future_to_url):
            target_url = future_to_url[future]
            try:
                if future.result():
                    success_count += 1
            except Exception as exc:
                logging.error("Unexpected error while crawling %s: %s", target_url, exc)
    return success_count


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    if args.max_request_delay is not None and args.max_request_delay < args.min_request_delay:
        raise SystemExit("--max-request-delay must be greater than or equal to --min-request-delay")

    allowed_extensions = args.allowed_extension or None
    throttler: RequestThrottler | None = None
    if args.min_request_delay > 0 or (args.max_request_delay is not None and args.max_request_delay > 0):
        throttler = RequestThrottler(
            min_delay=args.min_request_delay,
            max_delay=args.max_request_delay,
        )

    session_factory = create_session_factory(database_url=args.database_url)

    # If requested, bypass sitemap pipeline and crawl articles directly from a URL file.
    if args.use_url_file:
        urls_path = Path(args.urls_file)
        urls = read_url_list(urls_path)
        if not urls:
            logging.info("No URLs found in %s; nothing to crawl.", urls_path)
            return

        if args.max_total_urls is not None:
            urls = urls[: args.max_total_urls]

        workers = max(1, args.workers)
        crawler_factory = lambda: ArticleCrawler(
            session_factory=session_factory,
            user_agent=args.user_agent,
            throttler=throttler,
        )
        stored_count = crawl_urls_concurrently(urls, crawler_factory, workers)
        logging.info(
            "Finished crawling URL file %s; stored %s new articles with %s workers.",
            urls_path,
            stored_count,
            workers,
        )
        return
    sitemap_urls: list[str] | None = None
    need_sitemaps = args.direct_crawl or not args.skip_url_collection
    if need_sitemaps:
        sitemap_urls = read_sitemap_list(Path(args.sitemaps_file))

    sitemap_exclude_patterns = list(args.sitemap_exclude or [])
    for pattern in DEFAULT_SITEMAP_EXCLUDE_PATTERNS:
        if pattern not in sitemap_exclude_patterns:
            sitemap_exclude_patterns.append(pattern)

    sitemap_include_patterns = list(args.sitemap_include or [])
    if not args.sitemap_include:
        defaults = build_default_sitemap_include_patterns(sitemap_urls)
        # Avoid duplicates while preserving ordering preference.
        for pattern in defaults:
            if pattern not in sitemap_include_patterns:
                sitemap_include_patterns.append(pattern)

    url_export_path = Path(args.url_export) if args.url_export else None
    should_store_direct_urls = args.store_urls or url_export_path is not None

    pipeline = CrawlPipeline(
        stored_urls_dir=Path(args.stored_urls_dir),
        session_factory=session_factory,
        allowed_extensions=allowed_extensions,
        sitemap_include_patterns=sitemap_include_patterns or None,
        request_throttler=throttler,
        user_agent=args.user_agent,
        sitemap_exclude_patterns=sitemap_exclude_patterns or None,
        url_include_patterns=args.url_include,
        url_exclude_patterns=args.url_exclude,
        workers=args.workers,
    )

    if args.direct_crawl:
        summary = pipeline.crawl_from_sitemaps(
            sitemap_urls,
            slug_filter=args.slug,
            max_urls_per_site=args.max_urls_per_site,
            store_urls=should_store_direct_urls,
            max_total_urls=args.max_total_urls,
        )
        for slug, count in summary.items():
            logging.info("Direct crawl stored %s new articles for %s", count, slug)
        if url_export_path:
            exported = pipeline.export_all_urls(url_export_path)
            logging.info("Exported %s URLs to %s", exported, url_export_path)
        return

    if not args.skip_url_collection and sitemap_urls is not None:
        total_new = pipeline.collect_urls(sitemap_urls, slug_filter=args.slug)
        logging.info("Collected %s new URLs from sitemaps.", total_new)

    if not args.skip_article_ingest:
        summary = pipeline.ingest_articles(
            slug_filter=args.slug,
            max_urls_per_site=args.max_urls_per_site,
            max_total_urls=args.max_total_urls,
        )
        for slug, count in summary.items():
            logging.info("Stored %s new articles for %s", count, slug)
    if url_export_path:
        exported = pipeline.export_all_urls(url_export_path)
        logging.info("Exported %s URLs to %s", exported, url_export_path)


if __name__ == "__main__":
    main()
