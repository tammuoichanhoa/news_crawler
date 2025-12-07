import argparse
import mimetypes
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union
from urllib.parse import urlparse

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from crawler import VNExpressScraper
from models import Article, ArticleImage, ArticleVideo, Base, generate_uuid7


DEFAULT_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://crawl:crawl@localhost:5432/vnexpress",
)
IMAGE_STORAGE_DIR = Path(
    os.getenv("IMAGE_STORAGE_DIR", "/mnt/drive2/baoanh_crawler/vnexpress")
)

def resolve_date(value: Optional[str], fallback: datetime) -> datetime:
    """Resolve CLI-provided date strings into datetime instances."""
    if not value:
        return fallback
    try:
        resolved = datetime.fromisoformat(value)
        if resolved.tzinfo:
            resolved = resolved.astimezone(timezone.utc).replace(tzinfo=None)
        return resolved
    except ValueError as exc:
        raise ValueError(f"Invalid date format '{value}'. Use ISO format, e.g. 2024-10-10.") from exc


def truncate(text: Optional[str], max_length: int) -> Optional[str]:
    if text is None:
        return None
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def normalize_publish_date(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    return None


def ensure_image_storage_dir() -> Path:
    try:
        IMAGE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"Cannot create image storage directory '{IMAGE_STORAGE_DIR}': {exc}") from exc
    return IMAGE_STORAGE_DIR


def _is_subpath(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def cleanup_local_image_files(images: Iterable[ArticleImage], base_dir: Path) -> None:
    for stored_image in images:
        image_path = getattr(stored_image, "image_path", None)
        if not image_path:
            continue
        path_obj = Path(image_path)
        try:
            resolved = path_obj.resolve(strict=False)
        except OSError:
            continue
        if not resolved.exists():
            continue
        if not _is_subpath(resolved, base_dir):
            continue
        try:
            resolved.unlink()
        except OSError:
            continue


def _derive_image_extension(url: str, response: requests.Response) -> str:
    parsed = urlparse(url)
    _, ext = os.path.splitext(parsed.path)
    if ext and len(ext) <= 5:
        return ext.lower()

    content_type = response.headers.get("Content-Type")
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return guessed.lower()

    return ".jpg"


def download_image(
    url: str,
    article_id: Union[str, uuid.UUID],
    sequence: int,
    base_dir: Path,
) -> Optional[str]:
    if not url:
        return None
    article_id_str = str(article_id)
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARN] Failed to download image '{url}': {exc}")
        return None

    extension = _derive_image_extension(url, response)
    filename = f"{article_id_str}_img_{sequence}{extension}"
    destination = base_dir / filename
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
    except OSError as exc:
        print(f"[WARN] Failed to store image '{destination}': {exc}")
        return None

    return str(destination)


