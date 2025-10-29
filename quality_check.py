import argparse
import logging
from typing import Optional

from sqlalchemy import func, select

from db.models import Article
from db.session import create_session_factory


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate basic quality metrics for crawled articles."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. Falls back to DATABASE_URL / .env when omitted.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Limit analysis to articles whose URL contains this hostname fragment.",
    )
    parser.add_argument(
        "--content-threshold",
        type=int,
        default=200,
        help="Flag articles whose content length is below this value.",
    )
    parser.add_argument(
        "--show-samples",
        type=int,
        default=3,
        help="Display up to N sample URLs missing tags or with short content (0 to skip).",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def _apply_host_filter(query, column, host: Optional[str]):
    if host:
        return query.where(column.contains(host))
    return query


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    session_factory = create_session_factory(database_url=args.database_url)
    session = session_factory()

    try:
        base_query = select(func.count()).select_from(Article)
        total_articles = session.scalar(_apply_host_filter(base_query, Article.url, args.host))

        missing_tags_query = select(func.count()).select_from(Article).where(
            (Article.tags.is_(None)) | (func.trim(Article.tags) == "")
        )
        missing_tags = session.scalar(_apply_host_filter(missing_tags_query, Article.url, args.host))

        missing_content_query = select(func.count()).select_from(Article).where(
            (Article.content.is_(None)) | (func.length(func.trim(Article.content)) == 0)
        )
        missing_content = session.scalar(_apply_host_filter(missing_content_query, Article.url, args.host))

        short_content_query = select(func.count()).select_from(Article).where(
            func.length(Article.content) < args.content_threshold
        )
        short_content = session.scalar(_apply_host_filter(short_content_query, Article.url, args.host))

        avg_length_query = select(func.avg(func.length(Article.content))).select_from(Article).where(
            Article.content.isnot(None)
        )
        average_length = session.scalar(_apply_host_filter(avg_length_query, Article.url, args.host))

        logging.info("Total articles: %s", total_articles)
        logging.info("Missing tags: %s", missing_tags)
        logging.info("Missing content: %s", missing_content)
        logging.info(
            "Short content (< %s chars): %s", args.content_threshold, short_content
        )
        logging.info("Average content length: %s", int(average_length) if average_length else "N/A")

        if args.show_samples:
            missing_tags_query = session.query(Article).filter(
                (Article.tags.is_(None)) | (func.trim(Article.tags) == "")
            )
            if args.host:
                missing_tags_query = missing_tags_query.filter(Article.url.contains(args.host))
            missing_tags_samples = missing_tags_query.limit(args.show_samples).all()
            if missing_tags_samples:
                print("\nSample articles missing tags:")
                for article in missing_tags_samples:
                    print(f"- {article.url}")

            short_content_query = (
                session.query(Article)
                .filter(Article.content.isnot(None))
                .filter(func.length(Article.content) < args.content_threshold)
            )
            if args.host:
                short_content_query = short_content_query.filter(Article.url.contains(args.host))
            short_content_samples = short_content_query.limit(args.show_samples).all()
            if short_content_samples:
                print("\nSample articles with short content:")
                for article in short_content_samples:
                    snippet = (article.content or "").strip().replace("\n", " ")
                    if len(snippet) > 120:
                        snippet = snippet[:120] + "..."
                    print(f"- {article.url}\n  {snippet}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
