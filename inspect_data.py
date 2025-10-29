import argparse
import logging
from typing import Iterable

from sqlalchemy import func, select

from db.models import Article, ArticleImage, ArticleVideo
from db.session import create_session_factory


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect crawled article data stored in the database."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. If omitted, DATABASE_URL environment variable (or .env) is used.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Filter articles by hostname contained in the URL (e.g., 'baohaiphong.vn').",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of articles to display.",
    )
    parser.add_argument(
        "--order",
        choices=["publish_date", "created_at"],
        default="publish_date",
        help="Field to order articles by (descending).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--show-content",
        type=int,
        default=0,
        help="Print the first N characters of article content (0 to skip).",
    )
    return parser.parse_args()


def summarize_article(article: Article, content_preview: int = 0) -> str:
    publish_date = article.publish_date.isoformat() if article.publish_date else "N/A"
    description = article.description[:150] + "..." if article.description and len(article.description) > 150 else article.description
    image_count = len(article.images)
    video_count = len(article.videos)
    content_snippet = ""
    if content_preview and article.content:
        snippet = article.content.strip().replace("\n", " ")
        if len(snippet) > content_preview:
            snippet = snippet[:content_preview].rstrip() + "..."
        content_snippet = f"Content   : {snippet}\n"
    return (
        f"Title     : {article.title}\n"
        f"URL       : {article.url}\n"
        f"Published : {publish_date}\n"
        f"Category  : {article.category_name or 'N/A'} (id={article.category_id or 'N/A'})\n"
        f"Tags      : {article.tags or 'N/A'}\n"
        f"Images    : {image_count}  Videos: {video_count}\n"
        f"{content_snippet}"
        f"Description:\n{description or 'N/A'}\n"
        "----------"
    )


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    session_factory = create_session_factory(database_url=args.database_url)
    session = session_factory()

    try:
        total_articles = session.scalar(select(func.count()).select_from(Article))
        total_images = session.scalar(select(func.count()).select_from(ArticleImage))
        total_videos = session.scalar(select(func.count()).select_from(ArticleVideo))
        logging.info(
            "Database contains %s articles, %s images, %s videos",
            total_articles,
            total_images,
            total_videos,
        )

        query = session.query(Article)
        if args.host:
            query = query.filter(Article.url.contains(args.host))

        order_column = Article.publish_date.desc().nullslast() if args.order == "publish_date" else Article.created_at.desc()
        query = query.order_by(order_column).limit(args.limit)

        articles: Iterable[Article] = query.all()

        if not articles:
            logging.info("No articles matched the filters.")
            return

        for article in articles:
            session.refresh(article)  # ensure relationship collections are loaded
            print(summarize_article(article, content_preview=args.show_content))
    finally:
        session.close()


if __name__ == "__main__":
    main()
