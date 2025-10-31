import logging
import posixpath
import re
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse
import json
import requests
from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from db.models import Article, ArticleImage, ArticleVideo
from .sitemap import SitemapEntry
from .throttle import RequestThrottler
from .utils import parse_w3c_datetime


logger = logging.getLogger(__name__)


@dataclass
class ArticleData:
    url: str
    title: str | None = None
    description: str | None = None
    summary: str | None = None
    content_html: str | None = None
    content: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    tags: str | None = None
    publish_date: datetime | None = None
    last_modified: datetime | None = None
    author: str | None = None
    external_id: str | None = None
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
        data.summary = self._extract_summary(soup)

        main_container = self._find_main_container(soup)

        data.content_html = self._extract_content_html(main_container)
        data.content = self._extract_content(soup, main_container)
        data.category_id, data.category_name = self._extract_category(soup)
        data.tags = self._extract_tags(soup)
        data.publish_date = self._extract_publish_date(soup)
        data.last_modified = self._extract_last_modified(soup)
        data.author = self._extract_author(soup)

        data.images = self._extract_media_urls(
            soup,
            ["meta[property='og:image']", "meta[name='og:image']"],
            "content",
            skip_predicate=_should_skip_image_url,
        )
        data.images.extend(self._extract_inline_images(soup, main_container))
        data.images = _deduplicate_preserve_order(data.images)

        data.videos = self._extract_media_urls(soup, ["meta[property='og:video']"], "content")
        data.videos.extend(self._extract_inline_videos(soup, main_container))
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

    def _extract_summary(self, soup: BeautifulSoup) -> str | None:
        selectors = [
            "div.article__sapo",
            "div.article__lead",
            "div.article__desc",
            "div.cms-desc",
            "[itemprop='description']",
            ".article-sapo",
            ".article-summary",
        ]
        for selector in selectors:
            element = soup.select_one(selector)
            if not element:
                continue
            text = element.get_text(" ", strip=True)
            text = _normalize_whitespace(text)
            if text:
                return text
        return None

    def _extract_content_html(self, container: Tag | None) -> str | None:
        if container is None:
            return None
        soup_fragment = BeautifulSoup(str(container), "lxml")
        root = soup_fragment.find()
        if root is None:
            return None

        for selector in ["script", "style", "noscript", "iframe", "form"]:
            for element in root.select(selector):
                element.decompose()

        for selector in [".rennab", ".adsbygoogle", ".adv-box", "[data-position*='SdaArticle']"]:
            for element in root.select(selector):
                element.decompose()

        for img in root.find_all("img"):
            data_src = img.get("data-src") or img.get("data-original")
            if data_src and not img.get("src"):
                img["src"] = data_src

        cleaned_html = root.decode_contents().strip()
        return cleaned_html or None

    def _extract_content(self, soup: BeautifulSoup, container: Tag | None = None) -> str | None:
        if container is None:
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

        domain = urlparse(self.base_url).netloc.lower()
        is_baocamau = "baocamau.vn" in domain
        is_baodongkhoi = "baodongkhoi.vn" in domain

        explicit_category_id: str | None = None

        if is_baocamau:
            baocamau_category_id, baocamau_category_name = _extract_baocamau_category(soup)
            if baocamau_category_id:
                explicit_category_id = baocamau_category_id
            if baocamau_category_name:
                category_name = baocamau_category_name

        if is_baodongkhoi:
            hidden_category = soup.select_one("input#txtnewscate")
            if hidden_category and hidden_category.get("value"):
                explicit_category_id = hidden_category["value"].strip().lower() or None

        if not category_name:
            baodongkhoi_link = soup.select_one("h2.catename-h1 a")
            if baodongkhoi_link:
                link_text = _normalize_whitespace(baodongkhoi_link.get_text(" ", strip=True))
                if link_text:
                    category_name = link_text
                elif baodongkhoi_link.get("title"):
                    category_name = _normalize_whitespace(baodongkhoi_link["title"])
                if is_baodongkhoi and not explicit_category_id:
                    explicit_category_id = _slug_from_url(baodongkhoi_link.get("href"))

        if not category_name:
            titlecate = soup.select_one("div.titlecate h1")
            if titlecate:
                link_texts = [
                    _normalize_whitespace(link.get_text(" ", strip=True))
                    for link in titlecate.find_all("a")
                    if _normalize_whitespace(link.get_text(" ", strip=True))
                ]
                if link_texts:
                    category_name = " > ".join(link_texts)
                else:
                    text_value = _normalize_whitespace(titlecate.get_text(" ", strip=True))
                    if text_value:
                        category_name = text_value.replace(">", " > ")

        if not category_name and explicit_category_id:
            category_name = _prettify_slug(explicit_category_id)

        category_id = explicit_category_id or (_slugify(category_name) if category_name else None)
        return category_id, category_name

    def _extract_author(self, soup: BeautifulSoup) -> str | None:
        selectors = [
            ".article__author",
            ".article-author",
            "[itemprop='author']",
            ".author-name",
            "meta[name='author']",
            "meta[property='article:author']",
        ]
        for selector in selectors:
            element = soup.select_one(selector)
            if not element:
                continue
            if element.name == "meta":
                content = element.get("content")
                if content and content.strip():
                    return _normalize_whitespace(content)
            else:
                text = element.get_text(" ", strip=True)
                text = _normalize_whitespace(text)
                if text:
                    return text
        return None

    def _extract_tags(self, soup: BeautifulSoup) -> str | None:
        tags: List[str] = []
        for meta_tag in soup.select("meta[property='article:tag']"):
            if meta_tag.get("content"):
                content = meta_tag["content"].strip()
                if not content:
                    continue
                if "," in content:
                    for part in content.split(","):
                        part = part.strip()
                        if part:
                            tags.append(part)
                else:
                    tags.append(content)

        keywords_meta = soup.find("meta", attrs={"name": re.compile(r"^keywords$", re.IGNORECASE)})
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
            "div.block_tag a",
            "a.tag_item",
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

    def _extract_last_modified(self, soup: BeautifulSoup) -> datetime | None:
        selectors = [
            ("meta[property='article:modified_time']", "content"),
            ("meta[name='lastmod']", "content"),
            ("meta[name='last-modified']", "content"),
            ("time[itemprop='dateModified']", "datetime"),
            ("time[datetime][itemprop='dateModified']", "datetime"),
        ]
        for selector, attr in selectors:
            element = soup.select_one(selector)
            if element and element.get(attr):
                parsed = _parse_datetime(element[attr])
                if parsed:
                    return parsed
        return None

    def _extract_media_urls(
        self,
        soup: BeautifulSoup,
        selectors: Sequence[str],
        attr: str,
        skip_predicate: Optional[Callable[[str], bool]] = None,
    ) -> List[str]:
        urls: List[str] = []
        for selector in selectors:
            for element in soup.select(selector):
                if not element.get(attr):
                    continue
                media_url = element[attr].strip()
                if not media_url:
                    continue
                resolved_url = self._absolutize(media_url)
                if skip_predicate and skip_predicate(resolved_url):
                    continue
                urls.append(resolved_url)
        return urls

    def _extract_inline_images(self, soup: BeautifulSoup, container: Tag | None = None) -> List[str]:
        urls: List[str] = []
        search_space = container if container is not None else soup

        image_tags: Sequence[Tag]
        if container is not None:
            image_tags = container.find_all("img")
        else:
            image_tags = soup.select("article img, div[class*='article'] img, div[class*='content'] img")

        for img in image_tags:
            for candidate in _collect_image_candidates(img):
                resolved = self._absolutize(candidate)
                if _should_skip_image_url(resolved):
                    continue
                urls.append(resolved)

        source_tags: Sequence[Tag]
        if container is not None:
            source_tags = container.find_all("source")
        else:
            source_tags = soup.select("picture source, source[type*='image']")

        for source_tag in source_tags:
            for candidate in _collect_image_candidates(source_tag):
                resolved = self._absolutize(candidate)
                if _should_skip_image_url(resolved):
                    continue
                urls.append(resolved)

        for element in search_space.select("[style*='background']"):
            for candidate in _extract_urls_from_style(element.get("style", "")):
                resolved = self._absolutize(candidate)
                if _should_skip_image_url(resolved):
                    continue
                urls.append(resolved)
        return urls

    def _extract_inline_videos(self, soup: BeautifulSoup, container: Tag | None = None) -> List[str]:
        urls: List[str] = []
        search_space = container if container is not None else soup
        for video in search_space.find_all("video"):
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

    def crawl(self, entry: SitemapEntry | str) -> bool:
        if isinstance(entry, SitemapEntry):
            url = entry.url
            sitemap_lastmod = entry.lastmod
            sitemap_article_id = entry.article_id
        else:
            url = entry
            sitemap_lastmod = None
            sitemap_article_id = None

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
        article_data.external_id = article_data.external_id or sitemap_article_id
        if not article_data.title or not article_data.content:
            logger.info("Skipping %s due to missing title/content", url)
            return False

        return self._persist(
            article_data,
            sitemap_lastmod=sitemap_lastmod,
            sitemap_article_id=sitemap_article_id,
        )

    def _persist(
        self,
        data: ArticleData,
        sitemap_lastmod: str | None = None,
        sitemap_article_id: str | None = None,
    ) -> bool:
        session = self.session_factory()
        try:
            existing = session.query(Article).filter(Article.url == data.url).one_or_none()
            if existing:
                logger.debug("Article already stored: %s", data.url)
                return False

            description_value = data.summary or data.description
            article = Article(
                title=data.title[:1024],
                description=description_value,
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

            metadata: dict[str, str] = {}
            if data.summary:
                metadata["summary"] = data.summary
            if data.description and data.description != description_value:
                metadata["meta_description"] = data.description
            if data.content_html:
                metadata["body_html"] = data.content_html
            if data.author:
                metadata["author"] = data.author
            if data.last_modified:
                metadata["last_modified"] = data.last_modified.isoformat()
            sitemap_dt = parse_w3c_datetime(sitemap_lastmod) if sitemap_lastmod else None
            if sitemap_dt:
                metadata["sitemap_lastmod"] = sitemap_dt.isoformat()
            elif sitemap_lastmod:
                metadata["sitemap_lastmod_raw"] = sitemap_lastmod
            external_id = data.external_id or sitemap_article_id
            if external_id:
                metadata["article_external_id"] = external_id
            # if metadata:
                # article.comments = metadata
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


def _slugify(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    tokens = re.findall(r"[a-z0-9]+", stripped.lower())
    if not tokens:
        return None
    return "_".join(tokens)


_STYLE_URL_RE = re.compile(r"url\((['\"]?)(.+?)\1\)")
_IMAGE_PLACEHOLDER_KEYWORDS = {
    "logo",
    "placeholder",
    "default",
    "banner",
    "ads",
    "adserver",
    "icon",
    "sprite",
    "nophoto",
    "no-photo",
    "blank",
    "spacer",
    "tracking",
    "pixel",
}


def _collect_image_candidates(tag: Tag) -> List[str]:
    candidates: List[str] = []
    attr_names = [
        "src",
        "data-src",
        "data-original",
        "data-lazy-src",
        "data-medium-file",
        "data-large-file",
        "data-image",
        "data-fullsrc",
        "data-zoom-image",
        "data-highres",
    ]
    for attr_name in attr_names:
        value = tag.get(attr_name)
        if value:
            candidates.append(value)

    for attr_name in ("srcset", "data-srcset"):
        value = tag.get(attr_name)
        if value:
            candidates.extend(_parse_srcset(value))

    if tag.get("style"):
        candidates.extend(_extract_urls_from_style(tag["style"]))

    seen: set[str] = set()
    unique_candidates: List[str] = []
    for candidate in candidates:
        cleaned = candidate.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique_candidates.append(cleaned)
    return unique_candidates


def _parse_srcset(value: str) -> List[str]:
    results: List[str] = []
    for part in value.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        url_only = stripped.split(" ")[0]
        if url_only:
            results.append(url_only.strip())
    return results


def _extract_urls_from_style(style: str) -> List[str]:
    if not style:
        return []
    matches = _STYLE_URL_RE.findall(style)
    return [match[1].strip() for match in matches if match[1].strip()]


def _should_skip_image_url(url: str) -> bool:
    if not url:
        return True
    lowered = url.lower()
    if lowered.startswith("data:"):
        return True
    if "insert_random_number_here" in lowered:
        return True
    if "www/delivery" in lowered:
        return True

    parsed = urlparse(url)
    filename = posixpath.basename(parsed.path).lower()
    if filename and any(keyword in filename for keyword in _IMAGE_PLACEHOLDER_KEYWORDS):
        return True
    if not filename and not parsed.netloc:
        return True
    return False


def _extract_baocamau_category(soup: BeautifulSoup) -> Tuple[str | None, str | None]:
    def _clean_slug(value) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return None

    def _find_name_for_slug(slug: str | None) -> str | None:
        if not slug:
            return None
        normalized_slug = slug.strip("/").lower()
        candidate_selectors = [
            f".category-title-box a[href*='/{normalized_slug}/']",
            f"a[href*='/{normalized_slug}/']",
        ]
        for selector in candidate_selectors:
            for link in soup.select(selector):
                href = (link.get("href") or "").lower()
                if f"/{normalized_slug}/" not in href:
                    continue
                text = _normalize_whitespace(link.get_text(" ", strip=True))
                if text:
                    return text
        return None

    main_slug: str | None = None
    sub_slug: str | None = None
    input_element = soup.select_one("input[name='dataPostComment']")
    if input_element and input_element.get("value"):
        raw_value = input_element["value"]
        try:
            payload = json.loads(raw_value)
        except (json.JSONDecodeError, TypeError):
            payload = None
        if isinstance(payload, dict):
            main_slug = _clean_slug(payload.get("newsCate"))
            sub_slug = _clean_slug(payload.get("newsSubcate"))

    slug_to_use = sub_slug or main_slug
    main_name = _find_name_for_slug(main_slug)
    sub_name = _find_name_for_slug(sub_slug)

    if sub_slug and sub_name:
        category_name = f"{main_name} > {sub_name}" if main_name and main_name != sub_name else sub_name
    else:
        category_name = sub_name or main_name

    if not category_name:
        header_link = soup.select_one(".category-title-box .news-block-header span a")
        if header_link:
            text = _normalize_whitespace(header_link.get_text(" ", strip=True))
            if text:
                category_name = text
            if not slug_to_use:
                slug_to_use = _slug_from_url(header_link.get("href"))

    if slug_to_use:
        slug_to_use = slug_to_use.strip("/ ").lower()

    return slug_to_use, category_name


def _slug_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path or ""
    parts = [segment for segment in path.split("/") if segment]
    if not parts:
        return None
    slug = parts[-1]
    if slug.endswith(".html"):
        slug = slug[:-5]
    return slug.lower() if slug else None


def _prettify_slug(slug: str) -> str:
    tokens = [token for token in re.split(r"[-_]+", slug) if token]
    if not tokens:
        return slug
    return " ".join(tokens).upper()
