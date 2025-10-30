import json
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from db.models import Article, ArticleImage, ArticleVideo
from .throttle import RequestThrottler


logger = logging.getLogger(__name__)


@dataclass
class ArticleData:
    url: str
    title: str | None = None
    description: str | None = None
    content: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    tags: str | None = None
    publish_date: datetime | None = None
    images: List[str] = field(default_factory=list)
    videos: List[str] = field(default_factory=list)


class ArticleExtractor:
    """Extract structured article information from HTML content."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def extract(self, html: str) -> ArticleData:
        soup = BeautifulSoup(html, "lxml")
        data = ArticleData(url=self.base_url)
        data.title = self._extract_title(soup)
        data.description = self._extract_description(soup)
        data.content = self._extract_content(soup)
        data.category_id, data.category_name = self._extract_category(soup)
        data.tags = self._extract_tags(soup)
        data.publish_date = self._extract_publish_date(soup)
        data.images = self._extract_media_urls(soup, ["meta[property='og:image']", "meta[name='og:image']"], "content")
        data.images.extend(self._extract_inline_images(soup))
        data.images = _deduplicate_preserve_order(data.images)

        data.videos = self._extract_media_urls(soup, ["meta[property='og:video']"], "content")
        data.videos.extend(self._extract_inline_videos(soup))
        data.videos = _deduplicate_preserve_order(data.videos)

        return data

    def _extract_title(self, soup: BeautifulSoup) -> str | None:
        selectors = [
            "meta[property='og:title']",
            "meta[name='og:title']",
            "meta[name='title']",
            "h1",
            "title",
        ]
        return _first_text(soup, selectors)

    def _extract_description(self, soup: BeautifulSoup) -> str | None:
        selectors = [
            "meta[name='description']",
            "meta[property='og:description']",
            "p.summary",
        ]
        return _first_text(soup, selectors)

    def _extract_content(self, soup: BeautifulSoup) -> str | None:
        container = self._find_main_container(soup)
        if container is None:
            paragraphs = [
                p
                for p in soup.find_all("p")
                if not _contains_excluded_text(p) and not _is_in_excluded_section(p)
            ]
            if paragraphs:
                return _join_paragraphs(paragraphs)
            return None

        collected_texts: List[str] = []
        last_text: str | None = None
        queue: deque[Tag] = deque([container])

        while queue:
            current = queue.popleft()
            for child in current.children:
                if not isinstance(child, Tag):
                    continue
                if child.name in {"script", "style", "noscript", "iframe", "form"}:
                    continue
                if child.name in {"nav", "aside", "footer"}:
                    continue
                if _is_in_excluded_section(child):
                    continue

                if child.name in {"p", "h2", "h3", "h4", "li"}:
                    text = child.get_text(" ", strip=True)
                    text = _normalize_whitespace(text)
                    if not text:
                        continue
                    if _contains_excluded_text(text):
                        continue
                    if text == last_text:
                        continue
                    collected_texts.append(text)
                    last_text = text
                elif child.name == "table":
                    table_text = _table_to_text(child)
                    if not table_text or table_text == last_text:
                        continue
                    collected_texts.append(table_text)
                    last_text = table_text
                else:
                    queue.append(child)

        if not collected_texts:
            return None
        return "\n\n".join(collected_texts)

    def _find_main_container(self, soup: BeautifulSoup):
        selectors = [
            "[itemprop='articleBody']",
            "article",
            "section[itemtype*='Article']",
            "div[class*='article-body']",
            "section[class*='article-body']",
            "div[class*='entry']",
            "div[class*='content'], section[class*='content']",
        ]

        best_element: Tag | None = None
        best_length = 0
        for selector in selectors:
            for element in soup.select(selector):
                if _is_in_excluded_section(element):
                    continue
                text_length = len(element.get_text(" ", strip=True))
                if text_length > best_length:
                    best_length = text_length
                    best_element = element
        return best_element

    def _extract_category(self, soup: BeautifulSoup) -> Tuple[str | None, str | None]:
        category_meta = soup.select_one("meta[property='article:section'], meta[name='article:section']")
        category_name = category_meta["content"].strip() if category_meta and category_meta.get("content") else None
        category_id = category_name.lower().replace(" ", "_") if category_name else None
        return category_id, category_name

    def _extract_tags(self, soup: BeautifulSoup) -> str | None:
        tags: List[str] = []
        for meta_tag in soup.select("meta[property='article:tag']"):
            if meta_tag.get("content"):
                tags.append(meta_tag["content"].strip())

        keywords_meta = soup.select_one("meta[name='keywords']")
        if keywords_meta and keywords_meta.get("content"):
            keywords = [kw.strip() for kw in keywords_meta["content"].split(",") if kw.strip()]
            tags.extend(keywords)

        tag_selectors = [
            "a[rel='tag']",
            ".tags a",
            ".tag-list a",
            ".article-tags a",
            "ul[class*='tag'] a",
            "li[class*='tag'] a",
            "[class*='keyword'] a",
            ".c-widget-tags a",
            ".onecms__tags a",
        ]
        for selector in tag_selectors:
            for element in soup.select(selector):
                text = element.get_text(strip=True)
                if not text and element.get("title"):
                    text = element["title"].strip()
                if text:
                    tags.append(text)

        if not tags:
            return None
        tags = _deduplicate_preserve_order(tags)
        return ",".join(tags)

    def _extract_publish_date(self, soup: BeautifulSoup) -> datetime | None:
        selectors = [
            ("meta[property='article:published_time']", "content"),
            ("meta[name='pubdate']", "content"),
            ("meta[name='timestamp']", "content"),
            ("meta[itemprop='datePublished']", "content"),
            ("time[itemprop='datePublished']", "datetime"),
            ("time[datetime]", "datetime"),
            ("meta[property='og:updated_time']", "content"),
        ]
        for selector, attr in selectors:
            element = soup.select_one(selector)
            if element and element.get(attr):
                parsed = _parse_datetime(element[attr])
                if parsed:
                    return parsed
        jsonld_date = _extract_date_from_jsonld(soup)
        if jsonld_date:
            return jsonld_date

        attribute_candidates = ["data-date", "data-time", "data-published", "datetime"]
        for element in soup.select("[data-date], [data-time], [data-published]"):
            for attr in attribute_candidates:
                if element.get(attr):
                    parsed = _parse_datetime(element[attr])
                    if parsed:
                        return parsed

        text_selectors = [
            "span[class*='date']",
            "span[class*='time']",
            "div[class*='date']",
            "div[class*='time']",
            ".post-date",
            ".publish-date",
            ".detail-time",
            ".article__meta-time",
            ".meta-time",
            ".entry-date",
            ".date-post",
            ".time-post",
            ".c-time",
        ]
        for selector in text_selectors:
            for element in soup.select(selector):
                text = element.get_text(" ", strip=True)
                if not text:
                    continue
                parsed = _parse_datetime_text(text)
                if parsed:
                    return parsed
        return None

    def _extract_media_urls(
        self, soup: BeautifulSoup, selectors: Sequence[str], attr: str
    ) -> List[str]:
        urls: List[str] = []
        for selector in selectors:
            for element in soup.select(selector):
                if not element.get(attr):
                    continue
                media_url = element[attr].strip()
                if media_url:
                    urls.append(self._absolutize(media_url))
        return urls

    def _extract_inline_images(self, soup: BeautifulSoup) -> List[str]:
        urls: List[str] = []
        for img in soup.select("article img, div[class*='article'] img, div[class*='content'] img"):
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            urls.append(self._absolutize(src))
        return urls

    def _extract_inline_videos(self, soup: BeautifulSoup) -> List[str]:
        urls: List[str] = []
        for video in soup.find_all("video"):
            if video.get("src"):
                urls.append(self._absolutize(video["src"]))
            for source in video.find_all("source"):
                if source.get("src"):
                    urls.append(self._absolutize(source["src"]))
        return urls

    def _absolutize(self, href: str) -> str:
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return urljoin(self.base_url, href)


class ArticleCrawler:
    """Fetch article pages and persist them into the database."""

    def __init__(
        self,
        session_factory,
        timeout: int = 20,
        max_images: int = 10,
        max_videos: int = 5,
        user_agent: str | None = None,
        throttler: RequestThrottler | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.timeout = timeout
        self.http = requests.Session()
        self.max_images = max_images
        self.max_videos = max_videos
        self.throttler = throttler

        if user_agent:
            self.http.headers["User-Agent"] = user_agent

    def crawl(self, url: str) -> bool:
        try:
            if self.throttler:
                self.throttler.wait()
            response = self.http.get(url, timeout=self.timeout)
            response.raise_for_status()
        except Exception as exc:
            logger.error("Failed to fetch article %s: %s", url, exc)
            return False

        extractor = ArticleExtractor(url)
        article_data = extractor.extract(response.text)
        if not article_data.title or not article_data.content:
            logger.info("Skipping %s due to missing title/content", url)
            return False

        return self._persist(article_data)

    def _persist(self, data: ArticleData) -> bool:
        session = self.session_factory()
        try:
            existing = session.query(Article).filter(Article.url == data.url).one_or_none()
            if existing:
                logger.debug("Article already stored: %s", data.url)
                return False

            article = Article(
                title=data.title[:1024],
                description=data.description,
                content=data.content,
                category_id=data.category_id,
                category_name=data.category_name,
                tags=data.tags,
                url=data.url,
                publish_date=data.publish_date,
            )
            session.add(article)
            session.flush()  # ensures article.id is generated

            for idx, image_url in enumerate(data.images[: self.max_images], start=1):
                article.images.append(
                    ArticleImage(
                        image_path=image_url,  # storing original URL; adjust if downloads are required
                        sequence_number=idx,
                    )
                )

            for idx, video_url in enumerate(data.videos[: self.max_videos], start=1):
                article.videos.append(
                    ArticleVideo(
                        video_path=video_url,
                        sequence_number=idx,
                    )
                )

            session.commit()
            logger.info("Stored article: %s", data.url)
            return True
        except Exception as exc:
            session.rollback()
            logger.error("Failed to persist article %s: %s", data.url, exc)
            return False
        finally:
            session.close()


def _first_text(soup: BeautifulSoup, selectors: Sequence[str]) -> str | None:
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            if element.name == "meta":
                content = element.get("content")
                if content:
                    return content.strip()
            else:
                text = element.get_text(strip=True)
                if text:
                    return text
    return None


def _join_paragraphs(elements: Iterable) -> str | None:
    texts: List[str] = []
    for element in elements:
        text = element.get_text(" ", strip=True)
        if text:
            texts.append(text)
    if not texts:
        return None
    return "\n\n".join(texts)


def _parse_datetime(value: str) -> Optional[datetime]:
    try:
        parsed = date_parser.parse(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if parsed.tzinfo:
        return parsed.astimezone(timezone.utc)
    return parsed


def _deduplicate_preserve_order(items: Sequence[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _contains_excluded_text(element_or_text) -> bool:
    if isinstance(element_or_text, Tag):
        text = element_or_text.get_text(" ", strip=True)
    else:
        text = str(element_or_text)
    lowered = text.lower()
    excluded_keywords = [
        "chia sẻ facebook",
        "theo dõi trên",
        "bình luận của bạn",
        "ban biên tập",
        "thời gian",
        "số người thích",
        "sponsored",
        "quảng cáo",
    ]
    return any(keyword in lowered for keyword in excluded_keywords)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _table_to_text(table: Tag) -> str | None:
    rows: List[str] = []
    for tr in table.find_all("tr"):
        cells = []
        for cell in tr.find_all(["th", "td"]):
            cell_text = _normalize_whitespace(cell.get_text(" ", strip=True))
            if cell_text:
                cells.append(cell_text)
        if cells:
            rows.append(" | ".join(cells))
    if not rows:
        return None
    return "\n".join(rows)


def _tokenize_identifier(value: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


_EXCLUDED_SECTION_TOKENS = {
    "ads",
    "advert",
    "banner",
    "sponsor",
    "related",
    "share",
    "social",
    "comment",
    "promo",
    "widget",
    "tags",
    "tagbox",
    "taglist",
    "keyword",
    "subscribe",
    "breadcrumb",
}


def _has_excluded_marker(element: Tag) -> bool:
    attribute_names = [
        "class",
        "id",
        "data-role",
        "data-component",
        "data-block",
        "data-type",
    ]
    for attr_name in attribute_names:
        attr_value = element.get(attr_name)
        if not attr_value:
            continue
        values = attr_value if isinstance(attr_value, list) else [attr_value]
        for value in values:
            tokens = _tokenize_identifier(value)
            if any(
                token == keyword or token.startswith(keyword)
                for token in tokens
                for keyword in _EXCLUDED_SECTION_TOKENS
            ):
                return True
    return False


def _is_in_excluded_section(element: Tag) -> bool:
    current = element
    while isinstance(current, Tag):
        if _has_excluded_marker(current):
            return True
        current = current.parent
    return False


def _extract_date_from_jsonld(soup: BeautifulSoup) -> Optional[datetime]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("datePublished", "dateCreated", "dateModified"):
                if item.get(key):
                    parsed = _parse_datetime(item[key])
                    if parsed:
                        return parsed
    return None


def _parse_datetime_text(text: str) -> Optional[datetime]:
    cleaned = text.strip()
    if not cleaned:
        return None
    try:
        parsed = date_parser.parse(cleaned, fuzzy=True, dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return None
    if parsed.tzinfo:
        return parsed.astimezone(timezone.utc)
    return parsed
