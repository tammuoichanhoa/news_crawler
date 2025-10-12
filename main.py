"""
CLI entry point for crawling Tuoi Tre Online articles using the sitemap archive.

The script persists fetched data to a relational database using the SQLAlchemy
models defined in ``models.py``.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

try:  # Support execution as a module or a script.
    from .crawler import TuoitreCrawler
    from .models import Base
except ImportError:  # pragma: no cover
    from crawler import TuoitreCrawler  # type: ignore
    from models import Base  # type: ignore

DEFAULT_DB_URL = os.environ.get(
    "TUOITRE_DB_URL",
    "postgresql://crawler:password123@localhost:5432/tuoitre_news",
)
URLS_FILENAME = "urls.txt"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Value must be a positive integer")
    return parsed


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl Tuoi Tre Online articles using monthly XML sitemaps.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help="SQLAlchemy database URL (overrides TUOITRE_DB_URL env when provided).",
    )
    parser.add_argument("--start-year", type=int, default=2025)
    parser.add_argument("--start-month", type=int, default=10)
    parser.add_argument("--end-year", type=int, default=2015)
    parser.add_argument("--end-month", type=int, default=10)
    parser.add_argument(
        "--limit-per-month",
        type=_positive_int,
        default=None,
        help="Maximum number of articles to fetch from each monthly sitemap.",
    )
    parser.add_argument(
        "--max-articles",
        type=_positive_int,
        default=None,
        help="Stop after collecting this many new articles.",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=20,
        help="Number of articles between database commits.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Delay (seconds) between article requests.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP request timeout in seconds.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not persist data, only print article URLs as they are crawled.",
    )
    parser.add_argument(
        "--image-dir",
        default=TuoitreCrawler.DEFAULT_IMAGE_DIR,
        help="Directory where downloaded article images are stored.",
    )
    return parser.parse_args(argv)


def configure_logging(level_name: str) -> None:
    try:
        level = getattr(logging, level_name.upper())
    except AttributeError as exc:
        raise ValueError(f"Unsupported log level '{level_name}'") from exc

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    configure_logging(args.log_level)

    crawler = TuoitreCrawler(
        delay_seconds=args.delay,
        request_timeout=args.timeout,
        image_dir=args.image_dir,
    )
    processed = 0

    if (args.start_year, args.start_month) > (args.end_year, args.end_month):
        logging.error(
            "Invalid period: start %04d-%02d is after end %04d-%02d. "
            "Use --end-year/--end-month to set a later boundary.",
            args.start_year,
            args.start_month,
            args.end_year,
            args.end_month,
        )
        raise SystemExit(1)

    if args.dry_run:
        urls_path = Path(URLS_FILENAME)
        total_urls = _collect_urls(crawler, args, urls_path)
        if not total_urls:
            logging.info("Dry run completed: no URLs discovered.")
            return

        for article in crawler.crawl_urls(_iter_urls_from_file(urls_path)):
            logging.info("Would persist article: %s", article.url)
            processed += 1
            if args.max_articles and processed >= args.max_articles:
                break
        logging.info("Dry run completed: %d articles discovered.", processed)
        return

    engine = create_engine(args.db_url)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)

    try:
        with SessionFactory() as session:  # type: Session
            _crawl_and_store(
                crawler=crawler,
                session=session,
                args=args,
            )
    except SQLAlchemyError as exc:
        logging.error("Database error: %s", exc, exc_info=True)
        raise SystemExit(1) from exc


def _collect_urls(
    crawler: TuoitreCrawler,
    args: argparse.Namespace,
    output_path: Path,
) -> int:
    count = 0
    output_path = output_path.resolve()
    logging.info("Collecting article URLs into %s", output_path)
    with output_path.open("w", encoding="utf-8") as handle:
        for url in crawler.iter_article_urls(
            start_year=args.start_year,
            start_month=args.start_month,
            end_year=args.end_year,
            end_month=args.end_month,
            limit_per_month=args.limit_per_month,
        ):
            handle.write(f"{url}\n")
            count += 1
            if args.max_articles and count >= args.max_articles:
                break
    return count


def _iter_urls_from_file(path: Path) -> Iterator[str]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            url = line.strip()
            if url:
                yield url


def _crawl_and_store(
    crawler: TuoitreCrawler,
    session: Session,
    args: argparse.Namespace,
) -> None:
    logging.info(
        "Starting crawl: %04d-%02d to %04d-%02d",
        args.start_year,
        args.start_month,
        args.end_year,
        args.end_month,
    )
    persisted = 0
    errors = 0
    urls_path = Path(URLS_FILENAME)

    total_urls = _collect_urls(crawler, args, urls_path)
    if not total_urls:
        logging.info("No article URLs found for the provided period.")
        return

    logging.info("Saved %d URLs to %s", total_urls, urls_path)

    for article in crawler.crawl_urls(_iter_urls_from_file(urls_path)):
        try:
            _, created = crawler.persist_article(session, article, commit=False)
            if created:
                persisted += 1
        except SQLAlchemyError as exc:
            session.rollback()
            errors += 1
            logging.warning("Failed to persist article %s: %s", article.url, exc)
            continue

        if persisted and persisted % args.batch_size == 0:
            session.commit()
            logging.info("Committed %d articles so far", persisted)

        if args.max_articles and persisted >= args.max_articles:
            logging.info("Reached --max-articles=%d", args.max_articles)
            break

    session.commit()
    logging.info("Crawl finished. Articles persisted: %d. Errors: %d.", persisted, errors)


if __name__ == "__main__":
    main()
