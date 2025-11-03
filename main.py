import argparse
import logging
from pathlib import Path

from crawler.pipeline import CrawlPipeline
from crawler.throttle import RequestThrottler
from db.session import create_session_factory


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

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    if args.max_request_delay is not None and args.max_request_delay < args.min_request_delay:
        raise SystemExit("--max-request-delay must be greater than or equal to --min-request-delay")

    allowed_extensions = args.allowed_extension or [".html"]
    throttler: RequestThrottler | None = None
    if args.min_request_delay > 0 or (args.max_request_delay is not None and args.max_request_delay > 0):
        throttler = RequestThrottler(
            min_delay=args.min_request_delay,
            max_delay=args.max_request_delay,
        )

    session_factory = create_session_factory(database_url=args.database_url)
    pipeline = CrawlPipeline(
        stored_urls_dir=Path(args.stored_urls_dir),
        session_factory=session_factory,
        allowed_extensions=allowed_extensions,
        sitemap_include_patterns=args.sitemap_include,
        request_throttler=throttler,
        user_agent=args.user_agent,
        sitemap_exclude_patterns=args.sitemap_exclude,
        url_include_patterns=args.url_include,
        url_exclude_patterns=args.url_exclude,
    )

    sitemap_urls: list[str] | None = None
    need_sitemaps = args.direct_crawl or not args.skip_url_collection
    if need_sitemaps:
        sitemap_urls = read_sitemap_list(Path(args.sitemaps_file))

    if args.direct_crawl:
        summary = pipeline.crawl_from_sitemaps(
            sitemap_urls,
            slug_filter=args.slug,
            max_urls_per_site=args.max_urls_per_site,
            store_urls=False,
            max_total_urls=args.max_total_urls,
        )
        for slug, count in summary.items():
            logging.info("Direct crawl stored %s new articles for %s", count, slug)
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


if __name__ == "__main__":
    main()