def article_payload(article: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare payload for ORM persistence, enforcing column limits."""
    return {
        "title": truncate(article.get("title", ""), 500) or "Untitled",
        "description": article.get("description"),
        "content": article.get("content"),
        "category_id": truncate(article.get("category_id"), 100),
        "category_name": truncate(article.get("category_name"), 200),
        "tags": truncate(article.get("tags"), 500),
        "url": truncate(article.get("url"), 2000),
        "publish_date": normalize_publish_date(article.get("publish_date")),
        "comments": article.get("comments") or {"count": 0, "list": []},
    }


def build_image_models(
    article: Dict[str, Any],
    article_id: uuid.UUID,
    storage_dir: Path,
) -> List[ArticleImage]:
    images: List[ArticleImage] = []
    for idx, item in enumerate(article.get("images") or [], start=1):
        path = item.get("image_path") or item.get("path")
        if not path:
            continue
        local_path = download_image(path, article_id, idx, storage_dir)
        if not local_path:
            continue
        if len(local_path) > 500:
            print(f"[WARN] Skipping image for article {article_id}: local path exceeds column limit.")
            continue
        images.append(
            ArticleImage(
                article_id=article_id,
                image_path=local_path,
                sequence_number=idx,
            )
        )
    return images


def build_video_models(article: Dict[str, Any], article_id: uuid.UUID) -> List[ArticleVideo]:
    videos: List[ArticleVideo] = []
    for idx, item in enumerate(article.get("videos") or [], start=1):
        path = item.get("video_path") or item.get("path")
        if not path:
            continue
        sequence = item.get("sequence_number") or idx
        try:
            sequence = int(sequence)
        except (TypeError, ValueError):
            sequence = idx
        videos.append(
            ArticleVideo(
                article_id=article_id,
                video_path=truncate(path, 4096),
                sequence_number=sequence,
            )
        )
    return videos


def save_urls_to_file(articles: Iterable[Dict[str, Any]], destination: Path) -> int:
    unique_urls: List[str] = []
    seen = set()
    for article in articles:
        url = article.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        unique_urls.append(url)

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(unique_urls), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Cannot write URL cache to '{destination}': {exc}") from exc

    print(f"✓ Saved {len(unique_urls)} URLs to {destination}")
    return len(unique_urls)


def load_urls_from_file(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"URL cache '{path}' does not exist.")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"Cannot read URL cache '{path}': {exc}") from exc

    urls: List[str] = []
    seen = set()
    for line in lines:
        url = line.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def fetch_article_details(scraper: VNExpressScraper, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    total = len(articles)
    if total == 0:
        return []

    print(
        f"Fetching full content for {total} articles "
        f"with {scraper.detail_workers} worker(s)..."
    )
    detailed_articles: List[Dict[str, Any]] = []

    def _fetch_detail(article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Log URL being processed to track progress, especially when using a URL file.
        url = article.get("url")
        if url:
            print(f"[DETAIL] Fetching article detail for URL: {url}")
        return scraper.parse_article_detail(article["url"], summary=article)

    with ThreadPoolExecutor(max_workers=scraper.detail_workers) as executor:
        future_to_article = {
            executor.submit(_fetch_detail, article): article for article in articles
        }
        for idx, future in enumerate(as_completed(future_to_article), 1):
            article = future_to_article[future]
            try:
                detailed = future.result()
                if detailed:
                    detailed_articles.append(detailed)
            except Exception as exc:  # pragma: no cover - safety net for unexpected parser issues
                print(f"[WARN] Failed to fetch {article.get('url')}: {exc}")
            if idx % 10 == 0 or idx == total:
                print(f"Fetched {idx}/{total} articles")

    return detailed_articles


def upsert_articles(
    session: Session,
    articles: Iterable[Dict[str, Any]],
    image_dir: Path,
) -> int:
    """Insert or update articles by URL. Returns number of upserted rows."""
    articles = [a for a in articles if a.get("url")]
    if not articles:
        return 0

    urls = [article["url"] for article in articles if article.get("url")]
    existing_articles = (
        session.query(Article)
        .filter(Article.url.in_(urls))
        .all()
    )
    existing_by_url = {article.url: article for article in existing_articles}

    new_entries: List[Article] = []
    touched = 0

    for article in articles:
        payload = article_payload(article)
        existing = existing_by_url.get(payload["url"])
        if existing:
            cleanup_local_image_files(existing.images, image_dir)
            videos = build_video_models(article, existing.id)
            images = build_image_models(article, existing.id, image_dir)
            for key, value in payload.items():
                setattr(existing, key, value)
            existing.images[:] = images
            existing.videos[:] = videos
            touched += 1
        else:
            article_id = generate_uuid7()
            videos = build_video_models(article, article_id)
            images = build_image_models(article, article_id, image_dir)
            new_article = Article(id=article_id, **payload)
            new_article.images = images
            new_article.videos = videos
            new_entries.append(new_article)

    if new_entries:
        session.add_all(new_entries)
        touched += len(new_entries)

    session.commit()
    return touched


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl VNExpress articles and persist them to PostgreSQL."
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="ISO formatted start date (default: 7 days before end-date).",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="ISO formatted end date (default: now).",
    )
    parser.add_argument(
        "--interval-days",
        type=int,
        default=7,
        help="Size of the crawl window in days (default: 7).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Maximum pages per date window (default: 10).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent workers for fetching article details (default: 4).",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.2,
        help="Delay (seconds) between listing requests to reduce throttling (default: 0.25).",
    )
    parser.add_argument(
        "--skip-comments",
        action="store_true",
        help="Skip Selenium comment crawling for faster runs.",
    )
    parser.add_argument(
        "--categories",
        nargs="*",
        help="Optional list of category slugs to crawl (e.g. thoi-su the-gioi).",
    )
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DATABASE_URL,
        help="PostgreSQL connection string (default: %(default)s).",
    )
    parser.add_argument(
        "--urls-file",
        default="resume_url.txt",
        help="Path to store/load crawled article URLs (default: %(default)s).",
    )
    parser.add_argument(
        "--only-crawl-urls",
        action="store_true",
        help="Only crawl article URLs, save to --urls-file, then exit.",
    )
    parser.add_argument(
        "--use-url-file",
        action="store_true",
        help="Skip category crawling and load article URLs from --urls-file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    end_default = datetime.utcnow()
    start_default = end_default - timedelta(days=7)

    start_date = resolve_date(args.start_date, start_default)
    end_date = resolve_date(args.end_date, end_default)

    if start_date >= end_date:
        raise ValueError("start-date must be earlier than end-date.")

    scraper = VNExpressScraper(
        request_delay=args.request_delay,
        detail_workers=args.workers,
        fetch_comments=not args.skip_comments,
    )
    if args.categories and not args.use_url_file:
        selected = {
            slug: scraper.categories[slug]
            for slug in args.categories
            if slug in scraper.categories
        }
        if not selected:
            raise ValueError(
                f"No matching categories for {args.categories}. "
                f"Available: {', '.join(scraper.categories.keys())}"
            )
        scraper.categories = selected

    url_cache_path = Path(args.urls_file)

    if args.use_url_file:
        try:
            cached_urls = load_urls_from_file(url_cache_path)
        except (FileNotFoundError, RuntimeError) as exc:
            print(exc)
            return
        if not cached_urls:
            print(f"No URLs found in {url_cache_path}; nothing to fetch.")
            return
        print(f"Loaded {len(cached_urls)} URLs from {url_cache_path}; skipping category crawl.")
        article_summaries = [{"url": url} for url in cached_urls]
    else:
        print(
            f"Crawling categories {', '.join(scraper.categories.keys())} "
            f"from {start_date.date()} to {end_date.date()}..."
        )
        article_summaries = scraper.crawl_all_categories(
            start_date=start_date,
            end_date=end_date,
            interval_days=args.interval_days,
            max_pages_per_range=args.max_pages,
            get_full_content=False,
        )

        if not article_summaries:
            print("No articles fetched; nothing to persist.")
            return

        save_urls_to_file(article_summaries, url_cache_path)
        print(f"Saved {url_cache_path}")

        if args.only_crawl_urls:
            print("URLs saved; exiting because --only-crawl-urls is set.")
            return

    articles = fetch_article_details(scraper, article_summaries)

    if not articles:
        print("No articles fetched; nothing to persist.")
        return

    image_dir = ensure_image_storage_dir()

    engine = create_engine(args.database_url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        affected = upsert_articles(session, articles, image_dir)

    print(f"✓ Stored {affected} articles in database {args.database_url}")


if __name__ == "__main__":
    main()
